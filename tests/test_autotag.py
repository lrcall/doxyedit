"""autotag.py — image-derived tags. Pure math on PIL arrays, no Qt
dependency, so tests run fast and headless without a QApplication."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestComputeVisualTags(unittest.TestCase):
    """Smoke + targeted tags against synthetic single-color and shape
    images. The classifier thresholds are heuristic, but a dark-red
    image should reliably tag 'dark' + 'warm' and a bright-blue should
    tag 'bright' + 'cool'. Any drift in those thresholds breaks
    auto-tagging silently for the user; this catches it."""

    def test_dark_warm(self):
        from PIL import Image
        from doxyedit.autotag import compute_visual_tags
        img = Image.new("RGB", (100, 100), (60, 5, 5))
        tags = compute_visual_tags(img)
        self.assertIn("dark", tags)
        self.assertIn("warm", tags)

    def test_bright_cool(self):
        from PIL import Image
        from doxyedit.autotag import compute_visual_tags
        img = Image.new("RGB", (100, 100), (200, 220, 250))
        tags = compute_visual_tags(img)
        self.assertIn("bright", tags)
        self.assertIn("cool", tags)

    def test_aspect_panoramic(self):
        from PIL import Image
        from doxyedit.autotag import compute_visual_tags
        img = Image.new("RGB", (1000, 200), (128, 128, 128))
        self.assertIn("panoramic", compute_visual_tags(img))

    def test_aspect_portrait(self):
        from PIL import Image
        from doxyedit.autotag import compute_visual_tags
        img = Image.new("RGB", (300, 600), (128, 128, 128))
        self.assertIn("portrait", compute_visual_tags(img))

    def test_aspect_square(self):
        from PIL import Image
        from doxyedit.autotag import compute_visual_tags
        img = Image.new("RGB", (500, 500), (128, 128, 128))
        self.assertIn("square", compute_visual_tags(img))


class TestComputePhash(unittest.TestCase):
    """compute_phash returns a stable int for the same image and a
    different int for a visibly-different one."""

    def test_same_image_same_hash(self):
        from PIL import Image
        from doxyedit.autotag import compute_phash
        img = Image.new("RGB", (100, 100), (50, 100, 200))
        h1 = compute_phash(img)
        h2 = compute_phash(img)
        self.assertEqual(h1, h2)
        self.assertIsNotNone(h1)

    def test_different_images_different_hashes(self):
        """pHash compares pixels to the image mean, so a solid color
        image hashes to 0 regardless of which color it is. Use two
        images with actual pixel variation so the hashes diverge."""
        from PIL import Image, ImageDraw
        from doxyedit.autotag import compute_phash
        a = Image.new("RGB", (100, 100), (0, 0, 0))
        ImageDraw.Draw(a).rectangle([0, 0, 50, 100], fill=(255, 255, 255))
        b = Image.new("RGB", (100, 100), (0, 0, 0))
        ImageDraw.Draw(b).rectangle([0, 0, 100, 50], fill=(255, 255, 255))
        # 'a' is left-half-white, 'b' is top-half-white — different
        # pixel layouts so pHash should diverge.
        self.assertNotEqual(compute_phash(a), compute_phash(b))


if __name__ == "__main__":
    unittest.main()
