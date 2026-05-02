"""strategy._project_notes_block — assembles project.notes + the
Agent Primer sub_note for inclusion in the AI prompt.

The Agent Primer is a high-priority block the user uses to inject
'always do X / never do Y' rules into Claude's strategy output.
A regression that drops or merges this block lets Claude ignore
the user's standing instructions silently."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestProjectNotesBlock(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        from doxyedit.strategy import _project_notes_block
        from doxyedit.models import Project
        self.assertEqual(_project_notes_block(Project()), "")

    def test_notes_appear_with_heading(self):
        from doxyedit.strategy import _project_notes_block
        from doxyedit.models import Project
        p = Project()
        p.notes = "post Tuesdays/Thursdays only"
        out = _project_notes_block(p)
        self.assertIn("## Creator's Project Notes", out)
        self.assertIn("Tuesdays/Thursdays", out)

    def test_blank_notes_omitted(self):
        from doxyedit.strategy import _project_notes_block
        from doxyedit.models import Project
        p = Project()
        p.notes = "   \n\t"
        # Blank-only notes should NOT add the heading.
        out = _project_notes_block(p)
        self.assertNotIn("Creator's Project Notes", out)

    def test_agent_primer_appears(self):
        from doxyedit.strategy import _project_notes_block
        from doxyedit.models import Project
        p = Project()
        p.sub_notes = {"Agent Primer": "always say SFW first"}
        out = _project_notes_block(p)
        self.assertIn("Agent Primer", out)
        self.assertIn("FOLLOW THESE RULES", out)
        self.assertIn("always say SFW first", out)

    def test_both_blocks_separated_by_blank_line(self):
        from doxyedit.strategy import _project_notes_block
        from doxyedit.models import Project
        p = Project()
        p.notes = "n"
        p.sub_notes = {"Agent Primer": "p"}
        out = _project_notes_block(p)
        # Two blocks → at least one double-newline separator.
        self.assertIn("\n\n", out)

    def test_blank_primer_omitted(self):
        from doxyedit.strategy import _project_notes_block
        from doxyedit.models import Project
        p = Project()
        p.sub_notes = {"Agent Primer": "   "}
        self.assertEqual(_project_notes_block(p), "")


if __name__ == "__main__":
    unittest.main()
