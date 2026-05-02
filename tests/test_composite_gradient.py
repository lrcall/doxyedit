"""exporter._composite_gradient_overlay smoke tests — linear and
radial gradient paths via numpy. Pin the size-zero guard, the hex
parser (6 vs 8 chars), and that the gradient actually paints
non-uniform pixels (a regression that returned a flat fill would
silently break gradient overlays)."""
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


def _gradient_ov(**kw):
    from doxyedit.models import CanvasOverlay
    defaults = dict(type="shape", shape_kind="gradient_linear",
                    x=0, y=0, shape_w=100, shape_h=100,
                    gradient_start_color="#000000",
                    gradient_end_color="#ffffff",
                    gradient_angle=0,
                    opacity=1.0)
    return CanvasOverlay(**(defaults | kw))


class TestCompositeGradient(unittest.TestCase):
    def test_linear_horizontal_gradient_changes_pixels(self):
        from doxyedit.exporter import _composite_gradient_overlay
        out = _composite_gradient_overlay(_solid(), _gradient_ov())
        # Pixel near left edge should be darker than pixel near right edge.
        left = sum(out.getpixel((5, 50))[:3])
        right = sum(out.getpixel((95, 50))[:3])
        self.assertNotEqual(left, right)

    def test_radial_gradient_radius_changes(self):
        from doxyedit.exporter import _composite_gradient_overlay
        out = _composite_gradient_overlay(
            _solid(), _gradient_ov(shape_kind="gradient_radial"))
        # Center pixel should be black-ish (start color).
        center = out.getpixel((50, 50))
        # Edge pixel should be light-ish (end color).
        edge = out.getpixel((5, 5))
        self.assertNotEqual(center[:3], edge[:3])

    def test_zero_size_returns_unchanged(self):
        from doxyedit.exporter import _composite_gradient_overlay
        src = _solid()
        out = _composite_gradient_overlay(
            src, _gradient_ov(shape_w=0, shape_h=10))
        # Same object back when size is invalid.
        self.assertIs(out, src)

    def test_8_char_hex_with_alpha_parsed(self):
        """Gradient stops support #rrggbbaa (8 chars). Verify the
        parser handles both 6-char and 8-char input."""
        from doxyedit.exporter import _composite_gradient_overlay
        out = _composite_gradient_overlay(
            _solid(),
            _gradient_ov(gradient_start_color="#ff000080",
                          gradient_end_color="#00ff00ff"))
        self.assertEqual(out.size, (200, 200))


if __name__ == "__main__":
    unittest.main()
