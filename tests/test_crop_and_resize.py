"""exporter.crop_and_resize — wraps apply_crop_rect + resize. Tests
pin that the final dimensions always match the requested target,
regardless of source aspect ratio or whether a crop is applied.
The export pipeline depends on this contract — wrong-sized output
ships to platforms with hard size requirements (Steam capsules,
Patreon tier cards) and silently fails their validation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestCropAndResize(unittest.TestCase):
    def test_no_crop_resizes_to_target(self):
        from doxyedit.exporter import crop_and_resize
        src = Image.new("RGB", (200, 100), (10, 20, 30))
        out = crop_and_resize(src, None, 50, 50)
        self.assertEqual(out.size, (50, 50))

    def test_with_crop_resizes_to_target(self):
        from doxyedit.exporter import crop_and_resize
        from doxyedit.models import CropRegion
        src = Image.new("RGB", (200, 200), (10, 20, 30))
        out = crop_and_resize(src, CropRegion(x=10, y=10, w=80, h=80),
                              100, 100)
        self.assertEqual(out.size, (100, 100))

    def test_upscale_to_larger(self):
        from doxyedit.exporter import crop_and_resize
        src = Image.new("RGB", (50, 50), (200, 0, 0))
        out = crop_and_resize(src, None, 500, 500)
        self.assertEqual(out.size, (500, 500))

    def test_aspect_ratio_change(self):
        """Crop is honored independently from the target ratio — the
        output ratio is always the target, even if it doesn't match
        the source/crop ratio."""
        from doxyedit.exporter import crop_and_resize
        from doxyedit.models import CropRegion
        src = Image.new("RGB", (1000, 1000), (10, 20, 30))
        # Square crop, target ratio 16:9 → output is 16:9 even though
        # the crop was 1:1.
        out = crop_and_resize(src, CropRegion(x=0, y=0, w=500, h=500),
                              160, 90)
        self.assertEqual(out.size, (160, 90))


if __name__ == "__main__":
    unittest.main()
