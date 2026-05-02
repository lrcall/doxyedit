"""pipeline.py — pure geometry helpers used by the export pipeline.

_transform_region maps absolute coords into cropped+resized output
space. _auto_crop_for_ratio picks a center crop matching a target
aspect ratio. Both run on every export, so a regression silently
mis-positions censors / overlays for every platform export."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestTransformRegion(unittest.TestCase):
    def test_identity_no_crop_no_resize(self):
        from doxyedit.pipeline import _transform_region
        # Region (10,20,30,40) in 100x100 image, no crop change, no resize
        out = _transform_region(10, 20, 30, 40, (0, 0, 100, 100), (100, 100))
        self.assertEqual(out, (10, 20, 30, 40))

    def test_resize_2x(self):
        from doxyedit.pipeline import _transform_region
        out = _transform_region(10, 20, 30, 40, (0, 0, 100, 100), (200, 200))
        self.assertEqual(out, (20, 40, 60, 80))

    def test_crop_shifts_origin(self):
        from doxyedit.pipeline import _transform_region
        # Crop (10,10,80,80), region (20,20,40,40) → relative (10,10,40,40)
        out = _transform_region(20, 20, 40, 40, (10, 10, 80, 80), (80, 80))
        self.assertEqual(out, (10, 10, 40, 40))

    def test_region_partially_outside_crop_clipped(self):
        from doxyedit.pipeline import _transform_region
        # Region (-10,-10,30,30) clipped to crop (0,0,100,100) → (0,0,20,20)
        out = _transform_region(-10, -10, 30, 30, (0, 0, 100, 100), (100, 100))
        self.assertEqual(out, (0, 0, 20, 20))

    def test_region_entirely_outside_returns_zero(self):
        from doxyedit.pipeline import _transform_region
        out = _transform_region(200, 200, 50, 50, (0, 0, 100, 100), (100, 100))
        self.assertEqual(out, (0, 0, 0, 0))

    def test_minimum_w_h_one_pixel(self):
        """Sub-pixel regions get clamped to 1px so a censor never collapses
        to 0×0 (which Pillow rejects when drawing)."""
        from doxyedit.pipeline import _transform_region
        # 1px region in a 100→1px scaled output → would round to 0, must be 1
        out = _transform_region(0, 0, 1, 1, (0, 0, 100, 100), (10, 10))
        self.assertGreaterEqual(out[2], 1)
        self.assertGreaterEqual(out[3], 1)


class TestAutoCropForRatio(unittest.TestCase):
    def test_square_image_to_16_9_crops_top_bottom(self):
        from doxyedit.pipeline import _auto_crop_for_ratio
        cx, cy, cw, ch = _auto_crop_for_ratio(1000, 1000, 1600, 900)
        self.assertEqual(cw, 1000)  # full width
        self.assertLess(ch, 1000)
        self.assertEqual(cx, 0)
        self.assertGreater(cy, 0)  # centered vertically

    def test_wide_image_to_square_crops_sides(self):
        from doxyedit.pipeline import _auto_crop_for_ratio
        cx, cy, cw, ch = _auto_crop_for_ratio(2000, 1000, 1, 1)
        self.assertEqual(cw, 1000)  # height-bound
        self.assertEqual(ch, 1000)
        self.assertEqual(cy, 0)
        self.assertGreater(cx, 0)

    def test_already_correct_ratio_no_crop(self):
        from doxyedit.pipeline import _auto_crop_for_ratio
        cx, cy, cw, ch = _auto_crop_for_ratio(1600, 900, 16, 9)
        self.assertEqual((cx, cy), (0, 0))
        self.assertEqual((cw, ch), (1600, 900))

    def test_centered_crop(self):
        """Crop is centered: (cx, cy) symmetric to leftover space."""
        from doxyedit.pipeline import _auto_crop_for_ratio
        cx, cy, cw, ch = _auto_crop_for_ratio(2000, 1000, 1, 1)
        # Leftover horizontal space = 2000 - 1000 = 1000, centered → cx=500
        self.assertEqual(cx, 500)


if __name__ == "__main__":
    unittest.main()
