"""Platform assignment panel — two-column card layout + visual dashboard."""
from pathlib import Path
import uuid
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QSplitter, QStackedWidget,
    QProgressBar, QGridLayout, QComboBox, QDialog, QLineEdit,
    QDateEdit, QCheckBox, QDialogButtonBox, QInputDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QSettings, QDate
from PySide6.QtGui import QPixmap

from doxyedit.models import (
    Project, Asset, PlatformAssignment, PostStatus, PLATFORMS,
    Campaign, CampaignMilestone,
)


STATUS_ICONS = {
    "pending": "·",
    "ready":   "◑",
    "posted":  "●",
    "skip":    "✕",
}
STATUS_CYCLE = ["pending", "ready", "posted", "skip"]


class NewCampaignDialog(QDialog):
    """Simple dialog to create a new Campaign."""

    def __init__(self, platforms: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Campaign")
        layout = QVBoxLayout(self)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Campaign name")
        layout.addWidget(QLabel("Name"))
        layout.addWidget(self._name_edit)

        self._platform_combo = QComboBox()
        self._platform_combo.addItem("(none)", "")
        for pid in platforms:
            p = PLATFORMS.get(pid)
            if p:
                self._platform_combo.addItem(p.name, pid)
        layout.addWidget(QLabel("Platform"))
        layout.addWidget(self._platform_combo)

        self._launch_edit = QDateEdit(QDate.currentDate().addMonths(1))
        self._launch_edit.setCalendarPopup(True)
        layout.addWidget(QLabel("Launch date"))
        layout.addWidget(self._launch_edit)

        self._status_combo = QComboBox()
        for s in ("planning", "preparing", "live", "completed", "cancelled"):
            self._status_combo.addItem(s)
        layout.addWidget(QLabel("Status"))
        layout.addWidget(self._status_combo)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def result_campaign(self) -> Campaign:
        return Campaign(
            id=uuid.uuid4().hex[:12],
            name=self._name_edit.text().strip() or "Untitled",
            platform_id=self._platform_combo.currentData(),
            launch_date=self._launch_edit.date().toString("yyyy-MM-dd"),
            status=self._status_combo.currentText(),
        )


class CampaignBar(QWidget):
    """Campaign selector bar with milestone checklist."""

    modified = Signal()  # emitted when campaign data changes

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("campaign_bar")
        self.project = project
        self._current_campaign_id: str = ""
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ── Top row: combo + status + launch + milestones summary ──
        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(QLabel("Campaign:"))
        self._combo = QComboBox()
        self._combo.setObjectName("campaign_combo")
        self._combo.setMinimumWidth(140)
        self._combo.currentIndexChanged.connect(self._on_campaign_changed)
        row.addWidget(self._combo)

        self._new_btn = QPushButton("+ New")
        self._new_btn.setObjectName("campaign_new_btn")
        self._new_btn.clicked.connect(self._on_new_campaign)
        row.addWidget(self._new_btn)

        sep = QLabel("|")
        sep.setProperty("role", "muted")
        row.addWidget(sep)

        self._status_label = QLabel()
        self._status_label.setObjectName("campaign_status_label")
        row.addWidget(self._status_label)

        sep2 = QLabel("|")
        sep2.setProperty("role", "muted")
        row.addWidget(sep2)

        self._launch_label = QLabel()
        self._launch_label.setObjectName("campaign_launch_label")
        row.addWidget(self._launch_label)

        sep3 = QLabel("|")
        sep3.setProperty("role", "muted")
        row.addWidget(sep3)

        self._milestone_summary = QLabel()
        row.addWidget(self._milestone_summary)

        row.addStretch()
        outer.addLayout(row)

        # ── Milestone frame (collapsible) ──
        self._milestone_frame = QFrame()
        self._milestone_frame.setObjectName("campaign_milestones")
        self._ms_layout = QVBoxLayout(self._milestone_frame)
        self._ms_layout.setContentsMargins(20, 2, 4, 2)
        self._ms_layout.setSpacing(2)
        outer.addWidget(self._milestone_frame)

        self._populate_combo()

    # ── Combo helpers ──

    def _populate_combo(self):
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("All", "")
        for c in self.project.campaigns:
            self._combo.addItem(c.name, c.id)
        self._combo.blockSignals(False)
        self._on_campaign_changed(0)

    def _on_campaign_changed(self, idx: int):
        cid = self._combo.currentData() or ""
        self._current_campaign_id = cid
        cam = self.project.get_campaign(cid) if cid else None
        if cam:
            self._status_label.setText(f"Status: {cam.status}")
            self._launch_label.setText(f"Launch: {cam.launch_date or '—'}")
            done = sum(1 for m in cam.milestones if m.completed)
            self._milestone_summary.setText(f"Milestones: {done}/{len(cam.milestones)}")
            self._milestone_frame.show()
        else:
            self._status_label.setText("")
            self._launch_label.setText("")
            self._milestone_summary.setText("")
            self._milestone_frame.hide()
        self._rebuild_milestones(cam)

    def _rebuild_milestones(self, cam: "Campaign | None"):
        while self._ms_layout.count():
            item = self._ms_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not cam:
            return
        for ms in cam.milestones:
            row = QHBoxLayout()
            cb = QCheckBox(ms.label)
            cb.setObjectName("campaign_milestone_check")
            cb.setChecked(ms.completed)
            cb.toggled.connect(lambda checked, m=ms: self._toggle_milestone(m, checked))
            row.addWidget(cb)
            date_lbl = QLabel(ms.due_date or "")
            date_lbl.setProperty("role", "muted")
            row.addWidget(date_lbl)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            self._ms_layout.addWidget(w)
        add_btn = QPushButton("+ Add Milestone")
        add_btn.setObjectName("campaign_add_milestone_btn")
        add_btn.clicked.connect(lambda: self._add_milestone(cam))
        self._ms_layout.addWidget(add_btn)

    def _toggle_milestone(self, ms: CampaignMilestone, checked: bool):
        ms.completed = checked
        # Update summary
        cam = self.project.get_campaign(self._current_campaign_id)
        if cam:
            done = sum(1 for m in cam.milestones if m.completed)
            self._milestone_summary.setText(f"Milestones: {done}/{len(cam.milestones)}")
        self.modified.emit()

    def _add_milestone(self, cam: Campaign):
        label, ok = QInputDialog.getText(self, "Milestone", "Label:")
        if not ok or not label.strip():
            return
        date_str, ok2 = QInputDialog.getText(self, "Due Date", "Date (YYYY-MM-DD):",
                                              text=QDate.currentDate().toString("yyyy-MM-dd"))
        if not ok2:
            return
        ms = CampaignMilestone(
            id=uuid.uuid4().hex[:8],
            label=label.strip(),
            due_date=date_str.strip(),
        )
        cam.milestones.append(ms)
        self._on_campaign_changed(self._combo.currentIndex())
        self.modified.emit()

    def _on_new_campaign(self):
        dlg = NewCampaignDialog(self.project.platforms, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        cam = dlg.result_campaign()
        self.project.campaigns.append(cam)
        self._populate_combo()
        self._combo.setCurrentIndex(self._combo.count() - 1)
        self.modified.emit()

    @property
    def current_campaign_id(self) -> str:
        return self._current_campaign_id

    def set_project(self, project: Project):
        self.project = project
        self._populate_combo()


class PlatformPanel(QWidget):
    """Two-column card grid of platform slots."""

    request_asset_pick = Signal(str, str)  # platform_id, slot_name
    asset_selected = Signal(str)           # asset_id — hive cell clicked

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("platform_panel")
        self.project = project
        self._thumb_cache = None
        self._build()

    def set_thumb_cache(self, cache):
        """Accept ThumbCache reference for dashboard thumbnails."""
        self._thumb_cache = cache

    def _build(self):
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(_pad_lg)

        # Campaign bar
        self._campaign_bar = CampaignBar(self.project, self)
        self._campaign_bar.modified.connect(self._on_campaign_modified)
        outer.addWidget(self._campaign_bar)

        # Top bar: summary + view toggle
        top_bar = QHBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setProperty("role", "muted")
        top_bar.addWidget(self.summary_label, 1)
        self._view_toggle = QPushButton("Dashboard")
        self._view_toggle.setFixedWidth(80)
        self._view_toggle.setCheckable(True)
        self._view_toggle.setToolTip("Toggle between card and dashboard views")
        self._view_toggle.toggled.connect(self._on_view_toggled)
        top_bar.addWidget(self._view_toggle)
        outer.addLayout(top_bar)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        # ── Page 0: Cards view (existing) ─────────────────────────────────
        cards_page = QWidget()
        cards_layout = QVBoxLayout(cards_page)
        cards_layout.setContentsMargins(0, 0, 0, 0)  # scroll area provides framing

        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        cards_layout.addWidget(self._vsplit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._cards_widget = QWidget()
        scroll.setWidget(self._cards_widget)

        self._col_layout = QHBoxLayout(self._cards_widget)
        self._col_layout.setContentsMargins(0, 4, 0, 4)
        self._col_layout.setSpacing(_pad_lg * 2)

        self._col0 = QVBoxLayout()
        self._col1 = QVBoxLayout()
        self._col0.setSpacing(_pad_lg * 2)
        self._col1.setSpacing(_pad_lg * 2)
        self._col_layout.addLayout(self._col0)
        self._col_layout.addLayout(self._col1)

        self._vsplit.addWidget(scroll)

        # Image hive
        hive_container = QWidget()
        hive_container.setObjectName("hive_container")
        hive_v = QVBoxLayout(hive_container)
        hive_v.setContentsMargins(0, 4, 0, 0)
        hive_v.setSpacing(_pad)

        hive_header = QLabel("Assigned Art")
        _bold = hive_header.font(); _bold.setBold(True); hive_header.setFont(_bold)
        hive_header.setProperty("role", "secondary")
        hive_v.addWidget(hive_header)

        hive_scroll = QScrollArea()
        hive_scroll.setWidgetResizable(True)
        hive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        hive_scroll.setMinimumHeight(80)
        hive_v.addWidget(hive_scroll)

        self._hive_widget = QWidget()
        self._hive_layout = QHBoxLayout(self._hive_widget)
        self._hive_layout.setContentsMargins(4, 4, 4, 4)
        self._hive_layout.setSpacing(_pad_lg)
        self._hive_layout.addStretch()
        hive_scroll.setWidget(self._hive_widget)

        self._hive_container = hive_container  # exposed for reparenting by window.py
        self._vsplit.addWidget(hive_container)
        self._vsplit.setSizes([600, 180])
        self._vsplit.setStretchFactor(0, 1)
        self._vsplit.setStretchFactor(1, 0)

        self._stack.addWidget(cards_page)

        # ── Page 1: Dashboard view ──────────────────────────��─────────────
        self._dash_scroll = QScrollArea()
        self._dash_scroll.setWidgetResizable(True)
        self._dash_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._dash_widget = QWidget()
        self._dash_layout = QVBoxLayout(self._dash_widget)
        self._dash_layout.setContentsMargins(4, 4, 4, 4)
        self._dash_layout.setSpacing(_pad_lg * 2)
        self._dash_layout.addStretch()
        self._dash_scroll.setWidget(self._dash_widget)
        self._stack.addWidget(self._dash_scroll)

        self.refresh()

    def _on_view_toggled(self, checked: bool):
        self._stack.setCurrentIndex(1 if checked else 0)
        self._view_toggle.setText("Cards" if checked else "Dashboard")
        if checked:
            self._rebuild_dashboard()

    def _on_campaign_modified(self):
        """Called when CampaignBar changes data — refresh cards and propagate."""
        self.refresh()

    def refresh(self):
        # Clear both columns
        for col in (self._col0, self._col1):
            while col.count():
                item = col.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        # Build lookup: (platform_id, slot_name) → list of (asset, PlatformAssignment)
        cid = self._campaign_bar.current_campaign_id
        self._assign_map: dict[tuple, list] = {}
        for asset in self.project.assets:
            for pa in asset.assignments:
                if cid and pa.campaign_id != cid:
                    continue
                self._assign_map.setdefault((pa.platform, pa.slot), []).append((asset, pa))
        assign_map = self._assign_map

        total_slots = filled_slots = posted_slots = 0

        for i, (pid, platform) in enumerate(
            (pid, PLATFORMS[pid]) for pid in self.project.platforms if pid in PLATFORMS
        ):
            col = self._col0 if i % 2 == 0 else self._col1
            col.addWidget(self._build_card(platform, pid, assign_map))

            for slot in platform.slots:
                total_slots += 1
                key = (pid, slot.name)
                entries = assign_map.get(key, [])
                if entries:
                    filled_slots += 1
                    if all(str(pa.status) == "posted" for _, pa in entries):
                        posted_slots += 1

        self._col0.addStretch()
        self._col1.addStretch()

        empty = total_slots - filled_slots
        self.summary_label.setText(
            f"{filled_slots}/{total_slots} filled  ·  "
            f"{posted_slots} posted  ·  "
            f"{empty} empty"
        )
        self._rebuild_hive(assign_map)

    def _rebuild_hive(self, assign_map: dict):
        """Rebuild the thumbnail hive from current assignments."""
        # Clear previous thumbnails (keep trailing stretch)
        while self._hive_layout.count() > 1:
            item = self._hive_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Collect all (asset, slot_label, platform_name, status) in platform order
        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue
            for slot in platform.slots:
                key = (pid, slot.name)
                slot_entries = assign_map.get(key, [])
                n = len(slot_entries)
                for idx, (asset, pa) in enumerate(slot_entries):
                    label = slot.label if n == 1 else f"{slot.label} {idx + 1}/{n}"
                    cell = self._hive_cell(asset, label, platform.name, pa.status)
                    self._hive_layout.insertWidget(self._hive_layout.count() - 1, cell)

    def _hive_cell(self, asset, slot_label: str, plat_name: str, status: str) -> QWidget:
        """One thumbnail cell in the image hive."""
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        THUMB = 100
        cell = QWidget()
        cell.setFixedWidth(THUMB + 8)
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
        cell.setToolTip(f"{plat_name} — {slot_label}\n{asset.source_path}")
        v = QVBoxLayout(cell)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(max(2, _pad // 2))

        # Thumbnail
        thumb = QLabel()
        thumb.setObjectName("hive_thumb")
        thumb.setFixedSize(THUMB, THUMB)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = self._thumb_cache.get(asset.id) if self._thumb_cache else None
        if pm is None:
            pm = QPixmap()
        if not pm.isNull():
            pm = pm.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            thumb.setPixmap(pm)
        else:
            thumb.setText("?")
        v.addWidget(thumb)

        # Slot label
        slot_lbl = QLabel(slot_label)
        slot_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slot_lbl.setWordWrap(True)
        slot_lbl.setProperty("role", "muted")
        slot_lbl.setMaximumWidth(THUMB + 8)
        v.addWidget(slot_lbl)

        # Status dot
        dot = QLabel(STATUS_ICONS.get(str(status), "·"))
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setObjectName("hive_status_dot")
        dot.setProperty("status", str(status))
        v.addWidget(dot)

        # Click → emit asset_selected — capture asset_id via default arg
        asset_id = asset.id
        cell.mousePressEvent = lambda _, _aid=asset_id: self.asset_selected.emit(_aid)
        return cell

    def _build_card(self, platform, pid: str, assign_map: dict) -> QFrame:
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        card = QFrame()
        card.setObjectName("platform_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(max(2, _pad // 2))

        # ── Card header ──────────────────────────────────────────────────
        header = QHBoxLayout()
        name_lbl = QLabel(platform.name)
        _bold = name_lbl.font(); _bold.setBold(True); name_lbl.setFont(_bold)
        if platform.needs_censor:
            name_lbl.setProperty("severity", "error")
        header.addWidget(name_lbl)
        header.addStretch()

        filled = sum(1 for s in platform.slots if assign_map.get((pid, s.name)))
        total = len(platform.slots)
        # Progress dots
        dots = "".join("●" if assign_map.get((pid, s.name)) else "○" for s in platform.slots)
        dots_lbl = QLabel(dots)
        dots_lbl.setObjectName("platform_dots")
        dots_lbl.setToolTip(f"{filled}/{total} slots filled")
        header.addWidget(dots_lbl)

        count_lbl = QLabel(f"{filled}/{total}")
        count_lbl.setObjectName("platform_count")
        header.addWidget(count_lbl)
        layout.addLayout(header)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("card_divider")
        layout.addWidget(line)

        # ── Slot rows ─────────────────────────────────────────────────────
        for slot in platform.slots:
            key = (pid, slot.name)
            entries = assign_map.get(key, [])
            layout.addWidget(self._slot_row(slot, pid, entries))

        return card

    def _slot_row(self, slot, pid: str, entries: list) -> QWidget:
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad_lg = max(6, _f // 2)
        row = QWidget()
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, p=pid, s=slot, e=entries: self._slot_context_menu(row, pos, p, s, e))
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(_pad_lg)

        # Slot label
        label_text = slot.label + (" *" if slot.required else "")
        name_lbl = QLabel(label_text)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(name_lbl, 3)

        # Size badge
        size_lbl = QLabel(f"{slot.width}×{slot.height}")
        size_lbl.setObjectName("size_badge")
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(size_lbl)

        # Asset name label
        if len(entries) == 0:
            asset_lbl = QLabel("empty — right-click to assign")
            if slot.required:
                asset_lbl.setObjectName("slot_empty_required")
            else:
                asset_lbl.setObjectName("slot_empty")
        elif len(entries) == 1:
            asset, _ = entries[0]
            stem = Path(asset.source_path).stem
            display = stem if len(stem) <= 22 else stem[:20] + "…"
            asset_lbl = QLabel(display)
            asset_lbl.setToolTip(asset.source_path)
        else:
            asset_lbl = QLabel(f"{len(entries)} images")
            asset_lbl.setProperty("role", "accent")

        asset_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(asset_lbl, 2)

        # Status button — click to cycle
        if entries:
            first_status = str(entries[0][1].status)
            status_btn = QPushButton(STATUS_ICONS.get(first_status, "·"))
            status_btn.setFixedSize(24, 20)
            status_btn.setToolTip(f"{first_status} — click to cycle")
            self._style_status_btn(status_btn, first_status)
            status_btn.clicked.connect(
                lambda _, p=pid, s=slot.name, b=status_btn: self._cycle_status(p, s, b))
        else:
            status_btn = QPushButton("·")
            status_btn.setFixedSize(24, 20)
            status_btn.setToolTip("right-click row to assign")
            self._style_status_btn(status_btn, "pending")
            status_btn.setEnabled(False)
        h.addWidget(status_btn)

        # Show assignment notes as tooltip
        if entries:
            notes_parts = [pa.notes for _, pa in entries if pa.notes]
            if notes_parts:
                row.setToolTip("\n".join(notes_parts))

        return row

    def _slot_context_menu(self, row, pos, pid: str, slot, entries: list):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(row)
        menu.addAction("Add image to slot", lambda: self.request_asset_pick.emit(pid, slot.name))
        if entries:
            menu.addSeparator()
            for asset, pa in entries:
                name = Path(asset.source_path).name
                a = menu.addAction(f"Remove: {name}")
                a.triggered.connect(
                    lambda checked=False, aid=asset.id, p=pid, s=slot.name:
                        self._remove_asset_from_slot(aid, p, s))
            menu.addSeparator()
            menu.addAction("Edit Note", lambda: self._edit_slot_note(pid, slot.name, entries))
            menu.addSeparator()
            menu.addAction("Clear all", lambda: self._clear_assignment(pid, slot.name))
        menu.exec(row.mapToGlobal(pos))

    def _remove_asset_from_slot(self, asset_id: str, pid: str, slot_name: str):
        """Remove only a specific asset's assignment for that slot."""
        for asset in self.project.assets:
            if asset.id == asset_id:
                asset.assignments = [
                    pa for pa in asset.assignments
                    if not (pa.platform == pid and pa.slot == slot_name)
                ]
        self.refresh()

    def _clear_assignment(self, pid: str, slot_name: str):
        """Clear ALL assets assigned to this slot."""
        for asset in self.project.assets:
            asset.assignments = [
                pa for pa in asset.assignments
                if not (pa.platform == pid and pa.slot == slot_name)
            ]
        self.refresh()

    def _edit_slot_note(self, pid: str, slot_name: str, entries: list):
        """Edit the note on all assignments in a slot via QInputDialog."""
        current = entries[0][1].notes if entries else ""
        text, ok = QInputDialog.getText(self, "Edit Note", "Note:", text=current)
        if ok:
            for _, pa in entries:
                pa.notes = text
            self.refresh()

    def _style_status_btn(self, btn: QPushButton, status: str):
        btn.setObjectName("status_btn")
        btn.setProperty("status", status)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _advance_slot_status(self, pid: str, slot_name: str) -> str | None:
        """Cycle all assignments in the slot to the next status. Returns new status or None."""
        pas = [pa for asset in self.project.assets for pa in asset.assignments
               if pa.platform == pid and pa.slot == slot_name]
        if not pas:
            return None
        cur = str(pas[0].status)
        idx = STATUS_CYCLE.index(cur) if cur in STATUS_CYCLE else 0
        new_status = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]
        for pa in pas:
            pa.status = new_status
        return new_status

    def _cycle_status(self, pid: str, slot_name: str, btn: QPushButton):
        new_status = self._advance_slot_status(pid, slot_name)
        if not new_status:
            return
        btn.setText(STATUS_ICONS.get(new_status, "·"))
        self._style_status_btn(btn, new_status)
        btn.setToolTip(f"{new_status} — click to cycle")

    def _rebuild_dashboard(self):
        """Build visual dashboard grid: one row per platform, one cell per slot."""
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)
        _cb = max(14, _f + 2)
        # Clear previous dashboard contents
        while self._dash_layout.count() > 1:
            item = self._dash_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        assign_map = getattr(self, '_assign_map', {})
        if not assign_map:
            # Rebuild if not yet cached (e.g. toggle before first refresh)
            assign_map = {}
            for asset in self.project.assets:
                for pa in asset.assignments:
                    assign_map.setdefault((pa.platform, pa.slot), []).append((asset, pa))

        insert_idx = 0
        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue

            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(_pad)

            # Platform header with progress bar
            header_row = QHBoxLayout()
            name_lbl = QLabel(platform.name)
            _bold = name_lbl.font(); _bold.setBold(True); name_lbl.setFont(_bold)
            if platform.needs_censor:
                name_lbl.setProperty("severity", "error")
            header_row.addWidget(name_lbl)

            filled = sum(1 for s in platform.slots if assign_map.get((pid, s.name)))
            total = len(platform.slots)
            posted = sum(1 for s in platform.slots
                         if assign_map.get((pid, s.name)) and
                         all(str(pa.status) == "posted" for _, pa in assign_map[(pid, s.name)]))

            progress = QProgressBar()
            progress.setObjectName("dash_progress")
            progress.setRange(0, total)
            progress.setValue(filled)
            progress.setFormat(f"{filled}/{total} filled · {posted} posted")
            progress.setFixedHeight(max(14, _f))
            progress.setFixedWidth(200)
            header_row.addWidget(progress)
            header_row.addStretch()
            section_layout.addLayout(header_row)

            # Slot grid — flow layout of cells
            grid_widget = QWidget()
            grid_flow = QHBoxLayout(grid_widget)
            grid_flow.setContentsMargins(0, 0, 0, 0)
            grid_flow.setSpacing(_pad_lg)

            for slot in platform.slots:
                key = (pid, slot.name)
                entries = assign_map.get(key, [])
                cell = self._dash_cell(slot, pid, entries)
                grid_flow.addWidget(cell)
            grid_flow.addStretch()

            section_layout.addWidget(grid_widget)
            self._dash_layout.insertWidget(insert_idx, section)
            insert_idx += 1

    def _dash_cell(self, slot, pid: str, entries: list) -> QWidget:
        """One slot cell in the dashboard grid."""
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _cb = max(14, _f + 2)
        THUMB = 80
        cell = QWidget()
        cell.setFixedWidth(THUMB + 16)
        v = QVBoxLayout(cell)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(THUMB, THUMB)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setObjectName("dash_thumb")

        if entries:
            asset, pa = entries[0]
            pm = self._thumb_cache.get(asset.id) if self._thumb_cache else None
            if pm and not pm.isNull():
                pm = pm.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                thumb_lbl.setPixmap(pm)
            cell.setCursor(Qt.CursorShape.PointingHandCursor)
            _aid = asset.id
            cell.mousePressEvent = lambda _, _aid=_aid: self.asset_selected.emit(_aid)
            status = str(pa.status)
        else:
            thumb_lbl.setText("—")
            thumb_lbl.setProperty("empty", "true")
            status = "pending"

        v.addWidget(thumb_lbl)

        # Slot label
        slot_lbl = QLabel(slot.label)
        slot_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slot_lbl.setWordWrap(True)
        slot_lbl.setMaximumWidth(THUMB + 16)
        slot_lbl.setObjectName("dash_slot_label")
        v.addWidget(slot_lbl)

        # Status badge — clickable to cycle
        icon = STATUS_ICONS.get(status, "·")
        status_btn = QPushButton(f"{icon} {status}")
        status_btn.setFixedHeight(_cb)
        status_btn.setObjectName("status_btn")
        status_btn.setProperty("status", status)
        if entries:
            status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            status_btn.clicked.connect(
                lambda _, p=pid, s=slot.name, b=status_btn: self._cycle_dash_status(p, s, b))
        else:
            status_btn.setEnabled(False)
        v.addWidget(status_btn)

        # Context menu (same as card view)
        cell.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        cell.customContextMenuRequested.connect(
            lambda pos, p=pid, s=slot, e=entries: self._slot_context_menu(cell, pos, p, s, e))

        # Multi-asset indicator
        if len(entries) > 1:
            multi = QLabel(f"+{len(entries)-1} more")
            multi.setAlignment(Qt.AlignmentFlag.AlignCenter)
            multi.setObjectName("dash_multi")
            v.addWidget(multi)

        return cell

    def _cycle_dash_status(self, pid: str, slot_name: str, btn: QPushButton):
        new_status = self._advance_slot_status(pid, slot_name)
        if not new_status:
            return
        icon = STATUS_ICONS.get(new_status, "·")
        btn.setText(f"{icon} {new_status}")
        btn.setProperty("status", new_status)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def assign_asset(self, asset: Asset, platform_id: str, slot_name: str):
        """Add asset to slot without clearing existing — skip if already assigned."""
        for pa in asset.assignments:
            if pa.platform == platform_id and pa.slot == slot_name:
                return  # already assigned
        asset.assignments.append(PlatformAssignment(
            platform=platform_id,
            slot=slot_name,
            status=PostStatus.READY,
        ))
        self.refresh()
