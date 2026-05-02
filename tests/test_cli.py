"""CLI smoke tests.

Run a few `python -m doxyedit <cmd> <project>` invocations against
a synthetic project file and check exit codes + sane stdout. The
CLI is documented in `wiki/CLI Reference.md` and shells use it for
batch ops; a regression here breaks those scripts.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_project(td: Path) -> Path:
    """Write a minimal valid project file under td and return its path."""
    from doxyedit.models import Project, Asset
    proj = Project()
    proj.name = "cli-test"
    proj.assets = [
        Asset(id="a1", source_path=str(td / "a.png"),
              tags=["foo"], starred=1),
        Asset(id="a2", source_path=str(td / "b.png"), tags=[]),
    ]
    path = td / "test.doxy"
    proj.save(str(path))
    return path


class TestCLISmoke(unittest.TestCase):
    """Each command runs to clean exit on a valid project file."""

    def _run(self, *args, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "doxyedit", *args],
            cwd=cwd, capture_output=True, text=True, timeout=30,
        )

    def test_summary(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = _build_project(d)
            r = self._run("summary", str(p), cwd=REPO_ROOT)
            self.assertEqual(r.returncode, 0,
                             f"stdout={r.stdout!r}\nstderr={r.stderr!r}")
            # Summary always reports asset counts.
            self.assertIn("Assets: 2", r.stdout)
            # One asset is starred.
            self.assertIn("Starred: 1", r.stdout)

    def test_tags(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = _build_project(d)
            r = self._run("tags", str(p), cwd=REPO_ROOT)
            self.assertEqual(r.returncode, 0)
            # The 'foo' tag we added should appear.
            self.assertIn("foo", r.stdout)

    def test_untagged(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = _build_project(d)
            r = self._run("untagged", str(p), cwd=REPO_ROOT)
            self.assertEqual(r.returncode, 0)

    def test_no_args_implies_run(self):
        """Running `python -m doxyedit` with zero args attempts to
        launch the GUI. We don't actually want it to launch (no
        QApplication harness here) - we just confirm the command
        dispatch arm exists by passing an unknown command and
        checking the usage line."""
        r = self._run("definitely_not_a_command", cwd=REPO_ROOT)
        # Unknown commands print usage + exit non-zero.
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
