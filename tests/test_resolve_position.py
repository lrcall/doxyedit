"""exporter._resolve_position — overlay placement preset → top-left
xy. Used by every overlay composite (logo, watermark, text). Pin
the 6 named presets + 20px margin; a regression silently relocates
every watermark on every export."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestResolvePosition(unittest.TestCase):
    def setUp(self):
        self.img = (1000, 800)        # 1000x800 base canvas
        self.overlay = (100, 50)      # 100x50 overlay
        self.margin = 20

    def test_bottom_right(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "bottom-right")
        self.assertEqual(x, 1000 - 100 - 20)
        self.assertEqual(y, 800 - 50 - 20)

    def test_bottom_left(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "bottom-left")
        self.assertEqual(x, 20)
        self.assertEqual(y, 800 - 50 - 20)

    def test_top_right(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "top-right")
        self.assertEqual(x, 1000 - 100 - 20)
        self.assertEqual(y, 20)

    def test_top_left(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "top-left")
        self.assertEqual(x, 20)
        self.assertEqual(y, 20)

    def test_center(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "center")
        self.assertEqual(x, (1000 - 100) // 2)
        self.assertEqual(y, (800 - 50) // 2)

    def test_custom_uses_custom_xy(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "custom",
                                  custom_x=123, custom_y=456)
        self.assertEqual((x, y), (123, 456))

    def test_unknown_preset_falls_back_to_bottom_right(self):
        from doxyedit.exporter import _resolve_position
        x, y = _resolve_position(self.img, self.overlay, "elsewhere")
        self.assertEqual(x, 1000 - 100 - 20)
        self.assertEqual(y, 800 - 50 - 20)


if __name__ == "__main__":
    unittest.main()
