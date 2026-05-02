"""thumbcache.DiskCache — per-project sqlite + filesystem thumbnail
cache. Pin the json-index migration (legacy upgrade path), the
get-miss-returns-None contract, and put + get round-trip with
dims persistence."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _setup_qt():
    """DiskCache.get returns QImage so we need a QApplication."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestDiskCacheRoundTrip(unittest.TestCase):
    def setUp(self):
        self.app = _setup_qt()

    def test_get_miss_returns_none(self):
        from doxyedit.thumbcache import DiskCache
        with tempfile.TemporaryDirectory() as td:
            dc = DiskCache(cache_dir=td)
            try:
                self.assertIsNone(dc.get("/no/such/file.png", 160))
            finally:
                dc._con.close()

    def test_put_then_get_roundtrip(self):
        from doxyedit.thumbcache import DiskCache
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            # Source file has to exist (its mtime feeds _cache_key).
            src = Path(td) / "src.png"
            Image.new("RGB", (50, 50), (10, 20, 30)).save(str(src), "PNG")
            dc = DiskCache(cache_dir=td)
            try:
                pil = Image.new("RGB", (32, 32), (100, 200, 50))
                dc.put(str(src), 160, pil, 50, 50)
                hit = dc.get(str(src), 160)
                self.assertIsNotNone(hit)
                qimg, w, h = hit
                self.assertEqual(w, 50)
                self.assertEqual(h, 50)
                self.assertGreater(qimg.width(), 0)
            finally:
                dc._con.close()


class TestDiskCacheJSONMigration(unittest.TestCase):
    def setUp(self):
        self.app = _setup_qt()

    def test_legacy_index_json_imported_on_open(self):
        """An old project upgraded from the JSON-based cache must
        carry over its dims into the new sqlite db."""
        from doxyedit.thumbcache import DiskCache
        with tempfile.TemporaryDirectory() as td:
            # Drop a legacy index.json before constructing DiskCache.
            (Path(td) / "index.json").write_text(json.dumps({
                "deadbeef": {"w": 1024, "h": 768},
                "cafebabe": {"w": 200, "h": 100},
            }))
            dc = DiskCache(cache_dir=td)
            try:
                # The migration ran on construction; query directly.
                self.assertEqual(dc._get_dims("deadbeef"), (1024, 768))
                self.assertEqual(dc._get_dims("cafebabe"), (200, 100))
                # Old file renamed to .bak — never re-imported on second open.
                self.assertTrue((Path(td) / "index.json.bak").exists())
                self.assertFalse((Path(td) / "index.json").exists())
            finally:
                dc._con.close()

    def test_no_legacy_file_is_noop(self):
        from doxyedit.thumbcache import DiskCache
        with tempfile.TemporaryDirectory() as td:
            dc = DiskCache(cache_dir=td)
            try:
                # No crash, no .bak file created.
                self.assertFalse((Path(td) / "index.json.bak").exists())
            finally:
                dc._con.close()


if __name__ == "__main__":
    unittest.main()
