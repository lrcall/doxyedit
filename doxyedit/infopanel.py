"""Info panel — asset metadata display for the right sidebar."""
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor


class InfoPanel(QWidget):
    """Right sidebar showing metadata for the selected asset(s)."""

    tags_modified = Signal()  # emitted when user edits tags/notes inline

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("info_panel")
        self._assets = []
        self._theme = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        self._header = QLabel("No selection")
        self._header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._header.setStyleSheet("padding: 8px;")
        self._header.setWordWrap(True)
        outer.addWidget(self._header)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")
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
        self._palette_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._palette_header)
        self._palette_row = QHBoxLayout()
        self._palette_row.setSpacing(4)
        self._palette_row.setContentsMargins(0, 0, 0, 0)
        self._palette_container = QWidget()
        self._palette_container.setLayout(self._palette_row)
        self._layout.addWidget(self._palette_container)

        # Separator after palette
        self._layout.addWidget(self._separator())

        # Tags section
        self._tags_header = QLabel("Tags")
        self._tags_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._tags_header)
        self._tags_label = QLabel()
        self._tags_label.setWordWrap(True)
        self._tags_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._tags_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Assignments section
        self._assign_header = QLabel("Platforms")
        self._assign_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._assign_header)
        self._assign_label = QLabel()
        self._assign_label.setWordWrap(True)
        self._layout.addWidget(self._assign_label)

        # Separator
        self._layout.addWidget(self._separator())

        # Notes section
        self._notes_header = QLabel("Notes")
        self._notes_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._layout.addWidget(self._notes_header)
        self._notes_label = QLabel()
        self._notes_label.setWordWrap(True)
        self._notes_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self._notes_label)

        self._layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.setMinimumWidth(200)
        self.setMaximumWidth(350)

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
        line.setStyleSheet("color: rgba(255,255,255,0.1);")
        line.setFixedHeight(1)
        return line

    def set_assets(self, assets: list):
        """Update the panel to show info for the given asset(s)."""
        self._assets = assets

        if not assets:
            self._header.setText("No selection")
            self._name_label.setText("")
            self._props_label.setText("")
            self._tags_label.setText("")
            self._assign_label.setText("")
            self._notes_label.setText("")
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

        # Tags
        if asset.tags:
            tag_pills = " ".join(f'<span style="background:rgba(255,255,255,0.1);'
                                  f'padding:1px 6px;border-radius:3px;">{t}</span>'
                                  for t in asset.tags)
            self._tags_label.setText(tag_pills)
        else:
            self._tags_label.setText("<i>No tags</i>")

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

        # Notes
        if asset.notes:
            self._notes_label.setText(asset.notes)
        else:
            self._notes_label.setText("<i>No notes</i>")

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

        if common:
            tag_pills = " ".join(f'<span style="background:rgba(255,255,255,0.1);'
                                  f'padding:1px 6px;border-radius:3px;">{t}</span>'
                                  for t in sorted(common))
            self._tags_label.setText(f"Common: {tag_pills}")
        else:
            self._tags_label.setText("<i>No common tags</i>")

        self._assign_label.setText(
            f"{sum(1 for a in assets if a.assignments)} assigned")
        self._notes_label.setText(
            f"{sum(1 for a in assets if a.notes)} with notes")
        self._render_palette([])

    def apply_theme(self, theme):
        """Apply theme colors to the info panel."""
        self._theme = theme
        f = theme.font_size
        self.setStyleSheet(f"""
            #info_panel {{
                background: {theme.bg_main};
                color: {theme.text_primary};
                font-family: {theme.font_family};
                font-size: {f}px;
            }}
            QLabel {{
                color: {theme.text_primary};
            }}
            QScrollArea {{
                background: {theme.bg_main};
                border: none;
            }}
        """)
