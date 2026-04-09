"""Kanban board — posting schedule with draggable status cards."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
from PySide6.QtGui import QFont, QColor, QDrag, QPixmap, QPainter


STATUS_COLS = [
    ("pending", "Pending", "#666666"),
    ("ready", "Ready", "#ffa500"),
    ("posted", "Posted", "#44cc44"),
    ("skip", "Skip", "#555555"),
]


class KanbanCard(QFrame):
    """A draggable card representing one platform assignment."""

    def __init__(self, asset_id: str, platform: str, slot: str,
                 asset_name: str, status: str, parent=None):
        super().__init__(parent)
        self.asset_id = asset_id
        self.platform = platform
        self.slot = slot
        self.status = status
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(1)

        name_lbl = QLabel(asset_name)
        name_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        layout.addWidget(name_lbl)

        detail_lbl = QLabel(f"{platform} / {slot}")
        layout.addWidget(detail_lbl)

        self.setStyleSheet("")  # Themed by parent's apply_theme

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not hasattr(self, '_drag_start'):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        data = f"{self.asset_id}|{self.platform}|{self.slot}|{self.status}"
        mime.setData("application/x-kanban-card", QByteArray(data.encode("utf-8")))
        drag.setMimeData(mime)
        # Mini pixmap
        pm = QPixmap(self.size())
        pm.fill(QColor(60, 60, 60))
        p = QPainter(pm)
        p.setPen(QColor(200, 200, 200))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter,
                   f"{self.platform}/{self.slot}")
        p.end()
        drag.setPixmap(pm.scaled(120, 40, Qt.AspectRatioMode.KeepAspectRatio))
        drag.exec(Qt.DropAction.MoveAction)


class KanbanColumn(QWidget):
    """A single status column that accepts card drops."""

    card_dropped = Signal(str, str, str, str)  # asset_id, platform, slot, new_status

    def __init__(self, status: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self.status = status
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        dot = QLabel("\u25cf")
        dot.setStyleSheet(f"color: {color}; font-size: 14px;")
        dot.setFixedWidth(18)
        header.addWidget(dot)
        self._title = QLabel(f"{label}")
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        header.addWidget(self._title)
        self._count = QLabel("0")
        header.addWidget(self._count)
        header.addStretch()
        layout.addLayout(header)

        # Scrollable card area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._card_widget = QWidget()
        self._card_layout = QVBoxLayout(self._card_widget)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(4)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_widget)
        layout.addWidget(scroll, 1)

        self.setStyleSheet("")  # Themed by parent's apply_theme

    def add_card(self, card: KanbanCard):
        # Insert before the stretch
        idx = max(0, self._card_layout.count() - 1)
        self._card_layout.insertWidget(idx, card)
        self._count.setText(str(self._card_layout.count() - 1))

    def clear_cards(self):
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._count.setText("0")

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-kanban-card"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-kanban-card"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-kanban-card"):
            data = event.mimeData().data("application/x-kanban-card").data().decode("utf-8")
            parts = data.split("|")
            if len(parts) == 4:
                asset_id, platform, slot, old_status = parts
                if old_status != self.status:
                    self.card_dropped.emit(asset_id, platform, slot, self.status)
            event.acceptProposedAction()


class KanbanPanel(QWidget):
    """Kanban board showing platform assignments in status columns."""

    status_changed = Signal()  # emitted when any assignment status changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._theme = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Title
        title = QLabel("Posting Schedule")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # Summary
        self._summary = QLabel()
        layout.addWidget(self._summary)

        # Columns
        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(8)
        self._columns: dict[str, KanbanColumn] = {}
        for status, label, color in STATUS_COLS:
            col = KanbanColumn(status, label, color)
            col.card_dropped.connect(self._on_card_dropped)
            self._columns[status] = col
            cols_layout.addWidget(col, 1)
        layout.addLayout(cols_layout, 1)

    def set_project(self, project):
        self._project = project
        self.refresh()

    def refresh(self):
        if not self._project:
            return
        # Clear all columns
        for col in self._columns.values():
            col.clear_cards()
        # Populate from assignments
        total = 0
        for asset in self._project.assets:
            for pa in asset.assignments:
                status = pa.status if pa.status in self._columns else "pending"
                name = Path(asset.source_path).stem if asset.source_path else asset.id
                card = KanbanCard(asset.id, pa.platform, pa.slot, name, status)
                self._columns[status].add_card(card)
                total += 1
        # Summary
        counts = {s: int(self._columns[s]._count.text()) for s in self._columns}
        self._summary.setText(
            f"{total} assignments \u2014 "
            f"{counts.get('pending', 0)} pending, "
            f"{counts.get('ready', 0)} ready, "
            f"{counts.get('posted', 0)} posted, "
            f"{counts.get('skip', 0)} skip")
        # Re-apply theme to newly created cards
        if self._theme:
            self.apply_theme(self._theme)

    def _on_card_dropped(self, asset_id: str, platform: str, slot: str, new_status: str):
        """Update assignment status when card is dropped on a new column."""
        if not self._project:
            return
        asset = self._project.get_asset(asset_id)
        if not asset:
            return
        for pa in asset.assignments:
            if pa.platform == platform and pa.slot == slot:
                pa.status = new_status
                break
        self.refresh()
        self.status_changed.emit()

    def apply_theme(self, theme):
        self._theme = theme
        f = theme.font_size
        # Panel-level styles
        self.setStyleSheet(f"""
            QLabel {{ color: {theme.text_primary}; font-size: {f}px; }}
        """)
        self._summary.setStyleSheet(f"color: {theme.text_secondary}; font-size: {f - 1}px;")
        # Style each column directly
        col_style = (f"background: {theme.bg_deep}; border-radius: 6px;")
        card_style = (
            f"background: {theme.bg_raised}; border: 1px solid {theme.border};"
            f" border-radius: 4px; color: {theme.text_primary};")
        for col in self._columns.values():
            col.setStyleSheet(col_style)
            col._title.setStyleSheet(f"color: {theme.text_primary}; font-size: {f}px; background: transparent;")
            col._count.setStyleSheet(f"color: {theme.text_muted}; font-size: {f - 2}px; background: transparent;")
            # Style each card in this column
            for i in range(col._card_layout.count()):
                item = col._card_layout.itemAt(i)
                w = item.widget() if item else None
                if isinstance(w, KanbanCard):
                    w.setStyleSheet(card_style)
