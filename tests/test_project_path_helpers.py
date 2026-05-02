"""Project._to_rel / _to_abs — path-mode helpers used by save/load
when local_mode=True. They convert between absolute filesystem paths
and POSIX-relative paths against the project file's directory. The
local-mode user moves the project folder around, so a regression
either spreads absolute paths into the project file or fails to
resolve relative ones back at load."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestToRel(unittest.TestCase):
    def test_relative_to_base(self):
        from doxyedit.models import Project
        base = Path("E:/proj")
        self.assertEqual(
            Project._to_rel("E:/proj/assets/img.png", base),
            "assets/img.png",
        )

    def test_returns_posix_separator(self):
        """Project files are JSON shared across machines — must use /
        not backslashes regardless of source OS."""
        from doxyedit.models import Project
        base = Path("E:/proj")
        out = Project._to_rel("E:/proj/sub/dir/img.png", base)
        self.assertNotIn("\\", out)
        self.assertIn("/", out)

    def test_falls_back_to_absolute_when_different_drive(self):
        """If the asset lives on a different drive than the project file,
        relative_to fails — fall back to the original absolute path
        rather than crash the save."""
        from doxyedit.models import Project
        base = Path("E:/proj")
        out = Project._to_rel("F:/external/x.png", base)
        self.assertEqual(out, "F:/external/x.png")


class TestToAbs(unittest.TestCase):
    def test_absolute_path_unchanged(self):
        from doxyedit.models import Project
        out = Project._to_abs("E:/somewhere/x.png", Path("E:/proj"))
        self.assertEqual(out, "E:/somewhere/x.png")

    def test_relative_resolved_against_base(self):
        from doxyedit.models import Project
        # Use a real existing dir so .resolve() doesn't behave oddly
        # — the repo root is fine.
        base = REPO_ROOT
        out = Project._to_abs("doxyedit/models.py", base)
        # Whatever resolved form Path produces, it should end with the
        # original suffix and be absolute.
        self.assertTrue(Path(out).is_absolute())
        self.assertTrue(out.endswith("models.py"))


if __name__ == "__main__":
    unittest.main()
