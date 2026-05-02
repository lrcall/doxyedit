"""studio_items._resolve_platform_menu — pure function that turns a
platform-submenu choice into an updated platforms list. Right-click
on a censor/overlay → "Apply to platforms..." submenu uses this.
A regression silently corrupts which platforms an overlay applies to."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestResolvePlatformMenu(unittest.TestCase):
    def test_all_action_clears_platforms(self):
        from doxyedit.studio_items import _resolve_platform_menu
        all_act = object()
        out = _resolve_platform_menu(all_act, all_act, {},
                                     current_platforms=["a", "b"])
        # "All platforms" → empty list (= all)
        self.assertEqual(out, [])

    def test_toggling_platform_adds_when_absent(self):
        from doxyedit.studio_items import _resolve_platform_menu
        all_act = object()
        twitter_act = object()
        plat_actions = {twitter_act: "twitter"}
        out = _resolve_platform_menu(twitter_act, all_act, plat_actions,
                                     current_platforms=["bluesky"])
        self.assertIn("twitter", out)
        self.assertIn("bluesky", out)

    def test_toggling_platform_removes_when_present(self):
        from doxyedit.studio_items import _resolve_platform_menu
        all_act = object()
        twitter_act = object()
        plat_actions = {twitter_act: "twitter"}
        out = _resolve_platform_menu(twitter_act, all_act, plat_actions,
                                     current_platforms=["twitter", "bluesky"])
        self.assertNotIn("twitter", out)
        self.assertIn("bluesky", out)

    def test_cancelled_menu_returns_unchanged(self):
        """If `chosen` is None or some unrelated action, the current
        platforms list must round-trip unmodified — closing the menu
        with Escape mustn't wipe the user's selection."""
        from doxyedit.studio_items import _resolve_platform_menu
        all_act = object()
        original = ["twitter", "bluesky"]
        out = _resolve_platform_menu(None, all_act, {},
                                     current_platforms=original)
        self.assertEqual(out, original)

    def test_does_not_mutate_input(self):
        from doxyedit.studio_items import _resolve_platform_menu
        all_act = object()
        twitter_act = object()
        original = ["bluesky"]
        _resolve_platform_menu(twitter_act, all_act,
                               {twitter_act: "twitter"},
                               current_platforms=original)
        self.assertEqual(original, ["bluesky"])  # unchanged


if __name__ == "__main__":
    unittest.main()
