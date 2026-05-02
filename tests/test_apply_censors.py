"""exporter.apply_censors — paints censor rectangles onto a copy of
the source image. Three styles: black solid, gaussian blur, pixelate.
A regression here ships uncensored content to platforms that need
censoring; this is one of the more dangerous places to break."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _img(color=(200, 100, 50, 255)):
    return Image.new("RGBA", (100, 100), color)


class TestApplyCensors(unittest.TestCase):
    def test_no_censors_returns_copy(self):
        from doxyedit.exporter import apply_censors
        src = _img()
        out = apply_censors(src, [])
        self.assertIsNot(out, src)  # must be a copy, not the same object
        self.assertEqual(out.getpixel((50, 50)), src.getpixel((50, 50)))

    def test_black_style_paints_solid_black(self):
        from doxyedit.exporter import apply_censors
        from doxyedit.models import CensorRegion
        out = apply_censors(_img(), [
            CensorRegion(x=10, y=10, w=20, h=20, style="black")
        ])
        # Inside the censor box → black
        self.assertEqual(out.getpixel((15, 15)), (0, 0, 0, 255))
        # Outside → original color preserved
        self.assertEqual(out.getpixel((50, 50))[:3], (200, 100, 50))

    def test_zero_size_box_skipped(self):
        from doxyedit.exporter import apply_censors
        from doxyedit.models import CensorRegion
        # Zero-area box must not crash and must leave image untouched.
        out = apply_censors(_img(), [
            CensorRegion(x=10, y=10, w=0, h=20, style="black")
        ])
        self.assertEqual(out.getpixel((10, 10))[:3], (200, 100, 50))

    def test_box_clipped_to_image_bounds(self):
        from doxyedit.exporter import apply_censors
        from doxyedit.models import CensorRegion
        # Box extends past edge — must clip, not crash.
        out = apply_censors(_img(), [
            CensorRegion(x=80, y=80, w=50, h=50, style="black")
        ])
        # Pixel at (90, 90) is inside both image and box → black.
        self.assertEqual(out.getpixel((90, 90)), (0, 0, 0, 255))

    def test_negative_origin_clipped(self):
        from doxyedit.exporter import apply_censors
        from doxyedit.models import CensorRegion
        # Box with negative x/y must clip to (0, 0).
        out = apply_censors(_img(), [
            CensorRegion(x=-10, y=-10, w=30, h=30, style="black")
        ])
        self.assertEqual(out.getpixel((5, 5)), (0, 0, 0, 255))

    def test_blur_style_changes_pixels(self):
        from doxyedit.exporter import apply_censors
        from doxyedit.models import CensorRegion
        # Build an image with a sharp edge so blur is visible.
        src = Image.new("RGBA", (50, 50), (0, 0, 0, 255))
        from PIL import ImageDraw
        ImageDraw.Draw(src).rectangle([0, 0, 25, 50], fill=(255, 255, 255, 255))
        out = apply_censors(src, [
            CensorRegion(x=10, y=10, w=30, h=30, style="blur",
                         blur_radius=10)
        ])
        # In the blurred region, pixels along the original edge (x≈25)
        # must no longer be pure black or pure white.
        px = out.getpixel((25, 25))
        self.assertNotIn(px[:3], [(0, 0, 0), (255, 255, 255)])

    def test_pixelate_reduces_detail(self):
        from doxyedit.exporter import apply_censors
        from doxyedit.models import CensorRegion
        # Gradient image so pixelation is detectable.
        src = Image.new("RGBA", (40, 40), (0, 0, 0, 255))
        for x in range(40):
            for y in range(40):
                src.putpixel((x, y), (x * 6, y * 6, 0, 255))
        out = apply_censors(src, [
            CensorRegion(x=5, y=5, w=30, h=30, style="pixelate",
                         pixelate_ratio=10)
        ])
        # Inside pixelated region, the per-pixel gradient should flatten.
        # Adjacent inside-pixels should be more uniform than the source.
        a = out.getpixel((10, 10))
        b = out.getpixel((11, 10))
        self.assertEqual(a, b)  # pixelation → adjacent pixels match


if __name__ == "__main__":
    unittest.main()
