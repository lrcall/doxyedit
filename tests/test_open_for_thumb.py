"""imaging.open_for_thumb — format dispatch with placeholder
fallbacks. We can't easily fake the Win32 shell thumbnail API
or psd_tools, but we CAN exercise the standard-PIL branch and
the missing-file → placeholder branch deterministically."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestOpenForThumb(unittest.TestCase):
    def test_standard_png_loads(self):
        from doxyedit.imaging import open_for_thumb
        with tempfile.NamedTemporaryFile(suffix=".png",
                                          delete=False) as f:
            path = f.name
        try:
            Image.new("RGB", (100, 60), (10, 20, 30)).save(path, "PNG")
            img, w, h = open_for_thumb(path, 160)
            self.assertEqual(w, 100)
            self.assertEqual(h, 60)
            img.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_missing_png_returns_placeholder(self):
        from doxyedit.imaging import open_for_thumb
        # Non-existent but with a known extension → falls through to
        # the PIL try block, fails, returns placeholder.
        img, w, h = open_for_thumb("/no/such/missing.png", 160)
        # Placeholder reports w=0, h=0 (per _make_placeholder contract).
        self.assertEqual(w, 0)
        self.assertEqual(h, 0)
        self.assertEqual(img.size, (256, 256))

    def test_jpg_loads(self):
        from doxyedit.imaging import open_for_thumb
        with tempfile.NamedTemporaryFile(suffix=".jpg",
                                          delete=False) as f:
            path = f.name
        try:
            Image.new("RGB", (50, 50), (200, 100, 50)).save(path, "JPEG")
            img, w, h = open_for_thumb(path, 160)
            self.assertEqual(w, 50)
            self.assertEqual(h, 50)
            img.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_unknown_extension_falls_through_to_pil(self):
        """A made-up extension goes through the PIL branch. With no
        actual file → placeholder."""
        from doxyedit.imaging import open_for_thumb
        img, w, h = open_for_thumb("/nope/file.xyz", 160)
        self.assertEqual(img.size, (256, 256))


if __name__ == "__main__":
    unittest.main()
