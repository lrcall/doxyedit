"""__main__.cmd_post_show — print one post's fields. Pin the
prefix-match dispatch (so users can type the first 8 chars of the
UUID), the ambiguous / not-found exits, and the always-emitted
core fields."""
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


def _build_project_with(post_ids):
    from doxyedit.models import Project, SocialPost
    proj = Project()
    proj.posts = [SocialPost(id=pid,
                              platforms=["bluesky"],
                              caption_default=f"caption for {pid}")
                  for pid in post_ids]
    return proj


def _save(proj, td):
    p = td / "t.doxy"
    proj.save(str(p))
    return p


class TestCmdPostShow(unittest.TestCase):
    def test_exact_id_match(self):
        from doxyedit.__main__ import cmd_post_show
        with tempfile.TemporaryDirectory() as td:
            p = _save(_build_project_with(["abc12345-rest"]),
                      Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_show(str(p), "abc12345-rest")
            out = buf.getvalue()
            self.assertIn("abc12345-rest", out)
            self.assertIn("caption for abc12345-rest", out)

    def test_prefix_match_unique(self):
        """Partial id match — single hit picks that post."""
        from doxyedit.__main__ import cmd_post_show
        with tempfile.TemporaryDirectory() as td:
            p = _save(_build_project_with(
                ["abc12345-rest", "different-id"]), Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_show(str(p), "abc1")
            self.assertIn("abc12345-rest", buf.getvalue())

    def test_ambiguous_prefix_exits(self):
        from doxyedit.__main__ import cmd_post_show
        with tempfile.TemporaryDirectory() as td:
            p = _save(_build_project_with(
                ["abc12345-aaa", "abc12345-bbb"]), Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(SystemExit):
                    cmd_post_show(str(p), "abc12345")
            self.assertIn("Ambiguous", buf.getvalue())

    def test_no_match_exits(self):
        from doxyedit.__main__ import cmd_post_show
        with tempfile.TemporaryDirectory() as td:
            p = _save(_build_project_with(["abc12345"]), Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(SystemExit):
                    cmd_post_show(str(p), "totally-unknown-id")
            self.assertIn("not found", buf.getvalue())

    def test_core_fields_always_printed(self):
        """Fields the user counts on always being there (ID, Status,
        Schedule, Assets, Platforms, Caption, Created, Updated)."""
        from doxyedit.__main__ import cmd_post_show
        with tempfile.TemporaryDirectory() as td:
            p = _save(_build_project_with(["only-one"]), Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_show(str(p), "only-one")
            out = buf.getvalue()
            for field in ("ID:", "Status:", "Schedule:", "Assets:",
                          "Platforms:", "Caption:", "Created:",
                          "Updated:"):
                self.assertIn(field, out)


if __name__ == "__main__":
    unittest.main()
