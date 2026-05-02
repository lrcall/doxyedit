"""imaging._make_placeholder — generates a 256x256 placeholder image
for unsupported formats. Used by open_for_thumb when shell + psd_tools
both fail. Pin its return shape so the rest of the thumb pipeline
keeps working when it falls through to the placeholder branch."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestMakePlaceholder(unittest.TestCase):
    def test_returns_tuple_of_image_and_zero_dims(self):
        from doxyedit.imaging import _make_placeholder
        img, w, h = _make_placeholder("/some/file.exotic")
        # Original dims report 0,0 (placeholder, not real image dims).
        self.assertEqual(w, 0)
        self.assertEqual(h, 0)

    def test_placeholder_is_256_square(self):
        from doxyedit.imaging import _make_placeholder
        img, _, _ = _make_placeholder("/some/file.png")
        self.assertEqual(img.size, (256, 256))

    def test_placeholder_is_rgba(self):
        from doxyedit.imaging import _make_placeholder
        img, _, _ = _make_placeholder("/some/file.png")
        self.assertEqual(img.mode, "RGBA")

    def test_handles_long_filename(self):
        """Long names get truncated with '...'. Must not crash drawing."""
        from doxyedit.imaging import _make_placeholder
        long_name = "a" * 100 + ".weird"
        img, _, _ = _make_placeholder(f"/dir/{long_name}")
        self.assertEqual(img.size, (256, 256))

    def test_handles_blank_path(self):
        from doxyedit.imaging import _make_placeholder
        img, _, _ = _make_placeholder("")
        self.assertEqual(img.size, (256, 256))


if __name__ == "__main__":
    unittest.main()
