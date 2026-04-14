"""Month-view calendar widget for the Social tab."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QFrame, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt

from doxyedit.models import Project, SocialPostStatus


_DAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class _DayCell(QFrame):
    """Single day cell in the calendar grid."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("calendar_day_cell")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(48)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(1)

        self._day_label = QLabel()
        self._day_label.setObjectName("calendar_day_number")
        self._day_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._day_label)

        self._dot_row = QHBoxLayout()
        self._dot_row.setContentsMargins(0, 0, 0, 0)
        self._dot_row.setSpacing(2)
        self._dot_row.setAlignment(Qt.AlignLeft)
        layout.addLayout(self._dot_row)

        self._count_label = QLabel()
        self._count_label.setObjectName("calendar_day_count")
        self._count_label.setAlignment(Qt.AlignLeft)
        self._count_label.hide()
        layout.addWidget(self._count_label)

        self._iso: str = ""

    # -- public --

    @property
    def iso_date(self) -> str:
        return self._iso

    def configure(
        self,
        day_num: int,
        iso: str,
        day_type: str,
        statuses: dict[str, int] | None = None,
    ) -> None:
        """Set up this cell for a specific day.

        *day_type*: "today", "selected", "normal", "other_month"
        *statuses*: e.g. {"posted": 2, "queued": 1}
        """
        self._iso = iso
        self._day_label.setText(str(day_num))
        # Use distinct objectNames per day_type — Qt property selectors
        # are unreliable on dynamically-set properties
        self.setObjectName(f"calendar_day_{day_type}")

        # Clear old dots
        while self._dot_row.count():
            item = self._dot_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._count_label.hide()

        if not statuses:
            return

        total = sum(statuses.values())
        shown = 0
        for status, count in statuses.items():
            if shown >= 4:
                break
            for _ in range(min(count, 4 - shown)):
                dot = QLabel()
                dot.setObjectName("calendar_dot")
                dot.setProperty("dot_status", status)
                dot.setFixedSize(6, 6)
                # Color + border-radius come from QSS selector on dot_status
                self._dot_row.addWidget(dot)
                shown += 1

        if total > 1:
            self._count_label.setText(str(total))
            self._count_label.show()

    # -- events --

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._iso:
            self.clicked.emit()
        super().mousePressEvent(event)


class CalendarPane(QWidget):
    """Month-view calendar with post status dots."""

    day_selected = Signal(str)   # ISO date "2026-04-15"
    day_cleared = Signal()       # deselect / reset filter

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("calendar_pane")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        self._project: Project | None = None
        self._current_month: date = date.today().replace(day=1)
        self._selected_iso: str = ""

        self._build_ui()

    # ---- public API ----

    def set_project(self, project: Project) -> None:
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        self._populate_grid()

    # ---- UI construction ----

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # -- header row --
        header = QHBoxLayout()
        header.setContentsMargins(4, 4, 4, 0)

        self._btn_prev = QPushButton("\u25C0")
        self._btn_prev.setObjectName("calendar_nav_btn")
        self._btn_prev.setFixedSize(28, 28)
        self._btn_prev.clicked.connect(self._go_prev)
        header.addWidget(self._btn_prev)

        self._month_label = QLabel()
        self._month_label.setObjectName("calendar_header")
        self._month_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self._month_label, stretch=1)

        self._btn_next = QPushButton("\u25B6")
        self._btn_next.setObjectName("calendar_nav_btn")
        self._btn_next.setFixedSize(28, 28)
        self._btn_next.clicked.connect(self._go_next)
        header.addWidget(self._btn_next)

        self._btn_today = QPushButton("Today")
        self._btn_today.setObjectName("calendar_today_btn")
        self._btn_today.clicked.connect(self._go_today)
        header.addWidget(self._btn_today)

        root.addLayout(header)

        # -- JST clock --
        self._jst_label = QLabel()
        self._jst_label.setObjectName("calendar_jst_clock")
        self._jst_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._jst_label)
        self._update_jst_clock()

        # Timer to update clock every minute
        from PySide6.QtCore import QTimer
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_jst_clock)
        self._clock_timer.start(60_000)  # every 60 seconds

        # -- day-of-week headers --
        dow_row = QHBoxLayout()
        dow_row.setContentsMargins(4, 0, 4, 0)
        dow_row.setSpacing(2)
        for name in _DAY_HEADERS:
            lbl = QLabel(name)
            lbl.setObjectName("calendar_dow_header")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            dow_row.addWidget(lbl)
        root.addLayout(dow_row)

        # -- grid --
        self._grid = QGridLayout()
        self._grid.setContentsMargins(4, 0, 4, 4)
        self._grid.setSpacing(2)
        root.addLayout(self._grid)

        self._cells: list[_DayCell] = []

        self._populate_grid()

    # ---- grid population ----

    def _populate_grid(self) -> None:
        # Clear previous cells
        for cell in self._cells:
            cell.clicked.disconnect()
            cell.setParent(None)
            cell.deleteLater()
        self._cells.clear()

        year = self._current_month.year
        month = self._current_month.month
        self._month_label.setText(f"{calendar.month_name[month]} {year}")

        today = date.today()

        # Build status map from project posts
        day_statuses: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        if self._project:
            for post in self._project.posts:
                if post.scheduled_time:
                    day_key = post.scheduled_time[:10]
                    st = post.status if post.status else "draft"
                    day_statuses[day_key][st] += 1

        # calendar.monthcalendar gives weeks starting Monday
        weeks = calendar.monthcalendar(year, month)

        # Compute prev/next month days for leading/trailing zeros
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        prev_month_days = calendar.monthrange(prev_year, prev_month)[1]

        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        for row_idx, week in enumerate(weeks):
            for col_idx, day_num in enumerate(week):
                cell = _DayCell()

                if day_num == 0:
                    # Other month day
                    if row_idx == 0:
                        # Leading zeros — previous month
                        first_zero_col = week.index(0)
                        offset = col_idx - first_zero_col
                        # Count how many zeros before the first non-zero
                        leading_zeros = 0
                        for d in week:
                            if d == 0:
                                leading_zeros += 1
                            else:
                                break
                        actual_day = prev_month_days - (leading_zeros - 1) + offset
                        iso = f"{prev_year:04d}-{prev_month:02d}-{actual_day:02d}"
                    else:
                        # Trailing zeros — next month
                        trailing_start = None
                        for i, d in enumerate(week):
                            if d == 0 and trailing_start is None and i > 0:
                                trailing_start = i
                        if trailing_start is None:
                            trailing_start = col_idx
                        actual_day = col_idx - trailing_start + 1
                        iso = f"{next_year:04d}-{next_month:02d}-{actual_day:02d}"

                    statuses = dict(day_statuses[iso]) if iso in day_statuses else None
                    cell.configure(actual_day, iso, "other_month", statuses)
                else:
                    iso = f"{year:04d}-{month:02d}-{day_num:02d}"
                    if iso == self._selected_iso:
                        day_type = "selected"
                    elif date(year, month, day_num) == today:
                        day_type = "today"
                    elif date(year, month, day_num) < today:
                        day_type = "past"
                    else:
                        day_type = "normal"

                    statuses = dict(day_statuses[iso]) if iso in day_statuses else None

                    # Add gap indicator for days in the past with no posts
                    if (
                        day_type == "past"
                        and not statuses
                    ):
                        statuses = {"gap": 1}

                    cell.configure(day_num, iso, day_type, statuses)

                cell.clicked.connect(lambda c=cell: self._on_cell_clicked(c))
                self._grid.addWidget(cell, row_idx, col_idx)
                self._cells.append(cell)

    # ---- slots ----

    def _on_cell_clicked(self, cell: _DayCell) -> None:
        iso = cell.iso_date
        if not iso:
            return
        if iso == self._selected_iso:
            # Clicking the same day again clears selection
            self._selected_iso = ""
            self.day_cleared.emit()
        else:
            self._selected_iso = iso
            self.day_selected.emit(iso)
        self._populate_grid()

    def _go_prev(self) -> None:
        y, m = self._current_month.year, self._current_month.month
        if m == 1:
            self._current_month = date(y - 1, 12, 1)
        else:
            self._current_month = date(y, m - 1, 1)
        self._populate_grid()

    def _go_next(self) -> None:
        y, m = self._current_month.year, self._current_month.month
        if m == 12:
            self._current_month = date(y + 1, 1, 1)
        else:
            self._current_month = date(y, m + 1, 1)
        self._populate_grid()

    def _update_jst_clock(self) -> None:
        """Update the JST clock display."""
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime
            now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
            now_local = datetime.now().astimezone()
            local_str = now_local.strftime("%I:%M%p").lstrip("0")
            jst_str = now_jst.strftime("%I:%M%p %a").lstrip("0")
            self._jst_label.setText(f"Local: {local_str}  |  JST: {jst_str}")
        except Exception:
            self._jst_label.setText("")

    def _go_today(self) -> None:
        self._current_month = date.today().replace(day=1)
        self._populate_grid()
