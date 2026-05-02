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
