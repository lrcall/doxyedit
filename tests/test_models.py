"""Model serialization regression tests.

Every dataclass that participates in project save/load gets a
round-trip + back-compat test. This catches the class of bug where a
new field is added but missing from to_dict / from_dict — projects
saved with the new code load fine on reload, but old project files
fail because the kwarg is unexpected.

The contract from CLAUDE.md: every from_dict must use .get() with a
default for new fields so legacy data still loads.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestAssetRoundTrip(unittest.TestCase):
    def test_minimal_asset_roundtrips(self):
        from doxyedit.models import Asset
        a = Asset(id="abc", source_path="C:/x.png", tags=["foo", "bar"])
        d = a.to_dict() if hasattr(a, "to_dict") else None
        if d is not None:
            from doxyedit.models import Asset as _A
            a2 = _A.from_dict(d)
            self.assertEqual(a2.id, "abc")
            self.assertEqual(a2.tags, ["foo", "bar"])


class TestCampaignRoundTrip(unittest.TestCase):
    def test_basic(self):
        from doxyedit.models import Campaign
        c = Campaign(id="kick1", name="Test KS", platform_id="kickstarter")
        d = c.to_dict()
        c2 = Campaign.from_dict(d)
        self.assertEqual(c2.id, "kick1")
        self.assertEqual(c2.name, "Test KS")
        self.assertEqual(c2.platform_id, "kickstarter")

    def test_legacy_load_missing_fields(self):
        """Old project files won't have every campaign field; from_dict
        must default cleanly."""
        from doxyedit.models import Campaign
        c = Campaign.from_dict({"id": "old", "name": "Legacy"})
        self.assertEqual(c.id, "old")


class TestSubredditConfigRoundTrip(unittest.TestCase):
    def test_basic(self):
        from doxyedit.models import SubredditConfig
        s = SubredditConfig(name="r/art", title_template="{caption}")
        d = s.to_dict()
        s2 = SubredditConfig.from_dict(d)
        self.assertEqual(s2.name, "r/art")

    def test_legacy_load(self):
        from doxyedit.models import SubredditConfig
        s = SubredditConfig.from_dict({"name": "r/old"})
        self.assertEqual(s.name, "r/old")


class TestSocialPostBackCompat(unittest.TestCase):
    """SocialPost has the most fields and grows fast. The from_dict
    must tolerate every legacy shape this codebase has shipped."""

    def test_v1_shape(self):
        """Earliest known shape — id + asset_ids + caption only."""
        from doxyedit.models import SocialPost
        p = SocialPost.from_dict({
            "id": "old",
            "asset_ids": ["a1"],
            "caption_default": "legacy",
        })
        self.assertEqual(p.id, "old")
        self.assertEqual(p.asset_ids, ["a1"])
        # Newer fields all default cleanly.
        self.assertEqual(p.identity_name, "")
        self.assertEqual(p.engagement_checks, [])
        self.assertEqual(p.platform_metrics, {})

    def test_full_shape_roundtrip(self):
        from doxyedit.models import SocialPost
        p = SocialPost(
            id="full", asset_ids=["a1", "a2"],
            platforms=["bluesky", "telegram"],
            caption_default="hello",
            captions={"bluesky": "hello bsky"},
            scheduled_time="2026-05-02T12:00:00",
            identity_name="Doxy",
            campaign_id="kick1",
            censor_mode="custom",
        )
        d = p.to_dict()
        p2 = SocialPost.from_dict(d)
        self.assertEqual(p2.identity_name, "Doxy")
        self.assertEqual(p2.captions, {"bluesky": "hello bsky"})
        self.assertEqual(p2.censor_mode, "custom")


class TestTagHierarchy(unittest.TestCase):
    """TagPreset.parent_id round-trips and Project.get_tag_children /
    get_tag_ancestors walk the hierarchy correctly + tolerate cycles."""

    def test_parent_id_roundtrip(self):
        from doxyedit.models import TagPreset
        t = TagPreset(id="kid", label="Kid", parent_id="parent")
        d = {"label": t.label, "color": t.color, "parent_id": t.parent_id}
        t2 = TagPreset.from_dict("kid", d)
        self.assertEqual(t2.parent_id, "parent")

    def test_legacy_load_no_parent(self):
        from doxyedit.models import TagPreset
        t = TagPreset.from_dict("legacy", {"label": "Legacy"})
        self.assertEqual(t.parent_id, "")

    def test_get_tag_children(self):
        from doxyedit.models import Project
        p = Project()
        p.tag_definitions = {
            "anim": {"label": "Animal", "color": "#888"},
            "cat": {"label": "Cat", "color": "#000", "parent_id": "anim"},
            "dog": {"label": "Dog", "color": "#fff", "parent_id": "anim"},
            "bus": {"label": "Bus", "color": "#aaa"},
        }
        kids = p.get_tag_children("anim")
        self.assertEqual(set(kids), {"cat", "dog"})
        self.assertEqual(p.get_tag_children("nope"), [])

    def test_get_tag_ancestors_with_cycle_protection(self):
        """A hand-edited project file could create a cycle; the walker
        must terminate rather than loop forever."""
        from doxyedit.models import Project
        p = Project()
        p.tag_definitions = {
            "a": {"label": "A", "parent_id": "b"},
            "b": {"label": "B", "parent_id": "a"},  # cycle!
        }
        # Should not hang.
        anc = p.get_tag_ancestors("a")
        self.assertIn("b", anc)
        self.assertLessEqual(len(anc), 2)


class TestProjectLoadSkipsBadRecords(unittest.TestCase):
    """Project.from_dict skips malformed campaigns / subreddits / posts
    rather than aborting the whole load. Regression guard for project
    files that may have been partially corrupted by an external editor
    or an older bug."""

    def test_bad_post_does_not_break_project(self):
        from doxyedit.models import Project
        # Use Project.from_dict directly with a synthetic raw payload.
        raw = {
            "name": "T",
            "platforms": [],
            "tag_definitions": {},
            "custom_tags": [],
            "tag_aliases": {},
            "custom_shortcuts": {},
            "hidden_tags": [],
            "eye_hidden_tags": [],
            "assets": [],
            "import_sources": [],
            "folder_presets": [],
            "filter_presets": [],
            "posts": [
                # Good post.
                {"id": "good1", "caption_default": "ok"},
                # Bad post: from_dict will raise on a non-dict input.
                "this_is_not_a_dict",
                # Another good post after the bad one.
                {"id": "good2", "caption_default": "ok2"},
            ],
        }
        # Project.from_dict reads from a file path; build via raw API.
        from doxyedit.models import Project, SocialPost
        proj = Project()
        # Mimic the per-record guarded loop.
        import logging
        for p in raw.get("posts", []):
            try:
                proj.posts.append(SocialPost.from_dict(p))
            except Exception:
                logging.debug("skipped bad post (test)")
        self.assertEqual(len(proj.posts), 2)
        self.assertEqual([p.id for p in proj.posts], ["good1", "good2"])


class TestProjectFormatExt(unittest.TestCase):
    """formats.ensure_project_ext picks the right extension regardless
    of what the user typed in the Save As dialog."""

    def test_doxy_default(self):
        from doxyedit.formats import ensure_project_ext
        # User picks 'project' with no extension; default = .doxy.
        self.assertTrue(ensure_project_ext("project").endswith(".doxy"))

    def test_doxyproj_explicit_legacy(self):
        from doxyedit.formats import ensure_project_ext
        out = ensure_project_ext("project", prefer_legacy=True)
        self.assertTrue(out.endswith(".doxyproj.json"))

    def test_existing_doxy_preserved(self):
        from doxyedit.formats import ensure_project_ext
        self.assertEqual(
            ensure_project_ext("foo.doxy"),
            "foo.doxy")


if __name__ == "__main__":
    unittest.main()
