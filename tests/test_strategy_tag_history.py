"""strategy._build_tag_post_history — maps tags to posts that carry
assets with those tags. Used by the briefing's "tag trends" section.
A regression here mis-attributes posts to tags and the AI strategy
gets bad input."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _project_with_assets(asset_specs):
    """Build a Project with assets keyed by id, each carrying given tags."""
    from doxyedit.models import Project, Asset
    proj = Project()
    proj.assets = [Asset(id=aid, tags=list(tags)) for aid, tags in asset_specs]
    return proj


def _post(asset_ids):
    from doxyedit.models import SocialPost
    return SocialPost(asset_ids=list(asset_ids))


class TestBuildTagPostHistory(unittest.TestCase):
    def test_empty_posts(self):
        from doxyedit.strategy import _build_tag_post_history
        proj = _project_with_assets([])
        self.assertEqual(_build_tag_post_history([], proj), {})

    def test_single_post_single_asset(self):
        from doxyedit.strategy import _build_tag_post_history
        proj = _project_with_assets([("a1", ["marty", "color"])])
        post = _post(["a1"])
        out = _build_tag_post_history([post], proj)
        self.assertEqual(set(out.keys()), {"marty", "color"})
        self.assertEqual(out["marty"], [post])

    def test_post_dedupes_repeated_tag_across_assets(self):
        """If two assets in the same post share a tag, the post must
        appear once under that tag — not twice."""
        from doxyedit.strategy import _build_tag_post_history
        proj = _project_with_assets([
            ("a1", ["marty"]),
            ("a2", ["marty", "color"]),
        ])
        post = _post(["a1", "a2"])
        out = _build_tag_post_history([post], proj)
        self.assertEqual(out["marty"], [post])  # not [post, post]

    def test_skips_unknown_asset_ids(self):
        from doxyedit.strategy import _build_tag_post_history
        proj = _project_with_assets([("a1", ["marty"])])
        post = _post(["a1", "ghost"])  # ghost not in project
        out = _build_tag_post_history([post], proj)
        self.assertEqual(out, {"marty": [post]})

    def test_multiple_posts_grouped_per_tag(self):
        from doxyedit.strategy import _build_tag_post_history
        proj = _project_with_assets([
            ("a1", ["marty"]),
            ("a2", ["jenni"]),
        ])
        p1 = _post(["a1"])
        p2 = _post(["a2"])
        p3 = _post(["a1", "a2"])
        out = _build_tag_post_history([p1, p2, p3], proj)
        self.assertEqual(out["marty"], [p1, p3])
        self.assertEqual(out["jenni"], [p2, p3])


if __name__ == "__main__":
    unittest.main()
