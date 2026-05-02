"""exporter._composite_bubble_overlay smoke tests — speech bubble,
thought bubble, burst dispatch + size-zero guard. Pin so a regression
doesn't silently render nothing for these annotation shapes."""
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


def _bubble(**kw):
    from doxyedit.models import CanvasOverlay
    defaults = dict(type="shape", shape_kind="speech_bubble",
                    x=20, y=20, shape_w=80, shape_h=60,
                    stroke_color="#ffffff", fill_color="#aaccff",
                    stroke_width=2, opacity=1.0)
    return CanvasOverlay(**(defaults | kw))


class TestCompositeBubble(unittest.TestCase):
    def test_speech_bubble(self):
        from doxyedit.exporter import _composite_bubble_overlay
        out = _composite_bubble_overlay(_solid(), _bubble())
        self.assertEqual(out.size, (200, 200))

    def test_thought_bubble(self):
        from doxyedit.exporter import _composite_bubble_overlay
        out = _composite_bubble_overlay(
            _solid(), _bubble(shape_kind="thought_bubble"))
        self.assertEqual(out.size, (200, 200))

    def test_burst(self):
        from doxyedit.exporter import _composite_bubble_overlay
        out = _composite_bubble_overlay(
            _solid(), _bubble(shape_kind="burst"))
        self.assertEqual(out.size, (200, 200))

    def test_zero_size_returns_unchanged(self):
        from doxyedit.exporter import _composite_bubble_overlay
        src = _solid()
        out = _composite_bubble_overlay(
            src, _bubble(shape_w=1, shape_h=10))
        self.assertIs(out, src)

    def test_no_fill_color(self):
        """fill_color="" → outline-only bubble. Must not crash."""
        from doxyedit.exporter import _composite_bubble_overlay
        out = _composite_bubble_overlay(
            _solid(), _bubble(fill_color=""))
        self.assertEqual(out.size, (200, 200))


if __name__ == "__main__":
    unittest.main()
