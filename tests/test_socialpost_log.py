"""SocialPost.log_event — append-only event history per post.

Used to populate the per-post "Posting Log..." dialog the user opens
from the timeline. Pin the entry shape (5 keys: ts, platform, action,
url, detail) and the timestamp format so a future change doesn't
break log replay."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestSocialPostLogEvent(unittest.TestCase):
    def test_starts_empty(self):
        from doxyedit.models import SocialPost
        self.assertEqual(SocialPost().posting_log, [])

    def test_appends_entry(self):
        from doxyedit.models import SocialPost
        p = SocialPost()
        p.log_event(platform="bluesky", action="queued")
        self.assertEqual(len(p.posting_log), 1)

    def test_entry_shape(self):
        from doxyedit.models import SocialPost
        p = SocialPost()
        p.log_event(platform="bluesky", action="posted",
                    url="https://bsky.app/x", detail="ok")
        e = p.posting_log[0]
        self.assertEqual(set(e.keys()),
                         {"ts", "platform", "action", "url", "detail"})
        self.assertEqual(e["platform"], "bluesky")
        self.assertEqual(e["action"], "posted")
        self.assertEqual(e["url"], "https://bsky.app/x")
        self.assertEqual(e["detail"], "ok")

    def test_timestamp_iso_seconds_format(self):
        """ts must look like YYYY-MM-DDTHH:MM:SS (no microseconds, no
        timezone). Format = isoformat(timespec='seconds')."""
        from doxyedit.models import SocialPost
        p = SocialPost()
        p.log_event(platform="t", action="x")
        ts = p.posting_log[0]["ts"]
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_default_url_and_detail_blank(self):
        from doxyedit.models import SocialPost
        p = SocialPost()
        p.log_event(platform="x", action="queued")
        self.assertEqual(p.posting_log[0]["url"], "")
        self.assertEqual(p.posting_log[0]["detail"], "")

    def test_multiple_appends_preserve_order(self):
        from doxyedit.models import SocialPost
        p = SocialPost()
        for i, action in enumerate(("queued", "pushed", "posted")):
            p.log_event(platform="bluesky", action=action,
                        detail=f"step-{i}")
        actions = [e["action"] for e in p.posting_log]
        self.assertEqual(actions, ["queued", "pushed", "posted"])


if __name__ == "__main__":
    unittest.main()
