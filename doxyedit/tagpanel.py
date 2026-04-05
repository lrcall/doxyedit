"""Tag checklist panel — assign use-case tags to selected asset(s) with fitness indicators."""
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QFrame, QScrollArea, QTextEdit, QPushButton, QSplitter,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from doxyedit.models import Asset, TAG_PRESETS, TAG_SIZED, TAG_ALL, TAG_SHORTCUTS, TagPreset, check_fitness


FITNESS_COLORS = {
    "green": "#44cc44",
    "yellow": "#ffa500",
    "red": "#ff4444",
}


class TagRow(QFrame):
    """One tag checkbox with fitness indicator dot."""
    toggled = Signal(str, bool)
    hide_requested = Signal(str)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)
    pin_requested = Signal(str)
    shortcut_requested = Signal(str)
    visibility_toggled = Signal(str, bool)
    row_clicked = Signal(str, bool)  # tag_id, ctrl_held
    select_all_requested = Signal(str)  # tag_id

    def __init__(self, tag: TagPreset, parent=None):
        super().__init__(parent)
        self.tag = tag
        self._pinned = False
        self._row_selected = False
        self.setStyleSheet("TagRow { background: transparent; }")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        # Eye toggle — hide/show images with this tag
        self.eye_btn = QPushButton("\u25C9")  # ◉ when visible
        self.eye_btn.setFixedSize(24, 24)
        self.eye_btn.setCheckable(True)
        self.eye_btn.setChecked(True)
        self.eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.eye_btn.setToolTip("Toggle visibility — hide/show images with this tag")
        self.eye_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; font-size: 16px; padding: 0; color: rgba(100,200,100,0.8); }"
            "QPushButton:!checked { color: rgba(128,128,128,0.25); }")
        self.eye_btn.toggled.connect(self._on_eye_click)
        layout.addWidget(self.eye_btn)

        # Tag color dot (shows the tag's own color)
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.dot.setStyleSheet(
            f"background: {tag.color}; border-radius: 6px;"
            f" border: 1px solid rgba(0,0,0,0.3);")
        layout.addWidget(self.dot)

        # Checkbox — bold text in tag color
        self.checkbox = QCheckBox(tag.label)
        self.checkbox.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.checkbox.setStyleSheet(f"QCheckBox {{ color: {tag.color}; }}")
        self.checkbox.toggled.connect(lambda checked: self.toggled.emit(tag.id, checked))
        layout.addWidget(self.checkbox, 1)

        # Keyboard shortcut hint
        shortcut_key = ""
        for k, v in TAG_SHORTCUTS.items():
            if v == tag.id:
                shortcut_key = k
                break

        # Size + shortcut hint
        hints = []
        if tag.width and tag.height:
            hints.append(f"{tag.width}x{tag.height}")
        elif tag.width:
            hints.append(f"{tag.width}xflex")
        if shortcut_key:
            hints.append(f"[{shortcut_key}]")

        hint_label = QLabel("  ".join(hints) if hints else "any")
        hint_label.setFont(QFont("Segoe UI", 8))
        hint_label.setStyleSheet("color: rgba(128,128,128,0.5);")
        layout.addWidget(hint_label)

    def _set_fitness(self, level: str):
        color = FITNESS_COLORS.get(level, "#888")
        self.dot.setStyleSheet(
            f"background: {color}; border-radius: 6px; border: 1px solid rgba(0,0,0,0.3);"
        )
        self.dot.setToolTip(f"Fitness: {level}")

    def update_fitness(self, img_w: int, img_h: int):
        level = check_fitness(img_w, img_h, self.tag)
        self._set_fitness(level)

    def _on_eye_click(self, visible: bool):
        self.eye_btn.setText("\u25C9" if visible else "\u25CB")
        self.visibility_toggled.emit(self.tag.id, visible)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            self.row_clicked.emit(self.tag.id, bool(ctrl))
        super().mousePressEvent(event)

    def set_row_selected(self, selected: bool):
        self._row_selected = selected
        if selected:
            self.setStyleSheet("background: rgba(100,150,200,0.3); border-radius: 3px;")
        else:
            base = "border-left: 3px solid rgba(190,149,92,0.7);" if self._pinned else ""
            self.setStyleSheet(base)

    def set_checked(self, checked: bool, block_signals=True):
        if block_signals:
            self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        if block_signals:
            self.checkbox.blockSignals(False)

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        pin_label = "Unpin from top" if getattr(self, '_pinned', False) else "Pin to top"
        menu.addAction(pin_label, lambda: self.pin_requested.emit(self.tag.id))
        menu.addAction("Set Shortcut Key", lambda: self.shortcut_requested.emit(self.tag.id))
        menu.addSeparator()
        menu.addAction(f"Rename '{self.tag.label}'", self._request_rename)
        menu.addAction(f"Hide '{self.tag.label}'", lambda: self.hide_requested.emit(self.tag.id))
        menu.addAction(f"Delete '{self.tag.label}' from project", lambda: self.delete_requested.emit(self.tag.id))
        menu.addSeparator()
        menu.addAction(f"Select all with '{self.tag.label}'", lambda: self.select_all_requested.emit(self.tag.id))
        menu.exec(event.globalPos())

    def _request_rename(self):
        from PySide6.QtWidgets import QInputDialog
        dlg = QInputDialog(self.window())
        dlg.setWindowTitle("Rename Tag")
        dlg.setLabelText(f"New name for '{self.tag.label}':")
        dlg.setTextValue(self.tag.label)
        dlg.resize(400, 140)
        if dlg.exec():
            new_name = dlg.textValue().strip()
            if new_name and new_name != self.tag.label:
                self.rename_requested.emit(self.tag.id, new_name)


class TagPanel(QWidget):
    """Tag checklist for the currently selected asset(s)."""
    tags_changed = Signal()
    tag_deleted = Signal(str)
    tag_renamed = Signal(str, str, str)
    shortcut_changed = Signal(str, str)
    hidden_changed = Signal(list)
    filter_by_eye = Signal(list)  # list of tag_ids to HIDE from grid
    select_all_with_tag = Signal(str)  # select all assets with this tag

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_tagpanel")
        self._assets: list[Asset] = []
        self._img_dims: dict[str, tuple[int, int]] = {}
        self._rows: dict[str, TagRow] = {}
        self._tag_sections: dict[str, str] = {}  # tag_id → section name
        self._section_starts: dict[str, int] = {}  # section → layout index of first tag
        self._hidden_tags: set[str] = set()
        self._eye_hidden: set[str] = set()
        self._custom_shortcuts: dict[str, str] = {}
        self._selected_tag_rows: set[str] = set()  # multi-selected tag ids  # tag_id → key
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Header
        self.header = QLabel("Select an image to tag it")
        self.header.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.header.setStyleSheet("color: rgba(128,128,128,0.6); padding-bottom: 4px;")
        self.header.setWordWrap(True)
        root.addWidget(self.header)

        self.hint_label = QLabel("Click an image on the left, then check tags below")
        self.hint_label.setFont(QFont("Segoe UI", 9))
        self.hint_label.setStyleSheet("color: rgba(128,128,128,0.5); font-style: italic;")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.dim_label = QLabel("")
        self.dim_label.setFont(QFont("Segoe UI", 9))
        self.dim_label.setStyleSheet("color: rgba(128,128,128,0.7);")
        root.addWidget(self.dim_label)

        # Batch buttons
        batch_row = QHBoxLayout()
        btn_ignore = QPushButton("Mark Ignore")
        btn_ignore.setStyleSheet(self._btn_style())
        btn_ignore.clicked.connect(lambda: self._batch_tag("ignore", True))
        batch_row.addWidget(btn_ignore)

        btn_clear = QPushButton("Clear All")
        btn_clear.setStyleSheet(self._btn_style())
        btn_clear.clicked.connect(self._clear_all_tags)
        batch_row.addWidget(btn_clear)

        self._btn_show_all = QPushButton("Show All")
        self._btn_show_all.setStyleSheet(self._btn_style())
        self._btn_show_all.clicked.connect(self._show_all_tags)
        self._btn_show_all.setVisible(False)
        batch_row.addWidget(self._btn_show_all)

        batch_row.addStretch()
        root.addLayout(batch_row)

        # Tag checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { border: none; background: transparent; }")
        tag_widget = QWidget()
        tag_layout = QVBoxLayout(tag_widget)
        tag_layout.setSpacing(2)
        tag_layout.setContentsMargins(0, 0, 0, 0)

        self._tag_layout = tag_layout
        self._tag_scroll_widget = tag_widget

        self._collapsed_sections: set[str] = set()
        _lbl_style = ("QPushButton { color: rgba(128,128,128,0.4); padding: 2px 4px;"
                       " background: transparent; border: none; text-align: left; }"
                       "QPushButton:hover { color: rgba(128,128,128,0.7); }")

        def _make_section_label(text, section_id):
            btn = QPushButton(f"\u25BC {text}")  # ▼ expanded
            btn.setFont(QFont("Segoe UI", 8))
            btn.setStyleSheet(_lbl_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: self._toggle_section(section_id, btn, text))
            return btn

        def _make_sep(label_text, section_id, visible=True):
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("color: rgba(128,128,128,0.2);")
            sep.setVisible(visible)
            tag_layout.addWidget(sep)
            lbl = _make_section_label(label_text, section_id)
            lbl.setVisible(visible)
            tag_layout.addWidget(lbl)
            return sep, lbl

        # "Default" section label (no separator line above — it's the first section)
        self._default_lbl = _make_section_label("Default", "content")
        tag_layout.addWidget(self._default_lbl)

        # Content/workflow tags
        self._section_starts["content"] = tag_layout.count()
        for tag_id, tag in TAG_PRESETS.items():
            self._add_tag_row(tag_id, tag, section="content")

        self._sep1, self._sep1_label = _make_sep("Platform / Size targets", "sized")

        self._section_starts["sized"] = tag_layout.count()
        for tag_id, tag in TAG_SIZED.items():
            self._add_tag_row(tag_id, tag, section="sized")

        self._sep2, self._sep2_label = _make_sep("Custom / Project tags", "custom", visible=False)
        self._sep3, self._sep3_label = _make_sep("Visual / Mood / Dimension", "visual", visible=False)

        self._stretch = tag_layout.addStretch()
        scroll.setWidget(tag_widget)

        # Notes panel
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(2)
        notes_label = QLabel("Notes:")
        notes_label.setFont(QFont("Segoe UI", 9))
        notes_layout.addWidget(notes_label)
        self.notes_edit = QTextEdit()
        self.notes_edit.setMinimumHeight(30)
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        notes_layout.addWidget(self.notes_edit)

        # Splitter between tags and notes — draggable boundary
        self._tag_notes_split = QSplitter(Qt.Orientation.Vertical)
        self._tag_notes_split.addWidget(scroll)
        self._tag_notes_split.addWidget(notes_widget)
        self._tag_notes_split.setStretchFactor(0, 1)
        self._tag_notes_split.setStretchFactor(1, 0)
        self._tag_notes_split.setSizes([400, 80])
        root.addWidget(self._tag_notes_split)

    def _add_tag_row(self, tag_id: str, tag: TagPreset, section: str = "discovered", insert_after=None):
        row = TagRow(tag)
        row.toggled.connect(self._on_tag_toggled)
        row.hide_requested.connect(self._hide_tag)
        row.delete_requested.connect(self._delete_tag)
        row.rename_requested.connect(self._rename_tag)
        row.pin_requested.connect(self._pin_tag)
        row.shortcut_requested.connect(self._set_shortcut)
        row.visibility_toggled.connect(self._on_eye_toggled)
        row.row_clicked.connect(self._on_row_clicked)
        row.select_all_requested.connect(lambda tid: self.select_all_with_tag.emit(tid))
        if tag_id in self._hidden_tags:
            row.setVisible(False)
        if insert_after is not None:
            # Find the widget index and insert after it
            for i in range(self._tag_layout.count()):
                item = self._tag_layout.itemAt(i)
                if item and item.widget() is insert_after:
                    self._tag_layout.insertWidget(i + 1, row)
                    break
            else:
                self._tag_layout.addWidget(row)
        else:
            self._tag_layout.addWidget(row)
        self._rows[tag_id] = row
        self._tag_sections[tag_id] = section

    def refresh_discovered_tags(self, assets: list, project=None):
        """Add rows for tags found in assets and custom_tags, sorted into sections."""
        from doxyedit.models import VINIK_COLORS, VISUAL_TAGS
        existing_ids = set(self._rows.keys())
        color_idx = 0
        custom_tags = {}
        visual_tags = {}

        # From tag_definitions (preferred) and legacy custom_tags
        if project:
            all_project_tags = project.get_tags() if hasattr(project, 'get_tags') else {}
            for tid, preset in all_project_tags.items():
                if tid not in existing_ids and tid not in TAG_PRESETS and tid not in TAG_SIZED:
                    custom_tags[tid] = preset

        # From asset tags
        for asset in assets:
            for t in asset.tags:
                if t not in existing_ids and t not in custom_tags and t not in visual_tags:
                    preset = TagPreset(id=t, label=t,
                        color=VINIK_COLORS[color_idx % len(VINIK_COLORS)])
                    color_idx += 1
                    if t in VISUAL_TAGS:
                        visual_tags[t] = preset
                    else:
                        custom_tags[t] = preset

        # Add custom/project tags — insert after _sep2_label, sorted alphabetically
        if custom_tags:
            self._sep2.setVisible(True)
            self._sep2_label.setVisible(True)
            last_custom = self._sep2_label
            for tid, preset in sorted(custom_tags.items(), key=lambda x: x[1].label.lower()):
                self._add_tag_row(tid, preset, section="custom", insert_after=last_custom)
                last_custom = self._rows[tid]
                existing_ids.add(tid)

        # Add visual property tags — insert after _sep3_label (always last), sorted
        if visual_tags:
            self._sep3.setVisible(True)
            self._sep3_label.setVisible(True)
            last_visual = self._sep3_label
            for tid, preset in sorted(visual_tags.items(), key=lambda x: x[1].label.lower()):
                self._add_tag_row(tid, preset, section="visual", insert_after=last_visual)
                last_visual = self._rows[tid]
                existing_ids.add(tid)

    def _toggle_section(self, section_id: str, btn, label_text: str):
        """Collapse/expand a tag section."""
        if section_id in self._collapsed_sections:
            self._collapsed_sections.discard(section_id)
            btn.setText(f"\u25BC {label_text}")  # ▼ expanded
        else:
            self._collapsed_sections.add(section_id)
            btn.setText(f"\u25B6 {label_text}")  # ▶ collapsed
        for tag_id, row in self._rows.items():
            if self._tag_sections.get(tag_id) == section_id:
                row.setVisible(section_id not in self._collapsed_sections
                               and tag_id not in self._hidden_tags)

    def _btn_style(self):
        return "QPushButton { padding: 3px 8px; font-size: 10px; }"

    def update_font_size(self, font_size: int):
        """Scale all fonts in the tag panel."""
        f = font_size
        for row in self._rows.values():
            row._cb.setFont(QFont("Segoe UI", f, QFont.Weight.Bold))
            if hasattr(row, '_hint_label'):
                row._hint_label.setFont(QFont("Segoe UI", max(7, f - 2)))
        self.header.setFont(QFont("Segoe UI", f + 1, QFont.Weight.Bold))
        self.notes_edit.setFont(QFont("Segoe UI", f))

    def set_assets(self, assets: list[Asset]):
        """Set which asset(s) the tag panel is editing."""
        self._assets = assets

        if not assets:
            self.header.setText("Select an image to tag it")
            self.header.setStyleSheet("color: rgba(128,128,128,0.6); padding-bottom: 4px;")
            self.hint_label.setText("Click an image on the left, then check tags below")
            self.hint_label.show()
            self.dim_label.setText("")
            for row in self._rows.values():
                row.set_checked(False)
            return

        # Active state — highlight the panel
        self.header.setStyleSheet("padding-bottom: 4px;")
        self.hint_label.setText("Check the boxes below to tag this image for use")
        self.hint_label.setStyleSheet("font-style: italic; font-size: 9px;")

        if len(assets) == 1:
            a = assets[0]
            name = Path(a.source_path).stem
            self.header.setText(name)
            if a.tags:
                self.hint_label.hide()
            else:
                self.hint_label.hide()
            w, h = self._get_dims(a)
            if w and h:
                ratio = f"{w/h:.2f}" if h else "?"
                self.dim_label.setText(f"{w} x {h} px  (ratio {ratio})")
            else:
                self.dim_label.setText("dimensions unknown")

            # Update checkboxes
            for tag_id, row in self._rows.items():
                row.set_checked(tag_id in a.tags)

            self.notes_edit.blockSignals(True)
            self.notes_edit.setPlainText(a.notes)
            self.notes_edit.blockSignals(False)
        else:
            self.header.setText(f"{len(assets)} assets selected")
            self.dim_label.setText("batch mode — tags applied to all")
            # Show intersection of tags
            common_tags = set(assets[0].tags)
            for a in assets[1:]:
                common_tags &= set(a.tags)
            for tag_id, row in self._rows.items():
                row.set_checked(tag_id in common_tags)
            self.notes_edit.blockSignals(True)
            self.notes_edit.setPlainText("")
            self.notes_edit.blockSignals(False)

    def _get_dims(self, asset: Asset) -> tuple[int, int]:
        if asset.id in self._img_dims:
            return self._img_dims[asset.id]
        try:
            with Image.open(asset.source_path) as img:
                w, h = img.size
                self._img_dims[asset.id] = (w, h)
                return w, h
        except Exception:
            return 0, 0

    def _pin_tag(self, tag_id: str):
        """Pin/unpin a tag to the top of its own section."""
        if tag_id not in self._rows:
            return
        row = self._rows[tag_id]
        pinned = row._pinned
        row._pinned = not pinned

        if row._pinned:
            # Find the section start index
            section = self._tag_sections.get(tag_id, "content")
            # Find first row in this section
            target_idx = 0
            for i in range(self._tag_layout.count()):
                item = self._tag_layout.itemAt(i)
                if item and item.widget():
                    w = item.widget()
                    if isinstance(w, TagRow):
                        wid = w.tag.id
                        if self._tag_sections.get(wid) == section:
                            target_idx = i
                            break
            self._tag_layout.removeWidget(row)
            self._tag_layout.insertWidget(target_idx, row)
            row.setStyleSheet("border-left: 3px solid rgba(190,149,92,0.7);")
        else:
            row.setStyleSheet("")

    def _set_shortcut(self, tag_id: str):
        """Let user assign a keyboard shortcut key to a tag."""
        from PySide6.QtWidgets import QInputDialog
        key, ok = QInputDialog.getText(
            self.window(), "Set Shortcut",
            f"Enter a single key for '{self._rows[tag_id].tag.label}':\n"
            "(e.g. A, B, C, or a number)")
        if not ok or not key.strip():
            return
        key = key.strip().upper()[0]  # take first character
        self._custom_shortcuts[tag_id] = key
        # Update the hint label on the row
        if tag_id in self._rows:
            row = self._rows[tag_id]
            row.checkbox.setText(f"{row.tag.label} [{key}]")
        self.shortcut_changed.emit(tag_id, key)

    def _on_row_clicked(self, tag_id: str, ctrl_held: bool):
        """Ctrl+click to multi-select tag rows for batch operations."""
        if ctrl_held:
            if tag_id in self._selected_tag_rows:
                self._selected_tag_rows.discard(tag_id)
                if tag_id in self._rows:
                    self._rows[tag_id].set_row_selected(False)
            else:
                self._selected_tag_rows.add(tag_id)
                if tag_id in self._rows:
                    self._rows[tag_id].set_row_selected(True)
        else:
            # Clear previous, select this one
            for tid in self._selected_tag_rows:
                if tid in self._rows:
                    self._rows[tid].set_row_selected(False)
            self._selected_tag_rows = {tag_id}
            if tag_id in self._rows:
                self._rows[tag_id].set_row_selected(True)

        # If multiple selected, show batch context menu on right-click
        if len(self._selected_tag_rows) > 1:
            self.status_hint = f"{len(self._selected_tag_rows)} tags selected — right-click for batch actions"

    def contextMenuEvent(self, event):
        """Batch context menu when multiple tag rows are selected."""
        if len(self._selected_tag_rows) > 1:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            n = len(self._selected_tag_rows)
            menu.addAction(f"Hide All ({n})", self._batch_hide_selected)
            menu.addAction(f"Show All ({n})", self._batch_show_selected)
            menu.addAction(f"Delete All ({n})", self._batch_delete_selected)
            menu.addSeparator()
            menu.addAction("Clear Selection", self._clear_row_selection)
            menu.exec(event.globalPos())

    def _batch_hide_selected(self):
        for tid in list(self._selected_tag_rows):
            self._hide_tag(tid)
        self._clear_row_selection()

    def _batch_show_selected(self):
        for tid in list(self._selected_tag_rows):
            if tid in self._hidden_tags:
                self._hidden_tags.discard(tid)
            if tid in self._rows:
                self._rows[tid].setVisible(True)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        self.hidden_changed.emit(list(self._hidden_tags))
        self._clear_row_selection()

    def _batch_delete_selected(self):
        for tid in list(self._selected_tag_rows):
            self._delete_tag(tid)
        self._clear_row_selection()

    def _clear_row_selection(self):
        for tid in list(self._selected_tag_rows):
            if tid in self._rows:
                self._rows[tid].set_row_selected(False)
        self._selected_tag_rows.clear()

    def _on_eye_toggled(self, tag_id: str, visible: bool):
        """Eye button toggled — hide/show images tagged with this tag."""
        if visible:
            self._eye_hidden.discard(tag_id)
        else:
            self._eye_hidden.add(tag_id)
        self.filter_by_eye.emit(list(self._eye_hidden))

    def _hide_tag(self, tag_id: str):
        self._hidden_tags.add(tag_id)
        if tag_id in self._rows:
            self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        self.hidden_changed.emit(list(self._hidden_tags))

    def _show_all_tags(self):
        self._hidden_tags.clear()
        for row in self._rows.values():
            row.setVisible(True)
        self._btn_show_all.setVisible(False)
        self.hidden_changed.emit([])

    def load_hidden_tags(self, hidden: list[str]):
        """Restore hidden tags from project."""
        self._hidden_tags = set(hidden)
        for tag_id in hidden:
            if tag_id in self._rows:
                self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)

    def _rename_tag(self, old_id: str, new_label: str):
        """Rename a tag — updates the label in the row and the checkbox."""
        new_id = new_label.lower().replace(" ", "_").replace("/", "_")
        # Update all assets
        for asset in self._assets:
            if old_id in asset.tags:
                asset.tags.remove(old_id)
                if new_id not in asset.tags:
                    asset.tags.append(new_id)
        # Update the row widget
        if old_id in self._rows:
            row = self._rows.pop(old_id)
            row.tag = TagPreset(id=new_id, label=new_label, color=row.tag.color,
                                width=row.tag.width, height=row.tag.height, ratio=row.tag.ratio)
            row.checkbox.setText(new_label)
            self._rows[new_id] = row
        self.tag_renamed.emit(old_id, new_id, new_label)
        self.tags_changed.emit()

    def _delete_tag(self, tag_id: str):
        """Remove a tag from all assets and permanently hide the row."""
        for asset in self._assets:
            if tag_id in asset.tags:
                asset.tags.remove(tag_id)
        # Permanently hide (persists via hidden_tags)
        self._hidden_tags.add(tag_id)
        if tag_id in self._rows:
            self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        self.hidden_changed.emit(list(self._hidden_tags))
        self.tag_deleted.emit(tag_id)
        self.tags_changed.emit()

    def _set_tag(self, tag_id: str, checked: bool):
        for asset in self._assets:
            if checked and tag_id not in asset.tags:
                asset.tags.append(tag_id)
            elif not checked and tag_id in asset.tags:
                asset.tags.remove(tag_id)

    def _on_tag_toggled(self, tag_id: str, checked: bool):
        self._set_tag(tag_id, checked)
        self.tags_changed.emit()

    def _batch_tag(self, tag_id: str, checked: bool):
        self._set_tag(tag_id, checked)
        self._rows[tag_id].set_checked(checked)
        self.tags_changed.emit()

    def _clear_all_tags(self):
        for asset in self._assets:
            asset.tags.clear()
        for row in self._rows.values():
            row.set_checked(False)
        self.tags_changed.emit()

    def _on_notes_changed(self):
        if len(self._assets) == 1:
            self._assets[0].notes = self.notes_edit.toPlainText()
            self.tags_changed.emit()
