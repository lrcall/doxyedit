"""thumbcache._migrate_flat_cache — one-shot migration that moves
old flat-layout cache files into a 'default' subfolder. Pin its
no-op + actual-move behavior so users upgrading between versions
don't lose their thumbcache."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestMigrateFlatCache(unittest.TestCase):
    def test_empty_dir_is_noop(self):
        from doxyedit.thumbcache import _migrate_flat_cache
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _migrate_flat_cache(base)
            # No 'default' subfolder created if there's nothing to move.
            self.assertFalse((base / "default").exists())

    def test_moves_loose_pngs(self):
        from doxyedit.thumbcache import _migrate_flat_cache
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "abc123.png").write_bytes(b"fake")
            (base / "def456.png").write_bytes(b"fake2")
            _migrate_flat_cache(base)
            self.assertTrue((base / "default" / "abc123.png").exists())
            self.assertTrue((base / "default" / "def456.png").exists())
            # Originals gone from base.
            self.assertFalse((base / "abc123.png").exists())

    def test_moves_index_json(self):
        from doxyedit.thumbcache import _migrate_flat_cache
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "index.json").write_text('{"k": "v"}')
            _migrate_flat_cache(base)
            self.assertTrue((base / "default" / "index.json").exists())
            self.assertFalse((base / "index.json").exists())

    def test_idempotent_second_call(self):
        """Running migrate twice must not crash. Once nothing's loose
        the second pass is a no-op."""
        from doxyedit.thumbcache import _migrate_flat_cache
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "x.png").write_bytes(b"fake")
            _migrate_flat_cache(base)
            _migrate_flat_cache(base)  # must not raise
            self.assertTrue((base / "default" / "x.png").exists())


if __name__ == "__main__":
    unittest.main()
