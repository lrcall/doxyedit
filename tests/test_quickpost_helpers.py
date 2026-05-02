"""quickpost.py — pure helpers that decide which subscription
platforms a post should target. These run on every Quick Post action;
a regression sends the user to platforms with no URL configured or
re-prompts already-posted ones."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestGetAvailablePlatforms(unittest.TestCase):
    def test_no_identity_returns_empty(self):
        from doxyedit.quickpost import get_available_platforms
        self.assertEqual(get_available_platforms(None), [])

    def test_identity_with_no_urls_returns_empty(self):
        from doxyedit.quickpost import get_available_platforms
        from doxyedit.models import CollectionIdentity
        self.assertEqual(get_available_platforms(CollectionIdentity()), [])

    def test_only_returns_platforms_with_urls(self):
        from doxyedit.quickpost import get_available_platforms
        from doxyedit.models import CollectionIdentity
        ident = CollectionIdentity(
            patreon_url="https://patreon.com/me",
            kofi_url="https://ko-fi.com/me",
        )
        out = get_available_platforms(ident)
        ids = {p.id for p in out}
        self.assertIn("patreon", ids)
        self.assertIn("kofi", ids)
        self.assertNotIn("gumroad", ids)
        self.assertNotIn("fanbox", ids)


class TestGetPendingSubPlatforms(unittest.TestCase):
    def test_returns_unposted_sub_platforms(self):
        from doxyedit.quickpost import get_pending_sub_platforms
        from doxyedit.models import SocialPost
        post = SocialPost(platforms=["patreon", "fanbox", "kofi"],
                          sub_platform_status={
                              "patreon": {"status": "posted"},
                              "fanbox": {"status": "pending"},
                          })
        out = get_pending_sub_platforms(post)
        self.assertNotIn("patreon", out)
        self.assertIn("fanbox", out)
        self.assertIn("kofi", out)  # no status → still pending

    def test_skips_non_sub_platforms(self):
        """OneUp / direct-API platforms aren't in SUB_PLATFORMS — must
        not appear in the pending sub-platform list."""
        from doxyedit.quickpost import get_pending_sub_platforms
        from doxyedit.models import SocialPost
        post = SocialPost(platforms=["twitter", "bluesky", "patreon"])
        out = get_pending_sub_platforms(post)
        self.assertEqual(out, ["patreon"])

    def test_empty_post_platforms(self):
        from doxyedit.quickpost import get_pending_sub_platforms
        from doxyedit.models import SocialPost
        self.assertEqual(get_pending_sub_platforms(SocialPost()), [])


class TestCollectionIdentityCredentials(unittest.TestCase):
    """get_credentials always returns a dict — callers do .get(key) so
    None or non-dict values must be coerced to {}."""

    def test_empty_returns_empty_dict(self):
        from doxyedit.models import CollectionIdentity
        ident = CollectionIdentity()
        self.assertEqual(ident.get_credentials("bluesky"), {})

    def test_missing_platform_returns_empty_dict(self):
        from doxyedit.models import CollectionIdentity
        ident = CollectionIdentity(credentials={"bluesky": {"x": "y"}})
        self.assertEqual(ident.get_credentials("telegram"), {})

    def test_returns_stored_dict(self):
        from doxyedit.models import CollectionIdentity
        ident = CollectionIdentity(credentials={
            "bluesky": {"handle": "a.bsky.social", "app_password": "pw"}
        })
        out = ident.get_credentials("bluesky")
        self.assertEqual(out["handle"], "a.bsky.social")
        self.assertEqual(out["app_password"], "pw")

    def test_non_dict_value_returns_empty(self):
        """Defensive: if the JSON is corrupted and stores a string, must
        not crash callers doing .get()."""
        from doxyedit.models import CollectionIdentity
        ident = CollectionIdentity(credentials={"bluesky": "not_a_dict"})
        self.assertEqual(ident.get_credentials("bluesky"), {})


if __name__ == "__main__":
    unittest.main()
