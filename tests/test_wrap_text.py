"""exporter._wrap_text_to_width — text overlay word wrapping. Uses
PIL's default font and a real ImageDraw to measure widths so the
wrap math matches what _composite_text_overlay actually renders."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _draw_and_font():
    img = Image.new("RGB", (1000, 200), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    return draw, font


class TestWrapTextToWidth(unittest.TestCase):
    def test_empty_text_returns_empty(self):
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        self.assertEqual(_wrap_text_to_width("", font, 100, draw), "")

    def test_zero_width_returns_input_unchanged(self):
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        self.assertEqual(_wrap_text_to_width("hello world", font, 0, draw),
                         "hello world")

    def test_short_text_no_wrap(self):
        """Text that fits in the budget stays on one line — no spurious
        line breaks."""
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        out = _wrap_text_to_width("hi", font, 1000, draw)
        self.assertEqual(out, "hi")
        self.assertNotIn("\n", out)

    def test_long_text_wraps_to_multiple_lines(self):
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        long_text = " ".join(["word"] * 50)
        out = _wrap_text_to_width(long_text, font, 50, draw)
        self.assertIn("\n", out)
        # Each line must end with content, not a trailing space (that
        # would mean we broke after a space rather than between words).
        for line in out.split("\n"):
            self.assertEqual(line, line.rstrip())

    def test_explicit_newlines_preserved(self):
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        out = _wrap_text_to_width("first line\nsecond line",
                                  font, 1000, draw)
        # Both source lines must appear.
        self.assertIn("first line", out)
        self.assertIn("second line", out)
        self.assertGreaterEqual(out.count("\n"), 1)

    def test_blank_line_kept(self):
        """An empty source line produces an empty output line — blank
        paragraphs in user captions must round-trip."""
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        out = _wrap_text_to_width("a\n\nb", font, 1000, draw)
        self.assertEqual(out, "a\n\nb")

    def test_single_long_word_keeps_own_line(self):
        """Per docstring: words longer than max_width stay on their own
        line rather than being broken mid-word."""
        from doxyedit.exporter import _wrap_text_to_width
        draw, font = _draw_and_font()
        big = "x" * 200
        out = _wrap_text_to_width(f"hi {big} bye", font, 30, draw)
        self.assertIn(big, out)


if __name__ == "__main__":
    unittest.main()
