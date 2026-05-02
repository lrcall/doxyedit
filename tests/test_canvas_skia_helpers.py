"""canvas_skia._parse_hex_cached + skia_available — pure helpers we
can test without a working Skia install. The hex parser feeds every
overlay color path; pin its accept/reject contract so a regression
doesn't silently render every shape transparent."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestParseHexCached(unittest.TestCase):
    def test_6_char_hex_with_full_alpha(self):
        from doxyedit.canvas_skia import _parse_hex_cached
        self.assertEqual(_parse_hex_cached("#ff0000"), (255, 0, 0, 255))

    def test_6_char_hex_no_hash(self):
        """The leading # is optional — strip-prefix handles both."""
        from doxyedit.canvas_skia import _parse_hex_cached
        self.assertEqual(_parse_hex_cached("00ff00"), (0, 255, 0, 255))

    def test_8_char_hex_with_alpha(self):
        from doxyedit.canvas_skia import _parse_hex_cached
        self.assertEqual(_parse_hex_cached("#ff000080"), (255, 0, 0, 128))

    def test_invalid_length_returns_none(self):
        from doxyedit.canvas_skia import _parse_hex_cached
        self.assertIsNone(_parse_hex_cached("#abc"))     # 3-char short hex
        self.assertIsNone(_parse_hex_cached("#1234567")) # 7 char

    def test_garbage_returns_none(self):
        from doxyedit.canvas_skia import _parse_hex_cached
        self.assertIsNone(_parse_hex_cached("#zzzzzz"))
        self.assertIsNone(_parse_hex_cached(""))
        self.assertIsNone(_parse_hex_cached(None))


class TestSkiaAvailableContract(unittest.TestCase):
    """skia_available + skia_error never raise, even on systems
    without skia-python installed. Pin so a regression doesn't crash
    the studio at startup on machines lacking the optional dep."""

    def test_skia_available_returns_bool(self):
        from doxyedit.canvas_skia import skia_available
        self.assertIsInstance(skia_available(), bool)

    def test_skia_error_returns_string(self):
        from doxyedit.canvas_skia import skia_error
        self.assertIsInstance(skia_error(), str)


if __name__ == "__main__":
    unittest.main()
