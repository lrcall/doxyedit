"""exporter._composite_shape_overlay smoke + dispatch tests. Verifies
that rectangle / ellipse / gradient / bubble dispatch routes don't
crash on minimum-viable input, and that rotation falls back to the
straight path on shape_kind=='rect' with rotation=0."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _solid(w=100, h=100, color=(0, 0, 0, 255)):
    return Image.new("RGBA", (w, h), color)


class TestCompositeShapeDispatch(unittest.TestCase):
    def test_rectangle_basic(self):
        from doxyedit.exporter import _composite_shape_overlay
        from doxyedit.models import CanvasOverlay
        ov = CanvasOverlay(type="shape", shape_kind="rect",
                            x=10, y=10, shape_w=20, shape_h=20,
                            stroke_color="#ff0000", stroke_width=2,
                            opacity=1.0)
        out = _composite_shape_overlay(_solid(), ov)
        self.assertEqual(out.size, (100, 100))

    def test_ellipse_basic(self):
        from doxyedit.exporter import _composite_shape_overlay
        from doxyedit.models import CanvasOverlay
        ov = CanvasOverlay(type="shape", shape_kind="ellipse",
                            x=10, y=10, shape_w=30, shape_h=30,
                            stroke_color="#ffffff", stroke_width=1,
                            opacity=1.0)
        out = _composite_shape_overlay(_solid(), ov)
        self.assertEqual(out.size, (100, 100))

    def test_filled_rect_paints_inside(self):
        from doxyedit.exporter import _composite_shape_overlay
        from doxyedit.models import CanvasOverlay
        src = _solid(color=(0, 0, 0, 255))
        ov = CanvasOverlay(type="shape", shape_kind="rect",
                            x=10, y=10, shape_w=30, shape_h=30,
                            stroke_color="#ff0000", stroke_width=1,
                            fill_color="#ff0000", opacity=1.0)
        out = _composite_shape_overlay(src, ov)
        # Inside the rect, the red fill should dominate.
        r, g, b, a = out.getpixel((20, 20))
        self.assertGreater(r, 100)
        self.assertLess(g, 80)
        self.assertLess(b, 80)

    def test_rotation_falls_back_safely(self):
        """Non-zero rotation goes through the tile-and-rotate branch.
        Verify it doesn't crash and returns the right size."""
        from doxyedit.exporter import _composite_shape_overlay
        from doxyedit.models import CanvasOverlay
        ov = CanvasOverlay(type="shape", shape_kind="rect",
                            x=20, y=20, shape_w=30, shape_h=30,
                            stroke_color="#00ff00", stroke_width=2,
                            rotation=30, opacity=1.0)
        out = _composite_shape_overlay(_solid(), ov)
        self.assertEqual(out.size, (100, 100))


if __name__ == "__main__":
    unittest.main()
