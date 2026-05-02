"""exporter._composite_image_overlay — paints a watermark/logo image
onto the base. Tests focus on the resolution / safety paths the user
hits constantly: missing watermark → unchanged base, relative path
joined to project_dir, absolute path used as-is."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _solid(w=200, h=200, color=(50, 50, 50, 255)):
    return Image.new("RGBA", (w, h), color)


def _watermark_file():
    """Build a 50x50 red watermark to disk and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    f.close()
    Image.new("RGBA", (50, 50), (255, 0, 0, 255)).save(f.name, "PNG")
    return f.name


class TestCompositeImageOverlay(unittest.TestCase):
    def test_missing_path_returns_unchanged(self):
        from doxyedit.exporter import _composite_image_overlay
        from doxyedit.models import CanvasOverlay
        base = _solid()
        ov = CanvasOverlay(type="watermark",
                            image_path="/totally/missing.png", scale=0.2)
        out = _composite_image_overlay(base, ov, project_dir="")
        # No file → no composite → same object back.
        self.assertIs(out, base)

    def test_absolute_path_loaded(self):
        from doxyedit.exporter import _composite_image_overlay
        from doxyedit.models import CanvasOverlay
        wm_path = _watermark_file()
        try:
            base = _solid()
            ov = CanvasOverlay(type="watermark", image_path=wm_path,
                                scale=0.2, opacity=1.0,
                                position="top-left", enabled=True)
            out = _composite_image_overlay(base, ov, project_dir="")
            # Composite happened → returned image is NOT the base object
            self.assertIsNot(out, base)
            # Top-left pixel is now red-ish (watermark there).
            r, g, b, a = out.getpixel((25, 25))
            self.assertGreater(r, 100)
            self.assertLess(b, 100)
        finally:
            Path(wm_path).unlink(missing_ok=True)

    def test_relative_path_joined_to_project_dir(self):
        """Watermark path stored relatively in CanvasOverlay must be
        resolved against project_dir on export."""
        from doxyedit.exporter import _composite_image_overlay
        from doxyedit.models import CanvasOverlay
        with tempfile.TemporaryDirectory() as td:
            wm_path = Path(td) / "wm.png"
            Image.new("RGBA", (50, 50), (255, 0, 0, 255)).save(
                str(wm_path), "PNG")
            base = _solid()
            ov = CanvasOverlay(type="watermark", image_path="wm.png",
                                scale=0.2, opacity=1.0,
                                position="top-left", enabled=True)
            out = _composite_image_overlay(base, ov, project_dir=td)
            self.assertIsNot(out, base)


if __name__ == "__main__":
    unittest.main()
