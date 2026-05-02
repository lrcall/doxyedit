"""__main__.cmd_strip_tags + cmd_search — bulk and read CLI commands.
Tests call them directly to verify the file mutation (strip_tags) and
the stdout filter logic (search by stem or tag substring)."""
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
        Asset(id="a1", source_path=str(td / "marty_cover.png"),
              tags=["marty", "cover", "wip"]),
        Asset(id="a2", source_path=str(td / "jenni_sketch.png"),
              tags=["jenni", "sketch"]),
        Asset(id="a3", source_path=str(td / "blank.png"), tags=[]),
    ]
    path = td / "t.doxy"
    proj.save(str(path))
    return path


class TestCmdStripTags(unittest.TestCase):
    def test_single_tag_stripped_from_all(self):
        from doxyedit.__main__ import cmd_strip_tags
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_strip_tags(str(p), "wip")
            reloaded = Project.load(str(p))
            for a in reloaded.assets:
                self.assertNotIn("wip", a.tags)

    def test_multiple_tags_comma_separated(self):
        from doxyedit.__main__ import cmd_strip_tags
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_strip_tags(str(p), "wip,sketch")
            reloaded = Project.load(str(p))
            for a in reloaded.assets:
                self.assertNotIn("wip", a.tags)
                self.assertNotIn("sketch", a.tags)
            # Other tags untouched.
            self.assertIn("marty", reloaded.assets[0].tags)

    def test_unknown_tag_changes_nothing(self):
        from doxyedit.__main__ import cmd_strip_tags
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_strip_tags(str(p), "totally_unknown")
            self.assertIn("from 0 assets", buf.getvalue())


class TestCmdSearch(unittest.TestCase):
    def test_matches_by_stem(self):
        from doxyedit.__main__ import cmd_search
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_search(str(p), "marty")
            out = buf.getvalue()
            self.assertIn("marty_cover", out)
            self.assertNotIn("jenni_sketch", out)

    def test_matches_by_tag_substring(self):
        from doxyedit.__main__ import cmd_search
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_search(str(p), "sketch")
            self.assertIn("jenni_sketch", buf.getvalue())

    def test_no_match_returns_zero(self):
        from doxyedit.__main__ import cmd_search
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_search(str(p), "definitely_not_present_xyz")
            self.assertIn("0 matches", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
