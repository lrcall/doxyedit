"""bridge_data.build_bridge_data — assembles the userscript payload.

Pin the keys the autofill userscript reads, the bio-truncation tier
fallbacks (taglineShort < oneLine < bioShort < bioMedium < bioLong),
and the per-post / composer-override caption merging."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _proj(identity_kw=None, posts=None):
    from doxyedit.models import Project
    p = Project()
    if identity_kw is not None:
        p.identity = dict(identity_kw)
    if posts is not None:
        p.posts = posts
    return p


class TestBuildBridgeData(unittest.TestCase):
    def test_required_keys_present(self):
        from doxyedit.bridge_data import build_bridge_data
        from doxyedit.models import Project
        out = build_bridge_data(Project())
        for k in ("handle", "displayName", "bioLong", "tags", "posts",
                  "patreonURL", "gumroadURL", "kickstarterURL"):
            self.assertIn(k, out)

    def test_handle_is_slugified(self):
        from doxyedit.bridge_data import build_bridge_data
        proj = _proj(identity_kw={"name": "Doxy / Onta"})
        out = build_bridge_data(proj)
        self.assertEqual(out["handle"], "doxy_onta")
        self.assertEqual(out["displayName"], "Doxy / Onta")

    def test_bio_truncation_tiers(self):
        from doxyedit.bridge_data import build_bridge_data
        bio = "x" * 1000
        proj = _proj(identity_kw={"bio_blurb": bio})
        out = build_bridge_data(proj)
        # Each tier longer than the previous up to bioLong=full.
        self.assertLessEqual(len(out["taglineShort"]), 80)
        self.assertLessEqual(len(out["oneLine"]), 120)
        self.assertLessEqual(len(out["bioShort"]), 160)
        self.assertLessEqual(len(out["bioMedium"]), 500)
        self.assertEqual(out["bioLong"], bio)

    def test_hashtags_prefixed(self):
        """hashtags list rendered with leading # per item, single-spaced.
        Tags already starting with # don't get doubled."""
        from doxyedit.bridge_data import build_bridge_data
        proj = _proj(identity_kw={"hashtags": ["art", "#oc", "wip"]})
        out = build_bridge_data(proj)
        self.assertEqual(out["tags"], "#art #oc #wip")

    def test_post_caption_per_platform(self):
        from doxyedit.bridge_data import build_bridge_data
        from doxyedit.models import SocialPost
        post = SocialPost(id="p1", platforms=["bluesky"],
                          captions={"bluesky": "Hello bsky"})
        out = build_bridge_data(_proj(posts=[post]))
        self.assertEqual(out["posts"]["bluesky"], "Hello bsky")

    def test_default_caption_used_when_per_platform_missing(self):
        from doxyedit.bridge_data import build_bridge_data
        from doxyedit.models import SocialPost
        post = SocialPost(id="p1", platforms=["bluesky"],
                          caption_default="Fallback text")
        out = build_bridge_data(_proj(posts=[post]))
        self.assertEqual(out["posts"]["bluesky"], "Fallback text")

    def test_reddit_caption_split_to_title_body(self):
        from doxyedit.bridge_data import build_bridge_data
        from doxyedit.models import SocialPost
        post = SocialPost(id="p1", platforms=["r/IndieDev"],
                          captions={"r/IndieDev":
                                     "My title\n\nlong body here"})
        out = build_bridge_data(_proj(posts=[post]))
        self.assertIn("reddit_indiedev", out["posts"])
        entry = out["posts"]["reddit_indiedev"]
        self.assertEqual(entry["title"], "My title")
        self.assertIn("long body here", entry["body"])

    def test_composer_override_wins(self):
        """When composer_post is supplied, its caption replaces any
        previously-saved post's caption for the same platform."""
        from doxyedit.bridge_data import build_bridge_data
        from doxyedit.models import SocialPost
        saved = SocialPost(id="saved", platforms=["bluesky"],
                           captions={"bluesky": "old version"})
        composing = SocialPost(id="composing", platforms=["bluesky"],
                                captions={"bluesky": "fresh version"})
        out = build_bridge_data(_proj(posts=[saved]),
                                composer_post=composing)
        self.assertEqual(out["posts"]["bluesky"], "fresh version")


if __name__ == "__main__":
    unittest.main()
