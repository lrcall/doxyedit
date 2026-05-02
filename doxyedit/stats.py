"""Stats tab — project overview: counts, tag frequency, platform fill, folder breakdown."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QProgressBar, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal
from doxyedit.themes import ui_metrics, THEMES, DEFAULT_THEME

from doxyedit.models import Project, PLATFORMS
from doxyedit.panel_mixin import LazyRefreshMixin


class _DiskSizeThread(QThread):
    """Compute total disk size of a list of asset paths off the UI thread."""
    # total_bytes is Python int (unbounded). Signal(int, ...) maps to
    # C++ int (32-bit) and overflows once a project exceeds 2 GB — users
    # with ~85 GB of assets triggered libshiboken overflow warnings and
    # the cascading "Cannot create children" cross-thread error. Using
    # "qlonglong" (int64) carries 9 exabytes before overflowing.
    done = Signal("qlonglong", int)  # (total_bytes, token)

    def __init__(self, paths: list[str], token: int):
        # No Qt parent — QThread parent would be on the main thread and
        # any cross-thread object creation during emit (side effect of
        # an overflow on the legacy int signal) tried to create children
        # in the worker thread under the main-thread parent. Owner keeps
        # a Python-level ref via _size_thread for lifetime.
        super().__init__()
        self._paths = paths
        self._token = token

    def run(self):
        total = 0
        for p in self._paths:
            try:
                total += Path(p).stat().st_size
            except OSError:
                pass
        self.done.emit(total, self._token)


class StatsPanel(LazyRefreshMixin, QWidget):
    BAR_LABEL_WIDTH_RATIO = 15       # label column width = _f * 15
    BAR_COUNT_WIDTH_RATIO = 7.5      # count column width = _f * 7.5

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("stats_panel")
        self.project = project
        self.folder_bar_color = THEMES[DEFAULT_THEME].accent_bright
        self._size_cache: dict[int, int] = {}  # asset count -> total bytes
        self._size_card: QLabel | None = None
        self._size_thread: _DiskSizeThread | None = None
        self._size_token = 0
        self._build()

    def _build(self):
        _f, _pad, _pad_lg, _ = ui_metrics()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_pad, _pad, _pad, _pad)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(_pad_lg * 5, _pad_lg * 4, _pad_lg * 5, _pad_lg * 5)
        self._body_layout.setSpacing(_pad_lg * 4)
        scroll.setWidget(self._body)

        self.refresh()

    def refresh(self):
        _f, _pad, _pad_lg, _ = ui_metrics()
        # Clear previous content
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        assets = self.project.assets
        if not assets:
            lbl = QLabel("No assets loaded yet.")
            lbl.setProperty("role", "muted")
            self._body_layout.addWidget(lbl)
            self._body_layout.addStretch()
            return

        total = len(assets)
        tagged = sum(1 for a in assets if a.tags)
        starred = sum(1 for a in assets if a.starred)
        assigned = sum(1 for a in assets if a.assignments)

        cached_bytes = self._size_cache.get(total)
        if cached_bytes is not None:
            size_str = self._fmt_size(cached_bytes)
        else:
            size_str = "computing..."
            self._size_token += 1
            token = self._size_token
            paths = [a.source_path for a in assets]
            thread = _DiskSizeThread(paths, token)
            self._size_thread = thread

            def _on_done(total_bytes: int, tok: int):
                if tok != self._size_token:
                    return  # a newer refresh superseded this one
                self._size_cache[total] = total_bytes
                if self._size_card is not None:
                    self._size_card.setText(self._fmt_size(total_bytes))

            thread.done.connect(_on_done)
            thread.start()

        # ── Summary row ──────────────────────────────────────────────
        self._body_layout.addWidget(self._section_label("Overview"))
        grid = QWidget()
        grid_layout = QHBoxLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(_pad_lg * 2)
        self._size_card = None
        for label, value in [
            ("Total Assets", str(total)),
            ("Tagged", f"{tagged} ({tagged*100//total}%)"),
            ("Starred", str(starred)),
            ("Assigned", f"{assigned} ({assigned*100//total}%)"),
            ("Disk Size", size_str),
        ]:
            card = self._stat_card(label, value)
            if label == "Disk Size":
                self._size_card = card.findChild(QLabel)  # value label
            grid_layout.addWidget(card)
        self._body_layout.addWidget(grid)

        # ── Tag frequency ─────────────────────────────────────────────
        tag_counts: dict[str, int] = {}
        for a in assets:
            for t in a.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        if tag_counts:
            self._body_layout.addWidget(self._section_label("Tag Frequency"))
            top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:30]
            max_count = top_tags[0][1]
            all_tags = self.project.get_tags()
            tag_widget = QWidget()
            tag_layout = QVBoxLayout(tag_widget)
            tag_layout.setContentsMargins(0, 0, 0, 0)
            tag_layout.setSpacing(_pad)
            for tid, count in top_tags:
                label = all_tags[tid].label if tid in all_tags else tid
                color = all_tags[tid].color if tid in all_tags else "#888"
                tag_layout.addWidget(self._bar_row(label, count, max_count, color, f"{count} assets"))
            self._body_layout.addWidget(tag_widget)

        # ── Platform fill ─────────────────────────────────────────────
        assign_map: dict[tuple, bool] = {}
        for a in assets:
            for pa in a.assignments:
                assign_map[(pa.platform, pa.slot)] = True

        platform_rows = []
        for pid in self.project.platforms:
            plat = PLATFORMS.get(pid)
            if not plat:
                continue
            total_slots = len(plat.slots)
            if not total_slots:
                continue
            filled = sum(1 for s in plat.slots if (pid, s.name) in assign_map)
            platform_rows.append((plat.name, filled, total_slots,
                                   "#ff6b6b" if plat.needs_censor else "#7ca1c0"))

        if platform_rows:
            self._body_layout.addWidget(self._section_label("Platform Fill"))
            plat_widget = QWidget()
            plat_layout = QVBoxLayout(plat_widget)
            plat_layout.setContentsMargins(0, 0, 0, 0)
            plat_layout.setSpacing(_pad)
            for name, filled, total_slots, color in platform_rows:
                suffix = f"{filled}/{total_slots} slots"
                plat_layout.addWidget(
                    self._bar_row(name, filled, total_slots, color, suffix))
            self._body_layout.addWidget(plat_widget)

        # ── Folder breakdown ──────────────────────────────────────────
        folder_counts: dict[str, int] = {}
        for a in assets:
            folder = a.source_folder or str(Path(a.source_path).parent)
            # Use top-level folder name relative to common root
            p = Path(folder)
            folder_counts[p.name] = folder_counts.get(p.name, 0) + 1

        if folder_counts:
            self._body_layout.addWidget(self._section_label("By Folder"))
            top_folders = sorted(folder_counts.items(), key=lambda x: -x[1])[:20]
            max_f = top_folders[0][1]
            fold_widget = QWidget()
            fold_layout = QVBoxLayout(fold_widget)
            fold_layout.setContentsMargins(0, 0, 0, 0)
            fold_layout.setSpacing(_pad)
            for fname, count in top_folders:
                fold_layout.addWidget(
                    self._bar_row(fname, count, max_f, self.folder_bar_color, f"{count} assets"))
            self._body_layout.addWidget(fold_widget)

        self._body_layout.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font(); f.setBold(True); lbl.setFont(f)
        lbl.setProperty("role", "secondary")
        lbl.setObjectName("stats_section_label")
        return lbl

    def _stat_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("stat_card")
        layout = QVBoxLayout(card)
        _f, _pad, _pad_lg, _ = ui_metrics()
        layout.setContentsMargins(_pad_lg * 2, _pad_lg + _pad, _pad_lg * 2, _pad_lg + _pad)
        layout.setSpacing(max(2, _pad // 2))
        val_lbl = QLabel(value)
        f = val_lbl.font(); f.setBold(True); val_lbl.setFont(f)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_lbl = QLabel(label)
        lbl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_lbl.setProperty("role", "muted")
        layout.addWidget(val_lbl)
        layout.addWidget(lbl_lbl)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _bar_row(self, label: str, value: int, maximum: int,
                 color: str, suffix: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        _f, _, _pad_lg, _ = ui_metrics()
        h.setSpacing(_pad_lg)

        name_lbl = QLabel(label)
        name_lbl.setFixedWidth(int(_f * self.BAR_LABEL_WIDTH_RATIO))
        h.addWidget(name_lbl)

        bar = QProgressBar()
        bar.setMinimum(0)
        bar.setMaximum(maximum or 1)
        bar.setValue(value)
        bar.setTextVisible(False)
        bar.setFixedHeight(int(_f * 1.0))
        bar.setObjectName("stats_bar")
        _pad = max(4, _f // 3)
        bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; border-radius: {_pad}px; }}")
        h.addWidget(bar, 1)

        count_lbl = QLabel(suffix)
        count_lbl.setFixedWidth(int(_f * self.BAR_COUNT_WIDTH_RATIO))
        count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        count_lbl.setProperty("role", "muted")
        h.addWidget(count_lbl)

        return row

    @staticmethod
    def _fmt_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"
