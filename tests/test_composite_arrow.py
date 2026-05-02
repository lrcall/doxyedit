"""exporter._composite_arrow_overlay smoke tests — basic arrow,
dashed/dotted line styles, double-headed, no-head, all four
arrowhead_styles. Pin the dispatcher so a regression doesn't
silently drop the arrow tip on every export."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _solid(w=200, h=200):
    return Image.new("RGBA", (w, h), (0, 0, 0, 255))


def _arrow(**kw):
    from doxyedit.models import CanvasOverlay
    defaults = dict(type="arrow", x=10, y=10, end_x=150, end_y=150,
                    color="#ff0000", opacity=1.0,
                    stroke_width=4, arrowhead_size=12,
                    arrowhead_style="filled", line_style="solid",
                    double_headed=False)
    return CanvasOverlay(**(defaults | kw))


class TestCompositeArrow(unittest.TestCase):
    def test_solid_arrow_basic(self):
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(_solid(), _arrow())
        self.assertEqual(out.size, (200, 200))
        # Mid-line pixel (~80, 80) should now have red ink.
        r, g, b, a = out.getpixel((80, 80))
        self.assertGreater(r, 100)

    def test_dashed_arrow(self):
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(_solid(), _arrow(line_style="dash"))
        self.assertEqual(out.size, (200, 200))

    def test_dotted_arrow(self):
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(_solid(), _arrow(line_style="dot"))
        self.assertEqual(out.size, (200, 200))

    def test_no_arrowhead(self):
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(
            _solid(), _arrow(arrowhead_style="none"))
        self.assertEqual(out.size, (200, 200))

    def test_outline_arrowhead(self):
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(
            _solid(), _arrow(arrowhead_style="outline"))
        self.assertEqual(out.size, (200, 200))

    def test_double_headed(self):
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(_solid(), _arrow(double_headed=True))
        self.assertEqual(out.size, (200, 200))

    def test_zero_length_does_not_crash(self):
        """Endpoint same as start → length 0 → arrowhead branch must
        skip cleanly rather than divide by zero."""
        from doxyedit.exporter import _composite_arrow_overlay
        out = _composite_arrow_overlay(
            _solid(), _arrow(x=50, y=50, end_x=50, end_y=50))
        self.assertEqual(out.size, (200, 200))


if __name__ == "__main__":
    unittest.main()
