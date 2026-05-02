"""browser.auto_suggest_tags — pattern-match filenames to suggest
tags during folder import. The user expects 'cover_v2.png' to land
with #cover suggested. Pin the pattern dictionary so a regression
doesn't silently drop the default tag suggestions on import."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _setup_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestAutoSuggestTags(unittest.TestCase):
    def setUp(self):
        self.app = _setup_qt()

    def test_cover_suggests_cover(self):
        from doxyedit.browser import auto_suggest_tags
        self.assertEqual(auto_suggest_tags("cover_v1.png"), ["cover"])

    def test_case_insensitive(self):
        from doxyedit.browser import auto_suggest_tags
        self.assertIn("cover", auto_suggest_tags("COVER_FINAL.PSD"))

    def test_multiple_patterns_in_one_filename(self):
        from doxyedit.browser import auto_suggest_tags
        out = auto_suggest_tags("cover_sketch_wip.png")
        self.assertIn("cover", out)
        self.assertIn("sketch", out)
        self.assertIn("wip", out)

    def test_aliases_produce_canonical_tag(self):
        from doxyedit.browser import auto_suggest_tags
        # 'character' → 'character'; 'char' → 'character' (alias).
        # Both substrings present — tag must appear ONCE, not twice.
        out = auto_suggest_tags("char_main.png")
        self.assertEqual(out.count("character"), 1)

    def test_avatar_alias_maps_to_icon(self):
        from doxyedit.browser import auto_suggest_tags
        self.assertIn("icon", auto_suggest_tags("avatar.png"))

    def test_no_match_returns_empty(self):
        from doxyedit.browser import auto_suggest_tags
        self.assertEqual(auto_suggest_tags("totally_random_xyz.png"), [])

    def test_panel_alias_maps_to_page(self):
        from doxyedit.browser import auto_suggest_tags
        self.assertIn("page", auto_suggest_tags("panel_03.png"))


if __name__ == "__main__":
    unittest.main()
