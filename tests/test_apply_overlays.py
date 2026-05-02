"""exporter.apply_overlays — top-level overlay dispatcher. Pin the
disabled-skip and unknown-type-skip behaviors so a regression
doesn't either silently render disabled overlays or crash on a
future overlay type."""
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


class TestApplyOverlays(unittest.TestCase):
    def test_no_overlays_returns_copy(self):
        from doxyedit.exporter import apply_overlays
        src = _solid()
        out = apply_overlays(src, [])
        # Must be a copy (RGBA) — never the same object
        self.assertIsNot(out, src)
        self.assertEqual(out.mode, "RGBA")

    def test_disabled_overlay_skipped(self):
        from doxyedit.exporter import apply_overlays
        from doxyedit.models import CanvasOverlay
        src = _solid()
        ov = CanvasOverlay(type="text", text="hello", enabled=False)
        out = apply_overlays(src, [ov])
        # Pixel-equal to a copy of src — overlay was a no-op.
        self.assertEqual(out.size, src.size)

    def test_unknown_type_skipped_no_crash(self):
        """Future overlay types in old DoxyEdit must not crash apply."""
        from doxyedit.exporter import apply_overlays
        from doxyedit.models import CanvasOverlay
        src = _solid()
        ov = CanvasOverlay(type="future_unknown_type", enabled=True)
        out = apply_overlays(src, [ov])
        self.assertEqual(out.size, src.size)

    def test_image_overlay_with_blank_path_skipped(self):
        from doxyedit.exporter import apply_overlays
        from doxyedit.models import CanvasOverlay
        src = _solid()
        # type=watermark but image_path is blank
        ov = CanvasOverlay(type="watermark", image_path="", enabled=True)
        out = apply_overlays(src, [ov])
        self.assertEqual(out.size, src.size)

    def test_text_overlay_with_blank_text_skipped(self):
        from doxyedit.exporter import apply_overlays
        from doxyedit.models import CanvasOverlay
        src = _solid()
        ov = CanvasOverlay(type="text", text="", enabled=True)
        out = apply_overlays(src, [ov])
        self.assertEqual(out.size, src.size)


if __name__ == "__main__":
    unittest.main()
