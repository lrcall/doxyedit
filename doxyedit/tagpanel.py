"""Tag checklist panel — assign use-case tags to selected asset(s) with fitness indicators."""
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QFrame, QScrollArea, QTextEdit, QPushButton,
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
    toggled = Signal(str, bool)  # tag_id, checked
    hide_requested = Signal(str)  # tag_id
    delete_requested = Signal(str)  # tag_id
    rename_requested = Signal(str, str)  # old_tag_id, new_label

    def __init__(self, tag: TagPreset, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.setStyleSheet("TagRow { background: transparent; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # Fitness dot
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self._set_fitness("green")
        layout.addWidget(self.dot)

        # Checkbox
        self.checkbox = QCheckBox(tag.label)
        self.checkbox.setFont(QFont("Segoe UI", 10))
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

    def set_checked(self, checked: bool, block_signals=True):
        if block_signals:
            self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        if block_signals:
            self.checkbox.blockSignals(False)

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction(f"Rename '{self.tag.label}'", self._request_rename)
        menu.addAction(f"Hide '{self.tag.label}'", lambda: self.hide_requested.emit(self.tag.id))
        menu.addAction(f"Delete '{self.tag.label}' from project", lambda: self.delete_requested.emit(self.tag.id))
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
    tag_renamed = Signal(str, str, str)  # old_id, new_id, new_label

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_tagpanel")
        self._assets: list[Asset] = []
        self._img_dims: dict[str, tuple[int, int]] = {}
        self._rows: dict[str, TagRow] = {}
        self._hidden_tags: set[str] = set()
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

        # Content/workflow tags (no size requirements)
        for tag_id, tag in TAG_PRESETS.items():
            self._add_tag_row(tag_id, tag)

        # Separator
        self._sep1 = QFrame()
        self._sep1.setFrameShape(QFrame.Shape.HLine)
        self._sep1.setStyleSheet("color: rgba(128,128,128,0.2);")
        tag_layout.addWidget(self._sep1)
        self._sep1_label = QLabel("Platform / Size targets")
        self._sep1_label.setFont(QFont("Segoe UI", 8))
        self._sep1_label.setStyleSheet("color: rgba(128,128,128,0.4); padding: 2px 4px;")
        tag_layout.addWidget(self._sep1_label)

        # Sized tags (with dimensions)
        for tag_id, tag in TAG_SIZED.items():
            self._add_tag_row(tag_id, tag)

        # Separator for discovered/auto tags (hidden until needed)
        self._sep2 = QFrame()
        self._sep2.setFrameShape(QFrame.Shape.HLine)
        self._sep2.setStyleSheet("color: rgba(128,128,128,0.2);")
        self._sep2.setVisible(False)
        tag_layout.addWidget(self._sep2)
        self._sep2_label = QLabel("Discovered tags")
        self._sep2_label.setFont(QFont("Segoe UI", 8))
        self._sep2_label.setStyleSheet("color: rgba(128,128,128,0.4); padding: 2px 4px;")
        self._sep2_label.setVisible(False)
        tag_layout.addWidget(self._sep2_label)

        self._stretch = tag_layout.addStretch()
        scroll.setWidget(tag_widget)
        root.addWidget(scroll)

        # Notes
        notes_label = QLabel("Notes:")
        notes_label.setFont(QFont("Segoe UI", 9))
        notes_label.setStyleSheet("padding-top: 8px;")
        root.addWidget(notes_label)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        # Inherits from theme
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        root.addWidget(self.notes_edit)

    def _add_tag_row(self, tag_id: str, tag: TagPreset):
        row = TagRow(tag)
        row.toggled.connect(self._on_tag_toggled)
        row.hide_requested.connect(self._hide_tag)
        row.delete_requested.connect(self._delete_tag)
        row.rename_requested.connect(self._rename_tag)
        if tag_id in self._hidden_tags:
            row.setVisible(False)
        self._tag_layout.addWidget(row)
        self._rows[tag_id] = row

    def refresh_discovered_tags(self, assets: list, project=None):
        """Add rows for tags found in assets and custom_tags that aren't already in the panel."""
        from doxyedit.models import VINIK_COLORS
        added = False
        existing_ids = set(self._rows.keys())
        color_idx = 0

        # Collect all tag ids to add
        new_tags = {}

        # From project custom_tags
        if project and hasattr(project, 'custom_tags'):
            for ct in project.custom_tags:
                if isinstance(ct, dict) and ct.get("id") not in existing_ids:
                    tid = ct["id"]
                    new_tags[tid] = TagPreset(
                        id=tid, label=ct.get("label", tid),
                        color=ct.get("color", VINIK_COLORS[color_idx % len(VINIK_COLORS)]))
                    color_idx += 1

        # From asset tags
        for asset in assets:
            for t in asset.tags:
                if t not in existing_ids and t not in new_tags:
                    new_tags[t] = TagPreset(
                        id=t, label=t,
                        color=VINIK_COLORS[color_idx % len(VINIK_COLORS)])
                    color_idx += 1

        for tid, preset in new_tags.items():
            self._add_tag_row(tid, preset)
            existing_ids.add(tid)
            added = True

        if added:
            self._sep2.setVisible(True)
            self._sep2_label.setVisible(True)

    def _btn_style(self):
        return "QPushButton { padding: 4px 10px; }"

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
                self.hint_label.setText(f"{len(a.tags)} tag(s) applied — green dot = good fit")
            else:
                self.hint_label.setText("No tags yet — check boxes below to assign")
            w, h = self._get_dims(a)
            if w and h:
                ratio = f"{w/h:.2f}" if h else "?"
                self.dim_label.setText(f"{w} x {h} px  (ratio {ratio})")
            else:
                self.dim_label.setText("dimensions unknown")

            # Update fitness dots
            for tag_id, row in self._rows.items():
                if w and h:
                    row.update_fitness(w, h)
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

    def _hide_tag(self, tag_id: str):
        self._hidden_tags.add(tag_id)
        if tag_id in self._rows:
            self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)

    def _show_all_tags(self):
        self._hidden_tags.clear()
        for row in self._rows.values():
            row.setVisible(True)
        self._btn_show_all.setVisible(False)

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
        """Remove a tag from all assets and hide the row."""
        # Strip this tag from every asset in the current selection
        for asset in self._assets:
            if tag_id in asset.tags:
                asset.tags.remove(tag_id)
        # Hide the row
        if tag_id in self._rows:
            self._rows[tag_id].setVisible(False)
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
