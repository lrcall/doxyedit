"""imagehost.py — LRU upload cache. Skips re-uploads when the same
file (by content hash) was already uploaded in this session, keeping
quick-post snappy and avoiding burning Imgur API quota. The LRU cap
matters because a long batch can hash hundreds of distinct files."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestUploadCache(unittest.TestCase):
    def setUp(self):
        from doxyedit import imagehost
        self._mod = imagehost
        # Snapshot + clear so tests don't bleed into each other.
        self._saved = imagehost._upload_cache.copy()
        imagehost._upload_cache.clear()

    def tearDown(self):
        self._mod._upload_cache.clear()
        self._mod._upload_cache.update(self._saved)

    def test_get_miss_returns_none(self):
        self.assertIsNone(self._mod._cache_get("nope"))

    def test_set_then_get_hits(self):
        self._mod._cache_set("h1", "https://i.imgur.com/x.png")
        self.assertEqual(self._mod._cache_get("h1"), "https://i.imgur.com/x.png")

    def test_get_bumps_to_most_recent(self):
        """A cache hit must move the entry to the end so it survives
        eviction longer. Without this, frequently-used uploads get
        evicted before idle ones — exactly backwards."""
        m = self._mod
        m._cache_set("a", "u_a")
        m._cache_set("b", "u_b")
        m._cache_get("a")  # bumps a to end
        # Order should now be [b, a]
        self.assertEqual(list(m._upload_cache.keys()), ["b", "a"])

    def test_lru_evicts_oldest_at_cap(self):
        m = self._mod
        cap = m._UPLOAD_CACHE_MAX
        for i in range(cap + 5):
            m._cache_set(f"k{i}", f"u{i}")
        self.assertEqual(len(m._upload_cache), cap)
        # First five should be evicted.
        for i in range(5):
            self.assertIsNone(m._cache_get(f"k{i}"))
        # Most recent should remain.
        self.assertEqual(m._cache_get(f"k{cap + 4}"), f"u{cap + 4}")

    def test_set_existing_key_updates_value_and_position(self):
        m = self._mod
        m._cache_set("x", "u_old")
        m._cache_set("y", "u_y")
        m._cache_set("x", "u_new")  # update + bump
        self.assertEqual(m._cache_get("x"), "u_new")
        # x should be most recent now
        self.assertEqual(list(m._upload_cache.keys())[-1], "x")


class TestFileHash(unittest.TestCase):
    def test_same_content_same_hash(self):
        from doxyedit.imagehost import _file_hash
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            p = f.name
        try:
            h1 = _file_hash(p)
            h2 = _file_hash(p)
            self.assertEqual(h1, h2)
            self.assertEqual(len(h1), 32)  # md5 hex
        finally:
            os.unlink(p)

    def test_different_content_different_hash(self):
        from doxyedit.imagehost import _file_hash
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(b"aaa")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(b"bbb")
            p2 = f2.name
        try:
            self.assertNotEqual(_file_hash(p1), _file_hash(p2))
        finally:
            os.unlink(p1)
            os.unlink(p2)

    def test_chunks_large_file(self):
        """File hashing reads in 8KB chunks. Verify a >8KB file still
        hashes correctly (not silently truncated)."""
        from doxyedit.imagehost import _file_hash
        import hashlib
        payload = b"X" * 25000
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(payload)
            p = f.name
        try:
            self.assertEqual(_file_hash(p), hashlib.md5(payload).hexdigest())
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
