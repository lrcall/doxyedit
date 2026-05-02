"""bridge_data.py — pure helpers used to assemble the userscript
payload for the browser bridge. _truncate / _slugify_handle /
_split_title_body / _reddit_key all run on every push to the
userscript. Pin them so a refactor doesn't silently mangle the
handle, the Reddit title/body split, or the subreddit key
normalization."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestTruncate(unittest.TestCase):
    def test_short_string_unchanged(self):
        from doxyedit.bridge_data import _truncate
        self.assertEqual(_truncate("hello", 10), "hello")

    def test_exact_length_unchanged(self):
        from doxyedit.bridge_data import _truncate
        self.assertEqual(_truncate("12345", 5), "12345")

    def test_empty_returns_empty(self):
        from doxyedit.bridge_data import _truncate
        self.assertEqual(_truncate("", 10), "")
        self.assertEqual(_truncate(None, 10), "")

    def test_long_string_cut_on_word_boundary(self):
        from doxyedit.bridge_data import _truncate
        out = _truncate("hello there friend", 12)
        self.assertLessEqual(len(out), 12)
        # Cuts on space, so the result should not end with a partial word
        self.assertEqual(out, "hello there")

    def test_no_space_falls_back_to_hard_cut(self):
        from doxyedit.bridge_data import _truncate
        out = _truncate("supercalifragilistic", 5)
        self.assertEqual(len(out), 5)


class TestSlugifyHandle(unittest.TestCase):
    def test_collapses_special_chars_to_single_underscore(self):
        from doxyedit.bridge_data import _slugify_handle
        self.assertEqual(_slugify_handle("B.D. INC / Yacky"), "b_d_inc_yacky")

    def test_lowercases(self):
        from doxyedit.bridge_data import _slugify_handle
        self.assertEqual(_slugify_handle("HelloWorld"), "helloworld")

    def test_strips_leading_trailing_underscores(self):
        from doxyedit.bridge_data import _slugify_handle
        out = _slugify_handle("  -- name --  ")
        self.assertFalse(out.startswith("_"))
        self.assertFalse(out.endswith("_"))

    def test_unicode_collapsed(self):
        from doxyedit.bridge_data import _slugify_handle
        # Non-ASCII chars collapse to underscore
        out = _slugify_handle("café")
        self.assertNotIn("é", out)

    def test_empty_returns_empty(self):
        from doxyedit.bridge_data import _slugify_handle
        self.assertEqual(_slugify_handle(""), "")


class TestSplitTitleBody(unittest.TestCase):
    def test_empty_returns_empty_dict(self):
        from doxyedit.bridge_data import _split_title_body
        self.assertEqual(_split_title_body(""), {"title": "", "body": ""})

    def test_single_line_is_title_only(self):
        from doxyedit.bridge_data import _split_title_body
        self.assertEqual(
            _split_title_body("Just a title"),
            {"title": "Just a title", "body": ""},
        )

    def test_first_line_title_rest_body(self):
        from doxyedit.bridge_data import _split_title_body
        out = _split_title_body("Title here\n\nBody starts.\nMore body.")
        self.assertEqual(out["title"], "Title here")
        self.assertIn("Body starts", out["body"])

    def test_skips_leading_blank_lines(self):
        from doxyedit.bridge_data import _split_title_body
        out = _split_title_body("\n\nReal title\n\nBody.")
        self.assertEqual(out["title"], "Real title")

    def test_only_blank_lines_returns_empty(self):
        from doxyedit.bridge_data import _split_title_body
        self.assertEqual(_split_title_body("\n\n  \n"),
                         {"title": "", "body": ""})


class TestRedditKey(unittest.TestCase):
    def test_r_prefix_stripped(self):
        from doxyedit.bridge_data import _reddit_key
        self.assertEqual(_reddit_key("r/IndieDev"), "reddit_indiedev")

    def test_already_prefixed_lowercased(self):
        from doxyedit.bridge_data import _reddit_key
        self.assertEqual(_reddit_key("reddit_IndieDev"), "reddit_indiedev")

    def test_bare_subreddit_gets_prefix(self):
        from doxyedit.bridge_data import _reddit_key
        self.assertEqual(_reddit_key("hentai"), "reddit_hentai")

    def test_keeps_reddit_prefix_uppercase_subreddit_lowered(self):
        """Per the docstring: the literal `reddit_` prefix stays as-is,
        only the subreddit part lowercases."""
        from doxyedit.bridge_data import _reddit_key
        self.assertEqual(_reddit_key("reddit_RULE34"), "reddit_rule34")

    def test_plain_reddit_returns_lowercased(self):
        from doxyedit.bridge_data import _reddit_key
        self.assertEqual(_reddit_key("reddit"), "reddit")


if __name__ == "__main__":
    unittest.main()
