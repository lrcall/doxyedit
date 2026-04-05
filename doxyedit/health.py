"""File Health tab — scan assets for issues and surface them as clickable rows."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from doxyedit.models import Project, PLATFORMS


SEVERITY_COLORS = {
    "error":   "#e06c6c",
    "warning": "#ffa500",
    "info":    "#7ca1c0",
}

ISSUE_DEFS = [
    # (key, severity, label, check_fn(asset, project) -> bool)
    ("missing",    "error",   "Missing file",
     lambda a, _: not Path(a.source_path).exists()),
    ("zero_byte",  "error",   "Zero-byte file",
     lambda a, _: Path(a.source_path).exists() and Path(a.source_path).stat().st_size == 0),
    ("untagged",   "warning", "No tags",
     lambda a, _: not a.tags),
    ("unassigned", "info",    "No platform assignment",
     lambda a, _: not a.assignments),
    ("large",      "info",    "Large file (>50 MB)",
     lambda a, _: Path(a.source_path).exists() and Path(a.source_path).stat().st_size > 50 * 1024 * 1024),
]


class HealthPanel(QWidget):
    asset_selected = Signal(str)  # navigate browser to this asset_id

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("health_toolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(16, 8, 16, 8)

        self._summary_lbl = QLabel("Run a scan to check for issues.")
        self._summary_lbl.setProperty("role", "muted")
        tb_layout.addWidget(self._summary_lbl)
        tb_layout.addStretch()

        scan_btn = QPushButton("Scan Now")
        scan_btn.setStyleSheet("QPushButton { padding: 4px 16px; }")
        scan_btn.clicked.connect(self.run_scan)
        tb_layout.addWidget(scan_btn)
        outer.addWidget(toolbar)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.07); max-height: 1px;")
        outer.addWidget(line)

        # Scrollable results
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(16, 12, 16, 16)
        self._results_layout.setSpacing(16)
        self._results_layout.addStretch()
        scroll.setWidget(self._results_widget)

    def run_scan(self):
        # Clear previous results
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Collect issues per category
        buckets: dict[str, list] = {key: [] for key, *_ in ISSUE_DEFS}
        for asset in self.project.assets:
            for key, severity, label, check in ISSUE_DEFS:
                try:
                    if check(asset, self.project):
                        buckets[key].append(asset)
                except Exception:
                    pass

        total_issues = sum(len(v) for v in buckets.values())
        if total_issues == 0:
            ok = QLabel("✓  No issues found — project looks healthy.")
            ok.setStyleSheet("color: #44cc44; padding: 16px;")
            ok.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
            self._results_layout.addWidget(ok)
        else:
            for key, severity, label, _ in ISSUE_DEFS:
                assets = buckets[key]
                if not assets:
                    continue
                self._results_layout.addWidget(
                    self._issue_section(label, severity, assets))

        self._results_layout.addStretch()
        color = "#44cc44" if total_issues == 0 else SEVERITY_COLORS["error"] if any(
            buckets[k] for k, s, *_ in ISSUE_DEFS if s == "error") else SEVERITY_COLORS["warning"]
        self._summary_lbl.setText(
            f"{total_issues} issue{'s' if total_issues != 1 else ''} found across "
            f"{len(self.project.assets)} assets.")
        self._summary_lbl.setStyleSheet(f"color: {color};")

    def _issue_section(self, label: str, severity: str, assets: list) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        color = SEVERITY_COLORS.get(severity, "#888")
        header = QLabel(f"{label}  —  {len(assets)} asset{'s' if len(assets) != 1 else ''}")
        header.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {color};")
        layout.addWidget(header)

        for asset in assets[:50]:  # cap display at 50 per category
            row = self._asset_row(asset, color)
            layout.addWidget(row)

        if len(assets) > 50:
            more = QLabel(f"  … and {len(assets) - 50} more")
            more.setProperty("role", "muted")
            layout.addWidget(more)

        return section

    def _asset_row(self, asset, color: str) -> QWidget:
        row = QWidget()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet(
            "QWidget { border-radius: 4px; padding: 1px; }"
            "QWidget:hover { background: rgba(255,255,255,0.05); }")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 3, 8, 3)
        h.setSpacing(8)

        dot = QLabel("●")
        dot.setFixedWidth(12)
        dot.setStyleSheet(f"color: {color};")
        h.addWidget(dot)

        name = QLabel(Path(asset.source_path).name)
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(name)

        folder = QLabel(Path(asset.source_path).parent.name)
        folder.setProperty("role", "muted")
        h.addWidget(folder)

        # Make whole row clickable
        row.mousePressEvent = lambda _, aid=asset.id: self.asset_selected.emit(aid)
        return row

    def refresh(self):
        """Called on project switch — clear stale results."""
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._results_layout.addStretch()
        self._summary_lbl.setText("Run a scan to check for issues.")
        self._summary_lbl.setProperty("role", "muted")
