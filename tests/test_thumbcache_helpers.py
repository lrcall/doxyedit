"""Pure helpers from thumbcache.py: _cache_key, _safe_name,
_pixmap_bytes. These run on every thumb generated for a 70k-asset
project, so a regression here is hot-path expensive. Tests stay
Qt-free where possible."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestCacheKey(unittest.TestCase):
    def test_same_path_same_mtime_same_key(self):
        from doxyedit.thumbcache import _cache_key
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            p = f.name
        try:
            k1 = _cache_key(p, 160)
            k2 = _cache_key(p, 160)
            self.assertEqual(k1, k2)
            self.assertEqual(len(k1), 32)  # md5 hex
        finally:
            os.unlink(p)

    def test_different_size_different_key(self):
        from doxyedit.thumbcache import _cache_key
        with tempfile.NamedTemporaryFile(delete=False) as f:
            p = f.name
        try:
            self.assertNotEqual(_cache_key(p, 160), _cache_key(p, 256))
        finally:
            os.unlink(p)

    def test_missing_file_does_not_raise(self):
        """_cache_key must never raise — used in hot loop. Missing file
        falls back to mtime=0 so the key is still stable."""
        from doxyedit.thumbcache import _cache_key
        k = _cache_key("/path/that/does/not/exist.png", 160)
        self.assertEqual(len(k), 32)


class TestSafeName(unittest.TestCase):
    def test_strips_unsafe_chars(self):
        from doxyedit.thumbcache import _safe_name
        out = _safe_name('my:project<2025>?')
        self.assertNotIn(':', out)
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)
        self.assertNotIn('?', out)

    def test_strips_path_separators(self):
        from doxyedit.thumbcache import _safe_name
        for ch in '/\\|"*':
            self.assertNotIn(ch, _safe_name(f"a{ch}b"))

    def test_empty_falls_back_to_default(self):
        from doxyedit.thumbcache import _safe_name
        self.assertEqual(_safe_name(""), "default")
        self.assertEqual(_safe_name("..."), "default")
        self.assertEqual(_safe_name("   "), "default")

    def test_preserves_normal_name(self):
        from doxyedit.thumbcache import _safe_name
        self.assertEqual(_safe_name("doxyart"), "doxyart")
        self.assertEqual(_safe_name("My Project 2"), "My Project 2")

    def test_strips_control_chars(self):
        from doxyedit.thumbcache import _safe_name
        out = _safe_name("a\x00b\x1fc")
        self.assertNotIn("\x00", out)
        self.assertNotIn("\x1f", out)


class TestPixmapBytes(unittest.TestCase):
    def test_handles_invalid_object(self):
        """_pixmap_bytes is wrapped in try/except — anything that
        doesn't have width/height returns 0 instead of crashing."""
        from doxyedit.thumbcache import _pixmap_bytes
        self.assertEqual(_pixmap_bytes(None), 0)
        self.assertEqual(_pixmap_bytes("not a pixmap"), 0)

    def test_computes_4_bytes_per_pixel(self):
        from doxyedit.thumbcache import _pixmap_bytes

        class FakePM:
            def width(self):
                return 100
            def height(self):
                return 50

        # 100 * 50 * 4 = 20000 (RGBA)
        self.assertEqual(_pixmap_bytes(FakePM()), 20000)

    def test_negative_dims_clamped_to_zero(self):
        from doxyedit.thumbcache import _pixmap_bytes

        class FakePM:
            def width(self):
                return -1  # null QPixmap returns -1
            def height(self):
                return -1

        self.assertEqual(_pixmap_bytes(FakePM()), 0)


if __name__ == "__main__":
    unittest.main()
