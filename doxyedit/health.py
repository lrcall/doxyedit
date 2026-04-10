"""File Health tab — scan assets for issues and surface them as clickable rows."""
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QSettings
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


def _detect_path_mode_issues(project) -> str | None:
    """Detect local_mode vs absolute path mismatches that cause mass missing files.
    Returns a warning message or None."""
    if not project.assets:
        return None
    total = len(project.assets)
    missing = sum(1 for a in project.assets if not Path(a.source_path).exists())
    if missing < total * 0.5:
        return None  # less than half missing — probably individual file issues

    # Check for relative paths in a non-local project
    relative_count = sum(1 for a in project.assets if not Path(a.source_path).is_absolute())
    if not project.local_mode and relative_count > total * 0.5:
        return (f"⚠ {relative_count}/{total} assets have relative paths but Local Mode is OFF.\n"
                "The project may have been saved with Local Mode on a different machine.\n"
                "Try: File → Local Mode (toggle ON), then save and reopen.")

    # Check if all absolute paths share a root that doesn't exist on this machine
    if project.local_mode and missing > total * 0.8:
        return (f"⚠ {missing}/{total} assets are missing with Local Mode ON.\n"
                "The project file may have been moved since paths were saved.\n"
                "Paths are resolved relative to the project file location.")

    # General mass-missing: paths might be from a different machine
    if missing > total * 0.8:
        # Check if paths share a common root that doesn't exist
        sample = [a.source_path for a in project.assets[:20]]
        roots = set()
        for p in sample:
            parts = Path(p).parts
            if len(parts) >= 2:
                roots.add(parts[0] + parts[1] if len(parts[0]) <= 3 else parts[0])
        existing_roots = sum(1 for r in roots if Path(r).exists())
        if existing_roots == 0 and roots:
            root_str = ", ".join(sorted(roots)[:3])
            return (f"⚠ {missing}/{total} assets are missing.\n"
                    f"Paths point to: {root_str} — which don't exist on this machine.\n"
                    "This project may have been created on a different computer.")

    return None


class HealthPanel(QWidget):
    asset_selected = Signal(str)    # navigate browser to this asset_id
    missing_removed = Signal(int)   # emitted with count after removal

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("health_panel")
        self.project = project
        self._missing_assets: list = []
        self._build()

    def _build(self):
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("health_toolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(_pad_lg * 2, _pad_lg, _pad_lg * 2, _pad_lg)

        self._summary_lbl = QLabel("Run a scan to check for issues.")
        self._summary_lbl.setProperty("role", "muted")
        tb_layout.addWidget(self._summary_lbl)
        tb_layout.addStretch()

        self._auto_locate_btn = QPushButton("Auto-Locate All")
        self._auto_locate_btn.setStyleSheet("QPushButton { padding: 4px 16px; }")
        self._auto_locate_btn.setToolTip("Auto-update paths for all missing files with exactly one candidate match")
        self._auto_locate_btn.setEnabled(False)
        self._auto_locate_btn.clicked.connect(self._auto_locate_all)
        tb_layout.addWidget(self._auto_locate_btn)

        self._remove_missing_btn = QPushButton("Remove Missing")
        self._remove_missing_btn.setStyleSheet("QPushButton { padding: 4px 16px; }")
        self._remove_missing_btn.setToolTip("Delete all assets whose source file no longer exists")
        self._remove_missing_btn.setEnabled(False)
        self._remove_missing_btn.clicked.connect(self._confirm_remove_missing)
        tb_layout.addWidget(self._remove_missing_btn)

        scan_btn = QPushButton("Scan Now")
        scan_btn.setStyleSheet("QPushButton { padding: 4px 16px; }")
        scan_btn.clicked.connect(self.run_scan)
        tb_layout.addWidget(scan_btn)
        outer.addWidget(toolbar)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("card_divider")
        outer.addWidget(line)

        # Scrollable results
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(_pad_lg * 2, _pad_lg * 2, _pad_lg * 2, _pad_lg * 2)
        self._results_layout.setSpacing(_pad_lg * 2)
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

        self._missing_assets = buckets.get("missing", [])
        has_missing = bool(self._missing_assets)
        self._remove_missing_btn.setEnabled(has_missing)
        self._auto_locate_btn.setEnabled(has_missing)

        # Detect local_mode / path mismatch before showing individual results
        path_warning = _detect_path_mode_issues(self.project)
        if path_warning:
            warn_lbl = QLabel(path_warning)
            warn_lbl.setWordWrap(True)
            warn_lbl.setStyleSheet(
                "background: rgba(255,165,0,0.15); color: #ffa500; padding: 12px;"
                " border: 1px solid rgba(255,165,0,0.3); border-radius: 6px;")
            warn_lbl.setFont(QFont("Segoe UI", 10))
            self._results_layout.addWidget(warn_lbl)

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
                    self._issue_section(label, severity, assets, missing=(key == "missing")))

        self._results_layout.addStretch()
        color = "#44cc44" if total_issues == 0 else SEVERITY_COLORS["error"] if any(
            buckets[k] for k, s, *_ in ISSUE_DEFS if s == "error") else SEVERITY_COLORS["warning"]
        self._summary_lbl.setText(
            f"{total_issues} issue{'s' if total_issues != 1 else ''} found across "
            f"{len(self.project.assets)} assets.")
        self._summary_lbl.setStyleSheet(f"color: {color};")

    def _issue_section(self, label: str, severity: str, assets: list,
                       missing: bool = False) -> QWidget:
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_pad)

        color = SEVERITY_COLORS.get(severity, "#888")
        header = QLabel(f"{label}  —  {len(assets)} asset{'s' if len(assets) != 1 else ''}")
        header.setFont(QFont("Segoe UI", -1, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {color};")
        layout.addWidget(header)

        for asset in assets[:50]:
            if missing:
                row = self._missing_asset_row(asset, color)
            else:
                row = self._asset_row(asset, color)
            layout.addWidget(row)

        if len(assets) > 50:
            more = QLabel(f"  … and {len(assets) - 50} more")
            more.setProperty("role", "muted")
            layout.addWidget(more)

        return section

    def _asset_row(self, asset, color: str) -> QWidget:
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        row = QWidget()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet(
            "QWidget { border-radius: 4px; padding: 1px; }"
            "QWidget:hover { background: rgba(255,255,255,0.05); }")
        h = QHBoxLayout(row)
        h.setContentsMargins(_pad_lg, _pad, _pad_lg, _pad)
        h.setSpacing(_pad_lg)

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

        row.mousePressEvent = lambda _, aid=asset.id: self.asset_selected.emit(aid)
        return row

    def _missing_asset_row(self, asset, color: str) -> QWidget:
        """Row for a missing asset — includes rename detection."""
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(max(2, _pad // 2))

        # Main row
        row = QWidget()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet(
            "QWidget { border-radius: 4px; padding: 1px; }"
            "QWidget:hover { background: rgba(255,255,255,0.05); }")
        h = QHBoxLayout(row)
        h.setContentsMargins(_pad_lg, _pad, _pad_lg, _pad)
        h.setSpacing(_pad_lg)

        dot = QLabel("●")
        dot.setFixedWidth(12)
        dot.setStyleSheet(f"color: {color};")
        h.addWidget(dot)

        name_lbl = QLabel(Path(asset.source_path).name)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(name_lbl)

        folder_lbl = QLabel(Path(asset.source_path).parent.name)
        folder_lbl.setProperty("role", "muted")
        h.addWidget(folder_lbl)

        # Check for rename candidates immediately
        candidates = self._find_rename_candidates(asset)

        if candidates:
            best = candidates[0]
            # Show relative path from common ancestor if folder moved, otherwise just name
            try:
                rel = best.relative_to(Path(asset.source_path).parent.parent)
                hint_text = f"→ {rel}"
            except ValueError:
                hint_text = f"→ {best.name}"
            if len(candidates) > 1:
                hint_text += f"  (+{len(candidates)-1} more)"
            hint_lbl = QLabel(hint_text)
            hint_lbl.setStyleSheet("color: #7ca1c0; font-style: italic;")
            hint_lbl.setToolTip(str(best))
            h.addWidget(hint_lbl)

            accept_btn = QPushButton("Update Path")
            accept_btn.setStyleSheet("QPushButton { padding: 2px 10px; }")
            accept_btn.clicked.connect(
                lambda _, a=asset, c=candidates: self._apply_rename(a, c))
            h.addWidget(accept_btn)
        else:
            browse_btn = QPushButton("Locate…")
            browse_btn.setStyleSheet("QPushButton { padding: 2px 10px; }")
            browse_btn.clicked.connect(lambda _, a=asset: self._browse_for_rename(a))
            h.addWidget(browse_btn)

        row.mousePressEvent = lambda _, aid=asset.id: self.asset_selected.emit(aid)
        outer_layout.addWidget(row)
        return outer

    def _find_rename_candidates(self, asset) -> list[Path]:
        """Search for a renamed or moved file.

        Strategy (in order of confidence):
        1. Exact same filename anywhere under the original folder's parent tree (folder move)
        2. Same extension + same file size in original folder or parent folder tree (rename)
        Returns candidates sorted: exact name match first, then size match, then alpha.
        Limits search to 3 levels up from original folder to avoid scanning the whole drive.
        """
        src = Path(asset.source_path)
        ext = src.suffix.lower()
        stem = src.stem.lower()
        known_paths = {a.source_path for a in self.project.assets}

        # Try to get original file size from disk (may exist in a different location)
        old_size = None

        # Walk up at most 3 levels from the missing file's folder
        search_roots = []
        p = src.parent
        for _ in range(4):
            if p.exists():
                search_roots.append(p)
                break
            p = p.parent
            if len(p.parts) <= 1:
                break
        if not search_roots:
            # Even the drive root might work — try parent of parent
            if src.parent.parent.exists():
                search_roots.append(src.parent.parent)

        candidates: dict[str, Path] = {}  # str path → Path, dedup

        def _scan(root: Path, max_depth: int = 3):
            try:
                for f in root.iterdir():
                    if f.is_file():
                        if f.suffix.lower() == ext and str(f) not in known_paths:
                            candidates[str(f)] = f
                    elif f.is_dir() and max_depth > 0:
                        _scan(f, max_depth - 1)
            except PermissionError:
                pass

        for root in search_roots:
            _scan(root)

        if not candidates:
            return []

        found = list(candidates.values())

        # Score each candidate
        def _score(p: Path):
            name_match = p.stem.lower() == stem          # exact stem match
            try:
                sz = p.stat().st_size
                size_match = (old_size is not None and sz == old_size)
            except Exception:
                size_match = False
            # Lower score = better
            return (0 if name_match else 1, 0 if size_match else 1, p.name.lower())

        found.sort(key=_score)
        return found[:10]  # cap at 10 candidates

    def _apply_rename(self, asset, candidates: list[Path]):
        """Apply the rename — if multiple candidates, let user pick."""
        if len(candidates) == 1:
            new_path = candidates[0]
        else:
            from PySide6.QtWidgets import QInputDialog
            names = [str(p) for p in candidates]
            chosen, ok = QInputDialog.getItem(
                self, "Select Renamed File",
                f"Multiple candidates found for:\n{Path(asset.source_path).name}\n\nSelect the correct file:",
                names, 0, False)
            if not ok:
                return
            new_path = Path(chosen)

        asset.source_path = str(new_path)
        asset.source_folder = str(new_path.parent)
        self.project.invalidate_index()
        self.run_scan()

    def _browse_for_rename(self, asset):
        """Manual file picker for locating a renamed/moved asset."""
        ext = Path(asset.source_path).suffix
        folder = str(Path(asset.source_path).parent)
        new_path, _ = QFileDialog.getOpenFileName(
            self, f"Locate {Path(asset.source_path).name}",
            folder,
            f"Images (*{ext});;All Files (*)")
        if not new_path:
            return
        asset.source_path = new_path
        asset.source_folder = str(Path(new_path).parent)
        self.project.invalidate_index()
        self.run_scan()

    def _auto_locate_all(self):
        """For each missing asset with exactly one candidate, update its path automatically."""
        missing = list(self._missing_assets)
        if not missing:
            return
        updated = 0
        ambiguous = 0
        not_found = 0
        for asset in missing:
            candidates = self._find_rename_candidates(asset)
            if len(candidates) == 1:
                asset.source_path = str(candidates[0])
                asset.source_folder = str(candidates[0].parent)
                updated += 1
            elif len(candidates) > 1:
                ambiguous += 1
            else:
                not_found += 1
        if updated:
            self.project.invalidate_index()
        parts = [f"{updated} updated"]
        if ambiguous:
            parts.append(f"{ambiguous} ambiguous (use Update Path per row)")
        if not_found:
            parts.append(f"{not_found} not found (use Locate…)")
        self._summary_lbl.setText("  ·  ".join(parts))
        self.run_scan()

    def _confirm_remove_missing(self):
        missing = getattr(self, '_missing_assets', [])
        if not missing:
            return
        n = len(missing)
        reply = QMessageBox.question(
            self, "Remove Missing Files",
            f"Permanently remove {n} asset record{'s' if n != 1 else ''} whose source file no longer exists?\n\n"
            "This cannot be undone. The source files themselves are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        missing_ids = {a.id for a in missing}
        self.project.assets = [a for a in self.project.assets if a.id not in missing_ids]
        self.project.invalidate_index()
        self._missing_assets = []
        self._remove_missing_btn.setEnabled(False)
        self._summary_lbl.setText(f"Removed {n} missing asset record{'s' if n != 1 else ''}.")
        self.missing_removed.emit(n)
        self.run_scan()

    def refresh(self):
        """Called on project switch — clear stale results."""
        self._missing_assets = []
        self._remove_missing_btn.setEnabled(False)
        self._auto_locate_btn.setEnabled(False)
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._results_layout.addStretch()
        self._summary_lbl.setText("Run a scan to check for issues.")
        self._summary_lbl.setProperty("role", "muted")
