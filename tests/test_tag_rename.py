"""Project.rename_tag - project-wide tag rename integrity.

Renaming a tag must keep EVERY structure that references tag ids in
sync: tag_definitions (dict key + label), custom_tags (array ids,
no duplicate ids on collision), every asset.tags entry, tag_aliases
(both the new old->new entry AND existing alias values that pointed
at the old id), custom_shortcuts values, hidden_tags,
eye_hidden_tags, filter_presets tag_filters, and parent_id links.

Before this batch the rename logic lived split between
tagpanel._rename_tag (selected assets only) and window._on_tag_renamed
(project sweep), and MISSED: hidden/eye-hidden lists, alias value
re-pointing, filter presets, and custom_tags dedupe on collision.
These tests pin the extracted Project.rename_tag contract.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.factory import make_project


class TestProjectRenameTag(unittest.TestCase):
    """Pure model-level tests - no Qt required."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.proj = make_project(self.tmp_path, n_assets=3)

    def tearDown(self):
        self._tmp.cleanup()

    # ---- basic rename ------------------------------------------------

    def test_rename_updates_tag_definitions_key_and_label(self):
        changed = self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertTrue(changed)
        self.assertNotIn("subject_a", self.proj.tag_definitions)
        self.assertIn("hero_a", self.proj.tag_definitions)
        defn = self.proj.tag_definitions["hero_a"]
        self.assertEqual(defn["label"], "Hero A")
        # Color carried over from the old definition
        self.assertEqual(defn["color"], "#cc8844")

    def test_rename_updates_custom_tags_array(self):
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        ids = [ct["id"] for ct in self.proj.custom_tags]
        self.assertNotIn("subject_a", ids)
        self.assertIn("hero_a", ids)
        self.assertEqual(ids.count("hero_a"), 1)
        entry = next(ct for ct in self.proj.custom_tags
                     if ct["id"] == "hero_a")
        self.assertEqual(entry["label"], "Hero A")
        # tag_definitions and custom_tags stay in sync (project rule)
        self.assertEqual(set(self.proj.tag_definitions.keys()), set(ids))

    def test_rename_updates_every_asset(self):
        had_old = [a.id for a in self.proj.assets if "subject_a" in a.tags]
        self.assertTrue(had_old)  # factory gives even assets subject_a
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        for a in self.proj.assets:
            self.assertNotIn("subject_a", a.tags)
        for a in self.proj.assets:
            if a.id in had_old:
                self.assertEqual(a.tags.count("hero_a"), 1)
            else:
                self.assertNotIn("hero_a", a.tags)

    def test_rename_preserves_tag_position_in_asset(self):
        # subject_a is the SECOND tag on asset 0 (after "factory") -
        # rename must not shuffle it to the end.
        asset = self.proj.assets[0]
        idx = asset.tags.index("subject_a")
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertEqual(asset.tags.index("hero_a"), idx)

    def test_rename_adds_alias(self):
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertEqual(self.proj.tag_aliases.get("subject_a"), "hero_a")

    def test_rename_remaps_custom_shortcuts_values(self):
        self.proj.custom_shortcuts = {"q": "subject_a", "w": "factory"}
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertEqual(self.proj.custom_shortcuts["q"], "hero_a")
        self.assertEqual(self.proj.custom_shortcuts["w"], "factory")

    # ---- no-op guards ------------------------------------------------

    def test_same_id_label_only_change(self):
        # Renaming "Subject A" -> "SUBJECT  A" derives the same id -
        # only the display label changes, no alias is written.
        changed = self.proj.rename_tag("subject_a", "subject_a",
                                       "Subject Alpha")
        self.assertTrue(changed)
        self.assertEqual(
            self.proj.tag_definitions["subject_a"]["label"],
            "Subject Alpha")
        entry = next(ct for ct in self.proj.custom_tags
                     if ct["id"] == "subject_a")
        self.assertEqual(entry["label"], "Subject Alpha")
        # No self-alias
        self.assertNotIn("subject_a", self.proj.tag_aliases)

    def test_empty_ids_are_noop(self):
        self.assertFalse(self.proj.rename_tag("", "x", "X"))
        self.assertFalse(self.proj.rename_tag("subject_a", "", ""))
        self.assertIn("subject_a", self.proj.tag_definitions)

    def test_unknown_old_id_is_noop(self):
        before_aliases = dict(self.proj.tag_aliases)
        changed = self.proj.rename_tag("no_such_tag", "whatever", "Whatever")
        self.assertFalse(changed)
        self.assertEqual(self.proj.tag_aliases, before_aliases)
        self.assertNotIn("whatever", self.proj.tag_definitions)

    # ---- MISS #1: hidden / eye-hidden lists --------------------------

    def test_hidden_tags_follow_rename(self):
        self.proj.hidden_tags = ["subject_a", "factory"]
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertNotIn("subject_a", self.proj.hidden_tags)
        self.assertIn("hero_a", self.proj.hidden_tags)
        self.assertIn("factory", self.proj.hidden_tags)

    def test_eye_hidden_tags_follow_rename(self):
        self.proj.eye_hidden_tags = ["subject_a"]
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertNotIn("subject_a", self.proj.eye_hidden_tags)
        self.assertIn("hero_a", self.proj.eye_hidden_tags)

    def test_hidden_rename_does_not_duplicate(self):
        # Target id already hidden - membership swap must not create
        # a duplicate list entry.
        self.proj.hidden_tags = ["subject_a", "subject_b"]
        self.proj.rename_tag("subject_a", "subject_b", "Subject B")
        self.assertEqual(self.proj.hidden_tags.count("subject_b"), 1)
        self.assertNotIn("subject_a", self.proj.hidden_tags)

    # ---- MISS #2: alias values pointing at the old id ----------------

    def test_existing_alias_values_repointed(self):
        # legacy_a -> subject_a chain: after renaming subject_a the
        # alias must point at the NEW id, because load-time resolution
        # is single-hop (aliases.get(t, t)).
        self.proj.tag_aliases["legacy_a"] = "subject_a"
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertEqual(self.proj.tag_aliases["legacy_a"], "hero_a")
        self.assertEqual(self.proj.tag_aliases["subject_a"], "hero_a")

    def test_alias_chain_resolves_after_save_load(self):
        # End-to-end: a project file that still contains the LEGACY
        # tag id on an asset must load with the final renamed id.
        from doxyedit.models import Project
        self.proj.tag_aliases["legacy_a"] = "subject_a"
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        path = self.tmp_path / "renamed.doxyproj.json"
        self.proj.save(str(path))
        # Hand-edit the saved file: tag an asset with the legacy id
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["assets"][0]["tags"].append("legacy_a")
        path.write_text(json.dumps(raw, ensure_ascii=False),
                        encoding="utf-8")
        loaded = Project.load(str(path))
        tags0 = loaded.assets[0].tags
        self.assertNotIn("legacy_a", tags0)
        self.assertNotIn("subject_a", tags0)
        self.assertIn("hero_a", tags0)
        # No duplicate hero_a from the merge
        self.assertEqual(tags0.count("hero_a"), 1)

    def test_resurrected_id_alias_removed(self):
        # subject_a was once renamed away (alias subject_a -> gone_tag
        # exists). Renaming ANOTHER tag TO subject_a makes it live
        # again - the stale alias must go, or every subject_a tag
        # would be remapped away on next load.
        self.proj.tag_aliases["hero_a"] = "subject_b"
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertNotIn("hero_a", self.proj.tag_aliases)
        self.assertEqual(self.proj.tag_aliases["subject_a"], "hero_a")

    # ---- MISS #3: filter presets --------------------------------------

    def test_filter_presets_tag_filters_rewritten(self):
        self.proj.filter_presets = [
            {"name": "picks", "icon": "*",
             "state": {"tag_filters": ["subject_a", "factory"],
                       "starred_only": True}},
            {"name": "empty", "icon": "*", "state": {}},
        ]
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        filters = self.proj.filter_presets[0]["state"]["tag_filters"]
        self.assertEqual(filters, ["hero_a", "factory"])
        # Other state keys untouched
        self.assertTrue(
            self.proj.filter_presets[0]["state"]["starred_only"])
        # Preset without tag_filters survives
        self.assertEqual(self.proj.filter_presets[1]["state"], {})

    def test_filter_presets_dedupe_on_collision(self):
        self.proj.filter_presets = [
            {"name": "both", "icon": "*",
             "state": {"tag_filters": ["subject_a", "subject_b"]}},
        ]
        self.proj.rename_tag("subject_a", "subject_b", "Subject B")
        filters = self.proj.filter_presets[0]["state"]["tag_filters"]
        self.assertEqual(filters.count("subject_b"), 1)
        self.assertNotIn("subject_a", filters)

    # ---- MISS #4: collision with an existing target id ---------------

    def test_collision_merges_asset_tags_without_duplicates(self):
        # asset 1 has subject_b; give asset 0 both to force the merge
        self.proj.assets[0].tags.append("subject_b")
        self.proj.rename_tag("subject_a", "subject_b", "Subject B")
        for a in self.proj.assets:
            self.assertNotIn("subject_a", a.tags)
            self.assertLessEqual(a.tags.count("subject_b"), 1)
        self.assertIn("subject_b", self.proj.assets[0].tags)

    def test_collision_keeps_single_custom_tags_entry(self):
        self.proj.rename_tag("subject_a", "subject_b", "Subject B")
        ids = [ct["id"] for ct in self.proj.custom_tags]
        self.assertEqual(ids.count("subject_b"), 1)
        self.assertNotIn("subject_a", ids)
        # Sync rule holds after the merge
        self.assertEqual(set(self.proj.tag_definitions.keys()), set(ids))

    def test_collision_renamed_definition_wins(self):
        # Matches the pre-existing window behavior: the renamed tag's
        # definition takes over the target key.
        self.proj.rename_tag("subject_a", "subject_b", "Subject B")
        defn = self.proj.tag_definitions["subject_b"]
        self.assertEqual(defn["color"], "#cc8844")  # subject_a's color
        self.assertEqual(defn["label"], "Subject B")
        entry = next(ct for ct in self.proj.custom_tags
                     if ct["id"] == "subject_b")
        self.assertEqual(entry["color"], "#cc8844")

    # ---- related id references ----------------------------------------

    def test_parent_id_links_follow_rename(self):
        self.proj.tag_definitions["child_tag"] = {
            "label": "Child", "color": "#112233",
            "parent_id": "subject_a"}
        self.proj.custom_tags.append({
            "id": "child_tag", "label": "Child", "color": "#112233",
            "parent_id": "subject_a"})
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertEqual(
            self.proj.tag_definitions["child_tag"]["parent_id"], "hero_a")
        ct = next(c for c in self.proj.custom_tags
                  if c.get("id") == "child_tag")
        self.assertEqual(ct["parent_id"], "hero_a")
        self.assertEqual(self.proj.get_tag_children("hero_a"),
                         ["child_tag"])

    def test_tag_users_index_refreshed(self):
        # Build the inverted index, then rename - the index must not
        # serve stale ids afterwards.
        self.assertIn("subject_a", self.proj.tag_users)
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        self.assertNotIn("subject_a", self.proj.tag_users)
        self.assertIn("hero_a", self.proj.tag_users)

    # ---- round trip -----------------------------------------------------

    def test_save_load_round_trip_after_rename(self):
        from doxyedit.models import Project
        self.proj.hidden_tags = ["subject_a"]
        self.proj.custom_shortcuts = {"q": "subject_a"}
        self.proj.rename_tag("subject_a", "hero_a", "Hero A")
        path = self.tmp_path / "rt.doxyproj.json"
        self.proj.save(str(path))
        loaded = Project.load(str(path))
        self.assertIn("hero_a", loaded.tag_definitions)
        self.assertNotIn("subject_a", loaded.tag_definitions)
        self.assertIn("hero_a", loaded.hidden_tags)
        self.assertEqual(loaded.custom_shortcuts["q"], "hero_a")
        self.assertEqual(loaded.tag_aliases["subject_a"], "hero_a")
        for a in loaded.assets:
            self.assertNotIn("subject_a", a.tags)


class TestTagPanelRenameDelegation(unittest.TestCase):
    """tagpanel._rename_tag delegates the data sync to
    Project.rename_tag and keeps its widget bookkeeping local."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.proj = make_project(self.tmp_path, n_assets=3)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_panel(self):
        from doxyedit.tagpanel import TagPanel
        panel = TagPanel()
        panel.refresh_discovered_tags(self.proj.assets, self.proj)
        return panel

    def test_refresh_binds_project(self):
        panel = self._make_panel()
        self.assertIs(getattr(panel, "_project", None), self.proj)

    def test_rename_delegates_to_project(self):
        panel = self._make_panel()
        # Select only asset 1 (which has subject_b, NOT subject_a) to
        # prove the rename reaches ALL project assets via the model,
        # not just the panel's selection.
        panel.set_assets([self.proj.assets[1]])
        panel._rename_tag("subject_a", "Hero A")
        self.assertIn("hero_a", self.proj.tag_definitions)
        self.assertNotIn("subject_a", self.proj.tag_definitions)
        for a in self.proj.assets:
            self.assertNotIn("subject_a", a.tags)
        self.assertIn("hero_a", self.proj.assets[0].tags)
        self.assertEqual(self.proj.tag_aliases.get("subject_a"), "hero_a")

    def test_rename_emits_signal_and_swaps_row(self):
        panel = self._make_panel()
        got = []
        panel.tag_renamed.connect(
            lambda o, n, lbl: got.append((o, n, lbl)))
        panel._rename_tag("subject_a", "Hero A")
        self.assertEqual(got, [("subject_a", "hero_a", "Hero A")])
        self.assertIn("hero_a", panel._rows)
        self.assertNotIn("subject_a", panel._rows)
        self.assertEqual(panel._rows["hero_a"].tag.label, "Hero A")

    def test_rename_swaps_panel_hidden_sets(self):
        panel = self._make_panel()
        panel._hidden_tags.add("subject_a")
        panel._eye_hidden.add("subject_a")
        panel._rename_tag("subject_a", "Hero A")
        self.assertNotIn("subject_a", panel._hidden_tags)
        self.assertIn("hero_a", panel._hidden_tags)
        self.assertNotIn("subject_a", panel._eye_hidden)
        self.assertIn("hero_a", panel._eye_hidden)

    def test_rename_without_project_still_updates_selection(self):
        # Legacy fallback: no project bound - panel updates its own
        # selected assets and emits; the window layer does the sweep.
        from doxyedit.tagpanel import TagPanel
        panel = TagPanel()
        panel.set_assets([self.proj.assets[0]])
        panel._rename_tag("subject_a", "Hero A")
        self.assertIn("hero_a", self.proj.assets[0].tags)
        self.assertNotIn("subject_a", self.proj.assets[0].tags)


if __name__ == "__main__":
    unittest.main()
