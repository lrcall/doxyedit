"""Project.summary() and the small accessors that share it
(get_post / get_asset / path_index / tag_users). Used by the CLI
`python -m doxyedit summary` and several panels' status counters.
A regression here either crashes the CLI or shows wrong asset
counts to the user."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestProjectSummary(unittest.TestCase):
    def test_empty_project(self):
        from doxyedit.models import Project
        p = Project()
        p.platforms = []  # silence built-in platform list for asset-counts test
        s = p.summary()
        self.assertEqual(s["total_assets"], 0)
        self.assertEqual(s["starred"], 0)
        self.assertEqual(s["needs_censor"], 0)
        self.assertEqual(s["platforms"], {})

    def test_counts_starred_and_censored(self):
        from doxyedit.models import Project, Asset, CensorRegion
        p = Project()
        p.assets = [
            Asset(id="a", starred=1),
            Asset(id="b", starred=3),
            Asset(id="c", starred=0,
                  censors=[CensorRegion(x=0, y=0, w=10, h=10)]),
        ]
        s = p.summary()
        self.assertEqual(s["total_assets"], 3)
        self.assertEqual(s["starred"], 2)  # a + b
        self.assertEqual(s["needs_censor"], 1)

    def test_platform_assignment_counts(self):
        from doxyedit.models import (Project, Asset, PlatformAssignment,
                                      PostStatus, PLATFORMS)
        plat_id = next(iter(PLATFORMS))
        p = Project()
        p.platforms = [plat_id]
        p.assets = [
            Asset(id="a", assignments=[
                PlatformAssignment(platform=plat_id, slot="x",
                                   status=PostStatus.POSTED)]),
            Asset(id="b", assignments=[
                PlatformAssignment(platform=plat_id, slot="y",
                                   status=PostStatus.PENDING)]),
        ]
        s = p.summary()
        self.assertEqual(s["platforms"][plat_id]["assigned"], 2)
        self.assertEqual(s["platforms"][plat_id]["posted"], 1)


class TestProjectIndexes(unittest.TestCase):
    def test_get_asset_uses_id_index(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [Asset(id="a1"), Asset(id="a2")]
        self.assertIs(p.get_asset("a1"), p.assets[0])
        self.assertIsNone(p.get_asset("ghost"))

    def test_path_index_holds_source_paths(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [Asset(id="a1", source_path="/x/1.png"),
                    Asset(id="a2", source_path="/x/2.png")]
        self.assertEqual(p.path_index, {"/x/1.png", "/x/2.png"})

    def test_tag_users_inverted_index(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [
            Asset(id="a1", tags=["marty"]),
            Asset(id="a2", tags=["marty", "color"]),
        ]
        self.assertEqual(p.tag_users["marty"], {"a1", "a2"})
        self.assertEqual(p.tag_users["color"], {"a2"})

    def test_invalidate_index_does_not_bump_version(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [Asset(id="a1")]
        p._version = 5
        p.invalidate_index()
        self.assertEqual(p._version, 5)

    def test_mark_mutated_bumps_version_and_clears_indexes(self):
        from doxyedit.models import Project, Asset
        p = Project()
        p.assets = [Asset(id="a1")]
        p._version = 5
        # Trigger index build
        _ = p.path_index
        p.mark_mutated()
        self.assertGreater(p._version, 5)
        self.assertIsNone(p._asset_index)


class TestGetPost(unittest.TestCase):
    def test_finds_existing(self):
        from doxyedit.models import Project, SocialPost
        p = Project()
        p.posts = [SocialPost(id="p1"), SocialPost(id="p2")]
        self.assertIs(p.get_post("p2"), p.posts[1])

    def test_missing_returns_none(self):
        from doxyedit.models import Project
        self.assertIsNone(Project().get_post("ghost"))


if __name__ == "__main__":
    unittest.main()
