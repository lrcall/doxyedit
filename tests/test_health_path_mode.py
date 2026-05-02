"""health._detect_path_mode_issues — recognizes "this project came
from a different machine" symptoms (mass-missing files with
particular shapes) and tells the user how to fix it. Pin the four
detection branches so a refactor doesn't quietly drop one and leave
users confused."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _project(asset_specs, local_mode=False):
    """asset_specs: list of source paths (strings)."""
    from doxyedit.models import Project, Asset
    p = Project()
    p.assets = [Asset(id=f"a{i}", source_path=sp)
                for i, sp in enumerate(asset_specs)]
    p.local_mode = local_mode
    return p


class TestDetectPathModeIssues(unittest.TestCase):
    def test_empty_project_returns_none(self):
        from doxyedit.health import _detect_path_mode_issues
        from doxyedit.models import Project
        self.assertIsNone(_detect_path_mode_issues(Project()))

    def test_few_missing_returns_none(self):
        """If most files exist, individual missing files aren't a
        path-mode issue."""
        from doxyedit.health import _detect_path_mode_issues
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.png"
            real.touch()
            paths = [str(real)] * 10 + ["/nonexistent/x.png"]
            proj = _project(paths)
            self.assertIsNone(_detect_path_mode_issues(proj))

    def test_relative_paths_with_local_mode_off_warns(self):
        """All paths relative + local_mode=False is the classic "saved
        with local mode on a different machine" symptom."""
        from doxyedit.health import _detect_path_mode_issues
        # 100% relative paths, none exist, local_mode off
        proj = _project([f"relative/{i}.png" for i in range(10)],
                        local_mode=False)
        msg = _detect_path_mode_issues(proj)
        self.assertIsNotNone(msg)
        self.assertIn("Local Mode", msg)

    def test_local_mode_on_with_mass_missing_warns(self):
        """Local mode ON + 80%+ missing → project moved relative to
        its source files."""
        from doxyedit.health import _detect_path_mode_issues
        # All-absolute, none exist, local_mode ON
        if os.name == "nt":
            paths = [f"C:/nonexistent_dir/{i}.png" for i in range(10)]
        else:
            paths = [f"/nonexistent_root/{i}.png" for i in range(10)]
        proj = _project(paths, local_mode=True)
        msg = _detect_path_mode_issues(proj)
        self.assertIsNotNone(msg)
        self.assertIn("Local Mode", msg)


if __name__ == "__main__":
    unittest.main()
