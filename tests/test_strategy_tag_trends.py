"""strategy._section_tag_trends — bucket posted-counts per tag into
underrepresented / low / moderate / high. Pin the threshold edges
(0, 5, 10) so a refactor doesn't drift them and silently mis-label
the user's pacing recommendations."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _proj_with_history(tag, n_posted):
    """Build a Project with n posts that all touch one asset tagged `tag`."""
    from doxyedit.models import Project, Asset, SocialPost, SocialPostStatus
    asset = Asset(id="a1", tags=[tag])
    posts = [SocialPost(id=f"p{i}", asset_ids=["a1"],
                        status=SocialPostStatus.POSTED)
             for i in range(n_posted)]
    p = Project()
    p.assets = [asset]
    p.posts = posts
    return p, asset


class TestSectionTagTrends(unittest.TestCase):
    def test_no_tags_returns_placeholder(self):
        from doxyedit.strategy import _section_tag_trends
        from doxyedit.models import Project, Asset
        out = _section_tag_trends([Asset(id="a1")], Project())
        self.assertIn("No tags to analyze", out)

    def test_zero_posts_marks_underrepresented(self):
        from doxyedit.strategy import _section_tag_trends
        proj, asset = _proj_with_history("marty", 0)
        out = _section_tag_trends([asset], proj)
        self.assertIn("UNDERREPRESENTED", out)

    def test_low_bucket_below_5(self):
        from doxyedit.strategy import _section_tag_trends
        proj, asset = _proj_with_history("marty", 3)
        out = _section_tag_trends([asset], proj)
        self.assertIn("low", out)
        self.assertNotIn("UNDERREPRESENTED", out)
        self.assertNotIn("moderate", out)

    def test_moderate_bucket_5_to_9(self):
        from doxyedit.strategy import _section_tag_trends
        proj, asset = _proj_with_history("marty", 5)
        out = _section_tag_trends([asset], proj)
        self.assertIn("moderate", out)

    def test_high_bucket_at_10(self):
        from doxyedit.strategy import _section_tag_trends
        proj, asset = _proj_with_history("marty", 10)
        out = _section_tag_trends([asset], proj)
        self.assertIn("high frequency", out)
        self.assertIn("consider spacing", out)

    def test_count_value_appears(self):
        from doxyedit.strategy import _section_tag_trends
        proj, asset = _proj_with_history("marty", 7)
        out = _section_tag_trends([asset], proj)
        self.assertIn("7", out)

    def test_only_posted_status_counts(self):
        """Drafts and queued shouldn't bump the count — bucket flips
        based on POSTED only."""
        from doxyedit.strategy import _section_tag_trends
        from doxyedit.models import (Project, Asset, SocialPost,
                                      SocialPostStatus)
        asset = Asset(id="a1", tags=["marty"])
        posts = [
            SocialPost(id="p0", asset_ids=["a1"],
                       status=SocialPostStatus.DRAFT),
            SocialPost(id="p1", asset_ids=["a1"],
                       status=SocialPostStatus.QUEUED),
        ]
        p = Project()
        p.assets = [asset]
        p.posts = posts
        out = _section_tag_trends([asset], p)
        # Two non-posted entries → still 0 → UNDERREPRESENTED.
        self.assertIn("UNDERREPRESENTED", out)


if __name__ == "__main__":
    unittest.main()
