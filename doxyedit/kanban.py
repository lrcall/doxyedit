"""Kanban board — posting schedule with draggable status cards."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
from PySide6.QtGui import QColor, QDrag, QPixmap, QPainter, QPalette


STATUS_COLS = [
    ("pending", "Pending"),
    ("ready", "Ready"),
    ("posted", "Posted"),
    ("skip", "Skip"),
]

def _status_color(status: str, theme) -> str:
    """Resolve status to a theme-based color."""
    if theme is None:
        return "#666666"
    return {
        "pending": theme.text_muted,
        "ready": theme.warning,
        "posted": theme.post_posted,
        "skip": theme.text_muted,
    }.get(status, theme.text_muted)


class KanbanCard(QFrame):
    """A draggable card representing one platform assignment."""

    def __init__(self, asset_id: str, platform: str, slot: str,
                 asset_name: str, status: str, parent=None):
        super().__init__(parent)
        self.setObjectName("kanban_card")
        self.asset_id = asset_id
        self.platform = platform
        self.slot = slot
        self.status = status
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _card_height = round(_f * 4.67)  # ~56 at font_size 12
        self.setFixedHeight(_card_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_pad_lg, _pad, _pad_lg, _pad)
        layout.setSpacing(max(1, _pad // 4))

        self._name_lbl = QLabel(asset_name)
        layout.addWidget(self._name_lbl)

        self._detail_lbl = QLabel(f"{platform} / {slot}")
        layout.addWidget(self._detail_lbl)

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
        pm = QPixmap(self.size())
        # Use theme tokens for drag pixmap; fall back to column's cached theme
        _drag_bg = getattr(self, '_theme_bg_deep', "#3c3c3c")
        _drag_fg = getattr(self, '_theme_text_primary', "#c8c8c8")
        pm.fill(QColor(_drag_bg))
        p = QPainter(pm)
        p.setPen(QColor(_drag_fg))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter,
                   f"{self.platform}/{self.slot}")
        p.end()
        drag.setPixmap(pm.scaled(120, 40, Qt.AspectRatioMode.KeepAspectRatio))
        drag.exec(Qt.DropAction.MoveAction)


class KanbanColumn(QWidget):
    """A single status column that accepts card drops."""

    card_dropped = Signal(str, str, str, str)  # asset_id, platform, slot, new_status

    def __init__(self, status: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("kanban_column")
        self.status = status
        self._status_color = _status_color(status, None)
        self.setAcceptDrops(True)
        self.setAutoFillBackground(True)

        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        self._f = _f
        _pad = max(4, _f // 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_pad, _pad, _pad, _pad)
        layout.setSpacing(_pad)

        # Header
        header = QHBoxLayout()
        _dot_w = round(_f * 1.5)  # ~18 at font_size 12
        self._dot = QLabel("\u25cf")
        self._dot.setFixedWidth(_dot_w)
        header.addWidget(self._dot)
        self._title = QLabel(f"{label}")
        header.addWidget(self._title)
        self._count = QLabel("0")
        header.addWidget(self._count)
        header.addStretch()
        layout.addLayout(header)

        # Scrollable card area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._card_widget = QWidget()
        self._card_layout = QVBoxLayout(self._card_widget)
        self._card_layout.setContentsMargins(0, 0, 0, 0)  # inside scroll area
        self._card_layout.setSpacing(_pad)
        self._card_layout.addStretch()
        self._scroll.setWidget(self._card_widget)
        layout.addWidget(self._scroll, 1)

    def add_card(self, card: KanbanCard):
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

    def apply_theme(self, theme):
        """Apply theme via QPalette (reliable for nested widgets)."""
        self._status_color = _status_color(self.status, theme)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(theme.bg_main))
        self.setPalette(pal)
        # Scroll area + card widget backgrounds
        self._scroll.setStyleSheet(f"QScrollArea {{ background: {theme.bg_main}; border: none; }}")
        self._card_widget.setStyleSheet(f"background: {theme.bg_main};")
        # Status dot uses theme-derived color
        self._dot.setStyleSheet(f"color: {self._status_color}; font-size: {self._f}px; background: transparent;")
        self._title.setStyleSheet(f"color: {theme.text_primary}; background: transparent;")
        self._count.setStyleSheet(f"color: {theme.text_muted}; background: transparent;")


class KanbanPanel(QWidget):
    """Kanban board showing platform assignments in status columns."""

    status_changed = Signal()  # emitted when any assignment status changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kanban_panel")
        self._project = None
        self._theme = None

        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad_lg = max(6, _f // 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)
        layout.setSpacing(_pad_lg)

        # Title
        self._title = QLabel("Posting Schedule")
        layout.addWidget(self._title)

        # Summary / help text
        self._summary = QLabel()
        layout.addWidget(self._summary)

        # Columns
        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(_pad_lg)
        self._columns: dict[str, KanbanColumn] = {}
        for status, label in STATUS_COLS:
            col = KanbanColumn(status, label)
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
        for col in self._columns.values():
            col.clear_cards()
        total = 0
        for asset in self._project.assets:
            for pa in asset.assignments:
                status = pa.status if pa.status in self._columns else "pending"
                name = Path(asset.source_path).stem if asset.source_path else asset.id
                card = KanbanCard(asset.id, pa.platform, pa.slot, name, status)
                if self._theme:
                    card.setStyleSheet(
                        f"background: {self._theme.bg_raised};"
                        f" border: 1px solid {self._theme.border};"
                        f" border-radius: 4px;")
                    card._name_lbl.setStyleSheet(f"color: {self._theme.text_primary}; background: transparent;")
                    card._detail_lbl.setStyleSheet(f"color: {self._theme.text_secondary}; background: transparent;")
                    card._theme_bg_deep = self._theme.bg_deep
                    card._theme_text_primary = self._theme.text_primary
                self._columns[status].add_card(card)
                total += 1
        # Summary
        if total == 0:
            self._summary.setText(
                "No platform assignments yet.\n\n"
                "How to use:\n"
                "1. Go to the Assets tab, right-click an image → Assign to Platform\n"
                "2. Assigned images appear here as cards in the Pending column\n"
                "3. Drag cards between columns to track status: Pending → Ready → Posted")
        else:
            counts = {s: int(self._columns[s]._count.text()) for s in self._columns}
            self._summary.setText(
                f"{total} assignments \u2014 "
                f"{counts.get('pending', 0)} pending, "
                f"{counts.get('ready', 0)} ready, "
                f"{counts.get('posted', 0)} posted, "
                f"{counts.get('skip', 0)} skip")

    def _on_card_dropped(self, asset_id: str, platform: str, slot: str, new_status: str):
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
        """Apply theme to kanban panel and all columns/cards."""
        self._theme = theme
        self.setStyleSheet(f"background: {theme.bg_deep};")
        _title_size = round(theme.font_size * 1.08)  # slightly larger heading
        self._title.setStyleSheet(
            f"color: {theme.text_primary}; font-size: {_title_size}px;"
            f" font-weight: bold; background: transparent;")
        self._summary.setStyleSheet(
            f"color: {theme.text_secondary}; font-size: {round(theme.font_size * 0.92)}px;"
            f" background: transparent;")
        for col in self._columns.values():
            col.apply_theme(theme)
        # Re-theme existing cards
        self.refresh()
