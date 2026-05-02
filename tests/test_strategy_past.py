"""strategy._section_past_strategy — collects the most recent N
posts whose strategy_notes are non-empty (excluding self) and
formats them as a continuity hint. Pin the max_recent cap, the
self-exclusion rule, and the truncation at 200 chars."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _post(**kw):
    from doxyedit.models import SocialPost
    return SocialPost(**({"id": "p"} | kw))


def _proj(posts):
    from doxyedit.models import Project
    p = Project()
    p.posts = list(posts)
    return p


class TestSectionPastStrategy(unittest.TestCase):
    def test_no_notes_returns_placeholder(self):
        from doxyedit.strategy import _section_past_strategy
        out = _section_past_strategy(_post(id="cur"),
                                     _proj([_post(id="other",
                                                  strategy_notes="")]))
        self.assertIn("No previous strategy notes found", out)

    def test_recent_note_appears(self):
        from doxyedit.strategy import _section_past_strategy
        out = _section_past_strategy(_post(id="cur"), _proj([
            _post(id="prev", strategy_notes="lean into novelty",
                  scheduled_time="2026-04-15T10:00"),
        ]))
        self.assertIn("lean into novelty", out)

    def test_excludes_current_post(self):
        from doxyedit.strategy import _section_past_strategy
        out = _section_past_strategy(
            _post(id="cur", strategy_notes="self-note"),
            _proj([_post(id="cur", strategy_notes="self-note")]))
        self.assertNotIn("self-note", out)

    def test_max_recent_caps_at_3_by_default(self):
        from doxyedit.strategy import _section_past_strategy
        posts = [_post(id=f"p{i}", strategy_notes=f"note-{i}",
                       scheduled_time=f"2026-04-{10+i:02d}T10:00")
                 for i in range(6)]
        out = _section_past_strategy(_post(id="cur"), _proj(posts))
        # Only the last 3 (in reversed scan order) should appear.
        appearances = sum(1 for i in range(6) if f"note-{i}" in out)
        self.assertEqual(appearances, 3)

    def test_long_note_truncated(self):
        """Notes >200 chars get cut to 200 + ellipsis."""
        from doxyedit.strategy import _section_past_strategy
        long = "x" * 500
        out = _section_past_strategy(_post(id="cur"), _proj([
            _post(id="prev", strategy_notes=long,
                  scheduled_time="2026-04-15T10:00"),
        ]))
        self.assertIn("...", out)
        # The full 500-char string must NOT appear in full
        self.assertNotIn("x" * 300, out)

    def test_multi_line_note_collapsed_to_first_line(self):
        from doxyedit.strategy import _section_past_strategy
        out = _section_past_strategy(_post(id="cur"), _proj([
            _post(id="prev",
                  strategy_notes="first line\nsecond line\nthird",
                  scheduled_time="2026-04-15T10:00"),
        ]))
        self.assertIn("first line", out)
        self.assertNotIn("second line", out)


if __name__ == "__main__":
    unittest.main()
