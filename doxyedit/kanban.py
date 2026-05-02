"""Minimal Kanban board for posts.

Re-introduces the parked Kanban feature from BACKLOG #14 ("could be
reimagined if there's a workflow need") as an on-demand dialog rather
than a persistent tab. Posts are grouped by SocialPostStatus into
columns; drag a card between columns to change the post's status.

The dialog is non-modal so it can sit alongside the composer; on
close, the project's _dirty flag stays set so the next autosave
captures status changes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QDialogButtonBox, QPushButton,
)

from doxyedit.models import SocialPostStatus
from doxyedit.themes import themed_dialog_size

if TYPE_CHECKING:
    from doxyedit.models import SocialPost


# Order matters - left to right in the dialog.
# Use .value so dict keys match the bare-string status that older
# project files might serialize. SocialPostStatus is a str-Enum so
# both forms compare equal in the model, but dict lookups need
# consistent key types.
_COLUMNS: list[tuple[str, str]] = [
    (SocialPostStatus.DRAFT.value, "Draft"),
    (SocialPostStatus.QUEUED.value, "Queued"),
    (SocialPostStatus.POSTED.value, "Posted"),
    (SocialPostStatus.FAILED.value, "Failed"),
]


class _StatusList(QListWidget):
    """One column. Accepts drops from sibling columns; emits
    moved_to_column when a post lands here."""

    moved_here = Signal(str, str)  # post_id, new_status

    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self._status = status
        self.setObjectName(f"kanban_col_{status}")
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)

    def dropEvent(self, event):
        # Pull the post id from the dragged item's UserRole. Standard
        # QListWidget drop machinery moves the item; we layer the
        # status-change signal on top.
        src = event.source()
        if isinstance(src, _StatusList) and src is not self:
            for item in src.selectedItems():
                pid = item.data(Qt.ItemDataRole.UserRole)
                if pid:
                    self.moved_here.emit(str(pid), self._status)
        super().dropEvent(event)


class KanbanBoard(QDialog):
    """Dialog showing posts in DRAFT/QUEUED/POSTED/FAILED columns."""

    status_changed = Signal(str, str)  # post_id, new_status

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self._project = project
        self.setObjectName("kanban_board_dlg")
        self.setWindowTitle("Kanban Board")
        w, h = themed_dialog_size(75.0, 50.0)
        self.resize(w, h)

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "<b>Drag a post between columns to change its status.</b> "
            "Changes mark the project dirty; autosave picks them up "
            "on the next tick."))

        cols_row = QHBoxLayout()
        self._col_widgets: dict[str, _StatusList] = {}
        for status, label in _COLUMNS:
            col_box = QVBoxLayout()
            col_box.addWidget(QLabel(f"<b>{label}</b>"))
            lst = _StatusList(status)
            lst.moved_here.connect(self._on_card_moved)
            self._col_widgets[status] = lst
            col_box.addWidget(lst, 1)
            cols_row.addLayout(col_box, 1)
        outer.addLayout(cols_row, 1)

        self._refresh()

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        for btn in buttons.buttons():
            btn.clicked.connect(self.accept)
        btn_row.addWidget(buttons)
        outer.addLayout(btn_row)

    def _refresh(self):
        """Repopulate every column from project.posts."""
        for lst in self._col_widgets.values():
            lst.clear()
        for post in self._project.posts or []:
            label = (post.caption_default
                     or post.scheduled_time
                     or post.id)[:60]
            display = f"{post.id[:8]}  {label}"
            # post.status may be a SocialPostStatus enum or a bare str
            # (older project files). Normalize to the bare value so the
            # dict lookup matches the SocialPostStatus.* values.
            status_key = getattr(post.status, "value", post.status)
            target = self._col_widgets.get(status_key)
            if target is None:
                # Unknown / partial status -> put in Draft so the user
                # can see and re-route.
                target = self._col_widgets[SocialPostStatus.DRAFT.value]
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, post.id)
            target.addItem(item)

    def _on_card_moved(self, post_id: str, new_status: str):
        for post in self._project.posts:
            if post.id == post_id:
                post.status = new_status
                self.status_changed.emit(post_id, new_status)
                return
