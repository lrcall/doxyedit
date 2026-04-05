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
        self.setObjectName("platform_panel")
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

        # Build lookup: (platform_id, slot_name) → list of (asset, PlatformAssignment)
        assign_map: dict[tuple, list] = {}
        for asset in self.project.assets:
            for pa in asset.assignments:
                assign_map.setdefault((pa.platform, pa.slot), []).append((asset, pa))

        total_slots = filled_slots = posted_slots = 0

        for i, (pid, platform) in enumerate(
            (pid, PLATFORMS[pid]) for pid in self.project.platforms if pid in PLATFORMS
        ):
            col = self._col0 if i % 2 == 0 else self._col1
            col.addWidget(self._build_card(platform, pid, assign_map))

            for slot in platform.slots:
                total_slots += 1
                key = (pid, slot.name)
                entries = assign_map.get(key, [])
                if entries:
                    filled_slots += 1
                    if all(str(pa.status) == "posted" for _, pa in entries):
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

        # Collect all (asset, slot_label, platform_name, status) in platform order
        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue
            for slot in platform.slots:
                key = (pid, slot.name)
                slot_entries = assign_map.get(key, [])
                n = len(slot_entries)
                for idx, (asset, pa) in enumerate(slot_entries):
                    label = slot.label if n == 1 else f"{slot.label} {idx + 1}/{n}"
                    cell = self._hive_cell(asset, label, platform.name, pa.status)
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
        thumb.setObjectName("hive_thumb")
        thumb.setFixedSize(THUMB, THUMB)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        filled = sum(1 for s in platform.slots if assign_map.get((pid, s.name)))
        total = len(platform.slots)
        # Progress dots
        dots = "".join("●" if assign_map.get((pid, s.name)) else "○" for s in platform.slots)
        dots_lbl = QLabel(dots)
        dots_lbl.setProperty("role", "muted")
        dots_lbl.setStyleSheet("letter-spacing: 1px;")
        dots_lbl.setToolTip(f"{filled}/{total} slots filled")
        header.addWidget(dots_lbl)

        count_lbl = QLabel(f"{filled}/{total}")
        count_lbl.setProperty("role", "muted")
        count_lbl.setStyleSheet("margin-left: 6px;")
        header.addWidget(count_lbl)
        layout.addLayout(header)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("card_divider")
        layout.addWidget(line)

        # ── Slot rows ─────────────────────────────────────────────────────
        for slot in platform.slots:
            key = (pid, slot.name)
            entries = assign_map.get(key, [])
            layout.addWidget(self._slot_row(slot, pid, entries))

        return card

    def _slot_row(self, slot, pid: str, entries: list) -> QWidget:
        row = QWidget()
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, p=pid, s=slot, e=entries: self._slot_context_menu(row, pos, p, s, e))
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
        size_lbl.setObjectName("size_badge")
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(size_lbl)

        # Asset name label
        if len(entries) == 0:
            asset_lbl = QLabel("empty — right-click to assign")
            if slot.required:
                asset_lbl.setStyleSheet("color: #e06c6c; font-style: italic;")
            else:
                asset_lbl.setProperty("role", "muted")
                asset_lbl.setStyleSheet("font-style: italic;")
        elif len(entries) == 1:
            asset, _ = entries[0]
            stem = Path(asset.source_path).stem
            display = stem if len(stem) <= 22 else stem[:20] + "…"
            asset_lbl = QLabel(display)
            asset_lbl.setToolTip(asset.source_path)
        else:
            asset_lbl = QLabel(f"{len(entries)} images")
            asset_lbl.setProperty("role", "accent")

        asset_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(asset_lbl, 2)

        # Status button — click to cycle
        if entries:
            first_status = str(entries[0][1].status)
            status_btn = QPushButton(STATUS_ICONS.get(first_status, "·"))
            status_btn.setFixedSize(24, 20)
            status_btn.setToolTip(f"{first_status} — click to cycle")
            self._style_status_btn(status_btn, first_status)
            status_btn.clicked.connect(
                lambda _, p=pid, s=slot.name, b=status_btn: self._cycle_status(p, s, b))
        else:
            status_btn = QPushButton("·")
            status_btn.setFixedSize(24, 20)
            status_btn.setToolTip("right-click row to assign")
            self._style_status_btn(status_btn, "pending")
            status_btn.setEnabled(False)
        h.addWidget(status_btn)

        return row

    def _slot_context_menu(self, row, pos, pid: str, slot, entries: list):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(row)
        menu.addAction("Add image to slot", lambda: self.request_asset_pick.emit(pid, slot.name))
        if entries:
            menu.addSeparator()
            for asset, pa in entries:
                name = Path(asset.source_path).name
                a = menu.addAction(f"Remove: {name}")
                a.triggered.connect(
                    lambda checked=False, aid=asset.id, p=pid, s=slot.name:
                        self._remove_asset_from_slot(aid, p, s))
            menu.addSeparator()
            menu.addAction("Clear all", lambda: self._clear_assignment(pid, slot.name))
        menu.exec(row.mapToGlobal(pos))

    def _remove_asset_from_slot(self, asset_id: str, pid: str, slot_name: str):
        """Remove only a specific asset's assignment for that slot."""
        for asset in self.project.assets:
            if asset.id == asset_id:
                asset.assignments = [
                    pa for pa in asset.assignments
                    if not (pa.platform == pid and pa.slot == slot_name)
                ]
        self.refresh()

    def _clear_assignment(self, pid: str, slot_name: str):
        """Clear ALL assets assigned to this slot."""
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
        """Cycle ALL assignments in the slot to the same next status."""
        pas = [pa for asset in self.project.assets for pa in asset.assignments
               if pa.platform == pid and pa.slot == slot_name]
        if not pas:
            return
        cur = str(pas[0].status)
        idx = STATUS_CYCLE.index(cur) if cur in STATUS_CYCLE else 0
        new_status = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]
        for pa in pas:
            pa.status = new_status
        btn.setText(STATUS_ICONS.get(new_status, "·"))
        self._style_status_btn(btn, new_status)
        btn.setToolTip(f"{new_status} — click to cycle")

    def assign_asset(self, asset: Asset, platform_id: str, slot_name: str):
        """Add asset to slot without clearing existing — skip if already assigned."""
        for pa in asset.assignments:
            if pa.platform == platform_id and pa.slot == slot_name:
                return  # already assigned
        asset.assignments.append(PlatformAssignment(
            platform=platform_id,
            slot=slot_name,
            status=PostStatus.READY,
        ))
        self.refresh()
