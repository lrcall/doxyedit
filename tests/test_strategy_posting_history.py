"""strategy._section_posting_history — per-tag and per-asset
posting summary in the briefing. Pin the FRESH marker (never-posted
character/tag → flagged as good engagement candidate) and the
asset previously-posted line — both inform user posting cadence
decisions."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _proj(posts=None, assets=None):
    from doxyedit.models import Project
    p = Project()
    if posts is not None:
        p.posts = posts
    if assets is not None:
        p.assets = assets
    return p


class TestSectionPostingHistory(unittest.TestCase):
    def test_no_data_message(self):
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import Project, SocialPost
        out = _section_posting_history([], SocialPost(), Project())
        self.assertIn("## Posting History", out)
        self.assertIn("No posting history available", out)

    def test_fresh_marker_for_unposted_character(self):
        """Character with zero posted/queued posts → FRESH marker."""
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import SocialPost, Asset
        proj = _proj()
        out = _section_posting_history(
            [Asset(id="a1", tags=["marty"])], SocialPost(), proj)
        self.assertIn("FRESH", out)

    def test_posted_count_shown(self):
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import SocialPost, Asset, SocialPostStatus
        prev = SocialPost(id="prev", asset_ids=["a1"],
                          status=SocialPostStatus.POSTED,
                          scheduled_time="2026-04-15T10:00",
                          platforms=["bluesky"])
        proj = _proj(posts=[prev], assets=[Asset(id="a1", tags=["marty"])])
        out = _section_posting_history(
            [Asset(id="a1", tags=["marty"])], SocialPost(), proj)
        self.assertIn("posted 1x", out)

    def test_queued_count_shown(self):
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import SocialPost, Asset, SocialPostStatus
        q = SocialPost(id="q", asset_ids=["a1"],
                       status=SocialPostStatus.QUEUED)
        proj = _proj(posts=[q], assets=[Asset(id="a1", tags=["marty"])])
        out = _section_posting_history(
            [Asset(id="a1", tags=["marty"])], SocialPost(), proj)
        self.assertIn("queued 1x", out)

    def test_asset_never_posted_line(self):
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import SocialPost, Asset
        proj = _proj()
        out = _section_posting_history(
            [Asset(id="a1")], SocialPost(), proj)
        self.assertIn("Asset a1: never posted", out)

    def test_asset_previously_posted_line(self):
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import SocialPost, Asset, SocialPostStatus
        prev = SocialPost(id="prev", asset_ids=["a1"],
                          status=SocialPostStatus.POSTED)
        proj = _proj(posts=[prev])
        out = _section_posting_history(
            [Asset(id="a1")], SocialPost(), proj)
        self.assertIn("Asset a1: previously posted", out)

    def test_falls_back_to_unique_tags_when_no_characters(self):
        """No character tags → falls back to first 5 unique tags."""
        from doxyedit.strategy import _section_posting_history
        from doxyedit.models import SocialPost, Asset
        proj = _proj()
        out = _section_posting_history(
            [Asset(id="a1", tags=["random_tag_xyz"])],
            SocialPost(), proj)
        self.assertIn("random_tag_xyz", out)


if __name__ == "__main__":
    unittest.main()
