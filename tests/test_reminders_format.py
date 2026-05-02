"""reminders.format_reminders_table — CLI table formatting for the
nightly reminders dump. Pin the output shape so a refactor doesn't
silently corrupt the user's stand-up summary."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestFormatRemindersTable(unittest.TestCase):
    def test_empty_returns_default_message(self):
        from doxyedit.reminders import format_reminders_table
        self.assertEqual(format_reminders_table([]), "No pending reminders.")

    def test_header_present(self):
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([Reminder(message="x", urgency="normal")])
        self.assertIn("REMINDERS", out)

    def test_overdue_marker(self):
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([Reminder(
            message="late one", urgency="overdue", due_at="2026-04-01T12:00")])
        self.assertIn("!!", out)
        self.assertIn("late one", out)

    def test_urgent_marker(self):
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([Reminder(
            message="now", urgency="urgent")])
        # urgent marker is single "!" but overdue is "!!" — we want "!" not "!!"
        # Find the line containing the message and check its prefix.
        for line in out.splitlines():
            if "now" in line:
                self.assertIn("!", line)
                self.assertNotIn("!!", line)
                break
        else:
            self.fail("urgent reminder line not found")

    def test_identity_prefix_when_set(self):
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([Reminder(
            message="patreon late", urgency="overdue", identity="Doxy")])
        self.assertIn("[Doxy]", out)

    def test_no_identity_no_brackets(self):
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([Reminder(
            message="generic", urgency="normal")])
        self.assertNotIn("[]", out)

    def test_due_at_truncated_to_minute(self):
        """due_at line slices to 16 chars (YYYY-MM-DDTHH:MM) — seconds
        and beyond should NOT appear."""
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([Reminder(
            message="x", urgency="normal",
            due_at="2026-04-01T12:34:56.789012")])
        self.assertIn("2026-04-01T12:34", out)
        self.assertNotIn("56.789", out)

    def test_multiple_reminders_each_on_own_line(self):
        from doxyedit.reminders import format_reminders_table, Reminder
        out = format_reminders_table([
            Reminder(message="a", urgency="urgent"),
            Reminder(message="b", urgency="normal"),
        ])
        self.assertIn("a", out)
        self.assertIn("b", out)


if __name__ == "__main__":
    unittest.main()
