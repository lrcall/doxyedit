"""strategy._section_platform_analysis — per-platform notes that
the briefing surfaces for the user (last posted on this platform,
monetization hints, carousel suggestions). These reasonably-pure
heuristics deserve coverage so the recommendation logic doesn't
silently flip."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _proj(identity_kw=None, posts=None, assets=None):
    from doxyedit.models import Project
    p = Project()
    if identity_kw is not None:
        p.identity = dict(identity_kw)
    if posts is not None:
        p.posts = posts
    if assets is not None:
        p.assets = assets
    return p


class TestSectionPlatformAnalysis(unittest.TestCase):
    def test_no_platforms_short_circuits(self):
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import Project, SocialPost
        out = _section_platform_analysis([], SocialPost(), Project())
        self.assertIn("No platforms selected", out)

    def test_falls_back_to_identity_default_platforms(self):
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import SocialPost
        proj = _proj(identity_kw={"default_platforms": ["bluesky"]})
        out = _section_platform_analysis([], SocialPost(), proj)
        self.assertIn("bluesky", out)

    def test_patreon_link_hint(self):
        """Patreon platform + identity.patreon_url → caption suggestion."""
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import SocialPost
        proj = _proj(identity_kw={
            "patreon_url": "https://patreon.com/me",
            "default_platforms": []})
        out = _section_platform_analysis(
            [], SocialPost(platforms=["patreon"]), proj)
        self.assertIn("Link Patreon", out)
        self.assertIn("patreon.com/me", out)

    def test_gumroad_hint_for_social_platforms(self):
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import SocialPost
        proj = _proj(identity_kw={
            "gumroad_url": "https://gumroad.com/me",
            "default_platforms": []})
        out = _section_platform_analysis(
            [], SocialPost(platforms=["bluesky"]), proj)
        self.assertIn("Gumroad", out)

    def test_carousel_hint_only_on_instagram_with_multiple_assets(self):
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import SocialPost, Asset
        proj = _proj(assets=[Asset(id="a1"), Asset(id="a2")])
        out = _section_platform_analysis(
            [Asset(id="a1"), Asset(id="a2")],
            SocialPost(platforms=["instagram"]), proj)
        self.assertIn("carousel", out.lower())

    def test_no_carousel_hint_with_one_asset(self):
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import SocialPost, Asset
        proj = _proj()
        out = _section_platform_analysis(
            [Asset(id="a1")], SocialPost(platforms=["instagram"]), proj)
        self.assertNotIn("carousel", out.lower())

    def test_character_never_posted_marker(self):
        """Character tag with no past posts on this platform → "never
        posted - fresh" annotation."""
        from doxyedit.strategy import _section_platform_analysis
        from doxyedit.models import SocialPost, Asset
        proj = _proj()
        out = _section_platform_analysis(
            [Asset(id="a1", tags=["marty"])],
            SocialPost(platforms=["bluesky"]), proj)
        self.assertIn("fresh", out)


if __name__ == "__main__":
    unittest.main()
