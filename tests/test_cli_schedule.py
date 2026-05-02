"""__main__.cmd_schedule — chronological post listing with --from /
--to / --status / --format json filters. Pin date filtering and the
asset-id → asset.stem rendering so a regression doesn't silently
hide upcoming posts from the dashboard."""
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


def _build_project(td: Path):
    from doxyedit.models import (Project, Asset, SocialPost,
                                  SocialPostStatus)
    proj = Project()
    proj.assets = [
        Asset(id="a1", source_path=str(td / "marty.png")),
        Asset(id="a2", source_path=str(td / "jenni.png")),
    ]
    proj.posts = [
        SocialPost(id="p1", asset_ids=["a1"], platforms=["bluesky"],
                   caption_default="January post",
                   status=SocialPostStatus.POSTED,
                   scheduled_time="2026-01-15T10:00"),
        SocialPost(id="p2", asset_ids=["a2"], platforms=["telegram"],
                   caption_default="April post",
                   status=SocialPostStatus.QUEUED,
                   scheduled_time="2026-04-15T10:00"),
        SocialPost(id="p3", asset_ids=["a1", "a2"], platforms=["bluesky"],
                   caption_default="Future post",
                   status=SocialPostStatus.QUEUED,
                   scheduled_time="2026-06-01T10:00"),
    ]
    path = td / "t.doxy"
    proj.save(str(path))
    return path


class TestCmdSchedule(unittest.TestCase):
    def test_no_args_lists_all(self):
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p), [])
            self.assertIn("3 post(s)", buf.getvalue())

    def test_from_filter(self):
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p), ["--from", "2026-04-01"])
            out = buf.getvalue()
            self.assertNotIn("January post", out)
            self.assertIn("April post", out)
            self.assertIn("Future post", out)

    def test_to_filter(self):
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p), ["--to", "2026-04-30"])
            out = buf.getvalue()
            self.assertIn("April post", out)
            self.assertNotIn("Future post", out)

    def test_combined_from_to(self):
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p),
                             ["--from", "2026-04-01",
                              "--to", "2026-04-30"])
            self.assertIn("1 post(s)", buf.getvalue())

    def test_status_filter(self):
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p), ["--status", "queued"])
            self.assertIn("2 post(s)", buf.getvalue())

    def test_json_format_returns_post_list(self):
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p), ["--format", "json"])
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 3)

    def test_asset_stem_replaces_id_in_listing(self):
        """Output should print the asset stem (filename) rather than
        the raw asset id so the user sees something readable."""
        from doxyedit.__main__ import cmd_schedule
        with tempfile.TemporaryDirectory() as td:
            p = _build_project(Path(td))
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_schedule(str(p), [])
            out = buf.getvalue()
            self.assertIn("marty", out)
            self.assertIn("jenni", out)


if __name__ == "__main__":
    unittest.main()
