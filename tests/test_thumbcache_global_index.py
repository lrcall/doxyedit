"""thumbcache.GlobalCacheIndex — cross-project sqlite index that
lets one project find thumbnails another project already cached.
Pin lookup miss/hit, stale-entry pruning, register-then-lookup."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _idx(path: Path):
    """Build a fresh index in path; caller must close ._con before
    cleaning up the directory on Windows."""
    from doxyedit.thumbcache import GlobalCacheIndex
    return GlobalCacheIndex(path)


class TestGlobalCacheIndex(unittest.TestCase):
    def test_lookup_unknown_key_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            idx = _idx(Path(td))
            try:
                self.assertIsNone(idx.lookup("nope"))
            finally:
                idx._con.close()

    def test_register_then_lookup_returns_path(self):
        with tempfile.TemporaryDirectory() as td:
            idx = _idx(Path(td))
            try:
                png = Path(td) / "thumb.png"
                png.write_bytes(b"fake")
                idx.register("k1", png)
                idx.save()
                self.assertEqual(idx.lookup("k1"), png)
            finally:
                idx._con.close()

    def test_lookup_prunes_stale_entry(self):
        """If the cached file no longer exists, lookup returns None
        AND removes the dangling row so future lookups skip it fast."""
        with tempfile.TemporaryDirectory() as td:
            idx = _idx(Path(td))
            try:
                png = Path(td) / "thumb.png"
                png.write_bytes(b"fake")
                idx.register("k1", png)
                idx.save()
                png.unlink()
                self.assertIsNone(idx.lookup("k1"))
                self.assertIsNone(idx.lookup("k1"))
            finally:
                idx._con.close()

    def test_register_overwrites_existing_key(self):
        with tempfile.TemporaryDirectory() as td:
            idx = _idx(Path(td))
            try:
                png_a = Path(td) / "a.png"
                png_b = Path(td) / "b.png"
                png_a.write_bytes(b"a")
                png_b.write_bytes(b"b")
                idx.register("k", png_a)
                idx.register("k", png_b)
                idx.save()
                self.assertEqual(idx.lookup("k"), png_b)
            finally:
                idx._con.close()

    def test_save_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            idx = _idx(Path(td))
            try:
                idx.save()
                idx.save()
                idx.save()
            finally:
                idx._con.close()


if __name__ == "__main__":
    unittest.main()
