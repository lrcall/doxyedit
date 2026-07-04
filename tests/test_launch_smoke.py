"""Out-of-process launch smoke test.

Boots the real app (run.py --smoke) in a subprocess with the offscreen
Qt platform. --smoke skips restoring the user's last session, never
arms the crash sentinel, and auto-quits ~2.5s after the window shows.

We assert on the explicit SMOKE_OK marker, not just returncode == 0:
the app's global exception hook swallows unhandled exceptions (logs +
status bar, process keeps running), so a broken boot could otherwise
still exit 0. --smoke counts hook hits and plugin failures and exits
nonzero if any occurred."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestLaunchSmoke(unittest.TestCase):
    def test_run_py_smoke_boots_clean(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 not installed")

        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "run.py"), "--smoke"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            timeout=90,
            env=env,
        )
        self.assertEqual(
            result.returncode, 0,
            f"--smoke exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}")
        self.assertNotIn(
            "Traceback", result.stderr,
            f"traceback on stderr during smoke boot:\n{result.stderr}")
        self.assertIn(
            "SMOKE_OK", result.stdout,
            f"missing SMOKE_OK marker\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
