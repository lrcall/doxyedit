"""run._wire_log_for_pythonw — only redirects when sys.stdout/stderr
are None (the pythonw case). Test pinned because:

1. The helper is the only thing that prevents silent crashes when the
   user launches via .bat / .vbs (which use pythonw).
2. A regression that always-redirects breaks console launches by
   stealing terminal output.
3. A regression that never-redirects loses every traceback the user
   would otherwise paste in for the social-tab crash."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestWireLogForPythonw(unittest.TestCase):
    def setUp(self):
        # Snapshot streams so we can restore them after each test.
        self._saved_stdout = sys.stdout
        self._saved_stderr = sys.stderr

    def tearDown(self):
        # If a test redirected to a tempfile, close it so Windows lets
        # the tempdir cleanup delete the file.
        for stream in (sys.stdout, sys.stderr):
            if (stream is not None
                    and stream is not self._saved_stdout
                    and stream is not self._saved_stderr
                    and hasattr(stream, "close")):
                try:
                    stream.close()
                except Exception:
                    pass
        sys.stdout = self._saved_stdout
        sys.stderr = self._saved_stderr

    def _import_run(self):
        # `run` runs main() at import time; we need to import the
        # function directly without triggering main().
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_module_test", REPO_ROOT / "run.py")
        mod = importlib.util.module_from_spec(spec)
        # Patch main() to no-op before exec_module triggers it.
        with patch("doxyedit.main.main"):
            spec.loader.exec_module(mod)
        return mod

    def test_console_launch_leaves_streams_alone(self):
        """Streams are real I/O objects → don't redirect."""
        sys.stdout = self._saved_stdout
        sys.stderr = self._saved_stderr
        mod = self._import_run()
        # _wire_log_for_pythonw was called at import time; sys.stdout
        # should still be the real stdout.
        self.assertIs(sys.stdout, self._saved_stdout)
        self.assertIs(sys.stderr, self._saved_stderr)
        # And the helper itself, called fresh, must be a no-op.
        mod._wire_log_for_pythonw()
        self.assertIs(sys.stdout, self._saved_stdout)

    def test_none_streams_redirected_to_log(self):
        """When pythonw set both streams to None, the helper must open
        a log file and assign it to both."""
        with tempfile.TemporaryDirectory() as fake_home:
            mod = self._import_run()
            with patch.object(sys, "stdout", None), \
                 patch.object(sys, "stderr", None), \
                 patch.object(Path, "home",
                              lambda: Path(fake_home)):
                mod._wire_log_for_pythonw()
                redirected = sys.stdout
                self.assertIsNotNone(redirected)
                self.assertIs(sys.stdout, sys.stderr)
                self.assertTrue(
                    (Path(fake_home) / ".doxyedit"
                     / "last_run.log").exists())
            # Close the file *before* the tempdir context exits so
            # Windows can rmtree it.
            try:
                redirected.close()
            except Exception:
                pass

    def test_partial_none_also_triggers_redirect(self):
        """Helper logic: redirect unless BOTH streams are real. So if
        only stdout is None, redirect kicks in too — that's the safer
        choice (we'd rather lose terminal output than lose a traceback)."""
        with tempfile.TemporaryDirectory() as fake_home:
            mod = self._import_run()
            with patch.object(sys, "stdout", None), \
                 patch.object(Path, "home",
                              lambda: Path(fake_home)):
                mod._wire_log_for_pythonw()
                redirected = sys.stdout
                self.assertIsNotNone(redirected)
                self.assertTrue(
                    (Path(fake_home) / ".doxyedit"
                     / "last_run.log").exists())
            try:
                redirected.close()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
