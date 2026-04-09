"""Info panel — asset metadata display for the right sidebar."""
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QScrollArea, QFrame, QPushButton, QLineEdit, QCompleter,
)
from PySide6.QtCore import Qt, Signal, QStringListModel
from PySide6.QtGui import QFont, QColor

from doxyedit.browser import FlowLayout


class _TagPill(QPushButton):
    """Clickable tag pill with remove button."""
    removed = Signal(str)  # tag_id

    def __init__(self, tag_id: str, removable: bool = True, parent=None):
        super().__init__(parent)
        self.tag_id = tag_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(22)
        label = tag_id
        if removable:
            label += " \u00d7"
            self.clicked.connect(lambda: self.removed.emit(self.tag_id))
        self.setText(label)
        self.setStyleSheet("")


class InfoPanel(QWidget):
    """Right sidebar showing metadata for the selected asset(s)."""

    tags_modified = Signal()  # emitted when user edits tags/notes inline

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("info_panel")
        self._assets = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        self._header = QLabel("No selection")
        self._header.setFont(QFont("", -1, QFont.Weight.Bold))
        self._header.setWordWrap(True)
        outer.addWidget(self._header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("")
        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(8, 4, 8, 8)
        self._layout.setSpacing(6)

        # Filename
        self._name_label = QLabel()
        self._name_label.setWordWrap(True)
        self._name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._name_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Properties section
        self._props_label = QLabel()
        self._props_label.setWordWrap(True)
        self._props_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._props_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Palette section
        self._palette_header = QLabel("Palette")
        self._palette_header.setFont(QFont("", -1, QFont.Weight.Bold))
        self._layout.addWidget(self._palette_header)
        self._palette_row = QHBoxLayout()
        self._palette_row.setSpacing(4)
        self._palette_row.setContentsMargins(0, 0, 0, 0)
        self._palette_container = QWidget()
        self._palette_container.setLayout(self._palette_row)
        self._layout.addWidget(self._palette_container)

        # Separator after palette
        self._layout.addWidget(self._separator())

        # Tags section (editable)
        self._tags_header = QLabel("Tags")
        self._tags_header.setFont(QFont("", -1, QFont.Weight.Bold))
        self._layout.addWidget(self._tags_header)
        self._tag_flow_widget = QWidget()
        self._tag_flow = FlowLayout(self._tag_flow_widget, spacing=4)
        self._layout.addWidget(self._tag_flow_widget)
        # "+" add tag button
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setFixedSize(22, 22)
        self._add_tag_btn.setToolTip("Add tag")
        self._add_tag_btn.clicked.connect(self._start_add_tag)
        # Tag add inline editor (hidden by default)
        self._tag_add_edit = QLineEdit()
        self._tag_add_edit.setFixedHeight(22)
        self._tag_add_edit.setMaximumWidth(120)
        self._tag_add_edit.setPlaceholderText("tag name...")
        self._tag_add_edit.returnPressed.connect(self._finish_add_tag)
        self._tag_add_edit.hide()
        self._available_tags: list[str] = []
        self._completer_model = QStringListModel()
        self._completer = QCompleter(self._completer_model)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._tag_add_edit.setCompleter(self._completer)

        # Separator
        self._layout.addWidget(self._separator())

        # Assignments section
        self._assign_header = QLabel("Platforms")
        self._assign_header.setFont(QFont("", -1, QFont.Weight.Bold))
        self._layout.addWidget(self._assign_header)
        self._assign_label = QLabel()
        self._assign_label.setWordWrap(True)
        self._layout.addWidget(self._assign_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Notes section (editable)
        self._notes_header = QLabel("Notes")
        self._notes_header.setFont(QFont("", -1, QFont.Weight.Bold))
        self._layout.addWidget(self._notes_header)
        self._notes_edit = QTextEdit()
        self._notes_edit.setMinimumHeight(40)
        self._notes_edit.setMaximumHeight(120)
        self._notes_edit.setPlaceholderText("Add notes...")
        self._notes_edit.textChanged.connect(self._on_notes_changed)
        self._layout.addWidget(self._notes_edit)

        self._layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.setMinimumWidth(100)

    def _render_palette(self, colors: list):
        """Render color swatches from hex color list."""
        # Clear existing swatches
        while self._palette_row.count():
            item = self._palette_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not colors:
            self._palette_header.hide()
            self._palette_container.hide()
            return

        self._palette_header.show()
        self._palette_container.show()
        for hex_color in colors[:5]:
            swatch = QLabel()
            swatch.setFixedSize(20, 20)
            swatch.setStyleSheet(
                f"background: {hex_color}; border-radius: 10px; border: 1px solid rgba(255,255,255,0.15);")
            swatch.setToolTip(hex_color)
            self._palette_row.addWidget(swatch)
        self._palette_row.addStretch()

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("")
        line.setFixedHeight(1)
        return line

    def set_assets(self, assets: list):
        """Update the panel to show info for the given asset(s)."""
        self._assets = assets

        if not assets:
            self._header.setText("No selection")
            self._name_label.setText("")
            self._props_label.setText("")
            self._rebuild_tag_pills([])
            self._assign_label.setText("")
            self._notes_edit.blockSignals(True)
            self._notes_edit.clear()
            self._notes_edit.blockSignals(False)
            self._notes_edit.hide()
            self._render_palette([])
            return

        if len(assets) == 1:
            self._show_single(assets[0])
        else:
            self._show_multi(assets)

    def _show_single(self, asset):
        """Display detailed info for a single asset."""
        p = Path(asset.source_path)
        self._header.setText(p.name)
        self._name_label.setText(f"<b>Path:</b> {p.parent}")

        # Properties
        props = []
        ext = p.suffix.upper().lstrip(".")
        props.append(f"<b>Format:</b> {ext}")
        # File size
        try:
            size = os.path.getsize(asset.source_path)
            if size < 1024:
                props.append(f"<b>Size:</b> {size} B")
            elif size < 1024 * 1024:
                props.append(f"<b>Size:</b> {size / 1024:.1f} KB")
            else:
                props.append(f"<b>Size:</b> {size / (1024*1024):.1f} MB")
        except OSError:
            props.append("<b>Size:</b> unknown")
        # Dimensions from specs
        w = asset.specs.get("w", "")
        h = asset.specs.get("h", "")
        if w and h:
            props.append(f"<b>Dimensions:</b> {w} × {h}")
        # Star
        if asset.starred:
            stars = "★" * asset.starred
            props.append(f"<b>Rating:</b> {stars}")
        self._props_label.setText("<br>".join(props))

        # Tags (editable pills)
        self._rebuild_tag_pills(asset.tags, removable=True)

        # Assignments
        if asset.assignments:
            lines = []
            for a in asset.assignments:
                status_icon = {"posted": "✓", "ready": "●", "pending": "○", "skip": "—"}.get(
                    a.status, "?")
                lines.append(f"{status_icon} {a.platform} / {a.slot} — {a.status}")
            self._assign_label.setText("<br>".join(lines))
        else:
            self._assign_label.setText("<i>Not assigned</i>")

        # Palette
        self._render_palette(asset.specs.get("palette", []))

        # Notes (editable)
        self._notes_edit.show()
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(asset.notes or "")
        self._notes_edit.blockSignals(False)

    def _show_multi(self, assets):
        """Display summary info for multiple selected assets."""
        n = len(assets)
        self._header.setText(f"{n} assets selected")
        self._name_label.setText("")

        # Common tags
        tag_sets = [set(a.tags) for a in assets]
        common = tag_sets[0]
        for s in tag_sets[1:]:
            common &= s
        all_tags = set()
        for s in tag_sets:
            all_tags |= s

        self._props_label.setText(
            f"<b>Total tags:</b> {len(all_tags)}<br>"
            f"<b>Common tags:</b> {len(common)}<br>"
            f"<b>Starred:</b> {sum(1 for a in assets if a.starred)}"
        )

        # Common tags (read-only pills + add button for bulk add)
        self._rebuild_tag_pills(sorted(common) if common else [], removable=False)

        self._assign_label.setText(
            f"{sum(1 for a in assets if a.assignments)} assigned")
        self._notes_edit.hide()  # No inline notes editing for multi-select
        self._render_palette([])

    def set_available_tags(self, tags: list[str]):
        """Set the list of known tags for autocomplete."""
        self._available_tags = tags
        self._completer_model.setStringList(tags)

    def _rebuild_tag_pills(self, tags: list[str], removable: bool = True):
        """Rebuild the tag flow with pills for each tag."""
        # Clear existing
        while self._tag_flow.count():
            item = self._tag_flow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # Add pills
        for tag_id in tags:
            pill = _TagPill(tag_id, removable=removable)
            if removable:
                pill.removed.connect(self._remove_tag)
            self._tag_flow.addWidget(pill)
        # Add the "+" button and hide the editor
        self._tag_add_edit.hide()
        self._tag_add_edit.clear()
        self._tag_flow.addWidget(self._add_tag_btn)

    def _remove_tag(self, tag_id: str):
        """Remove a tag from the current asset(s)."""
        for asset in self._assets:
            if tag_id in asset.tags:
                asset.tags.remove(tag_id)
        if self._assets and len(self._assets) == 1:
            self._rebuild_tag_pills(self._assets[0].tags)
        else:
            common = set(self._assets[0].tags) if self._assets else set()
            for a in self._assets[1:]:
                common &= set(a.tags)
            self._rebuild_tag_pills(sorted(common), removable=False)
        self.tags_modified.emit()

    def _start_add_tag(self):
        """Show the inline tag name editor."""
        self._tag_add_edit.show()
        self._tag_add_edit.setFocus()

    def _finish_add_tag(self):
        """Add the typed tag to the current asset(s)."""
        text = self._tag_add_edit.text().strip().lower().replace(" ", "_")
        if not text:
            self._tag_add_edit.hide()
            return
        for asset in self._assets:
            if text not in asset.tags:
                asset.tags.append(text)
        self._tag_add_edit.hide()
        self._tag_add_edit.clear()
        if self._assets and len(self._assets) == 1:
            self._rebuild_tag_pills(self._assets[0].tags)
        else:
            # Multi-select: rebuild common tags
            common = set(self._assets[0].tags)
            for a in self._assets[1:]:
                common &= set(a.tags)
            self._rebuild_tag_pills(sorted(common), removable=False)
        self.tags_modified.emit()

    def _on_notes_changed(self):
        """Sync notes editor text back to asset."""
        if not self._assets or len(self._assets) != 1:
            return
        self._assets[0].notes = self._notes_edit.toPlainText()
        self.tags_modified.emit()

