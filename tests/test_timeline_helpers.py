"""timeline._resolve_chrome_profile — looks up the Chrome profile
to use for an identity+account pair from the project's identities
config. Pin so a regression doesn't silently route every browser
launch through the default profile, mixing accounts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestResolveChromeProfile(unittest.TestCase):
    def test_no_project_returns_default(self):
        from doxyedit.timeline import _resolve_chrome_profile
        self.assertEqual(_resolve_chrome_profile(None, "doxy", "twitter"),
                         "Default")

    def test_no_collection_returns_default(self):
        from doxyedit.timeline import _resolve_chrome_profile
        from doxyedit.models import Project
        self.assertEqual(_resolve_chrome_profile(Project(), "", "x"),
                         "Default")

    def test_unknown_collection_returns_default(self):
        from doxyedit.timeline import _resolve_chrome_profile
        from doxyedit.models import Project
        p = Project()
        p.identities = {"other": {"chrome_profiles": {"x": "Profile 5"}}}
        self.assertEqual(_resolve_chrome_profile(p, "doxy", "x"), "Default")

    def test_known_collection_known_account(self):
        from doxyedit.timeline import _resolve_chrome_profile
        from doxyedit.models import Project
        p = Project()
        p.identities = {"doxy": {"chrome_profiles": {
            "twitter": "Profile 5",
            "bluesky": "Profile 7",
        }}}
        self.assertEqual(_resolve_chrome_profile(p, "doxy", "twitter"),
                         "Profile 5")
        self.assertEqual(_resolve_chrome_profile(p, "doxy", "bluesky"),
                         "Profile 7")

    def test_known_collection_unknown_account_returns_default(self):
        from doxyedit.timeline import _resolve_chrome_profile
        from doxyedit.models import Project
        p = Project()
        p.identities = {"doxy": {"chrome_profiles": {"twitter": "P5"}}}
        self.assertEqual(_resolve_chrome_profile(p, "doxy", "instagram"),
                         "Default")

    def test_collection_without_chrome_profiles_key(self):
        from doxyedit.timeline import _resolve_chrome_profile
        from doxyedit.models import Project
        p = Project()
        p.identities = {"doxy": {"voice": "casual"}}
        self.assertEqual(_resolve_chrome_profile(p, "doxy", "twitter"),
                         "Default")


if __name__ == "__main__":
    unittest.main()
