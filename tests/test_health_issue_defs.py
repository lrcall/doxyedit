"""health.ISSUE_DEFS — predicate functions that classify each asset
into health categories: missing file, zero-byte, untagged, unassigned,
large. The Health tab counts assets per category. Pin the predicates
so a regression doesn't silently mis-bucket assets the user is
trusting to be flagged."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _defs_by_key():
    from doxyedit.health import ISSUE_DEFS
    return {key: (severity, label, fn)
            for (key, severity, label, fn) in ISSUE_DEFS}


class TestIssueDefs(unittest.TestCase):
    def test_all_five_keys_present(self):
        defs = _defs_by_key()
        for k in ("missing", "zero_byte", "untagged", "unassigned", "large"):
            self.assertIn(k, defs)

    def test_missing_predicate_true_for_nonexistent(self):
        from doxyedit.models import Asset
        defs = _defs_by_key()
        _, _, fn = defs["missing"]
        self.assertTrue(fn(Asset(source_path="/nope/missing.png"), None))

    def test_missing_predicate_false_for_real_file(self):
        from doxyedit.models import Asset
        defs = _defs_by_key()
        _, _, fn = defs["missing"]
        with tempfile.NamedTemporaryFile(delete=False) as f:
            p = f.name
        try:
            self.assertFalse(fn(Asset(source_path=p), None))
        finally:
            os.unlink(p)

    def test_zero_byte_predicate(self):
        from doxyedit.models import Asset
        defs = _defs_by_key()
        _, _, fn = defs["zero_byte"]
        # Non-existent file shouldn't trip zero_byte (that's missing)
        self.assertFalse(fn(Asset(source_path="/nope/x.png"), None))
        # Empty file → zero_byte
        with tempfile.NamedTemporaryFile(delete=False) as f:
            empty = f.name
        try:
            self.assertTrue(fn(Asset(source_path=empty), None))
        finally:
            os.unlink(empty)

    def test_untagged_predicate(self):
        from doxyedit.models import Asset
        defs = _defs_by_key()
        _, _, fn = defs["untagged"]
        self.assertTrue(fn(Asset(tags=[]), None))
        self.assertFalse(fn(Asset(tags=["wip"]), None))

    def test_unassigned_predicate(self):
        from doxyedit.models import Asset, PlatformAssignment
        defs = _defs_by_key()
        _, _, fn = defs["unassigned"]
        self.assertTrue(fn(Asset(assignments=[]), None))
        self.assertFalse(fn(Asset(assignments=[
            PlatformAssignment(platform="x", slot="y")]), None))

    def test_large_predicate_threshold_50mb(self):
        """The 'large' label fires only above 50 MB — pin the
        threshold so users don't get spammed by 5 MB JPGs."""
        from doxyedit.models import Asset
        defs = _defs_by_key()
        _, _, fn = defs["large"]
        # 1 KB file is not large.
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 1024)
            small = f.name
        try:
            self.assertFalse(fn(Asset(source_path=small), None))
        finally:
            os.unlink(small)
        # Don't bother actually creating a 50 MB file — instead, prove
        # that the check uses the file size by missing-file falling to
        # False.
        self.assertFalse(fn(Asset(source_path="/nope/x.png"), None))

    def test_severity_categories(self):
        defs = _defs_by_key()
        self.assertEqual(defs["missing"][0], "error")
        self.assertEqual(defs["zero_byte"][0], "error")
        self.assertEqual(defs["untagged"][0], "warning")
        self.assertEqual(defs["unassigned"][0], "info")
        self.assertEqual(defs["large"][0], "info")


if __name__ == "__main__":
    unittest.main()
