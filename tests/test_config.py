"""config.py — global doxyedit.config.json overrides for tag presets,
shortcuts, and platforms.

The accessors fall back to model defaults when no override is set,
and merge config dicts over defaults when one is. Tests pin the
fallback / merge contract — if it breaks, users either lose their
saved overrides or get hardcoded defaults silently overwritten."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestAppConfigDefaults(unittest.TestCase):
    def test_get_tag_presets_falls_back_to_model_defaults(self):
        from doxyedit.config import AppConfig
        from doxyedit.models import TAG_PRESETS
        cfg = AppConfig()
        out = cfg.get_tag_presets()
        # All hardcoded preset IDs must be present.
        for tid in TAG_PRESETS:
            self.assertIn(tid, out)

    def test_get_tag_sized_falls_back(self):
        from doxyedit.config import AppConfig
        from doxyedit.models import TAG_SIZED
        cfg = AppConfig()
        out = cfg.get_tag_sized()
        for tid in TAG_SIZED:
            self.assertIn(tid, out)

    def test_get_tag_all_combines_both(self):
        from doxyedit.config import AppConfig
        from doxyedit.models import TAG_PRESETS, TAG_SIZED
        cfg = AppConfig()
        out = cfg.get_tag_all()
        for tid in {**TAG_PRESETS, **TAG_SIZED}:
            self.assertIn(tid, out)

    def test_get_shortcuts_falls_back(self):
        from doxyedit.config import AppConfig
        from doxyedit.models import TAG_SHORTCUTS_DEFAULT
        cfg = AppConfig()
        self.assertEqual(cfg.get_tag_shortcuts(), TAG_SHORTCUTS_DEFAULT)


class TestAppConfigOverrides(unittest.TestCase):
    def test_set_tag_preset_overrides_label_only(self):
        from doxyedit.config import AppConfig
        cfg = AppConfig()
        cfg.set_tag_preset("page", label="Custom Page")
        out = cfg.get_tag_presets()
        self.assertEqual(out["page"].label, "Custom Page")

    def test_set_tag_preset_creates_new_entry(self):
        from doxyedit.config import AppConfig
        cfg = AppConfig()
        cfg.set_tag_preset("brand_new", label="New", color="#abcdef")
        out = cfg.get_tag_presets()
        self.assertIn("brand_new", out)
        self.assertEqual(out["brand_new"].label, "New")

    def test_set_shortcut_assigns_key(self):
        from doxyedit.config import AppConfig
        cfg = AppConfig()
        cfg.set_shortcut("z", "wip")
        self.assertEqual(cfg.get_tag_shortcuts().get("z"), "wip")

    def test_set_shortcut_clears_old_binding_for_same_tag(self):
        """Re-binding a tag to a new key must drop the old key — otherwise
        a tag ends up with two shortcuts and the user can't clear it."""
        from doxyedit.config import AppConfig
        cfg = AppConfig()
        cfg.set_shortcut("z", "wip")
        cfg.set_shortcut("y", "wip")
        sc = cfg.get_tag_shortcuts()
        self.assertEqual(sc.get("y"), "wip")
        self.assertNotIn("z", sc)

    def test_set_shortcut_with_none_tag_clears_key(self):
        from doxyedit.config import AppConfig
        cfg = AppConfig()
        cfg.set_shortcut("z", "wip")
        cfg.set_shortcut("z", None)
        self.assertNotIn("z", cfg.get_tag_shortcuts())


class TestAppConfigPersistence(unittest.TestCase):
    def test_load_corrupt_file_returns_defaults(self):
        """Garbage JSON in the config file must NOT crash the app — the
        loader silently falls back to hardcoded defaults."""
        from doxyedit import config as cfg_mod
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doxyedit.config.json"
            p.write_text("{ this is not json", encoding="utf-8")
            with patch.object(cfg_mod, "CONFIG_PATH", p):
                cfg = cfg_mod.AppConfig().load()
                # Falls back to None (signal for "use model defaults")
                self.assertIsNone(cfg._tag_presets)

    def test_load_missing_file_is_noop(self):
        from doxyedit import config as cfg_mod
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "missing.json"
            with patch.object(cfg_mod, "CONFIG_PATH", p):
                cfg = cfg_mod.AppConfig().load()
                self.assertIsNone(cfg._tag_presets)
                self.assertIsNone(cfg._tag_shortcuts)

    def test_load_reads_overrides(self):
        from doxyedit import config as cfg_mod
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doxyedit.config.json"
            p.write_text(json.dumps({
                "tag_shortcuts": {"q": "page"},
            }), encoding="utf-8")
            with patch.object(cfg_mod, "CONFIG_PATH", p):
                cfg = cfg_mod.AppConfig().load()
                self.assertEqual(cfg.get_tag_shortcuts().get("q"), "page")


if __name__ == "__main__":
    unittest.main()
