# Asset Groups (Duplicates & Variants) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent duplicate groups and variant sets to assets, with a "Link Mode" toggle that visually highlights related assets when one is clicked.

**Architecture:** Two `specs` keys (`duplicate_group`, `variant_set`) on Asset objects store group membership. The browser builds lookup indexes on refresh. The delegate draws corner dots (always) and highlight borders (in Link Mode). Four creation paths: enhanced duplicate scanner, manual linking, perceptual hash auto-suggest, and filename stem auto-detect.

**Tech Stack:** PySide6 (QStyledItemDelegate painting, QPushButton toggle, QMenu context actions), existing MD5/phash infrastructure.

---

### Task 1: Data Model — Lookup Indexes on AssetBrowser

**Files:**
- Modify: `doxyedit/browser.py:1129` (AssetBrowser.__init__)
- Modify: `doxyedit/browser.py:2104` (_refresh_grid, end of method)

- [ ] **Step 1: Add link mode state and lookup dicts to AssetBrowser.__init__**

In `AssetBrowser.__init__` (around line 1129), after `self._selected_ids: set[str] = set()`, add:

```python
        # Link Mode — highlight duplicate/variant groups
        self._link_mode = False
        self._link_highlight_dupes: set[str] = set()   # asset IDs to draw red border
        self._link_highlight_variants: set[str] = set() # asset IDs to draw teal border
        self._duplicate_groups: dict[str, list[str]] = {}  # group_id → [asset_id, ...]
        self._variant_sets: dict[str, list[str]] = {}      # set_id → [asset_id, ...]
```

- [ ] **Step 2: Build indexes at end of _refresh_grid**

In `_refresh_grid` (around line 2156, after the count_label update), add index rebuild:

```python
        # Rebuild group/variant lookup indexes
        self._duplicate_groups.clear()
        self._variant_sets.clear()
        for a in self.project.assets:
            dg = a.specs.get("duplicate_group")
            if dg:
                self._duplicate_groups.setdefault(dg, []).append(a.id)
            vs = a.specs.get("variant_set")
            if vs:
                self._variant_sets.setdefault(vs, []).append(a.id)
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat(groups): add link mode state and group/variant lookup indexes"
```

---

### Task 2: Link Mode Toggle Button

**Files:**
- Modify: `doxyedit/browser.py:1244` (after filter buttons in toolbar)

- [ ] **Step 1: Add Link Mode toggle button after the filter buttons**

After `toolbar.addWidget(self.filter_show_ignored)` (line 1244), add:

```python
        self._link_mode_btn = QPushButton("Link Mode")
        self._link_mode_btn.setCheckable(True)
        self._link_mode_btn.setToolTip("Highlight duplicate groups and variant sets on click")
        self._link_mode_btn.setStyleSheet(self._btn_style())
        self._link_mode_btn.toggled.connect(self._on_link_mode_toggled)
        toolbar.addWidget(self._link_mode_btn)
```

- [ ] **Step 2: Add the toggle handler method**

Add to AssetBrowser (after `_on_filter_changed` or nearby):

```python
    def _on_link_mode_toggled(self, checked: bool):
        self._link_mode = checked
        if not checked:
            self._link_highlight_dupes.clear()
            self._link_highlight_variants.clear()
        self._list_view.viewport().update()
        for section in self._folder_sections:
            section.view.viewport().update()
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat(groups): add Link Mode toggle button to browser toolbar"
```

---

### Task 3: Selection Handler — Populate Highlights on Click

**Files:**
- Modify: `doxyedit/browser.py:2532` (_on_selection_changed_internal)
- Modify: `doxyedit/browser.py:2448` (_on_folder_selection_changed)

- [ ] **Step 1: Add highlight update helper**

Add to AssetBrowser:

```python
    def _update_link_highlights(self):
        """When link mode is active, find groups/variants of selected assets."""
        self._link_highlight_dupes.clear()
        self._link_highlight_variants.clear()
        if not self._link_mode or not self._selected_ids:
            return
        for aid in self._selected_ids:
            asset = self.project.get_asset(aid)
            if not asset:
                continue
            dg = asset.specs.get("duplicate_group")
            if dg and dg in self._duplicate_groups:
                for sibling_id in self._duplicate_groups[dg]:
                    if sibling_id != aid:
                        self._link_highlight_dupes.add(sibling_id)
            vs = asset.specs.get("variant_set")
            if vs and vs in self._variant_sets:
                for sibling_id in self._variant_sets[vs]:
                    if sibling_id != aid:
                        self._link_highlight_variants.add(sibling_id)
```

- [ ] **Step 2: Call it from _on_selection_changed_internal**

At the end of `_on_selection_changed_internal` (line ~2542), add:

```python
        self._update_link_highlights()
```

- [ ] **Step 3: Call it from _on_folder_selection_changed**

At the end of `_on_folder_selection_changed` (line ~2463), add:

```python
        self._update_link_highlights()
```

- [ ] **Step 4: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat(groups): populate link highlights on selection change"
```

---

### Task 4: Delegate Rendering — Corner Dots and Link Borders

**Files:**
- Modify: `doxyedit/browser.py:302` (ThumbnailModel — add new role)
- Modify: `doxyedit/browser.py:324` (ThumbnailModel.data — return specs)
- Modify: `doxyedit/browser.py:427` (_update_metrics — add new constants)
- Modify: `doxyedit/browser.py:530` (ThumbnailDelegate.paint — add dot/border drawing)

- [ ] **Step 1: Add GroupInfoRole to ThumbnailModel**

After the existing roles (line ~311), add:

```python
    GroupInfoRole = Qt.ItemDataRole.UserRole + 10  # (duplicate_group, variant_set, asset_id)
```

- [ ] **Step 2: Return group info in ThumbnailModel.data**

In the `data` method (around line 348), before `return None`, add:

```python
        elif role == self.GroupInfoRole:
            return (asset.specs.get("duplicate_group", ""),
                    asset.specs.get("variant_set", ""),
                    asset.id)
```

- [ ] **Step 3: Add dot/border metrics to _update_metrics**

In `_update_metrics` (around line 460, in the ratios section), add:

```python
        # Group/variant indicators
        GROUP_DOT_RATIO            = 0.45    # corner indicator dot radius
        LINK_BORDER_RATIO          = 0.2     # link mode highlight border width
```

In the derived measurements section (after star measurements), add:

```python
        # Group/variant indicators
        self.group_dot_radius = max(3, int(font_size * GROUP_DOT_RATIO))
        self.link_border_width = max(2, int(font_size * LINK_BORDER_RATIO))
```

- [ ] **Step 4: Draw corner dots and link borders in paint()**

In `ThumbnailDelegate.paint`, after the star drawing block (line ~748, before `painter.restore()`), add:

```python
        # Group/variant corner dots (always visible)
        group_info = index.data(ThumbnailModel.GroupInfoRole)
        if group_info:
            dup_group, var_set, asset_id = group_info
            dot_r = self.group_dot_radius
            # Red dot top-right for duplicate group
            if dup_group:
                dx = rect.x() + rect.width() - self.cell_padding - dot_r - 1
                dy = rect.y() + self.cell_padding + dot_r + 1
                painter.setBrush(QColor("#e06c6c"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(dx, dy), dot_r, dot_r)
            # Teal dot top-left for variant set
            if var_set:
                vx = rect.x() + self.cell_padding + dot_r + 1
                vy = rect.y() + self.cell_padding + dot_r + 1
                painter.setBrush(QColor("#5ca8b8"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(vx, vy), dot_r, dot_r)

            # Link mode highlight borders
            browser = self.parent()
            if browser and getattr(browser, '_link_mode', False):
                bw = self.link_border_width
                thumb_rect = QRect(rect.x() + self.cell_padding,
                                   rect.y() + self.cell_padding, ts, ts)
                if asset_id in getattr(browser, '_link_highlight_dupes', set()):
                    painter.setPen(QPen(QColor("#e06c6c"), bw))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(thumb_rect.adjusted(bw//2, bw//2, -bw//2, -bw//2),
                                            self.thumb_corner, self.thumb_corner)
                if asset_id in getattr(browser, '_link_highlight_variants', set()):
                    painter.setPen(QPen(QColor("#5ca8b8"), bw))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(thumb_rect.adjusted(bw//2, bw//2, -bw//2, -bw//2),
                                            self.thumb_corner, self.thumb_corner)
```

- [ ] **Step 5: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat(groups): delegate draws corner dots + link mode highlight borders"
```

---

### Task 5: Enhanced Duplicate Scanner — Write Group IDs

**Files:**
- Modify: `doxyedit/window.py:4538` (_find_duplicates)

- [ ] **Step 1: Add "Link as Duplicate Groups" button to the duplicate dialog**

In `_find_duplicates`, after the `remove_btn` block and before `btn_row.addStretch()` (around line 4635), add:

```python
            link_btn = QPushButton("Link as Duplicate Groups")
            link_btn.setToolTip("Write duplicate_group IDs to asset specs for Link Mode highlighting")
            def _link_dupes():
                for group in dupe_groups:
                    # Use the MD5 hash as the group ID (all in group share same hash)
                    h = hashlib.md5(Path(group[0].source_path).read_bytes()).hexdigest()
                    for i, asset in enumerate(group):
                        asset.specs["duplicate_group"] = h
                        if i == 0:
                            asset.specs["duplicate_keep"] = True
                        else:
                            asset.specs.pop("duplicate_keep", None)
                self._dirty = True
                self.browser.refresh()
                self.status.showMessage(f"Linked {len(dupe_groups)} duplicate group(s)", 3000)
                dlg.accept()
            link_btn.clicked.connect(_link_dupes)
            btn_row.addWidget(link_btn)
```

- [ ] **Step 2: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat(groups): duplicate scanner can write persistent group IDs"
```

---

### Task 6: Enhanced Similar Scanner — Create Variant Sets

**Files:**
- Modify: `doxyedit/window.py:4753` (_find_similar, after tag_btn)

- [ ] **Step 1: Add "Create Variant Sets" button to the similar images dialog**

After the `tag_btn` connect (around line 4753), add:

```python
        import uuid as _uuid
        link_btn = QPushButton(f"Create Variant Sets ({len(similar_groups)} groups)")
        link_btn.setToolTip("Write variant_set IDs to asset specs for Link Mode highlighting")
        def do_link_variants():
            for group in similar_groups:
                set_id = "vs_" + _uuid.uuid4().hex[:8]
                for asset in group:
                    asset.specs["variant_set"] = set_id
            self._dirty = True
            self.browser.refresh()
            self.status.showMessage(f"Created {len(similar_groups)} variant set(s)", 3000)
            dlg.accept()
        link_btn.clicked.connect(do_link_variants)
        btn_row.addWidget(link_btn)
```

- [ ] **Step 2: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat(groups): similar scanner can create persistent variant sets"
```

---

### Task 7: Manual Variant Linking — Right-Click Menu

**Files:**
- Modify: `doxyedit/browser.py:2900` (_on_context_menu)

- [ ] **Step 1: Add group/variant context menu actions**

In `_on_context_menu`, after the "Quick Tag" block and before the "Add Tag..." action (around line 2999), add:

```python
        # --- Group / Variant linking ---
        menu.addSeparator()
        if n_sel > 1:
            menu.addAction(f"Link {n_sel} as Variants", self._link_selected_as_variants)

        # Show group actions if asset belongs to a group
        dup_grp = asset.specs.get("duplicate_group")
        var_set = asset.specs.get("variant_set")
        if dup_grp and dup_grp in self._duplicate_groups:
            grp_ids = self._duplicate_groups[dup_grp]
            dup_menu = menu.addMenu(f"Duplicate Group ({len(grp_ids)})")
            dup_menu.addAction(f"Select All ({len(grp_ids)})", lambda: self._select_ids(grp_ids))
            is_keeper = asset.specs.get("duplicate_keep", False)
            if not is_keeper:
                dup_menu.addAction("Mark as Keeper", lambda a=asset: self._mark_as_keeper(a))
            dup_menu.addAction("Remove from Group", lambda a=asset: self._unlink_duplicate(a))
            dup_menu.addAction("Dissolve Group", lambda gid=dup_grp: self._dissolve_duplicate_group(gid))

        if var_set and var_set in self._variant_sets:
            set_ids = self._variant_sets[var_set]
            var_menu = menu.addMenu(f"Variant Set ({len(set_ids)})")
            var_menu.addAction(f"Select All ({len(set_ids)})", lambda: self._select_ids(set_ids))
            var_menu.addAction("Remove from Set", lambda a=asset: self._unlink_variant(a))
            var_menu.addAction("Dissolve Set", lambda sid=var_set: self._dissolve_variant_set(sid))
```

- [ ] **Step 2: Add the handler methods to AssetBrowser**

```python
    def _link_selected_as_variants(self):
        """Link all selected assets as a variant set."""
        import uuid
        assets = self.get_selected_assets()
        if len(assets) < 2:
            return
        # If any selected asset already has a variant_set, merge into that one
        existing_set = None
        for a in assets:
            vs = a.specs.get("variant_set")
            if vs:
                existing_set = vs
                break
        set_id = existing_set or ("vs_" + uuid.uuid4().hex[:8])
        for a in assets:
            a.specs["variant_set"] = set_id
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass

    def _select_ids(self, ids: list[str]):
        """Hard-select a list of asset IDs in the grid."""
        sel = self._list_view.selectionModel()
        sel.clearSelection()
        for i in range(self._model.rowCount()):
            idx = self._model.index(i)
            asset = self._model.get_asset(idx)
            if asset and asset.id in ids:
                sel.select(idx, sel.SelectionFlag.Select)

    def _mark_as_keeper(self, asset):
        dg = asset.specs.get("duplicate_group")
        if not dg:
            return
        for a in self.project.assets:
            if a.specs.get("duplicate_group") == dg:
                a.specs.pop("duplicate_keep", None)
        asset.specs["duplicate_keep"] = True
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass

    def _unlink_duplicate(self, asset):
        asset.specs.pop("duplicate_group", None)
        asset.specs.pop("duplicate_keep", None)
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass

    def _dissolve_duplicate_group(self, group_id: str):
        for a in self.project.assets:
            if a.specs.get("duplicate_group") == group_id:
                a.specs.pop("duplicate_group", None)
                a.specs.pop("duplicate_keep", None)
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass

    def _unlink_variant(self, asset):
        asset.specs.pop("variant_set", None)
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass

    def _dissolve_variant_set(self, set_id: str):
        for a in self.project.assets:
            if a.specs.get("variant_set") == set_id:
                a.specs.pop("variant_set", None)
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat(groups): right-click menu for manual variant linking and group management"
```

---

### Task 8: Filename Stem Auto-Detect

**Files:**
- Modify: `doxyedit/window.py:1534` (tools_menu, after Find Similar)

- [ ] **Step 1: Add menu action**

After `tools_menu.addAction("Find Similar Images (Perceptual)...", self._find_similar)` (line 1535), add:

```python
        tools_menu.addAction("Auto-Link Variants by Filename...", self._auto_link_by_filename)
```

- [ ] **Step 2: Add the method to MainWindow**

After `_find_similar` method (around line 4776), add:

```python
    def _auto_link_by_filename(self):
        """Group assets by shared filename stem and propose variant sets."""
        import re
        import uuid as _uuid
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel

        # Strip trailing suffixes to get canonical stem
        STRIP_PATTERN = re.compile(
            r'[_\-\s]*(0*\d{1,3}|v\d+|final|draft|wip|nsfw|sfw|color|bw|'
            r'sketch|lineart|flat|rendered|clean|raw|alt|crop|web|hd|hq|lq)$',
            re.IGNORECASE)

        def canonical_stem(name: str) -> str:
            stem = Path(name).stem
            prev = ""
            while stem != prev:
                prev = stem
                stem = STRIP_PATTERN.sub("", stem)
            return stem.lower().strip("_- ")

        # Group by canonical stem
        groups: dict[str, list] = {}
        for asset in self.project.assets:
            cs = canonical_stem(asset.source_path)
            if cs:
                groups.setdefault(cs, []).append(asset)

        # Only keep groups with 2+ assets that aren't already in a variant set
        proposable = {}
        for stem, assets in groups.items():
            unlinked = [a for a in assets if not a.specs.get("variant_set")]
            if len(unlinked) >= 2:
                proposable[stem] = unlinked

        if not proposable:
            QMessageBox.information(self, "Auto-Link", "No filename-based variant groups found.")
            return

        # Build preview
        total_assets = sum(len(g) for g in proposable.values())
        lines = [f"Found {len(proposable)} group(s) with {total_assets} assets\n"]
        for stem, assets in sorted(proposable.items()):
            lines.append(f"--- {stem} ({len(assets)} files) ---")
            for a in assets:
                lines.append(f"  {Path(a.source_path).name}")
            lines.append("")

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Auto-Link Variants — {len(proposable)} groups")
        dlg.resize(600, 450)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"{len(proposable)} groups · {total_assets} assets"))

        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)

        btn_row = QHBoxLayout()
        link_btn = QPushButton(f"Create {len(proposable)} Variant Sets")
        def do_link():
            for assets in proposable.values():
                set_id = "vs_" + _uuid.uuid4().hex[:8]
                for a in assets:
                    a.specs["variant_set"] = set_id
            self._dirty = True
            self.browser.refresh()
            self.status.showMessage(
                f"Created {len(proposable)} variant set(s) ({total_assets} assets)", 3000)
            dlg.accept()
        link_btn.clicked.connect(do_link)
        btn_row.addWidget(link_btn)
        close_btn = QPushButton("Cancel")
        close_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dlg.exec()
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat(groups): auto-link variants by filename stem detection"
```

---

### Task 9: Integration Test — End-to-End Verification

- [ ] **Step 1: Launch the app and verify**

```bash
cd E:/git/doxyedit && python -m doxyedit
```

Test checklist:
1. Open a project with multiple assets
2. Tools → Find Duplicates → "Link as Duplicate Groups" → red dots appear on grouped thumbnails
3. Multi-select 3 assets → right-click → "Link as Variants" → teal dots appear
4. Toggle "Link Mode" button on toolbar
5. Click a linked asset → siblings get colored borders
6. Click empty space → borders clear
7. Toggle Link Mode off → borders clear, dots remain
8. Right-click grouped asset → "Duplicate Group" / "Variant Set" submenus appear
9. "Select All" from submenu → all group members selected
10. "Dissolve" → dots disappear
11. Tools → Find Similar → "Create Variant Sets" works
12. Tools → Auto-Link Variants by Filename → dialog shows proposals, linking works

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "feat: asset groups — duplicates & variants with link mode highlighting"
git push
```
