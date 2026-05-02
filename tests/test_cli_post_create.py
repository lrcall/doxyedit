"""__main__.cmd_post_create — argv parser for new draft posts.
Pin which flags map to which SocialPost fields, the comma-split for
multi-value flags, and the per-platform --caption-PLAT override
mechanism."""
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


def _empty_project_at(td: Path) -> Path:
    from doxyedit.models import Project
    p = td / "t.doxy"
    Project().save(str(p))
    return p


class TestCmdPostCreate(unittest.TestCase):
    def test_minimal_create(self):
        from doxyedit.__main__ import cmd_post_create
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _empty_project_at(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_create(str(p), [
                    "--platforms", "bluesky",
                    "--caption", "Hello world",
                ])
            reloaded = Project.load(str(p))
            self.assertEqual(len(reloaded.posts), 1)
            post = reloaded.posts[0]
            self.assertEqual(post.platforms, ["bluesky"])
            self.assertEqual(post.caption_default, "Hello world")

    def test_multi_value_flags_comma_split(self):
        from doxyedit.__main__ import cmd_post_create
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _empty_project_at(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_create(str(p), [
                    "--assets", "a1,a2,a3",
                    "--platforms", "bluesky,telegram",
                    "--nsfw-platforms", "telegram",
                ])
            reloaded = Project.load(str(p))
            post = reloaded.posts[0]
            self.assertEqual(post.asset_ids, ["a1", "a2", "a3"])
            self.assertEqual(post.platforms, ["bluesky", "telegram"])
            self.assertEqual(post.nsfw_platforms, ["telegram"])

    def test_per_platform_caption(self):
        """--caption-PLATFORM populates the captions dict."""
        from doxyedit.__main__ import cmd_post_create
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _empty_project_at(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_create(str(p), [
                    "--platforms", "bluesky,telegram",
                    "--caption", "default text",
                    "--caption-bluesky", "bsky special",
                    "--caption-telegram", "tg special",
                ])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.captions.get("bluesky"), "bsky special")
            self.assertEqual(post.captions.get("telegram"), "tg special")

    def test_format_json_outputs_post_dict(self):
        from doxyedit.__main__ import cmd_post_create
        with tempfile.TemporaryDirectory() as td:
            p = _empty_project_at(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_post_create(str(p), [
                    "--platforms", "bluesky",
                    "--caption", "x",
                    "--format", "json",
                ])
            data = json.loads(buf.getvalue())
            self.assertEqual(data["caption_default"], "x")
            self.assertEqual(data["platforms"], ["bluesky"])

    def test_creates_with_default_status_draft(self):
        from doxyedit.__main__ import cmd_post_create
        from doxyedit.models import Project, SocialPostStatus
        with tempfile.TemporaryDirectory() as td:
            p = _empty_project_at(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_create(str(p), [
                    "--platforms", "bluesky", "--caption", "x"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.status, SocialPostStatus.DRAFT)


if __name__ == "__main__":
    unittest.main()
