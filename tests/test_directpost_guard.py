"""push_to_direct double-send guard - the only thing standing between
a queued post and a duplicate Telegram/Discord/Bluesky send is the
sub_platform_status skip check in doxyedit/directpost.py.

Fake clients are injected by monkeypatching the client-lookup
(doxyedit.directpost.get_direct_clients) and the asset exporter
(doxyedit.directpost._export_assets). No network, no Qt.

The write-back between calls mirrors the canonical shape used by the
production writers (window.py sync _finalize and _AutoPostThread
result handler):
    success -> {"status": "posted", "posted_at": iso}
    failure -> {"status": "failed", "error": str}
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.factory import make_project, make_saved_project


class FakeClient:
    """Stands in for TelegramBotClient / DiscordWebhookClient /
    BlueskyClient. Records every send call."""

    def __init__(self, platform: str, succeed: bool = True):
        self.platform = platform
        self.succeed = succeed
        self.calls: list[tuple] = []

    def _result(self):
        from doxyedit.directpost import DirectPostResult
        if self.succeed:
            return DirectPostResult(
                success=True, platform=self.platform,
                data={"url": f"https://example.test/{self.platform}"})
        return DirectPostResult(
            success=False, platform=self.platform, data={},
            error=f"{self.platform} boom")

    # Telegram surface
    def send_media_group(self, caption, image_paths):
        self.calls.append(("media_group", caption, tuple(image_paths)))
        return self._result()

    def send_photo(self, caption, image_path):
        self.calls.append(("photo", caption, image_path))
        return self._result()

    def send_message(self, caption, image_path=""):
        self.calls.append(("message", caption, image_path))
        return self._result()

    # Bluesky surface
    def send_post(self, caption, image_path=""):
        self.calls.append(("post", caption, image_path))
        return self._result()


def _no_clients():
    return {"telegram": [], "discord": [], "bluesky": []}


def _apply_results(post, results):
    """Canonical write-back, mirroring window.py's sync/_AutoPost writers."""
    now = datetime.now().isoformat()
    for r in results:
        if r.success:
            post.sub_platform_status[r.platform] = {
                "status": "posted", "posted_at": now}
        else:
            post.sub_platform_status[r.platform] = {
                "status": "failed", "error": r.error}


class TestPushToDirectGuard(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _push(self, post, project, clients, export_paths=None):
        """Run push_to_direct with fakes injected. Returns
        (results, export_mock)."""
        from doxyedit.directpost import push_to_direct
        export_mock = MagicMock(return_value=list(export_paths or []))
        with patch("doxyedit.directpost.get_direct_clients",
                   return_value=clients), \
             patch("doxyedit.directpost._export_assets", export_mock):
            results = push_to_direct(post, project, str(self.tmp_path))
        return results, export_mock

    # (a) already-posted platforms are skipped -------------------------------

    def test_already_posted_platform_is_skipped(self):
        proj = make_project(self.tmp_path)
        post = proj.posts[0]
        post.sub_platform_status = {
            "telegram": {"status": "posted",
                         "posted_at": "2026-07-01T09:00:00"},
        }
        tg = FakeClient("telegram")
        dc = FakeClient("discord")
        clients = {"telegram": [tg], "discord": [dc], "bluesky": []}

        results, _ = self._push(post, proj, clients,
                                export_paths=["img_a.png"])

        self.assertEqual(tg.calls, [])
        self.assertEqual(len(dc.calls), 1)
        self.assertEqual([r.platform for r in results], ["discord"])

    # (b) second call sends nothing (double-send guard) ----------------------

    def test_second_call_sends_nothing(self):
        proj = make_project(self.tmp_path)
        post = proj.posts[0]
        tg = FakeClient("telegram")
        dc = FakeClient("discord")
        bs = FakeClient("bluesky")
        clients = {"telegram": [tg], "discord": [dc], "bluesky": [bs]}

        results1, export1 = self._push(post, proj, clients,
                                       export_paths=["img_a.png"])
        self.assertEqual(len(results1), 3)
        self.assertEqual(export1.call_count, 1)
        _apply_results(post, results1)

        results2, export2 = self._push(post, proj, clients,
                                       export_paths=["img_a.png"])
        self.assertEqual(results2, [])
        self.assertEqual(len(tg.calls), 1)
        self.assertEqual(len(dc.calls), 1)
        self.assertEqual(len(bs.calls), 1)
        export2.assert_not_called()

    # (c) partial failure leaves per-platform status correct -----------------

    def test_partial_failure_status_and_retry(self):
        proj = make_project(self.tmp_path)
        post = proj.posts[0]
        tg = FakeClient("telegram", succeed=True)
        dc = FakeClient("discord", succeed=False)
        clients = {"telegram": [tg], "discord": [dc], "bluesky": []}

        results1, _ = self._push(post, proj, clients,
                                 export_paths=["img_a.png"])
        _apply_results(post, results1)

        self.assertEqual(
            post.sub_platform_status["telegram"]["status"], "posted")
        self.assertIn("posted_at", post.sub_platform_status["telegram"])
        self.assertEqual(
            post.sub_platform_status["discord"]["status"], "failed")
        self.assertEqual(
            post.sub_platform_status["discord"]["error"], "discord boom")

        # Second call: posted telegram is skipped, failed discord retries.
        results2, _ = self._push(post, proj, clients,
                                 export_paths=["img_a.png"])
        self.assertEqual(len(tg.calls), 1)
        self.assertEqual(len(dc.calls), 2)
        self.assertEqual([r.platform for r in results2], ["discord"])

    # (d) no clients configured -> no export attempted -----------------------

    def test_no_clients_means_no_export(self):
        proj = make_project(self.tmp_path)
        post = proj.posts[0]

        results, export_mock = self._push(post, proj, _no_clients())

        self.assertEqual(results, [])
        export_mock.assert_not_called()

    # (e) simulated restart: reloaded project still sends nothing ------------

    def test_guard_survives_save_and_reload(self):
        from doxyedit.models import Project
        proj, path = make_saved_project(self.tmp_path)
        post = proj.posts[0]
        post.sub_platform_status = {
            "telegram": {"status": "posted",
                         "posted_at": "2026-07-01T09:00:00"},
            "discord": {"status": "posted",
                        "posted_at": "2026-07-01T09:00:01"},
            "bluesky": {"status": "posted",
                        "posted_at": "2026-07-01T09:00:02"},
        }
        proj.save(str(path))

        # Fresh objects, as after an app restart.
        reloaded = Project.load(str(path))
        loaded_post = reloaded.posts[0]
        self.assertEqual(
            loaded_post.sub_platform_status["telegram"]["status"], "posted")

        tg = FakeClient("telegram")
        dc = FakeClient("discord")
        bs = FakeClient("bluesky")
        clients = {"telegram": [tg], "discord": [dc], "bluesky": [bs]}

        results, export_mock = self._push(loaded_post, reloaded, clients,
                                          export_paths=["img_a.png"])

        self.assertEqual(results, [])
        self.assertEqual(tg.calls, [])
        self.assertEqual(dc.calls, [])
        self.assertEqual(bs.calls, [])
        export_mock.assert_not_called()

    # Legacy shape hardening: bare-string values must not crash the guard ----

    def test_legacy_string_shape_does_not_crash_guard(self):
        proj = make_project(self.tmp_path)
        post = proj.posts[0]
        # Hand-edited / legacy file shape: bare strings instead of dicts.
        post.sub_platform_status = {
            "telegram": "posted",
            "discord": "queued",
        }
        tg = FakeClient("telegram")
        dc = FakeClient("discord")
        clients = {"telegram": [tg], "discord": [dc], "bluesky": []}

        results, _ = self._push(post, proj, clients,
                                export_paths=["img_a.png"])

        # "posted" string still counts as posted; anything else sends.
        self.assertEqual(tg.calls, [])
        self.assertEqual(len(dc.calls), 1)
        self.assertEqual([r.platform for r in results], ["discord"])

    def test_none_value_does_not_crash_guard(self):
        proj = make_project(self.tmp_path)
        post = proj.posts[0]
        post.sub_platform_status = {"telegram": None}
        tg = FakeClient("telegram")
        clients = {"telegram": [tg], "discord": [], "bluesky": []}

        results, _ = self._push(post, proj, clients,
                                export_paths=["img_a.png"])

        self.assertEqual(len(tg.calls), 1)
        self.assertEqual([r.platform for r in results], ["telegram"])


if __name__ == "__main__":
    unittest.main()
