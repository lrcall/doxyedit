"""Top-level helpers in models.py: next_tag_color, check_fitness,
toggle_tags. These run on every tag-add/asset-fitness check across a
70k-asset project — silent regressions corrupt user data or mislead
the fitness traffic light."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestNextTagColor(unittest.TestCase):
    def test_empty_returns_first_palette_color(self):
        from doxyedit.models import next_tag_color, VINIK_COLORS
        self.assertEqual(next_tag_color({}), VINIK_COLORS[0])

    def test_skips_used_colors(self):
        from doxyedit.models import next_tag_color, VINIK_COLORS, TagPreset
        existing = {"a": TagPreset("a", "A", None, None, "", VINIK_COLORS[0])}
        out = next_tag_color(existing)
        self.assertNotEqual(out, VINIK_COLORS[0])
        self.assertEqual(out, VINIK_COLORS[1])

    def test_cycles_when_all_used(self):
        from doxyedit.models import next_tag_color, VINIK_COLORS, TagPreset
        existing = {f"t{i}": TagPreset(f"t{i}", "L", None, None, "", c)
                    for i, c in enumerate(VINIK_COLORS)}
        # All colors used — must still return one rather than crash.
        out = next_tag_color(existing)
        self.assertIn(out, VINIK_COLORS)


class TestCheckFitness(unittest.TestCase):
    def test_no_size_requirement_is_green(self):
        from doxyedit.models import check_fitness, TagPreset
        tag = TagPreset("any", "Any", None, None, "", "#000000")
        self.assertEqual(check_fitness(100, 100, tag), "green")

    def test_too_small_is_red(self):
        from doxyedit.models import check_fitness, TagPreset
        tag = TagPreset("hero", "Hero", 1024, 576, "16:9", "#000000")
        self.assertEqual(check_fitness(800, 400, tag), "red")

    def test_correct_size_and_ratio_is_green(self):
        from doxyedit.models import check_fitness, TagPreset
        tag = TagPreset("hero", "Hero", 1024, 576, "16:9", "#000000")
        self.assertEqual(check_fitness(1920, 1080, tag), "green")

    def test_correct_size_wrong_ratio_is_yellow(self):
        from doxyedit.models import check_fitness, TagPreset
        tag = TagPreset("hero", "Hero", 1024, 576, "16:9", "#000000")
        # Square image, large enough, but wrong ratio
        self.assertEqual(check_fitness(2000, 2000, tag), "yellow")

    def test_flex_height_accepts_any_height(self):
        from doxyedit.models import check_fitness, TagPreset
        tag = TagPreset("stretch", "Stretch", 680, None, "flex", "#000000")
        # Wide enough → should be green regardless of height
        self.assertIn(check_fitness(800, 400, tag), ("green", "yellow"))
        self.assertEqual(check_fitness(500, 1000, tag), "red")  # too narrow


class TestToggleTags(unittest.TestCase):
    def test_adds_tag_to_assets_lacking_it(self):
        from doxyedit.models import toggle_tags, Asset
        a = Asset(id="a1", tags=[])
        b = Asset(id="b1", tags=["other"])
        added = toggle_tags([a, b], "wip")
        self.assertTrue(added)
        self.assertIn("wip", a.tags)
        self.assertIn("wip", b.tags)

    def test_removes_when_all_have(self):
        from doxyedit.models import toggle_tags, Asset
        a = Asset(id="a1", tags=["wip"])
        b = Asset(id="b1", tags=["wip", "other"])
        added = toggle_tags([a, b], "wip")
        self.assertFalse(added)
        self.assertNotIn("wip", a.tags)
        self.assertNotIn("wip", b.tags)
        self.assertIn("other", b.tags)  # other tags preserved

    def test_mixed_state_adds(self):
        from doxyedit.models import toggle_tags, Asset
        a = Asset(id="a1", tags=["wip"])
        b = Asset(id="b1", tags=[])
        added = toggle_tags([a, b], "wip")
        # Not all had it → add to those that didn't
        self.assertTrue(added)
        self.assertIn("wip", b.tags)
        # No duplicate added to a
        self.assertEqual(a.tags.count("wip"), 1)

    def test_empty_asset_list_returns_false(self):
        from doxyedit.models import toggle_tags
        # all() of empty is True so this is the "all have" branch → returns False
        self.assertFalse(toggle_tags([], "wip"))


if __name__ == "__main__":
    unittest.main()
