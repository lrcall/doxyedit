"""Stats tab — project overview: counts, tag frequency, platform fill, folder breakdown."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QProgressBar, QSizePolicy, QPushButton,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from doxyedit.models import Project, PLATFORMS


class StatsPanel(QWidget):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("stats_panel")
        self.project = project
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(32, 24, 32, 32)
        self._body_layout.setSpacing(24)
        scroll.setWidget(self._body)

        self.refresh()

    def refresh(self):
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
        total_bytes = 0
        for a in assets:
            try:
                total_bytes += Path(a.source_path).stat().st_size
            except OSError:
                pass
        size_str = self._fmt_size(total_bytes)

        # ── Summary row ──────────────────────────────────────────────
        self._body_layout.addWidget(self._section_label("Overview"))
        grid = QWidget()
        grid_layout = QHBoxLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(12)
        for label, value in [
            ("Total Assets", str(total)),
            ("Tagged", f"{tagged} ({tagged*100//total}%)"),
            ("Starred", str(starred)),
            ("Assigned", f"{assigned} ({assigned*100//total}%)"),
            ("Disk Size", size_str),
        ]:
            grid_layout.addWidget(self._stat_card(label, value))
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
            tag_layout.setSpacing(3)
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
            plat_layout.setSpacing(3)
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
            fold_layout.setSpacing(3)
            for fname, count in top_folders:
                fold_layout.addWidget(
                    self._bar_row(fname, count, max_f, "#93a167", f"{count} assets"))
            self._body_layout.addWidget(fold_widget)

        self._body_layout.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        lbl.setProperty("role", "secondary")
        lbl.setStyleSheet("padding-top: 4px;")
        return lbl

    def _stat_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("stat_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        val_lbl = QLabel(value)
        val_lbl.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
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
        h.setSpacing(8)

        name_lbl = QLabel(label)
        name_lbl.setFixedWidth(180)
        h.addWidget(name_lbl)

        bar = QProgressBar()
        bar.setMinimum(0)
        bar.setMaximum(maximum or 1)
        bar.setValue(value)
        bar.setTextVisible(False)
        bar.setFixedHeight(12)
        bar.setStyleSheet(
            f"QProgressBar {{ background: rgba(255,255,255,0.06); border: none;"
            f" border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}")
        h.addWidget(bar, 1)

        count_lbl = QLabel(suffix)
        count_lbl.setFixedWidth(90)
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
