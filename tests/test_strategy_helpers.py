"""strategy.py — pure helpers used by the strategy briefing generator.

These don't touch Qt or the Claude CLI; they are simple tag/date/text
utilities that the briefing builder relies on. Pinning their contracts
prevents silent regressions in the markdown output the user reads when
they hit "Generate Briefing"."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestClassifyTags(unittest.TestCase):
    def test_splits_character_content_campaign_other(self):
        from doxyedit.strategy import _classify_tags
        chars, content, camps, other = _classify_tags(
            ["marty", "color", "kickstarter", "blue_hair"])
        self.assertEqual(chars, ["marty"])
        self.assertEqual(content, ["color"])
        self.assertEqual(camps, ["kickstarter"])
        self.assertEqual(other, ["blue_hair"])

    def test_case_insensitive_match(self):
        from doxyedit.strategy import _classify_tags
        chars, content, camps, other = _classify_tags(["MARTY", "Color"])
        self.assertEqual(chars, ["MARTY"])
        self.assertEqual(content, ["Color"])

    def test_empty_input(self):
        from doxyedit.strategy import _classify_tags
        self.assertEqual(_classify_tags([]), ([], [], [], []))

    def test_unknown_tag_goes_to_other(self):
        from doxyedit.strategy import _classify_tags
        chars, content, camps, other = _classify_tags(["totally_made_up"])
        self.assertEqual(other, ["totally_made_up"])
        self.assertEqual(chars + content + camps, [])


class TestParseDt(unittest.TestCase):
    def test_iso_with_seconds(self):
        from doxyedit.strategy import _parse_dt
        d = _parse_dt("2026-04-15T10:30:45")
        self.assertEqual(d, datetime(2026, 4, 15, 10, 30, 45))

    def test_iso_minute_precision(self):
        from doxyedit.strategy import _parse_dt
        d = _parse_dt("2026-04-15T10:30")
        self.assertEqual(d, datetime(2026, 4, 15, 10, 30))

    def test_space_separator(self):
        from doxyedit.strategy import _parse_dt
        self.assertEqual(_parse_dt("2026-04-15 10:30"),
                         datetime(2026, 4, 15, 10, 30))

    def test_date_only(self):
        from doxyedit.strategy import _parse_dt
        self.assertEqual(_parse_dt("2026-04-15"),
                         datetime(2026, 4, 15))

    def test_strips_z_suffix(self):
        from doxyedit.strategy import _parse_dt
        self.assertEqual(_parse_dt("2026-04-15T10:30:00Z"),
                         datetime(2026, 4, 15, 10, 30))

    def test_strips_tz_offset(self):
        from doxyedit.strategy import _parse_dt
        self.assertEqual(_parse_dt("2026-04-15T10:30:00+09:00"),
                         datetime(2026, 4, 15, 10, 30))

    def test_empty_returns_none(self):
        from doxyedit.strategy import _parse_dt
        self.assertIsNone(_parse_dt(""))
        self.assertIsNone(_parse_dt(None))

    def test_garbage_returns_none(self):
        from doxyedit.strategy import _parse_dt
        self.assertIsNone(_parse_dt("not a date"))


class TestDaysAgo(unittest.TestCase):
    def test_same_day(self):
        from doxyedit.strategy import _days_ago
        d = datetime(2026, 4, 15)
        self.assertEqual(_days_ago(d, d), 0)

    def test_yesterday(self):
        from doxyedit.strategy import _days_ago
        self.assertEqual(_days_ago(datetime(2026, 4, 14),
                                   datetime(2026, 4, 15)), 1)

    def test_future_negative(self):
        from doxyedit.strategy import _days_ago
        self.assertEqual(_days_ago(datetime(2026, 4, 16),
                                   datetime(2026, 4, 15)), -1)


class TestCleanAiOutput(unittest.TestCase):
    """User has a hard rule: no em-dashes anywhere. AI output gets
    sanitized through this. If the replacement table breaks, em-dashes
    leak into the user's clipboard."""

    def test_em_dash_to_comma(self):
        from doxyedit.strategy import _clean_ai_output
        out = _clean_ai_output("hello—world")
        self.assertNotIn("—", out)
        self.assertIn(",", out)

    def test_en_dash_to_hyphen(self):
        from doxyedit.strategy import _clean_ai_output
        out = _clean_ai_output("page 1–2")
        self.assertNotIn("–", out)
        self.assertIn("-", out)

    def test_html_entity_em_dash(self):
        from doxyedit.strategy import _clean_ai_output
        out = _clean_ai_output("a&mdash;b")
        self.assertNotIn("&mdash;", out)

    def test_html_entity_en_dash(self):
        from doxyedit.strategy import _clean_ai_output
        out = _clean_ai_output("a&ndash;b")
        self.assertNotIn("&ndash;", out)

    def test_double_space_before_comma_collapsed(self):
        from doxyedit.strategy import _clean_ai_output
        out = _clean_ai_output("a — b")
        self.assertNotIn(" ,", out)


if __name__ == "__main__":
    unittest.main()
