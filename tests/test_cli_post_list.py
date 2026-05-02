"""__main__.cmd_post_list — list posts with --status filter and
--format json. Pin the JSON output shape (round-trippable through
SocialPost.from_dict) and the filter."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_project(td: Path) -> Path:
    from doxyedit.models import Project, SocialPost, SocialPostStatus
    proj = Project()
    proj.posts = [
        SocialPost(id="p1", platforms=["bluesky"],
                   caption_default="Posted one",
                   status=SocialPostStatus.POSTED,
                   scheduled_time="2026-04-01T10:00"),
        SocialPost(id="p2", platforms=["telegram"],
                   caption_default="Queued one",
                   status=SocialPostStatus.QUEUED,
                   scheduled_time="2026-04-15T10:00"),
        SocialPost(id="p3", platforms=["bluesky"],
                   caption_default="Draft one",
                   status=SocialPostStatus.DRAFT),
    ]
    path = td / "t.doxy"
    proj.save(str(path))
    return path


class TestCmdPostList(unittest.TestCase):
    def test_no_args_lists_all_posts(self):
        from doxyedit.__main__ import cmd_post_list
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_list(str(p), [])
            out = buf.getvalue()
            self.assertIn("3 post(s)", out)

    def test_status_filter(self):
        from doxyedit.__main__ import cmd_post_list
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_list(str(p), ["--status", "posted"])
            out = buf.getvalue()
            self.assertIn("Posted one", out)
            self.assertNotIn("Queued one", out)
            self.assertNotIn("Draft one", out)

    def test_json_format(self):
        from doxyedit.__main__ import cmd_post_list
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_list(str(p), ["--format", "json"])
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 3)
            ids = {entry["id"] for entry in data}
            self.assertEqual(ids, {"p1", "p2", "p3"})

    def test_json_with_status_filter(self):
        from doxyedit.__main__ import cmd_post_list
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_list(str(p),
                              ["--format", "json", "--status", "queued"])
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["id"], "p2")

    def test_no_posts_message(self):
        from doxyedit.__main__ import cmd_post_list
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty.doxy"
            Project().save(str(empty))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_list(str(empty), [])
            self.assertIn("No posts found", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
