"""__main__.cmd_add_tag / cmd_remove_tag / cmd_set_star — CLI
mutation commands. Tests call them directly (faster than subprocess)
and verify the project file actually changes on disk."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_project(td: Path) -> Path:
    from doxyedit.models import Project, Asset
    proj = Project()
    proj.assets = [
        Asset(id="a1", source_path=str(td / "a.png"),
              tags=["foo"], starred=0),
    ]
    path = td / "t.doxy"
    proj.save(str(path))
    return path


class TestCmdAddTag(unittest.TestCase):
    def test_adds_to_persisted_project(self):
        from doxyedit.__main__ import cmd_add_tag
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_add_tag(str(p), "a1", "newtag")
            reloaded = Project.load(str(p))
            self.assertIn("newtag", reloaded.assets[0].tags)

    def test_idempotent_when_already_present(self):
        from doxyedit.__main__ import cmd_add_tag
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_add_tag(str(p), "a1", "foo")  # already there
            self.assertIn("already on", buf.getvalue())
            reloaded = Project.load(str(p))
            self.assertEqual(reloaded.assets[0].tags.count("foo"), 1)

    def test_unknown_asset_exits(self):
        from doxyedit.__main__ import cmd_add_tag
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cmd_add_tag(str(p), "ghost", "x")


class TestCmdRemoveTag(unittest.TestCase):
    def test_removes_from_persisted_project(self):
        from doxyedit.__main__ import cmd_remove_tag
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_remove_tag(str(p), "a1", "foo")
            reloaded = Project.load(str(p))
            self.assertNotIn("foo", reloaded.assets[0].tags)

    def test_noop_when_tag_missing(self):
        from doxyedit.__main__ import cmd_remove_tag
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_remove_tag(str(p), "a1", "nope")
            self.assertIn("not on", buf.getvalue())


class TestCmdSetStar(unittest.TestCase):
    def test_persists_star_value(self):
        from doxyedit.__main__ import cmd_set_star
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_set_star(str(p), "a1", "3")
            reloaded = Project.load(str(p))
            self.assertEqual(reloaded.assets[0].starred, 3)


if __name__ == "__main__":
    unittest.main()
