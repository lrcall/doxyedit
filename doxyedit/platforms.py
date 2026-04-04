"""Platform assignment panel — assign assets to platform slots, track status."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QHeaderView, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap, QIcon

from doxyedit.models import (
    Project, Asset, Platform, PlatformAssignment, PostStatus, PLATFORMS,
)


STATUS_COLORS = {
    PostStatus.PENDING: "#888888",
    PostStatus.READY: "#ffa500",
    PostStatus.POSTED: "#44cc44",
    PostStatus.SKIP: "#555555",
}


class PlatformPanel(QWidget):
    """Shows all platforms and their slots, lets you assign assets and track status."""

    request_asset_pick = Signal(str, str)  # platform_id, slot_name → asks browser to pick

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Summary bar
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("color: #aaa; font-size: 12px; padding: 4px;")
        root.addWidget(self.summary_label)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Platform / Slot", "Size", "Asset", "Status", ""])
        self.tree.setStyleSheet("""
            QTreeWidget {
                background: #1e1e1e; color: #ccc; border: none;
                font-size: 12px; font-family: "Segoe UI";
            }
            QTreeWidget::item { padding: 4px; }
            QTreeWidget::item:selected { background: #094771; }
            QHeaderView::section {
                background: #252526; color: #888; border: none;
                padding: 4px 8px; font-size: 11px;
            }
        """)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.tree)

        self.refresh()

    def refresh(self):
        self.tree.clear()
        total_slots = 0
        filled_slots = 0
        posted_slots = 0

        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue

            p_item = QTreeWidgetItem([platform.name, "", "", ""])
            p_item.setFont(0, QFont("Segoe UI", 11, QFont.Weight.Bold))
            if platform.needs_censor:
                p_item.setForeground(0, QColor("#ff6b6b"))
            self.tree.addTopLevelItem(p_item)

            for slot in platform.slots:
                total_slots += 1
                size_str = f"{slot.width}x{slot.height}"

                # Find assignment
                assignment = None
                assigned_asset = None
                for asset in self.project.assets:
                    for pa in asset.assignments:
                        if pa.platform == pid and pa.slot == slot.name:
                            assignment = pa
                            assigned_asset = asset
                            break
                    if assignment:
                        break

                if assigned_asset:
                    asset_name = Path(assigned_asset.source_path).stem
                    filled_slots += 1
                else:
                    asset_name = "— empty —"

                status = assignment.status if assignment else PostStatus.PENDING
                if status == PostStatus.POSTED:
                    posted_slots += 1

                required_marker = " *" if slot.required else ""
                s_item = QTreeWidgetItem([
                    f"  {slot.label}{required_marker}",
                    size_str,
                    asset_name,
                    status,
                ])

                color = QColor(STATUS_COLORS.get(status, "#888"))
                s_item.setForeground(3, color)
                if not assigned_asset and slot.required:
                    s_item.setForeground(2, QColor("#ff6b6b"))

                p_item.addChild(s_item)

                # Status combo
                combo = QComboBox()
                combo.addItems([s.value for s in PostStatus])
                combo.setCurrentText(status)
                combo.setStyleSheet(
                    "QComboBox { background: #333; color: #ccc; border: 1px solid #444;"
                    " border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
                )
                combo.currentTextChanged.connect(
                    lambda val, p=pid, s=slot.name: self._set_status(p, s, val)
                )
                self.tree.setItemWidget(s_item, 4, combo)

            p_item.setExpanded(True)

        self.summary_label.setText(
            f"{filled_slots}/{total_slots} slots filled, "
            f"{posted_slots} posted, "
            f"{total_slots - filled_slots} empty"
        )

    def _set_status(self, platform_id: str, slot_name: str, status_str: str):
        for asset in self.project.assets:
            for pa in asset.assignments:
                if pa.platform == platform_id and pa.slot == slot_name:
                    pa.status = status_str
                    self.refresh()
                    return

    def assign_asset(self, asset: Asset, platform_id: str, slot_name: str):
        """Assign an asset to a platform slot."""
        # Remove any existing assignment to this slot
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
