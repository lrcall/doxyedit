"""SocialPost.from_dict — defensive defaults that prevent older
project files (or hand-edited JSON) from crashing the loader. Each
default below corresponds to a field that was added in a later
version; pin them so a later refactor can't drop one."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestSocialPostFromDict(unittest.TestCase):
    def test_minimal_dict_loads_with_defaults(self):
        from doxyedit.models import SocialPost
        p = SocialPost.from_dict({"id": "p1"})
        self.assertEqual(p.id, "p1")
        self.assertEqual(p.asset_ids, [])
        self.assertEqual(p.platforms, [])
        self.assertEqual(p.captions, {})
        self.assertEqual(p.identity_name, "")
        self.assertEqual(p.posting_log, [])

    def test_unknown_keys_ignored(self):
        """Forward-compat: a project file from a future DoxyEdit may
        carry fields we don't know yet. from_dict must not crash —
        it picks named keys via .get and ignores the rest."""
        from doxyedit.models import SocialPost
        p = SocialPost.from_dict({
            "id": "p1",
            "totally_made_up_future_field": {"nested": [1, 2, 3]},
        })
        self.assertEqual(p.id, "p1")

    def test_release_chain_rebuilt_as_objects(self):
        from doxyedit.models import SocialPost, ReleaseStep
        p = SocialPost.from_dict({
            "id": "p1",
            "release_chain": [
                {"platform": "bluesky", "delay_hours": 0, "status": "posted"},
                {"platform": "twitter", "delay_hours": 24},
            ],
        })
        self.assertEqual(len(p.release_chain), 2)
        self.assertIsInstance(p.release_chain[0], ReleaseStep)
        self.assertEqual(p.release_chain[0].platform, "bluesky")
        self.assertEqual(p.release_chain[1].delay_hours, 24)

    def test_status_defaults_to_draft(self):
        from doxyedit.models import SocialPost, SocialPostStatus
        p = SocialPost.from_dict({"id": "p1"})
        self.assertEqual(p.status, SocialPostStatus.DRAFT)

    def test_explicit_status_preserved(self):
        from doxyedit.models import SocialPost, SocialPostStatus
        p = SocialPost.from_dict({"id": "p1",
                                   "status": SocialPostStatus.POSTED})
        self.assertEqual(p.status, SocialPostStatus.POSTED)

    def test_censor_mode_defaults_to_auto(self):
        from doxyedit.models import SocialPost
        p = SocialPost.from_dict({"id": "p1"})
        self.assertEqual(p.censor_mode, "auto")

    def test_posting_log_is_copy_not_alias(self):
        """posting_log = list(d.get(...)) should produce an independent
        list — mutating the loaded post mustn't reach back into the
        source dict."""
        from doxyedit.models import SocialPost
        src_log = [{"ts": "x", "platform": "p", "action": "queued",
                    "url": "", "detail": ""}]
        d = {"id": "p1", "posting_log": src_log}
        p = SocialPost.from_dict(d)
        p.posting_log.append({"ts": "y", "platform": "p2",
                               "action": "posted", "url": "", "detail": ""})
        self.assertEqual(len(src_log), 1)


if __name__ == "__main__":
    unittest.main()
