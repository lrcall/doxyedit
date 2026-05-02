"""perf.py — slow-op telemetry. The decorator must NOT swallow return
values, must propagate exceptions, and must only write to the log when
duration exceeds the threshold. If any of those invariants break, every
decorated hot path silently changes behavior."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestPerfTime(unittest.TestCase):
    def test_returns_value_under_threshold(self):
        from doxyedit.perf import perf_time

        @perf_time("fast", threshold_ms=10000.0)
        def f(x, y):
            return x + y

        self.assertEqual(f(2, 3), 5)

    def test_propagates_exception(self):
        from doxyedit.perf import perf_time

        @perf_time("boom", threshold_ms=10000.0)
        def f():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            f()

    def test_below_threshold_does_not_log(self):
        from doxyedit import perf

        fake = MagicMock()
        with patch.object(perf, "_ensure_handle", return_value=fake):
            @perf.perf_time("quick", threshold_ms=10000.0)
            def f():
                return 1
            f()
        fake.write.assert_not_called()

    def test_above_threshold_logs(self):
        from doxyedit import perf

        fake = MagicMock()
        with patch.object(perf, "_ensure_handle", return_value=fake):
            @perf.perf_time("slow", threshold_ms=0.0)
            def f():
                time.sleep(0.001)
                return 42
            self.assertEqual(f(), 42)
        self.assertTrue(fake.write.called)
        written = "".join(c.args[0] for c in fake.write.call_args_list)
        self.assertIn("slow", written)
        self.assertIn("ms", written)

    def test_disabled_handle_skipped_silently(self):
        """When _ensure_handle returns False (open failed), the wrapper
        must not crash."""
        from doxyedit import perf

        with patch.object(perf, "_ensure_handle", return_value=False):
            @perf.perf_time("disabled", threshold_ms=0.0)
            def f():
                return "ok"
            self.assertEqual(f(), "ok")


class TestPerfBlock(unittest.TestCase):
    def test_below_threshold_no_log(self):
        from doxyedit import perf
        fake = MagicMock()
        with patch.object(perf, "_ensure_handle", return_value=fake):
            perf.perf_block("a", 5.0, threshold_ms=100.0)
        fake.write.assert_not_called()

    def test_above_threshold_writes(self):
        from doxyedit import perf
        fake = MagicMock()
        with patch.object(perf, "_ensure_handle", return_value=fake):
            perf.perf_block("a", 250.0, threshold_ms=100.0)
        fake.write.assert_called_once()
        self.assertIn("a", fake.write.call_args.args[0])

    def test_disabled_handle_no_crash(self):
        from doxyedit import perf
        with patch.object(perf, "_ensure_handle", return_value=False):
            perf.perf_block("a", 999.0, threshold_ms=0.0)


if __name__ == "__main__":
    unittest.main()
