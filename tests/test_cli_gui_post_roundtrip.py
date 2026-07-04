"""CLI <-> Project API post round trip. A post created through the
real `python -m doxyedit post create` subprocess must come back
intact through Project.load, and a Project-API edit saved to disk
must be visible to the CLI `post list --format json` view. Pure
subprocess + file assertions - no GUI construction, no QApplication.
Project files come from tests/factory.py (real tiny PNGs)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.factory import make_saved_project  # noqa: E402


def _run_cli(*args) -> subprocess.CompletedProcess:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(
        [sys.executable, "-m", "doxyedit", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, **kwargs)


class TestCliCreateVisibleToProjectLoad(unittest.TestCase):
    def test_post_create_round_trips_through_load(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            proj, proj_path = make_saved_project(
                Path(td), n_assets=2, with_posts=False)
            asset_id = proj.assets[0].id

            r = _run_cli(
                "post", "create", str(proj_path),
                "--assets", asset_id,
                "--platforms", "twitter,patreon",
                "--caption", "CLI made this",
                "--caption-twitter", "tw flavored",
                "--schedule", "2026-08-01T10:00:00",
                "--strategy-notes", "cli strategy",
                "--category", "86698",
            )
            self.assertEqual(
                r.returncode, 0,
                f"stdout={r.stdout!r}\nstderr={r.stderr!r}")
            self.assertIn("Created post", r.stdout)

            reloaded = Project.load(str(proj_path))
            self.assertEqual(len(reloaded.posts), 1)
            post = reloaded.posts[0]
            self.assertEqual(post.asset_ids, [asset_id])
            self.assertEqual(post.platforms, ["twitter", "patreon"])
            self.assertEqual(post.caption_default, "CLI made this")
            self.assertEqual(post.captions.get("twitter"), "tw flavored")
            self.assertEqual(post.scheduled_time, "2026-08-01T10:00:00")
            self.assertEqual(post.strategy_notes, "cli strategy")
            self.assertEqual(post.category_id, "86698")
            # SocialPostStatus is a str Enum, so plain compare works.
            self.assertEqual(post.status, "draft")
            self.assertTrue(post.id)          # CLI assigns a uuid
            self.assertTrue(post.created_at)  # CLI stamps timestamps

    def test_post_create_json_matches_saved_file(self):
        """--format json output and the saved file agree on the id."""
        with tempfile.TemporaryDirectory() as td:
            proj, proj_path = make_saved_project(
                Path(td), n_assets=1, with_posts=False)
            r = _run_cli(
                "post", "create", str(proj_path),
                "--platforms", "twitter",
                "--caption", "json check",
                "--format", "json",
            )
            self.assertEqual(
                r.returncode, 0,
                f"stdout={r.stdout!r}\nstderr={r.stderr!r}")
            created = json.loads(r.stdout)
            on_disk = json.loads(
                Path(proj_path).read_text(encoding="utf-8"))
            self.assertEqual(len(on_disk["posts"]), 1)
            self.assertEqual(on_disk["posts"][0]["id"], created["id"])
            self.assertEqual(on_disk["posts"][0]["caption_default"],
                             "json check")


class TestApiEditVisibleToCli(unittest.TestCase):
    def test_project_api_edit_shows_in_cli_post_list(self):
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            proj, proj_path = make_saved_project(
                Path(td), n_assets=1, with_posts=False)
            asset_id = proj.assets[0].id

            # 1. Create via CLI.
            r = _run_cli(
                "post", "create", str(proj_path),
                "--assets", asset_id,
                "--platforms", "twitter",
                "--caption", "original caption",
            )
            self.assertEqual(
                r.returncode, 0,
                f"stdout={r.stdout!r}\nstderr={r.stderr!r}")

            # 2. Modify via the Project API and save.
            loaded = Project.load(str(proj_path))
            post = loaded.posts[0]
            post.caption_default = "API edited caption"
            post.status = "queued"
            post.log_event(platform="twitter", action="queued",
                           detail="edited via API in test")
            loaded.save(str(proj_path))

            # 3. The CLI view must see the edit.
            r2 = _run_cli("post", "list", str(proj_path),
                          "--format", "json")
            self.assertEqual(
                r2.returncode, 0,
                f"stdout={r2.stdout!r}\nstderr={r2.stderr!r}")
            posts = json.loads(r2.stdout)
            match = [p for p in posts if p["id"] == post.id]
            self.assertEqual(len(match), 1)
            self.assertEqual(match[0]["caption_default"],
                             "API edited caption")
            self.assertEqual(match[0]["status"], "queued")
            self.assertEqual(len(match[0]["posting_log"]), 1)
            self.assertEqual(match[0]["posting_log"][0]["action"],
                             "queued")

            # 4. Status filter agrees too.
            r3 = _run_cli("post", "list", str(proj_path),
                          "--status", "queued", "--format", "json")
            self.assertEqual(r3.returncode, 0)
            self.assertEqual(len(json.loads(r3.stdout)), 1)


if __name__ == "__main__":
    unittest.main()
