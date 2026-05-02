"""__main__.cmd_post_update — argv parser for in-place post edits.
Pin the unique flags (add-platform / remove-platform / status /
schedule), the per-platform caption override, and the unknown-id
SystemExit."""
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


def _build_project(td: Path):
    from doxyedit.models import Project, SocialPost, SocialPostStatus
    proj = Project()
    proj.posts = [SocialPost(
        id="p1", platforms=["bluesky"],
        caption_default="orig",
        status=SocialPostStatus.DRAFT,
    )]
    path = td / "t.doxy"
    proj.save(str(path))
    return path


class TestCmdPostUpdate(unittest.TestCase):
    def test_caption_replace(self):
        from doxyedit.__main__ import cmd_post_update
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_update(str(p), "p1",
                                ["--caption", "updated text"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.caption_default, "updated text")

    def test_add_platform_idempotent(self):
        from doxyedit.__main__ import cmd_post_update
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            # Add an existing platform — should not duplicate.
            with redirect_stdout(io.StringIO()):
                cmd_post_update(str(p), "p1",
                                ["--add-platform", "bluesky"])
                cmd_post_update(str(p), "p1",
                                ["--add-platform", "telegram"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.platforms.count("bluesky"), 1)
            self.assertIn("telegram", post.platforms)

    def test_remove_platform(self):
        from doxyedit.__main__ import cmd_post_update
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_update(str(p), "p1",
                                ["--remove-platform", "bluesky"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.platforms, [])

    def test_remove_platform_not_present_is_noop(self):
        from doxyedit.__main__ import cmd_post_update
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_update(str(p), "p1",
                                ["--remove-platform", "ghost"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.platforms, ["bluesky"])

    def test_schedule_set(self):
        from doxyedit.__main__ import cmd_post_update
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_update(str(p), "p1",
                                ["--schedule", "2026-04-15T10:00"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.scheduled_time, "2026-04-15T10:00")

    def test_unknown_id_exits(self):
        from doxyedit.__main__ import cmd_post_update
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cmd_post_update(str(p), "ghost", ["--caption", "x"])

    def test_assets_replaces_list(self):
        """--assets fully replaces the asset_ids list (comma-split)."""
        from doxyedit.__main__ import cmd_post_update
        from doxyedit.models import Project
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            with redirect_stdout(io.StringIO()):
                cmd_post_update(str(p), "p1",
                                ["--assets", "a1,a2,a3"])
            post = Project.load(str(p)).posts[0]
            self.assertEqual(post.asset_ids, ["a1", "a2", "a3"])


if __name__ == "__main__":
    unittest.main()
