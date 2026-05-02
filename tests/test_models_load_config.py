"""models.load_config + merge_platforms — per-project config.yaml
loading and platform merging. Used to add custom platforms (e.g., a
new tier card preset) without modifying the core PLATFORMS dict.
Tests pin the merge behavior so a regression doesn't silently drop
custom platforms or replace the built-ins."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestLoadConfig(unittest.TestCase):
    def test_missing_file_returns_empty_dict(self):
        from doxyedit.models import load_config
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(load_config(td), {})

    def test_valid_yaml_returns_dict(self):
        from doxyedit.models import load_config
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.yaml").write_text(
                "platforms:\n  custom:\n    name: Custom\n",
                encoding="utf-8")
            data = load_config(td)
            self.assertIn("platforms", data)

    def test_corrupt_yaml_returns_empty_dict(self):
        from doxyedit.models import load_config
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.yaml").write_text(
                "key: [unclosed\n  - inner: \"quote", encoding="utf-8")
            self.assertEqual(load_config(td), {})

    def test_non_dict_yaml_returns_empty(self):
        """A YAML file containing a top-level list or scalar is invalid
        for our purposes — must coerce to {} rather than crash callers
        that do `data.get(...)`."""
        from doxyedit.models import load_config
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "config.yaml").write_text(
                "- one\n- two\n", encoding="utf-8")
            self.assertEqual(load_config(td), {})


class TestMergePlatforms(unittest.TestCase):
    def test_empty_config_returns_builtin_platforms(self):
        from doxyedit.models import merge_platforms, PLATFORMS
        out = merge_platforms({})
        # All built-in platforms must still be present.
        for pid in PLATFORMS:
            self.assertIn(pid, out)

    def test_custom_platform_added(self):
        from doxyedit.models import merge_platforms
        cfg = {
            "platforms": {
                "myplat": {
                    "name": "My Platform",
                    "export_prefix": "myp",
                    "slots": [
                        {"name": "main", "width": 1200, "height": 800,
                         "required": True}
                    ],
                },
            },
        }
        out = merge_platforms(cfg)
        self.assertIn("myplat", out)
        self.assertEqual(out["myplat"].name, "My Platform")
        self.assertEqual(len(out["myplat"].slots), 1)
        self.assertEqual(out["myplat"].slots[0].width, 1200)

    def test_custom_overrides_builtin(self):
        """A custom platform with the same id replaces the built-in
        entry — that's how users tweak preset slot dimensions."""
        from doxyedit.models import merge_platforms, PLATFORMS
        any_builtin = next(iter(PLATFORMS))
        cfg = {
            "platforms": {
                any_builtin: {
                    "name": "Overridden",
                    "slots": [],
                },
            },
        }
        out = merge_platforms(cfg)
        self.assertEqual(out[any_builtin].name, "Overridden")

    def test_non_dict_platforms_section_ignored(self):
        from doxyedit.models import merge_platforms, PLATFORMS
        cfg = {"platforms": "not a dict"}
        out = merge_platforms(cfg)
        # Built-ins still present; nothing added.
        for pid in PLATFORMS:
            self.assertIn(pid, out)

    def test_non_dict_platform_entry_skipped(self):
        from doxyedit.models import merge_platforms
        cfg = {"platforms": {"bad": "string instead of dict"}}
        out = merge_platforms(cfg)
        self.assertNotIn("bad", out)

    def test_label_falls_back_to_name_then_slot(self):
        """slot.label defaults to slot.name if label key absent."""
        from doxyedit.models import merge_platforms
        cfg = {"platforms": {"p1": {"name": "P", "slots": [
            {"name": "slot_a", "width": 100, "height": 100},
        ]}}}
        out = merge_platforms(cfg)
        self.assertEqual(out["p1"].slots[0].label, "slot_a")


if __name__ == "__main__":
    unittest.main()
