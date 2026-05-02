"""windroptarget.parse_paths — clipboard-text-to-paths helper used
by the global drop hotkey. Not Win32-specific despite the module
name. Pin the parsing rules so a regression doesn't silently drop
real files on the floor when the user invokes the hotkey."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestParsePaths(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.real_a = Path(self._tmpdir.name) / "a.png"
        self.real_b = Path(self._tmpdir.name) / "b.png"
        self.real_a.touch()
        self.real_b.touch()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_text_returns_empty(self):
        from doxyedit.windroptarget import parse_paths
        self.assertEqual(parse_paths(""), [])

    def test_single_real_path(self):
        from doxyedit.windroptarget import parse_paths
        out = parse_paths(str(self.real_a))
        self.assertEqual(out, [str(self.real_a)])

    def test_strips_double_quotes(self):
        from doxyedit.windroptarget import parse_paths
        out = parse_paths(f'"{self.real_a}"')
        self.assertEqual(out, [str(self.real_a)])

    def test_strips_single_quotes(self):
        from doxyedit.windroptarget import parse_paths
        out = parse_paths(f"'{self.real_a}'")
        self.assertEqual(out, [str(self.real_a)])

    def test_multiple_lines_collected(self):
        from doxyedit.windroptarget import parse_paths
        text = f"{self.real_a}\n{self.real_b}"
        out = parse_paths(text)
        self.assertEqual(set(out), {str(self.real_a), str(self.real_b)})

    def test_mixed_line_endings(self):
        from doxyedit.windroptarget import parse_paths
        # CRLF + bare CR
        text = f"{self.real_a}\r\n{self.real_b}\r"
        out = parse_paths(text)
        self.assertEqual(len(out), 2)

    def test_blank_lines_skipped(self):
        from doxyedit.windroptarget import parse_paths
        text = f"\n\n   \n{self.real_a}\n\n"
        out = parse_paths(text)
        self.assertEqual(out, [str(self.real_a)])

    def test_nonexistent_paths_filtered(self):
        from doxyedit.windroptarget import parse_paths
        text = f"/totally/fake/file.png\n{self.real_a}"
        out = parse_paths(text)
        self.assertEqual(out, [str(self.real_a)])

    def test_whitespace_trimmed(self):
        from doxyedit.windroptarget import parse_paths
        text = f"   {self.real_a}   "
        out = parse_paths(text)
        self.assertEqual(out, [str(self.real_a)])


if __name__ == "__main__":
    unittest.main()
