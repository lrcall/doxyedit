"""Platform assignment panel — two-column card layout + visual dashboard."""
from pathlib import Path
import uuid
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QSplitter,
    QProgressBar, QGridLayout, QComboBox, QDialog, QLineEdit,
    QDateEdit, QCheckBox, QDialogButtonBox, QInputDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QSettings, QDate
from PySide6.QtGui import QPixmap
from doxyedit.browser import FlowLayout

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

# ── Layout ratios (multiply by font_size to get pixel values) ──
PLATFORM_SEARCH_WIDTH_RATIO = 12.5    # search field width
PLATFORM_VIEW_TOGGLE_RATIO = 6.7      # Dashboard toggle button
PLATFORM_BTN_RATIO = 5.0              # compact action buttons (Auto-Fill, Export)
PLATFORM_EXPORT_BTN_RATIO = 5.5       # Export All button
PLATFORM_PROGRESS_WIDTH_RATIO = 16.7  # dashboard progress bar
PLATFORM_SLOT_PREVIEW_HEIGHT = 60     # slot preview thumbnail height (px)
CARD_MARGIN_RATIO = 1.0               # card internal margin
CARD_SPACING_RATIO = 0.33             # card internal spacing
COL_SPACING_RATIO = 1.0               # spacing between cards in a column
SLOT_ROW_MARGIN_V = 1                 # slot row vertical margin (px, intentionally small)
STATUS_BTN_PAD_W = 10                 # status button extra width (px)
STATUS_BTN_PAD_H = 6                  # status button extra height (px)
DASH_CELL_THUMB = 80                  # dashboard cell thumbnail size (px)
DASH_CELL_PAD = 4                     # dashboard cell internal padding (px)
DASH_CELL_EXTRA_W = 16                # dashboard cell extra width beyond thumb


class _DroppableSlotRow(QWidget):
    """Slot row that accepts file drops from the browser grid or tray."""

    dropped = Signal(str)  # emits file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("slot_row_drag_hover")
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setObjectName("")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setObjectName("")
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.dropped.emit(path)
                event.acceptProposedAction()
                return


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
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        outer.setSpacing(_pad)

        # ── Top row: combo + status + launch + milestones summary ──
        row = QHBoxLayout()
        row.setSpacing(_pad * 2)

        row.addWidget(QLabel("Campaign:"))
        self._combo = QComboBox()
        self._combo.setObjectName("campaign_combo")
        from PySide6.QtCore import QSettings
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        COMBO_MIN_WIDTH_RATIO = 11.7       # campaign combo minimum width
        self._combo.setMinimumWidth(int(_f * COMBO_MIN_WIDTH_RATIO))
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
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 3-pane horizontal splitter: sidebar | cards | dashboard ──────
        self._plat_hsplit = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(self._plat_hsplit, 1)

        # ── Pane 1: Sidebar (campaign, filter, summary, actions) ─────────
        sidebar = QWidget()
        sidebar.setObjectName("platform_sidebar")
        sidebar.setMaximumWidth(int(_f * 15))  # cap sidebar width
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)
        sb_layout.setSpacing(_pad_lg)

        self._campaign_bar = CampaignBar(self.project, self)
        self._campaign_bar.modified.connect(self._on_campaign_modified)
        sb_layout.addWidget(self._campaign_bar)

        self._search_platforms = QLineEdit()
        self._search_platforms.setPlaceholderText("Filter platforms...")
        self._search_platforms.setObjectName("platform_search")
        self._search_platforms.textChanged.connect(lambda _: self.refresh())
        sb_layout.addWidget(self._search_platforms)

        self.summary_label = QLabel()
        self.summary_label.setProperty("role", "muted")
        self.summary_label.setWordWrap(True)
        sb_layout.addWidget(self.summary_label)

        btn_export_ready = QPushButton("Export Ready")
        btn_export_ready.setObjectName("platform_action_btn")
        btn_export_ready.setToolTip("Export all platforms with required slots filled")
        btn_export_ready.clicked.connect(self._export_ready_platforms)
        sb_layout.addWidget(btn_export_ready)

        sb_layout.addStretch()
        self._plat_hsplit.addWidget(sidebar)

        # ── Pane 2: Cards (single scrollable column) ────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._cards_widget = QWidget()
        scroll.setWidget(self._cards_widget)

        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        self._cards_layout.setSpacing(int(_f * COL_SPACING_RATIO))

        self._plat_hsplit.addWidget(scroll)

        # ── Right: Dashboard view ────────────────────────────────────────
        dash_container = QWidget()
        dash_outer = QVBoxLayout(dash_container)
        dash_outer.setContentsMargins(0, 0, 0, 0)
        dash_outer.setSpacing(0)

        self._dash_scroll = QScrollArea()
        self._dash_scroll.setWidgetResizable(True)
        self._dash_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._dash_widget = QWidget()
        self._dash_layout = QVBoxLayout(self._dash_widget)
        self._dash_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        self._dash_layout.setSpacing(int(_f * COL_SPACING_RATIO))
        self._dash_layout.addStretch()
        self._dash_scroll.setWidget(self._dash_widget)
        dash_outer.addWidget(self._dash_scroll, 1)
        self._plat_hsplit.addWidget(dash_container)

        self._plat_hsplit.setStretchFactor(0, 0)  # sidebar fixed
        self._plat_hsplit.setStretchFactor(1, 1)  # cards stretch
        self._plat_hsplit.setStretchFactor(2, 1)  # dashboard stretch
        self._plat_hsplit.setSizes([int(_f * 12), 500, 400])

        self.refresh()

    def _on_campaign_modified(self):
        """Called when CampaignBar changes data — refresh cards and propagate."""
        self.refresh()

    def refresh(self):
        # Clear cards
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
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

        # Campaign platform filter — match exact ID or by name prefix
        campaign_platforms: set[str] = set()
        if cid:
            for c in self.project.campaigns:
                if c.id == cid:
                    if c.platform_id:
                        # Match exact + variants (e.g., "kickstarter" matches "kickstarter_jp")
                        for pid_key in PLATFORMS:
                            if pid_key == c.platform_id or pid_key.startswith(c.platform_id + "_"):
                                campaign_platforms.add(pid_key)
                        if not campaign_platforms:
                            campaign_platforms.add(c.platform_id)
                    break

        # Search filter
        search_text = ""
        if hasattr(self, '_search_platforms'):
            search_text = self._search_platforms.text().strip().lower()

        total_slots = filled_slots = posted_slots = 0

        placed = 0
        for pid, platform in (
            (pid, PLATFORMS[pid]) for pid in self.project.platforms if pid in PLATFORMS
        ):
            if campaign_platforms and pid not in campaign_platforms:
                continue
            if search_text and search_text not in platform.name.lower() and search_text not in pid.lower():
                continue
            self._cards_layout.addWidget(self._build_card(platform, pid, assign_map))

            for slot in platform.slots:
                total_slots += 1
                key = (pid, slot.name)
                entries = assign_map.get(key, [])
                if entries:
                    filled_slots += 1
                    if all(str(pa.status) == "posted" for _, pa in entries):
                        posted_slots += 1

        self._cards_layout.addStretch()

        empty = total_slots - filled_slots
        self.summary_label.setText(
            f"{filled_slots}/{total_slots} filled  ·  "
            f"{posted_slots} posted  ·  "
            f"{empty} empty"
        )
        self._rebuild_dashboard()

    def _build_card(self, platform, pid: str, assign_map: dict) -> QFrame:
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        card = QFrame()
        card.setObjectName("platform_card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        _card_m = int(_f * CARD_MARGIN_RATIO)
        layout.setContentsMargins(_card_m, _card_m, _card_m, _card_m)
        layout.setSpacing(max(2, int(_f * CARD_SPACING_RATIO)))

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

        # Readiness badge
        required_slots = [s for s in platform.slots if s.required]
        filled_required = sum(1 for s in required_slots if assign_map.get((pid, s.name)))
        total_required = len(required_slots)
        if total_required > 0:
            if filled_required == total_required:
                badge_text = f"● {filled_required}/{total_required}"
                badge_name = "platform_badge_green"
            elif filled_required > 0:
                badge_text = f"◑ {filled_required}/{total_required}"
                badge_name = "platform_badge_yellow"
            else:
                badge_text = f"○ 0/{total_required}"
                badge_name = "platform_badge_red"
            badge = QLabel(badge_text)
            badge.setObjectName(badge_name)
            header.addWidget(badge)

        autofill_btn = QPushButton("Auto-Fill")
        autofill_btn.setFixedWidth(int(_f * PLATFORM_BTN_RATIO))
        autofill_btn.setObjectName("platform_action_btn")
        autofill_btn.setToolTip("Auto-assign best matching assets to empty slots")
        autofill_btn.clicked.connect(lambda _, p=pid: self._auto_fill_platform(p))
        header.addWidget(autofill_btn)

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
        _cb = max(14, _f + 2)
        _pad_lg = max(6, _f // 2)
        row = _DroppableSlotRow()
        row.dropped.connect(lambda path, p=pid, s=slot: self._on_file_dropped(path, p, s))
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, p=pid, s=slot, e=entries: self._slot_context_menu(row, pos, p, s, e))
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(_pad_lg)

        # Slot label
        label_text = slot.label + (" *" if slot.required else "")
        name_lbl = QLabel(label_text)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        h.addWidget(name_lbl, 1)

        # Size badge
        size_lbl = QLabel(f"{slot.width}×{slot.height}")
        size_lbl.setObjectName("size_badge")
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(size_lbl)

        # Slot preview thumbnail at platform aspect ratio
        if entries and slot.width and slot.height:
            asset, _ = entries[0]
            thumb_w = int(60 * slot.width / slot.height) if slot.height else 60
            thumb_h = 60
            preview = QLabel()
            preview.setFixedSize(thumb_w, thumb_h)
            preview.setObjectName("slot_preview")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Try to load thumbnail
            pm = None
            if self._thumb_cache:
                pm = self._thumb_cache.get(asset.id)
            if pm and not pm.isNull():
                scaled = pm.scaled(thumb_w, thumb_h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                # Center crop
                cx = (scaled.width() - thumb_w) // 2
                cy = (scaled.height() - thumb_h) // 2
                cropped = scaled.copy(cx, cy, thumb_w, thumb_h)
                preview.setPixmap(cropped)
            else:
                preview.setText("?")
                preview.setObjectName("slot_preview_empty")
            h.insertWidget(1, preview)
        elif slot.width and slot.height:
            thumb_w = int(60 * slot.width / slot.height) if slot.height else 60
            empty_prev = QLabel()
            empty_prev.setFixedSize(thumb_w, 60)
            empty_prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_prev.setText(f"{slot.width}×{slot.height}")
            empty_prev.setObjectName("slot_preview_dims")
            h.insertWidget(1, empty_prev)

        # Asset name label
        if len(entries) == 0:
            asset_lbl = QLabel("drop image here")
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
            status_btn.setFixedSize(_cb + STATUS_BTN_PAD_W, _cb + STATUS_BTN_PAD_H)
            status_btn.setToolTip(f"{first_status} — click to cycle")
            self._style_status_btn(status_btn, first_status)
            status_btn.clicked.connect(
                lambda _, p=pid, s=slot.name, b=status_btn: self._cycle_status(p, s, b))
        else:
            status_btn = QPushButton("·")
            status_btn.setFixedSize(_cb + STATUS_BTN_PAD_W, _cb + STATUS_BTN_PAD_H)
            status_btn.setToolTip("right-click row to assign")
            self._style_status_btn(status_btn, "pending")
            status_btn.setEnabled(False)
        h.addWidget(status_btn)

        # Show assignment notes as tooltip
        if entries:
            notes_parts = [pa.notes for _, pa in entries if pa.notes]
            if notes_parts:
                row.setToolTip("\n".join(notes_parts))

        # Show notes inline if present
        for asset, pa in entries:
            if pa.notes:
                note_lbl = QLabel(pa.notes)
                note_lbl.setObjectName("slot_note_label")
                note_lbl.setWordWrap(True)
                h.addWidget(note_lbl)
                break  # only show first note

        return row

    def _on_file_dropped(self, path: str, platform_id: str, slot):
        """Handle drag-drop of asset file onto a slot."""
        import os
        norm = os.path.normpath(path).lower()
        for asset in self.project.assets:
            if os.path.normpath(asset.source_path).lower() == norm:
                self.assign_asset(asset, platform_id, slot.name)
                self.refresh()
                return
        event.acceptProposedAction()

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
            progress.setFixedWidth(int(_f * PLATFORM_PROGRESS_WIDTH_RATIO))
            header_row.addWidget(progress)

            # Export button — shown when all required slots are filled
            required_slots = [s for s in platform.slots if s.required]
            filled_required = sum(1 for s in required_slots if assign_map.get((pid, s.name)))
            if filled_required == len(required_slots) and required_slots:
                export_btn = QPushButton("Export All")
                export_btn.setObjectName("platform_action_btn")
                export_btn.setFixedWidth(int(_f * PLATFORM_EXPORT_BTN_RATIO))
                export_btn.clicked.connect(lambda _, p=pid: self._export_platform(p))
                header_row.addWidget(export_btn)

            header_row.addStretch()
            section_layout.addLayout(header_row)

            # Slot grid — flow layout of cells
            grid_widget = QWidget()
            grid_flow = FlowLayout(grid_widget, spacing=_pad_lg)

            for slot in platform.slots:
                key = (pid, slot.name)
                entries = assign_map.get(key, [])
                cell = self._dash_cell(slot, pid, entries)
                grid_flow.addWidget(cell)

            section_layout.addWidget(grid_widget)
            self._dash_layout.insertWidget(insert_idx, section)
            insert_idx += 1

    def _dash_cell(self, slot, pid: str, entries: list) -> QWidget:
        """One slot cell in the dashboard grid."""
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _cb = max(14, _f + 2)
        cell = QWidget()
        cell.setFixedWidth(DASH_CELL_THUMB + DASH_CELL_EXTRA_W)
        v = QVBoxLayout(cell)
        v.setContentsMargins(DASH_CELL_PAD, DASH_CELL_PAD, DASH_CELL_PAD, DASH_CELL_PAD)
        v.setSpacing(2)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(DASH_CELL_THUMB, DASH_CELL_THUMB)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setObjectName("dash_thumb")

        if entries:
            asset, pa = entries[0]
            pm = self._thumb_cache.get(asset.id) if self._thumb_cache else None
            if pm and not pm.isNull():
                pm = pm.scaled(DASH_CELL_THUMB, DASH_CELL_THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                thumb_lbl.setPixmap(pm)
            elif self._thumb_cache and asset.source_path:
                # Request generation — will appear next time dashboard is rebuilt
                self._thumb_cache.request(asset.id, asset.source_path)
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
        slot_lbl.setMaximumWidth(DASH_CELL_THUMB + DASH_CELL_EXTRA_W)
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

    def _export_ready_platforms(self):
        """Export all platforms that have all required slots filled."""
        from doxyedit.pipeline import prepare_for_platform
        exported = 0
        for pid in self.project.platforms:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue
            required = [s for s in platform.slots if s.required]
            all_filled = all((pid, s.name) in self._assign_map for s in required)
            if not all_filled:
                continue
            for slot in platform.slots:
                entries = self._assign_map.get((pid, slot.name), [])
                if entries:
                    asset, _ = entries[0]
                    result = prepare_for_platform(asset, pid, self.project, slot_name=slot.name)
                    if result.success:
                        exported += 1
                        print(f"[Export] {pid}/{slot.name}: {result.output_path}")
        print(f"[Export] Done: {exported} slot(s) exported")

    def _export_platform(self, platform_id: str):
        """Export all assigned slots for a platform."""
        from doxyedit.pipeline import prepare_for_platform
        platform = PLATFORMS.get(platform_id)
        if not platform:
            return
        exported = 0
        for slot in platform.slots:
            entries = self._assign_map.get((platform_id, slot.name), [])
            if entries:
                asset, _ = entries[0]
                result = prepare_for_platform(asset, platform_id, self.project, slot_name=slot.name)
                if result.success:
                    exported += 1
                    print(f"[Export] {platform_id}/{slot.name}: {result.output_path}")
        print(f"[Export] {platform_id}: {exported} slot(s) exported")

    def _auto_fill_platform(self, platform_id: str):
        """Auto-assign best matching assets to empty slots."""
        platform = PLATFORMS.get(platform_id)
        if not platform:
            return

        filled = 0
        for slot in platform.slots:
            key = (platform_id, slot.name)
            if key in self._assign_map:
                continue  # already assigned

            # Find best matching asset
            best_asset = None
            best_score = -1

            for asset in self.project.assets:
                # Skip already-assigned-to-this-platform assets
                if any(pa.platform == platform_id for pa in asset.assignments):
                    continue

                score = 0
                # Star rating bonus
                score += asset.starred * 2

                # Tag match bonus
                if asset.tags:
                    score += 1

                # Aspect ratio fitness
                if slot.width and slot.height and asset.source_path:
                    try:
                        from PIL import Image
                        with Image.open(asset.source_path) as img:
                            iw, ih = img.size
                            target_ratio = slot.width / slot.height
                            img_ratio = iw / ih
                            ratio_diff = abs(target_ratio - img_ratio) / target_ratio
                            score += max(0, 5 * (1 - ratio_diff))  # 0-5 points for ratio match
                            # Resolution bonus
                            if iw >= slot.width and ih >= slot.height:
                                score += 3
                    except Exception:
                        pass

                if score > best_score:
                    best_score = score
                    best_asset = asset

            if best_asset:
                self.assign_asset(best_asset, platform_id, slot.name)
                filled += 1

        if filled:
            self.refresh()
            print(f"[Auto-Fill] Filled {filled} slot(s) for {platform_id}")

    def assign_asset(self, asset: Asset, platform_id: str, slot_name: str):
        """Add asset to slot without clearing existing — skip if already assigned."""
        for pa in asset.assignments:
            if pa.platform == platform_id and pa.slot == slot_name:
                return  # already assigned
        # Find slot object for aspect-ratio check
        slot_obj = None
        plat = PLATFORMS.get(platform_id)
        if plat:
            for _s in plat.slots:
                if _s.name == slot_name:
                    slot_obj = _s
                    break

        asset.assignments.append(PlatformAssignment(
            platform=platform_id,
            slot=slot_name,
            status=PostStatus.PENDING,
        ))

        # Warn on aspect ratio mismatch
        if slot_obj and slot_obj.width and slot_obj.height:
            from pathlib import Path as _P
            src = _P(asset.source_path)
            if src.exists():
                try:
                    from PIL import Image
                    with Image.open(str(src)) as img:
                        iw, ih = img.size
                        target_ratio = slot_obj.width / slot_obj.height
                        img_ratio = iw / ih
                        if abs(target_ratio - img_ratio) / target_ratio > 0.15:
                            print(f"[Platforms] Warning: {asset.id} ratio {img_ratio:.2f} vs slot {target_ratio:.2f}")
                except Exception:
                    pass

        self.refresh()
