"""__main__.cmd_gaps — find days in a window with no scheduled
posts. Pin --from / --days / --format json + the implicit "today"
default. The user runs this to spot empty calendar slots; a
regression that mis-detects gaps wastes a posting day."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _project_with_dates(td: Path, dates: list[str]):
    from doxyedit.models import Project, SocialPost
    proj = Project()
    proj.posts = [SocialPost(id=f"p{i}",
                              scheduled_time=f"{d}T10:00",
                              caption_default=f"on {d}")
                  for i, d in enumerate(dates)]
    path = td / "t.doxy"
    proj.save(str(path))
    return path


class TestCmdGaps(unittest.TestCase):
    def test_filled_window_says_no_gaps(self):
        from doxyedit.__main__ import cmd_gaps
        with tempfile.TemporaryDirectory() as td:
            # 5 consecutive days fully scheduled.
            dates = [
                (datetime(2026, 4, 15) + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(5)
            ]
            p = _project_with_dates(Path(td), dates)
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_gaps(str(p), ["--from", "2026-04-15", "--days", "5"])
            self.assertIn("No gaps", buf.getvalue())

    def test_empty_window_lists_all_days(self):
        from doxyedit.__main__ import cmd_gaps
        with tempfile.TemporaryDirectory() as td:
            p = _project_with_dates(Path(td), [])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_gaps(str(p), ["--from", "2026-04-15", "--days", "3"])
            out = buf.getvalue()
            self.assertIn("2026-04-15", out)
            self.assertIn("2026-04-16", out)
            self.assertIn("2026-04-17", out)
            self.assertIn("3 gap day(s)", out)

    def test_partial_window(self):
        from doxyedit.__main__ import cmd_gaps
        with tempfile.TemporaryDirectory() as td:
            # Day 2 is filled; days 1, 3, 4, 5 are gaps.
            p = _project_with_dates(Path(td), ["2026-04-16"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_gaps(str(p), ["--from", "2026-04-15", "--days", "5"])
            out = buf.getvalue()
            self.assertNotIn("2026-04-16\n", out)  # filled day NOT listed
            self.assertIn("4 gap day(s)", out)

    def test_json_format(self):
        from doxyedit.__main__ import cmd_gaps
        with tempfile.TemporaryDirectory() as td:
            p = _project_with_dates(Path(td), [])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_gaps(str(p),
                         ["--from", "2026-04-15", "--days", "3",
                          "--format", "json"])
            data = json.loads(buf.getvalue())
            self.assertEqual(data, ["2026-04-15", "2026-04-16",
                                     "2026-04-17"])

    def test_default_days_is_30(self):
        """Without --days, the function checks 30 days forward."""
        from doxyedit.__main__ import cmd_gaps
        with tempfile.TemporaryDirectory() as td:
            p = _project_with_dates(Path(td), [])
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_gaps(str(p),
                         ["--from", "2026-04-15", "--format", "json"])
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 30)


if __name__ == "__main__":
    unittest.main()
