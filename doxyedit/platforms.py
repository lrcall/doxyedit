"""Platform assignment panel — two-column card layout."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

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

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: rgba(180,180,180,0.7); font-size: 11px; padding: 2px 0;")
        outer.addWidget(self.summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

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
        name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        if platform.needs_censor:
            name_lbl.setStyleSheet("color: #ff6b6b;")
        header.addWidget(name_lbl)
        header.addStretch()

        filled = sum(1 for s in platform.slots if (pid, s.name) in assign_map)
        total = len(platform.slots)
        # Progress dots
        dots = "".join("●" if (pid, s.name) in assign_map else "○" for s in platform.slots)
        dots_lbl = QLabel(dots)
        dots_lbl.setStyleSheet("color: rgba(150,150,150,0.5); font-size: 8px; letter-spacing: 1px;")
        dots_lbl.setToolTip(f"{filled}/{total} slots filled")
        header.addWidget(dots_lbl)

        count_lbl = QLabel(f"{filled}/{total}")
        count_lbl.setStyleSheet("color: rgba(180,180,180,0.5); font-size: 10px; margin-left: 6px;")
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
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(8)

        # Slot label
        label_text = slot.label + (" *" if slot.required else "")
        name_lbl = QLabel(label_text)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        name_lbl.setStyleSheet("font-size: 12px;")
        h.addWidget(name_lbl, 3)

        # Size badge
        size_lbl = QLabel(f"{slot.width}×{slot.height}")
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_lbl.setStyleSheet(
            "color: rgba(160,160,160,0.55); font-size: 10px;"
            "background: rgba(255,255,255,0.05); border-radius: 3px; padding: 0 5px;")
        h.addWidget(size_lbl)

        # Asset name
        if asset:
            stem = Path(asset.source_path).stem
            # Truncate long names
            display = stem if len(stem) <= 22 else stem[:20] + "…"
            asset_lbl = QLabel(display)
            asset_lbl.setToolTip(stem)
            asset_lbl.setStyleSheet("color: rgba(200,200,200,0.85); font-size: 11px;")
        else:
            asset_lbl = QLabel("empty")
            color = "#e06c6c" if slot.required else "rgba(110,110,110,0.7)"
            asset_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")
        asset_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(asset_lbl, 2)

        # Status badge — click to cycle
        status = str(pa.status) if pa else "pending"
        status_btn = QPushButton(STATUS_ICONS.get(status, "·"))
        status_btn.setFixedSize(24, 20)
        status_btn.setToolTip(f"{status} — click to cycle" if pa else "no asset assigned")
        self._style_status_btn(status_btn, status)
        if pa:
            status_btn.clicked.connect(
                lambda _, p=pid, s=slot.name, b=status_btn: self._cycle_status(p, s, b))
        else:
            status_btn.setEnabled(False)
        h.addWidget(status_btn)

        return row

    def _style_status_btn(self, btn: QPushButton, status: str):
        color = STATUS_COLORS.get(status, "#666")
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  color: {color}; background: transparent;"
            f"  border: 1px solid {color}; border-radius: 3px; font-size: 11px;"
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
