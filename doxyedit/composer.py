"""composer.py -- Post composer dialog (thin shell).

Two-column layout:
  Left:  ImagePreviewPanel (from composer_left.py)
  Right: ContentPanel (from composer_right.py)

PostComposerWidget is the reusable QWidget core.
PostComposer wraps it as a QDialog for floating use.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel,
    QPushButton, QSplitter, QWidget, QDateTimeEdit,
)
from PySide6.QtCore import Qt, QSettings, Signal

from doxyedit.models import Project, SocialPost, SocialPostStatus, ReleaseStep
from doxyedit.composer_left import ImagePreviewPanel
from doxyedit.composer_right import ContentPanel


# Keep for backward compat (docs reference it)
SOCIAL_PLATFORMS = [
    "twitter", "instagram", "bluesky", "reddit",
    "patreon", "discord", "tiktok", "pinterest",
]


class AssetDropLineEdit(QLineEdit):
    """QLineEdit that accepts file drops and resolves to asset IDs."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._project = project
        self._path_index: dict[str, str] = {}  # normalized path -> asset id
        for a in project.assets:
            if a.source_path:
                self._path_index[os.path.normpath(a.source_path).lower()] = a.id

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            ids = []
            names = []
            for p in paths:
                norm = os.path.normpath(p).lower()
                aid = self._path_index.get(norm, "")
                if aid:
                    ids.append(aid)
                    asset = self._project.get_asset(aid)
                    names.append(Path(asset.source_path).stem if asset else aid)
            if ids:
                existing = [x.strip() for x in self.text().split(",") if x.strip()]
                merged = existing + [i for i in ids if i not in existing]
                self.setText(", ".join(merged))
                self.setToolTip("Assets: " + ", ".join(names))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class _NoScrollDateTimeEdit(QDateTimeEdit):
    """QDateTimeEdit that ignores scroll wheel to prevent accidental changes."""
    def wheelEvent(self, event):
        event.ignore()


# ======================================================================
# PostComposerWidget — reusable QWidget (dockable or embeddable)
# ======================================================================

class PostComposerWidget(QWidget):
    """Core composer UI as a QWidget — can live inside a QDialog or docked panel."""

    save_requested = Signal(object)    # emits SocialPost
    cancel_requested = Signal()
    dock_toggled = Signal(bool)        # True=dock, False=float
    open_in_studio = Signal(str)       # asset_id
    open_in_preview = Signal(str)      # asset_id

    def __init__(self, project: Project, post: SocialPost | None = None,
                 project_dir: str = "", parent=None, extra_projects: list | None = None):
        super().__init__(parent)
        self.setObjectName("post_composer_widget")
        self._project = project
        self._editing = post
        self._project_dir = project_dir
        self._extra_projects: list = extra_projects or []
        self._settings = QSettings("DoxyEdit", "DoxyEdit")

        self._build_ui()
        self._prefill(post)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        _f = self._settings.value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        root = QVBoxLayout(self)
        root.setSpacing(_pad)
        root.setContentsMargins(_pad_lg + _pad, _pad_lg + _pad, _pad_lg + _pad, _pad_lg + _pad)

        # --- Two-column splitter ---
        self._composer_split = QSplitter(Qt.Orientation.Horizontal)
        self._composer_split.setObjectName("composer_hsplit")

        # Left panel — asset input + image preview + SFW/NSFW + crops
        self._left_wrapper = QWidget()
        left_layout = QVBoxLayout(self._left_wrapper)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(_pad)

        # Schedule picker (top of left panel for visibility)
        from PySide6.QtWidgets import QDateTimeEdit, QGroupBox
        from PySide6.QtCore import QDateTime
        from datetime import datetime as _dt, timedelta as _td

        sched_box = QGroupBox("Schedule")
        sched_box.setObjectName("composer_left_schedule")
        sched_lay = QVBoxLayout(sched_box)
        sched_lay.setContentsMargins(_pad, _pad, _pad, _pad)
        self._left_schedule = _NoScrollDateTimeEdit()
        self._left_schedule.setObjectName("composer_left_schedule_edit")
        self._left_schedule.setCalendarPopup(True)
        self._left_schedule.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        tomorrow = _dt.now() + _td(days=1)
        self._left_schedule.setDateTime(
            QDateTime(tomorrow.year, tomorrow.month, tomorrow.day,
                      tomorrow.hour, tomorrow.minute, 0))
        sched_lay.addWidget(self._left_schedule)

        # Timezone display
        self._left_tz_label = QLabel()
        self._left_tz_label.setObjectName("composer_tz_clock")
        sched_lay.addWidget(self._left_tz_label)
        self._left_schedule.dateTimeChanged.connect(self._update_left_tz)
        self._update_left_tz()
        left_layout.addWidget(sched_box)

        # Asset ID input + Use Selected
        images_row = QHBoxLayout()
        self._images_edit = AssetDropLineEdit(self._project)
        self._images_edit.setPlaceholderText("Asset ID or drag from tray")
        images_row.addWidget(self._images_edit, 1)
        self._use_selected_btn = QPushButton("Use Selected")
        self._use_selected_btn.setToolTip("Grab currently selected assets from the browser")
        self._use_selected_btn.clicked.connect(self._use_selected_assets)
        images_row.addWidget(self._use_selected_btn)
        left_layout.addLayout(images_row)

        # Image preview panel
        self._left_panel = ImagePreviewPanel(self._project)
        self._left_panel.open_in_studio.connect(self.open_in_studio)
        self._left_panel.open_in_preview.connect(self.open_in_preview)
        left_layout.addWidget(self._left_panel, 1)

        self._composer_split.addWidget(self._left_wrapper)

        # Right panel — content
        self._right_panel = ContentPanel(self._project, project_dir=self._project_dir,
                                         extra_projects=self._extra_projects)
        self._composer_split.addWidget(self._right_panel)

        # Restore or set default splitter sizes
        saved = self._settings.value("composer_hsplit", None)
        if saved:
            self._composer_split.setSizes([int(s) for s in saved])
        else:
            self._composer_split.setSizes([350, 650])
        self._composer_split.setStretchFactor(0, 0)
        self._composer_split.setStretchFactor(1, 1)

        # Restore content splitter
        content_saved = self._settings.value("composer_content_split", None)
        if content_saved:
            self._right_panel.set_splitter_sizes([int(s) for s in content_saved])

        root.addWidget(self._composer_split, 1)

        # --- Signal wiring ---
        self._images_edit.textChanged.connect(self._on_images_changed)
        self._right_panel.platforms_changed.connect(self._on_platforms_changed)
        self._right_panel.platforms_changed.connect(self._update_prep_strip)

        # --- Button bar ---
        btn_layout = QHBoxLayout()
        btn_draft = QPushButton("Save Draft")
        btn_draft.clicked.connect(lambda: self._save(SocialPostStatus.DRAFT))
        btn_queue = QPushButton("Queue to OneUp")
        btn_queue.clicked.connect(lambda: self._save(SocialPostStatus.QUEUED))

        self._dock_btn = QPushButton("Dock")
        self._dock_btn.setObjectName("composer_dock_btn")
        self._dock_btn.setCheckable(True)
        self._dock_btn.setToolTip("Toggle between floating dialog and docked panel")
        self._dock_btn.clicked.connect(lambda c: self.dock_toggled.emit(c))

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.cancel_requested.emit)

        btn_layout.addWidget(btn_draft)
        btn_layout.addWidget(btn_queue)
        btn_layout.addStretch()
        btn_layout.addWidget(self._dock_btn)
        btn_layout.addWidget(btn_cancel)
        root.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Compact mode (for docked layout)
    # ------------------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """Mark as docked — same horizontal layout as floating."""
        self._dock_btn.setChecked(compact)

    # ------------------------------------------------------------------
    # Load / reload a post
    # ------------------------------------------------------------------

    def load_post(self, project: Project, post: SocialPost | None) -> None:
        """Re-prefill from a different post (for switching posts while docked)."""
        self._project = project
        self._editing = post
        # Rebuild asset drop index
        self._images_edit._project = project
        self._images_edit._path_index.clear()
        for a in project.assets:
            if a.source_path:
                self._images_edit._path_index[os.path.normpath(a.source_path).lower()] = a.id
        self._left_panel._project = project
        self._right_panel._project = project
        self._images_edit.clear()
        self._prefill(post)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _update_left_tz(self):
        """Update timezone display on left schedule picker."""
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as _dtm
            qt_dt = self._left_schedule.dateTime()
            py_dt = qt_dt.toPython()
            local_tz = _dtm.now().astimezone().tzinfo
            aware = py_dt.replace(tzinfo=local_tz)
            parts = []
            for tz_name, label in [("US/Eastern", "EST"), ("US/Pacific", "PST"), ("Asia/Tokyo", "JST")]:
                conv = aware.astimezone(ZoneInfo(tz_name))
                parts.append(f"{label} {conv.strftime('%I:%M%p').lstrip('0')}")
            self._left_tz_label.setText("  |  ".join(parts))
        except Exception:
            pass

        # Sync to right panel schedule
        if hasattr(self, '_right_panel') and hasattr(self._right_panel, '_schedule_edit'):
            self._right_panel._schedule_edit.blockSignals(True)
            self._right_panel._schedule_edit.setDateTime(self._left_schedule.dateTime())
            self._right_panel._schedule_edit.blockSignals(False)
            if hasattr(self._right_panel, '_update_tz_display'):
                self._right_panel._update_tz_display()

    def _on_images_changed(self) -> None:
        """Update left panel when asset IDs change."""
        ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        self._left_panel.set_assets(ids)
        # Also update platforms on left panel
        platforms = [p for p, cb in self._right_panel._platform_checks.items()
                     if cb.isChecked()]
        self._left_panel.set_platforms(platforms)

    def _on_platforms_changed(self, platforms: list[str]) -> None:
        """Update left panel when platform selection changes."""
        self._left_panel.set_platforms(platforms)

    def _update_prep_strip(self, platforms: list[str]) -> None:
        ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        self._left_panel.rebuild_prep_strip(ids, platforms, self._project)

    # ------------------------------------------------------------------
    # Pre-fill
    # ------------------------------------------------------------------

    def _prefill(self, post: SocialPost | None) -> None:
        if post is None:
            # Default platform selection from project identity
            try:
                identity = self._project.get_identity()
                defaults = identity.default_platforms if identity else []
            except Exception:
                defaults = []
            self._right_panel.set_default_platforms(defaults)
            return

        # Images
        self._images_edit.setText(", ".join(post.asset_ids))

        # Right panel fields
        self._right_panel.set_post(post)

        # Sync schedule to left panel
        if post.scheduled_time:
            try:
                from datetime import datetime as _dtm
                from PySide6.QtCore import QDateTime
                dt = _dtm.fromisoformat(post.scheduled_time)
                self._left_schedule.setDateTime(
                    QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0))
            except Exception:
                pass

        # Left panel NSFW
        if post.nsfw_platforms:
            self._left_panel.set_nsfw_platforms(post.nsfw_platforms)

    # ------------------------------------------------------------------
    # Image picker
    # ------------------------------------------------------------------

    def _use_selected_assets(self):
        """Grab selected asset IDs from the main window's browser."""
        # Walk up to find a parent with a browser
        w = self.parent()
        while w is not None:
            if hasattr(w, 'browser'):
                break
            w = w.parent() if hasattr(w, 'parent') and callable(w.parent) else None
        if w and hasattr(w, 'browser'):
            selected = list(w.browser._selected_ids)
            if selected:
                names = []
                for aid in selected:
                    asset = self._project.get_asset(aid)
                    if asset:
                        names.append(Path(asset.source_path).stem)
                    else:
                        names.append(aid)
                self._images_edit.setText(", ".join(selected))
                self._images_edit.setToolTip("Selected: " + ", ".join(names))
            else:
                self._images_edit.setPlaceholderText(
                    "No assets selected, select in Assets tab first")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self, status) -> None:
        status = status.value if hasattr(status, 'value') else str(status)
        now = datetime.now().isoformat()

        asset_ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        data = self._right_panel.get_post_data()
        nsfw_platforms = self._left_panel.get_nsfw_platforms()
        # sfw_asset_ids not yet wired — placeholder
        sfw_asset_ids = getattr(self._editing, 'sfw_asset_ids', []) if self._editing else []

        if self._editing is not None:
            p = self._editing
            p.asset_ids = asset_ids
            p.platforms = data["platforms"]
            p.caption_default = data["caption_default"]
            p.captions = data["captions"]
            p.links = data["links"]
            p.scheduled_time = data["scheduled_time"]
            p.status = status
            p.reply_templates = data["reply_templates"]
            p.strategy_notes = data["strategy_notes"]
            p.nsfw_platforms = nsfw_platforms
            p.sfw_asset_ids = sfw_asset_ids
            p.collection = data.get("collection", "")
            p.release_chain = [ReleaseStep.from_dict(s) for s in data.get("release_chain", [])]
            p.campaign_id = data.get("campaign_id", getattr(p, "campaign_id", ""))
            # Preserve fields not yet in the UI
            p.updated_at = now
            result_post = p
        else:
            result_post = SocialPost(
                id=str(uuid.uuid4()),
                asset_ids=asset_ids,
                platforms=data["platforms"],
                caption_default=data["caption_default"],
                captions=data["captions"],
                links=data["links"],
                scheduled_time=data["scheduled_time"],
                status=status,
                reply_templates=data["reply_templates"],
                strategy_notes=data["strategy_notes"],
                nsfw_platforms=nsfw_platforms,
                sfw_asset_ids=sfw_asset_ids,
                collection=data.get("collection", ""),
                release_chain=[ReleaseStep.from_dict(s) for s in data.get("release_chain", [])],
                campaign_id=data.get("campaign_id", ""),
                created_at=now,
                updated_at=now,
            )

        # Advisory readiness check
        if status == SocialPostStatus.QUEUED and asset_ids:
            from doxyedit.pipeline import check_readiness
            from doxyedit.models import PLATFORMS
            issues = []
            for aid in asset_ids[:1]:
                asset = self._project.get_asset(aid)
                if not asset:
                    continue
                for pid in data["platforms"]:
                    if pid not in PLATFORMS:
                        continue
                    r = check_readiness(asset, pid, self._project)
                    if r["status"] == "red":
                        issues.extend(r["issues"])
            if issues:
                from PySide6.QtWidgets import QMessageBox
                msg = "Some platforms need prep:\n\n" + "\n".join(f"• {i}" for i in issues[:5])
                msg += "\n\nPost anyway?"
                reply = QMessageBox.question(
                    self, "Platform Prep", msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return

        self.save_requested.emit(result_post)

    def save_splitter_state(self) -> None:
        """Persist splitter sizes to QSettings."""
        self._settings.setValue("composer_hsplit", self._composer_split.sizes())
        self._settings.setValue("composer_content_split",
                                self._right_panel.get_splitter_sizes())

    def disconnect_workers(self) -> None:
        """Proxy to right panel worker cleanup."""
        self._right_panel.disconnect_workers()


# ======================================================================
# PostComposer — QDialog wrapper around PostComposerWidget
# ======================================================================

class PostComposer(QDialog):
    """Two-column post composer dialog (floating window)."""

    DIALOG_MIN_WIDTH_RATIO = 75.0
    DIALOG_MIN_HEIGHT_RATIO = 50.0

    def __init__(self, project: Project, post: SocialPost | None = None,
                 project_dir: str = "", parent=None, extra_projects: list | None = None):
        super().__init__(parent)
        self.setObjectName("post_composer")
        self.setWindowTitle("Edit Post" if post else "New Post")
        self.setWindowModality(Qt.WindowModality.NonModal)
        _f = QSettings("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        self.setMinimumSize(int(_f * self.DIALOG_MIN_WIDTH_RATIO), int(_f * self.DIALOG_MIN_HEIGHT_RATIO))

        # Restore saved geometry
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        geo = self._settings.value("composer_geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1100, 750)

        self.result_post: SocialPost | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._widget = PostComposerWidget(project, post, project_dir=project_dir, parent=self,
                                          extra_projects=extra_projects)
        layout.addWidget(self._widget)

        self._widget.save_requested.connect(self._on_save)
        self._widget.cancel_requested.connect(self.reject)
        self._widget.dock_toggled.connect(self._on_dock_toggled)

    @property
    def widget(self) -> PostComposerWidget:
        return self._widget

    # ------------------------------------------------------------------
    # Geometry persistence
    # ------------------------------------------------------------------

    def _save_geometry(self):
        self._settings.setValue("composer_geometry", self.saveGeometry())
        self._widget.save_splitter_state()

    def closeEvent(self, event):
        self._save_geometry()
        self._widget.disconnect_workers()
        super().closeEvent(event)

    def accept(self):
        self._save_geometry()
        super().accept()

    def reject(self):
        self._save_geometry()
        super().reject()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_save(self, post: SocialPost):
        self.result_post = post
        self.accept()

    def _on_dock_toggled(self, checked: bool):
        """When dock is toggled from the dialog, save pref and let parent handle it."""
        self._settings.setValue("composer_docked", checked)
        if checked:
            # Close dialog — the parent window will re-open docked
            self._save_geometry()
            self._widget.disconnect_workers()
            # Stash the post data so the parent can re-dock it
            self._dock_requested = True
            self.reject()
