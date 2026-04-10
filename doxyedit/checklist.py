"""Checklist tab — project posting checklist backed by project.checklist."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QCheckBox, QProgressBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QFont, QKeySequence, QShortcut


class ChecklistPanel(QWidget):
    modified = Signal()  # emitted whenever checklist changes

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setObjectName("checklist_panel")
        self.project = project
        self._build()

    def _build(self):
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad_lg = max(6, _f // 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_pad_lg * 6, _pad_lg * 4, _pad_lg * 6, _pad_lg * 4)
        outer.setSpacing(_pad_lg * 2)

        # ── Header ────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Posting Checklist")
        title.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        header.addWidget(title)
        header.addStretch()

        self._clear_btn = QPushButton("Clear Completed")
        self._clear_btn.setStyleSheet("QPushButton { padding: 3px 10px; }")
        self._clear_btn.clicked.connect(self._clear_completed)
        header.addWidget(self._clear_btn)
        outer.addLayout(header)

        # ── Progress bar ──────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setMinimum(0)
        self._progress.setMaximum(1)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.08); border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: #44cc44; border-radius: 3px; }")
        outer.addWidget(self._progress)

        self._progress_lbl = QLabel("0 / 0 complete")
        self._progress_lbl.setProperty("role", "muted")
        outer.addWidget(self._progress_lbl)

        # ── Scrollable item list ───────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)

        # ── Add item row ───────────────────────────────────────────────
        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("Add checklist item…")
        self._add_input.returnPressed.connect(self._add_item_from_input)
        add_row.addWidget(self._add_input)

        add_btn = QPushButton("Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_item_from_input)
        add_row.addWidget(add_btn)
        outer.addLayout(add_row)

        self.refresh()

    def refresh(self):
        """Rebuild the list from project.checklist."""
        # Remove all rows except the trailing stretch
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for raw in self.project.checklist:
            checked = raw.startswith("[x] ")
            text = raw[4:] if raw.startswith(("[x] ", "[ ] ")) else raw
            self._insert_row(text, checked, at_end=False)

        self._update_progress()

    def _insert_row(self, text: str, checked: bool, at_end: bool = True):
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad_lg = max(6, _f // 2)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(_pad_lg * 2)

        cb = QCheckBox(text)
        cb.setChecked(checked)
        cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        cb.stateChanged.connect(lambda _: self._on_check_changed())
        self._apply_check_style(cb, checked)
        cb.stateChanged.connect(lambda state, c=cb: self._apply_check_style(c, bool(state)))
        h.addWidget(cb)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " color: rgba(180,100,100,0.5); }"
            "QPushButton:hover { color: rgba(220,80,80,0.9); }")
        del_btn.clicked.connect(lambda _, r=row: self._delete_row(r))
        h.addWidget(del_btn)

        # Insert before the trailing stretch
        pos = self._list_layout.count() - 1 if at_end else 0
        self._list_layout.insertWidget(pos, row)

    def _apply_check_style(self, cb: QCheckBox, checked: bool):
        if checked:
            cb.setStyleSheet("color: rgba(150,150,150,0.5); text-decoration: line-through;")
        else:
            cb.setStyleSheet("")

    def _on_check_changed(self):
        self._sync_to_project()
        self._update_progress()
        self.modified.emit()

    def _delete_row(self, row: QWidget):
        self._list_layout.removeWidget(row)
        row.deleteLater()
        self._sync_to_project()
        self._update_progress()
        self.modified.emit()

    def _add_item_from_input(self):
        text = self._add_input.text().strip()
        if not text:
            return
        self._add_input.clear()
        self._insert_row(text, checked=False, at_end=True)
        self.project.checklist.append(f"[ ] {text}")
        self._update_progress()
        self.modified.emit()

    def _clear_completed(self):
        rows_to_delete = []
        for i in range(self._list_layout.count() - 1):  # skip stretch
            item = self._list_layout.itemAt(i)
            if not item or not item.widget():
                continue
            row = item.widget()
            cb = row.findChild(QCheckBox)
            if cb and cb.isChecked():
                rows_to_delete.append(row)
        for row in rows_to_delete:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._sync_to_project()
        self._update_progress()
        self.modified.emit()

    def _sync_to_project(self):
        items = []
        for i in range(self._list_layout.count() - 1):  # skip stretch
            item = self._list_layout.itemAt(i)
            if not item or not item.widget():
                continue
            cb = item.widget().findChild(QCheckBox)
            if cb:
                prefix = "[x] " if cb.isChecked() else "[ ] "
                items.append(prefix + cb.text())
        self.project.checklist = items

    def _update_progress(self):
        total = self._list_layout.count() - 1  # exclude stretch
        done = 0
        for i in range(total):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                cb = item.widget().findChild(QCheckBox)
                if cb and cb.isChecked():
                    done += 1
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(done)
        self._progress_lbl.setText(f"{done} / {total} complete")
        self._clear_btn.setEnabled(done > 0)
