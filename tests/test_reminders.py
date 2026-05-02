"""reminders.generate_engagement_windows — produces a 5-step
engagement check schedule per platform after a post goes live. Pin
the schedule offsets and the URL pattern lookup so a refactor can't
silently drop the +1day metrics check or break the bsky URL format."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _post(**kw):
    from doxyedit.models import SocialPost
    return SocialPost(**({"id": "p1", "platforms": ["twitter"]} | kw))


class TestGenerateEngagementWindows(unittest.TestCase):
    def test_five_windows_per_platform(self):
        from doxyedit.reminders import generate_engagement_windows
        windows = generate_engagement_windows(_post(platforms=["twitter"]),
                                              connected_accounts=[])
        self.assertEqual(len(windows), 5)

    def test_actions_match_schedule(self):
        from doxyedit.reminders import generate_engagement_windows
        windows = generate_engagement_windows(_post(), connected_accounts=[])
        actions = [w.action for w in windows]
        self.assertEqual(actions, [
            "first_reactions", "peak_engagement", "follow_up",
            "next_day", "metrics",
        ])

    def test_check_at_is_increasing(self):
        from doxyedit.reminders import generate_engagement_windows
        windows = generate_engagement_windows(_post(), connected_accounts=[])
        times = [datetime.fromisoformat(w.check_at) for w in windows]
        for a, b in zip(times, times[1:]):
            self.assertLess(a, b)

    def test_offsets_match_spec(self):
        """Specified offsets: 15m / 60m / 240m / 1440m / 2880m. If anyone
        tightens these the user gets prompted at the wrong wall-clock
        moments — pin them down."""
        from doxyedit.reminders import generate_engagement_windows
        windows = generate_engagement_windows(_post(), connected_accounts=[])
        times = [datetime.fromisoformat(w.check_at) for w in windows]
        anchor = times[0]
        # First window is +15m from "now". Compute the implicit base time.
        base = anchor - timedelta(minutes=15)
        expected_offsets = [15, 60, 240, 1440, 2880]
        for w, off in zip(windows, expected_offsets):
            actual = datetime.fromisoformat(w.check_at)
            self.assertEqual(actual, base + timedelta(minutes=off))

    def test_multi_platform_doubles_count(self):
        from doxyedit.reminders import generate_engagement_windows
        post = _post(platforms=["twitter", "bluesky"])
        windows = generate_engagement_windows(post, connected_accounts=[])
        self.assertEqual(len(windows), 10)
        self.assertEqual({w.platform for w in windows}, {"twitter", "bluesky"})

    def test_bluesky_url_format(self):
        from doxyedit.reminders import generate_engagement_windows
        post = _post(platforms=["bluesky"])
        accounts = [{"id": "bluesky", "name": "Display Name (@handle.bsky.social)"}]
        windows = generate_engagement_windows(post, accounts)
        self.assertTrue(all("bsky.app/profile/" in w.url for w in windows))

    def test_twitter_url_format(self):
        from doxyedit.reminders import generate_engagement_windows
        post = _post(platforms=["twitter"])
        accounts = [{"id": "twitter", "name": "Display (@user)"}]
        windows = generate_engagement_windows(post, accounts)
        self.assertTrue(all("x.com/" in w.url for w in windows))

    def test_unknown_platform_url_blank(self):
        from doxyedit.reminders import generate_engagement_windows
        post = _post(platforms=["mastodon"])
        windows = generate_engagement_windows(post, [])
        self.assertTrue(all(w.url == "" for w in windows))

    def test_post_id_carries_through(self):
        from doxyedit.reminders import generate_engagement_windows
        post = _post(id="abc-123")
        windows = generate_engagement_windows(post, [])
        self.assertTrue(all(w.post_id == "abc-123" for w in windows))


if __name__ == "__main__":
    unittest.main()
