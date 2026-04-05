"""Platform assignment panel — two-column card layout."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QSplitter,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QPixmap

from doxyedit.models import Project, Asset, PlatformAssignment, PostStatus, PLATFORMS


STATUS_COLORS = {
    "pending": "#666666",
    "ready":   "#ffa500",
    "posted":  "#44cc44",
    "skip":    "#555555",
}
STATUS_ICONS = {
    "pending": "·",
    "ready":   "◑",
    "posted":  "●",
    "skip":    "✕",
}
STATUS_CYCLE = ["pending", "ready", "posted", "skip"]


class PlatformPanel(QWidget):
    """Two-column card grid of platform slots."""

    request_asset_pick = Signal(str, str)  # platform_id, slot_name
    asset_selected = Signal(str)           # asset_id — hive cell clicked

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        self.summary_label = QLabel()
        self.summary_label.setProperty("role", "muted")
        self.summary_label.setStyleSheet("padding: 2px 0;")
        outer.addWidget(self.summary_label)

        # Vertical splitter: card columns (top) + image hive (bottom)
        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        outer.addWidget(self._vsplit, 1)

        # ── Card columns ──────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._cards_widget = QWidget()
        scroll.setWidget(self._cards_widget)

        self._col_layout = QHBoxLayout(self._cards_widget)
        self._col_layout.setContentsMargins(0, 4, 0, 4)
        self._col_layout.setSpacing(12)

        self._col0 = QVBoxLayout()
        self._col1 = QVBoxLayout()
        self._col0.setSpacing(10)
        self._col1.setSpacing(10)
        self._col_layout.addLayout(self._col0)
        self._col_layout.addLayout(self._col1)

        self._vsplit.addWidget(scroll)

        # ── Image hive ────────────────────────────────────────────────────
        hive_container = QWidget()
        hive_container.setObjectName("hive_container")
        hive_v = QVBoxLayout(hive_container)
        hive_v.setContentsMargins(0, 4, 0, 0)
        hive_v.setSpacing(4)

        hive_header = QLabel("Assigned Art")
        hive_header.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        hive_header.setProperty("role", "secondary")
        hive_v.addWidget(hive_header)

        hive_scroll = QScrollArea()
        hive_scroll.setWidgetResizable(True)
        hive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        hive_scroll.setFixedHeight(160)
        hive_v.addWidget(hive_scroll)

        self._hive_widget = QWidget()
        self._hive_layout = QHBoxLayout(self._hive_widget)
        self._hive_layout.setContentsMargins(4, 4, 4, 4)
        self._hive_layout.setSpacing(8)
        self._hive_layout.addStretch()
        hive_scroll.setWidget(self._hive_widget)

        self._vsplit.addWidget(hive_container)
        self._vsplit.setSizes([600, 180])
        self._vsplit.setStretchFactor(0, 1)
        self._vsplit.setStretchFactor(1, 0)

        self.refresh()

    def refresh(self):
        # Clear both columns
        for col in (self._col0, self._col1):
            while col.count():
                item = col.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        # Build O(1) lookup: (platform_id, slot_name) → (asset, PlatformAssignment)
        assign_map: dict[tuple, tuple] = {}
        for asset in self.project.assets:
            for pa in asset.assignments:
                assign_map[(pa.platform, pa.slot)] = (asset, pa)

        total_slots = filled_slots = posted_slots = 0

        platforms = [p for pid in self.project.platforms if (p := PLATFORMS.get(pid))]
        for i, (pid, platform) in enumerate(
            (pid, PLATFORMS[pid]) for pid in self.project.platforms if pid in PLATFORMS
        ):
            col = self._col0 if i % 2 == 0 else self._col1
            col.addWidget(self._build_card(platform, pid, assign_map))

            for slot in platform.slots:
                total_slots += 1
                key = (pid, slot.name)
                if key in assign_map:
                    filled_slots += 1
                    if assign_map[key][1].status == "posted":
                        posted_slots += 1

        self._col0.addStretch()
        self._col1.addStretch()

        empty = total_slots - filled_slots
        self.summary_label.setText(
            f"{filled_slots}/{total_slots} filled  ·  "
            f"{posted_slots} posted  ·  "
            f"{empty} empty"
        )
        self._rebuild_hive(assign_map)

    def _rebuild_hive(self, assign_map: dict):
        """Rebuild the thumbnail hive from current assignments."""
        # Clear previous thumbnails (keep trailing stretch)
        while self._hive_layout.count() > 1:
            item = self._hive_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Collect unique (asset, slot_label, platform_name) in platform order
        seen_assets: set[str] = set()
        entries = []
        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue
            for slot in platform.slots:
                key = (pid, slot.name)
                entry = assign_map.get(key)
                if entry:
                    asset, pa = entry
                    entries.append((asset, slot.label, platform.name, pa.status))

        for asset, slot_label, plat_name, status in entries:
            cell = self._hive_cell(asset, slot_label, plat_name, status)
            self._hive_layout.insertWidget(self._hive_layout.count() - 1, cell)

    def _hive_cell(self, asset, slot_label: str, plat_name: str, status: str) -> QWidget:
        """One thumbnail cell in the image hive."""
        THUMB = 100
        cell = QWidget()
        cell.setFixedWidth(THUMB + 8)
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
        cell.setToolTip(f"{plat_name} — {slot_label}\n{asset.source_path}")
        v = QVBoxLayout(cell)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(3)

        # Thumbnail
        thumb = QLabel()
        thumb.setFixedSize(THUMB, THUMB)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.05); border-radius: 4px;"
            " border: 1px solid rgba(255,255,255,0.08); }")
        pm = QPixmap(asset.source_path)
        if not pm.isNull():
            pm = pm.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            thumb.setPixmap(pm)
        else:
            thumb.setText("?")
        v.addWidget(thumb)

        # Slot label
        slot_lbl = QLabel(slot_label)
        slot_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slot_lbl.setWordWrap(True)
        slot_lbl.setProperty("role", "muted")
        slot_lbl.setMaximumWidth(THUMB + 8)
        v.addWidget(slot_lbl)

        # Status dot
        color = STATUS_COLORS.get(str(status), "#666")
        dot = QLabel(STATUS_ICONS.get(str(status), "·"))
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet(f"color: {color};")
        v.addWidget(dot)

        # Click → emit asset_selected if signal wired (handled via mousePressEvent)
        cell.mousePressEvent = lambda _, aid=asset.id: self.asset_selected.emit(aid)
        return cell

    def _build_card(self, platform, pid: str, assign_map: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("platform_card")
        card.setStyleSheet(
            "QFrame#platform_card {"
            "  border: 1px solid rgba(255,255,255,0.09);"
            "  border-radius: 8px;"
            "  background: rgba(255,255,255,0.03);"
            "}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(3)

        # ── Card header ──────────────────────────────────────────────────
        header = QHBoxLayout()
        name_lbl = QLabel(platform.name)
        name_lbl.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        if platform.needs_censor:
            name_lbl.setStyleSheet("color: #ff6b6b;")
        header.addWidget(name_lbl)
        header.addStretch()

        filled = sum(1 for s in platform.slots if (pid, s.name) in assign_map)
        total = len(platform.slots)
        # Progress dots
        dots = "".join("●" if (pid, s.name) in assign_map else "○" for s in platform.slots)
        dots_lbl = QLabel(dots)
        dots_lbl.setStyleSheet("color: rgba(150,150,150,0.5); letter-spacing: 1px;")
        dots_lbl.setToolTip(f"{filled}/{total} slots filled")
        header.addWidget(dots_lbl)

        count_lbl = QLabel(f"{filled}/{total}")
        count_lbl.setStyleSheet("color: rgba(180,180,180,0.5); margin-left: 6px;")
        header.addWidget(count_lbl)
        layout.addLayout(header)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.07); max-height: 1px; margin: 4px 0;")
        layout.addWidget(line)

        # ── Slot rows ─────────────────────────────────────────────────────
        for slot in platform.slots:
            key = (pid, slot.name)
            entry = assign_map.get(key)
            asset = entry[0] if entry else None
            pa = entry[1] if entry else None
            layout.addWidget(self._slot_row(slot, pid, asset, pa))

        return card

    def _slot_row(self, slot, pid: str, asset, pa) -> QWidget:
        row = QWidget()
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, p=pid, s=slot, a=asset: self._slot_context_menu(row, pos, p, s, a))
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(8)

        # Slot label
        label_text = slot.label + (" *" if slot.required else "")
        name_lbl = QLabel(label_text)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(name_lbl, 3)

        # Size badge
        size_lbl = QLabel(f"{slot.width}×{slot.height}")
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_lbl.setStyleSheet(
            "color: rgba(160,160,160,0.55);"
            "background: rgba(255,255,255,0.05); border-radius: 3px; padding: 0 5px;")
        h.addWidget(size_lbl)

        # Asset name / thumbnail tooltip
        if asset:
            stem = Path(asset.source_path).stem
            display = stem if len(stem) <= 22 else stem[:20] + "…"
            asset_lbl = QLabel(display)
            asset_lbl.setToolTip(asset.source_path)
            asset_lbl.setStyleSheet("color: rgba(200,200,200,0.85);")
            # Show thumbnail in tooltip if available
            self._set_thumb_tooltip(asset_lbl, asset)
        else:
            asset_lbl = QLabel("empty — right-click to assign")
            color = "#e06c6c" if slot.required else "rgba(110,110,110,0.5)"
            asset_lbl.setStyleSheet(f"color: {color}; font-style: italic;")
        asset_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(asset_lbl, 2)

        # Status badge — click to cycle
        status = str(pa.status) if pa else "pending"
        status_btn = QPushButton(STATUS_ICONS.get(status, "·"))
        status_btn.setFixedSize(24, 20)
        status_btn.setToolTip(f"{status} — click to cycle" if pa else "right-click row to assign")
        self._style_status_btn(status_btn, status)
        if pa:
            status_btn.clicked.connect(
                lambda _, p=pid, s=slot.name, b=status_btn: self._cycle_status(p, s, b))
        else:
            status_btn.setEnabled(False)
        h.addWidget(status_btn)

        return row

    def _set_thumb_tooltip(self, label: QLabel, asset):
        """Set an image thumbnail as the tooltip for an assigned asset label."""
        from PySide6.QtGui import QPixmap
        try:
            pm = QPixmap(asset.source_path)
            if not pm.isNull():
                pm = pm.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                label.setPixmap(pm)
                label.setToolTip(asset.source_path)
        except Exception:
            pass

    def _slot_context_menu(self, row, pos, pid: str, slot, current_asset):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(row)
        menu.addAction("Assign selected asset", lambda: self.request_asset_pick.emit(pid, slot.name))
        if current_asset:
            menu.addAction("Clear assignment", lambda: self._clear_assignment(pid, slot.name))
        menu.exec(row.mapToGlobal(pos))

    def _clear_assignment(self, pid: str, slot_name: str):
        for asset in self.project.assets:
            asset.assignments = [
                pa for pa in asset.assignments
                if not (pa.platform == pid and pa.slot == slot_name)
            ]
        self.refresh()

    def _style_status_btn(self, btn: QPushButton, status: str):
        color = STATUS_COLORS.get(status, "#666")
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  color: {color}; background: transparent;"
            f"  border: 1px solid {color}; border-radius: 3px;"
            f"}}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.08); }}"
            f"QPushButton:disabled {{ color: #333; border-color: #333; }}"
        )

    def _cycle_status(self, pid: str, slot_name: str, btn: QPushButton):
        for asset in self.project.assets:
            for pa in asset.assignments:
                if pa.platform == pid and pa.slot == slot_name:
                    cur = str(pa.status)
                    idx = STATUS_CYCLE.index(cur) if cur in STATUS_CYCLE else 0
                    pa.status = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]
                    btn.setText(STATUS_ICONS.get(pa.status, "·"))
                    self._style_status_btn(btn, pa.status)
                    btn.setToolTip(f"{pa.status} — click to cycle")
                    return

    def assign_asset(self, asset: Asset, platform_id: str, slot_name: str):
        """Assign an asset to a platform slot."""
        for a in self.project.assets:
            a.assignments = [
                pa for pa in a.assignments
                if not (pa.platform == platform_id and pa.slot == slot_name)
            ]
        asset.assignments.append(PlatformAssignment(
            platform=platform_id,
            slot=slot_name,
            status=PostStatus.READY,
        ))
        self.refresh()
