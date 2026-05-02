"""strategy._section_brand_notes / _section_asset_context / generate_strategy_briefing
end-to-end smoke. Pin the markdown shape so a refactor doesn't drop
required headings or mangle the structure Claude reads."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _project(identity_kw=None, posts=None, assets=None):
    from doxyedit.models import Project
    p = Project()
    if identity_kw is not None:
        # Project.identity is a dict that get_identity() splats into a
        # CollectionIdentity, so pass a plain dict here.
        p.identity = dict(identity_kw)
    if posts is not None:
        p.posts = posts
    if assets is not None:
        p.assets = assets
    return p


class TestSectionBrandNotes(unittest.TestCase):
    def test_unconfigured_identity_marks_voice_not_set(self):
        from doxyedit.strategy import _section_brand_notes
        from doxyedit.models import Project
        out = _section_brand_notes(Project())
        self.assertIn("## Brand Notes", out)
        # Empty identity → "Voice: Not set" line appears.
        self.assertIn("Not set", out)

    def test_voice_appears(self):
        from doxyedit.strategy import _section_brand_notes
        proj = _project(identity_kw={"voice": "Cheeky and warm"})
        out = _section_brand_notes(proj)
        self.assertIn("Cheeky and warm", out)
        self.assertIn("**Voice:**", out)

    def test_hashtags_appear(self):
        from doxyedit.strategy import _section_brand_notes
        proj = _project(identity_kw={
            "voice": "v", "hashtags": ["#art", "#oc"]})
        out = _section_brand_notes(proj)
        self.assertIn("#art", out)
        self.assertIn("#oc", out)

    def test_monetization_links_appear(self):
        from doxyedit.strategy import _section_brand_notes
        proj = _project(identity_kw={
            "voice": "v",
            "patreon_url": "https://patreon.com/x",
            "gumroad_url": "https://gumroad.com/y"})
        out = _section_brand_notes(proj)
        self.assertIn("Patreon: https://patreon.com/x", out)
        self.assertIn("Gumroad: https://gumroad.com/y", out)

    def test_bio_and_content_notes_included(self):
        from doxyedit.strategy import _section_brand_notes
        proj = _project(identity_kw={
            "voice": "v",
            "bio_blurb": "Indie artist, NSFW friendly",
            "content_notes": "No politics"})
        out = _section_brand_notes(proj)
        self.assertIn("Indie artist", out)
        self.assertIn("No politics", out)


class TestSectionAssetContext(unittest.TestCase):
    def test_no_assets_message(self):
        from doxyedit.strategy import _section_asset_context
        from doxyedit.models import Project
        out = _section_asset_context([], Project())
        self.assertIn("## Asset Context", out)
        self.assertIn("No assets linked", out)

    def test_categorizes_tags(self):
        from doxyedit.strategy import _section_asset_context
        from doxyedit.models import Project, Asset
        proj = Project()
        a = Asset(id="a1", tags=["marty", "color", "kickstarter"])
        out = _section_asset_context([a], proj)
        self.assertIn("Characters", out)
        self.assertIn("Content type", out)
        self.assertIn("Campaign", out)

    def test_starred_flag_yes_no(self):
        from doxyedit.strategy import _section_asset_context
        from doxyedit.models import Project, Asset
        proj = Project()
        starred_out = _section_asset_context([Asset(id="a1", starred=1)], proj)
        unstarred_out = _section_asset_context([Asset(id="a2", starred=0)], proj)
        self.assertIn("Starred", starred_out)
        self.assertIn("Yes", starred_out)
        self.assertIn("No", unstarred_out)


class TestGenerateStrategyBriefing(unittest.TestCase):
    """End-to-end: every section heading must show up in the output.
    If any section silently disappears, the AI strategy gets degraded
    context and the user can't tell."""

    def test_all_sections_present(self):
        from doxyedit.strategy import generate_strategy_briefing
        from doxyedit.models import Project, SocialPost
        out = generate_strategy_briefing(Project(), SocialPost(id="x"))
        for heading in (
            "## Asset Context",
            "## Brand Notes",
            "## Past Strategy Continuity",
        ):
            self.assertIn(heading, out)

    def test_returns_non_empty_with_minimal_input(self):
        from doxyedit.strategy import generate_strategy_briefing
        from doxyedit.models import Project, SocialPost
        out = generate_strategy_briefing(Project(), SocialPost())
        self.assertGreater(len(out), 100)

    def test_trailing_newline(self):
        from doxyedit.strategy import generate_strategy_briefing
        from doxyedit.models import Project, SocialPost
        out = generate_strategy_briefing(Project(), SocialPost())
        self.assertTrue(out.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
