"""strategy.py — post-history aggregation helpers.

These run on every Generate Briefing call to summarize the user's
posting history into the markdown context Claude reads. Wrong counts
or wrong "last posted" → bad strategy advice."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _post(**kwargs):
    from doxyedit.models import SocialPost, SocialPostStatus
    defaults = dict(
        id="p", asset_ids=[], platforms=[], status=SocialPostStatus.DRAFT,
        scheduled_time="", created_at="", updated_at="",
    )
    defaults.update(kwargs)
    return SocialPost(**defaults)


class TestPostStatusCounts(unittest.TestCase):
    def test_mixed_statuses_count(self):
        from doxyedit.strategy import _post_status_counts
        from doxyedit.models import SocialPostStatus as S
        posts = [
            _post(status=S.POSTED), _post(status=S.POSTED),
            _post(status=S.QUEUED),
            _post(status=S.DRAFT),
            _post(status=S.FAILED),
        ]
        posted, queued = _post_status_counts(posts)
        self.assertEqual(posted, 2)
        self.assertEqual(queued, 1)

    def test_empty_list(self):
        from doxyedit.strategy import _post_status_counts
        self.assertEqual(_post_status_counts([]), (0, 0))


class TestAssetEverPosted(unittest.TestCase):
    def test_returns_true_when_posted(self):
        from doxyedit.strategy import _asset_ever_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [_post(asset_ids=["a1"], status=S.POSTED)]
        self.assertTrue(_asset_ever_posted("a1", posts))

    def test_returns_false_when_only_drafted(self):
        from doxyedit.strategy import _asset_ever_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [_post(asset_ids=["a1"], status=S.DRAFT),
                 _post(asset_ids=["a1"], status=S.QUEUED)]
        self.assertFalse(_asset_ever_posted("a1", posts))

    def test_returns_false_when_asset_absent(self):
        from doxyedit.strategy import _asset_ever_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [_post(asset_ids=["other"], status=S.POSTED)]
        self.assertFalse(_asset_ever_posted("a1", posts))


class TestLastPosted(unittest.TestCase):
    def test_picks_most_recent_posted(self):
        from doxyedit.strategy import _last_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [
            _post(status=S.POSTED, scheduled_time="2026-01-01T10:00",
                  platforms=["twitter"]),
            _post(status=S.POSTED, scheduled_time="2026-04-15T10:00",
                  platforms=["bluesky"]),
            _post(status=S.POSTED, scheduled_time="2026-02-10T10:00",
                  platforms=["telegram"]),
        ]
        result = _last_posted(posts)
        self.assertIsNotNone(result)
        dt, plat = result
        self.assertEqual(dt, datetime(2026, 4, 15, 10, 0))
        self.assertEqual(plat, "bluesky")

    def test_ignores_non_posted(self):
        from doxyedit.strategy import _last_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [
            _post(status=S.QUEUED, scheduled_time="2026-04-15T10:00"),
            _post(status=S.POSTED, scheduled_time="2026-01-01T10:00",
                  platforms=["x"]),
        ]
        result = _last_posted(posts)
        self.assertIsNotNone(result)
        dt, _ = result
        self.assertEqual(dt, datetime(2026, 1, 1, 10, 0))

    def test_falls_back_to_updated_then_created(self):
        from doxyedit.strategy import _last_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [
            _post(status=S.POSTED, scheduled_time="",
                  updated_at="2026-04-15T10:00", platforms=["t"]),
        ]
        result = _last_posted(posts)
        self.assertEqual(result[0], datetime(2026, 4, 15, 10, 0))

    def test_no_posted_returns_none(self):
        from doxyedit.strategy import _last_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [_post(status=S.DRAFT, scheduled_time="2026-04-15T10:00")]
        self.assertIsNone(_last_posted(posts))

    def test_multi_platform_joined(self):
        from doxyedit.strategy import _last_posted
        from doxyedit.models import SocialPostStatus as S
        posts = [_post(status=S.POSTED, scheduled_time="2026-04-15T10:00",
                       platforms=["bluesky", "telegram"])]
        _, plat = _last_posted(posts)
        self.assertEqual(plat, "bluesky, telegram")


if __name__ == "__main__":
    unittest.main()
