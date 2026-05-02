"""composer_right.list_chrome_profiles — scans
%LocalAppData%\\Google\\Chrome\\User Data and returns
[(dir_name, display_name)] for each profile. Cached for 30s
to keep the dropdown snappy. Tests use a tempdir as fake user
data so they don't depend on the user's real Chrome install."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _setup_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_profile(user_data: Path, dir_name: str, display: str | None):
    p = user_data / dir_name
    p.mkdir(parents=True, exist_ok=True)
    if display is not None:
        (p / "Preferences").write_text(
            json.dumps({"profile": {"name": display}}), encoding="utf-8")


class TestListChromeProfiles(unittest.TestCase):
    def setUp(self):
        self.app = _setup_qt()
        # Reset the module-level cache so each test gets a clean read.
        from doxyedit import composer_right
        composer_right._chrome_profile_cache = None
        composer_right._chrome_cache_time = 0

    def test_returns_empty_when_no_user_data_dir(self):
        from doxyedit.composer_right import list_chrome_profiles
        with patch("os.path.expandvars",
                   lambda s: "/no/such/dir"):
            self.assertEqual(list_chrome_profiles(), [])

    def test_lists_profile_with_display_name(self):
        from doxyedit.composer_right import list_chrome_profiles
        with tempfile.TemporaryDirectory() as td:
            ud = Path(td)
            _make_profile(ud, "Default", "Personal")
            _make_profile(ud, "Profile 1", "Work")
            with patch("os.path.expandvars", lambda s: str(ud)):
                profiles = list_chrome_profiles()
            names = dict(profiles)
            self.assertEqual(names.get("Default"), "Personal")
            self.assertEqual(names.get("Profile 1"), "Work")

    def test_falls_back_to_dir_name_when_preferences_corrupt(self):
        from doxyedit.composer_right import list_chrome_profiles
        with tempfile.TemporaryDirectory() as td:
            ud = Path(td)
            (ud / "BadProfile").mkdir()
            (ud / "BadProfile" / "Preferences").write_text("not json")
            with patch("os.path.expandvars", lambda s: str(ud)):
                profiles = dict(list_chrome_profiles())
            # Display falls back to the directory name.
            self.assertEqual(profiles.get("BadProfile"), "BadProfile")

    def test_skips_directories_without_preferences(self):
        """A folder without a Preferences file isn't a real Chrome
        profile; skip it."""
        from doxyedit.composer_right import list_chrome_profiles
        with tempfile.TemporaryDirectory() as td:
            ud = Path(td)
            (ud / "Default").mkdir()  # No Preferences inside
            with patch("os.path.expandvars", lambda s: str(ud)):
                self.assertEqual(list_chrome_profiles(), [])

    def test_cache_returns_same_list_within_30s(self):
        from doxyedit.composer_right import list_chrome_profiles
        from doxyedit import composer_right
        with tempfile.TemporaryDirectory() as td:
            ud = Path(td)
            _make_profile(ud, "Default", "P1")
            with patch("os.path.expandvars", lambda s: str(ud)):
                first = list_chrome_profiles()
                # Add another profile after the first call. Cache means
                # the second call must NOT see it.
                _make_profile(ud, "Profile 2", "P2")
                second = list_chrome_profiles()
            self.assertEqual(first, second)
            # Wind the cache clock back so a 30s+ refresh would pick
            # up the new profile.
            composer_right._chrome_cache_time = 0
            with patch("os.path.expandvars", lambda s: str(ud)):
                third = list_chrome_profiles()
            self.assertGreater(len(third), len(first))


if __name__ == "__main__":
    unittest.main()
