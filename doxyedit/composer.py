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
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel,
    QPushButton, QSplitter, QWidget, QDateTimeEdit, QMessageBox,
    QGroupBox,
)
from PySide6.QtCore import Qt, QSettings, Signal, QDateTime
from doxyedit.themes import ui_font_size, ui_metrics

from doxyedit.models import Project, SocialPost, SocialPostStatus, ReleaseStep, PLATFORMS
from doxyedit.composer_left import ImagePreviewPanel
from doxyedit.composer_right import ContentPanel


# Keep for backward compat (docs reference it)
SOCIAL_PLATFORMS = [
    "twitter", "instagram", "bluesky", "reddit",
    "patreon", "discord", "tiktok", "pinterest",
]


# ----------------------------------------------------------------------
# SocialPost field ownership.
#
# _save() no longer hand-copies each field one by one. It builds a
# widget-state dict (ContentPanel.get_post_data() plus a few direct
# widget values) and merges it into the post with apply_post_data(),
# a to_dict()/from_dict() round-trip that mutates the live post in
# place. Any SocialPost field returned by get_post_data() therefore
# flows through automatically - a new field can never silently revert
# on save again.
#
# When adding a field to SocialPost, classify it in exactly ONE of the
# three sets below (and, for UI fields, return it from get_post_data()
# in composer_right.py). tests/test_composer_save_parity.py fails
# until every dataclass field is classified.
# ----------------------------------------------------------------------

# Fields sourced from ContentPanel.get_post_data() (composer_right.py).
COMPOSER_UI_FIELDS = frozenset({
    "platforms", "caption_default", "captions", "links",
    "scheduled_time", "reply_templates", "strategy_notes",
    "release_chain", "collection", "identity_name",
    "category_id", "censor_mode",
})

# Fields _save() writes directly from its own widgets / arguments,
# outside get_post_data().
COMPOSER_DIRECT_FIELDS = frozenset({
    "asset_ids", "status", "nsfw_platforms", "sfw_asset_ids",
    "updated_at",
})

# Pipeline-owned fields the composer must NEVER write: identity fields
# set once at creation (id, created_at) plus state maintained by the
# posting pipeline. apply_post_data() refuses to merge these even if a
# data dict names them, so a composer save preserves them verbatim.
COMPOSER_PRESERVED_FIELDS = frozenset({
    "id", "created_at", "notes", "platform_status", "oneup_post_id",
    "tier_assets", "sub_platform_status", "published_urls",
    "engagement_checks", "platform_censor", "platform_metrics",
    "posting_log",
    # campaign_id is assigned from the campaign side (not the composer
    # UI); get_post_data() does not return it. Move it to
    # COMPOSER_UI_FIELDS if the composer ever grows a campaign picker.
    "campaign_id",
})


def apply_post_data(post: SocialPost, data: dict) -> SocialPost:
    """Merge a widget-state dict into an existing SocialPost IN PLACE.

    Dict-merge mechanism: round-trips through SocialPost.to_dict() /
    from_dict() so nested values (e.g. release_chain step dicts) are
    coerced by the model's own deserializer, then copies the merged
    values back onto the original object so live references held by
    the timeline / window stay valid.

    Merge rules:
      - keys that are not SocialPost dataclass fields are ignored
      - keys in COMPOSER_PRESERVED_FIELDS are ignored (pipeline-owned)
      - keys whose value is None are ignored (absent widget, e.g.
        identity_name on older composers)

    Returns the same post object for convenience.
    """
    merge_keys = [
        k for k, v in data.items()
        if k in SocialPost.__dataclass_fields__
        and k not in COMPOSER_PRESERVED_FIELDS
        and v is not None
    ]
    base = post.to_dict()
    for k in merge_keys:
        v = data[k]
        if k == "release_chain":
            # from_dict expects raw step dicts; tolerate ReleaseStep
            # instances handed in by callers.
            v = [s.to_dict() if isinstance(s, ReleaseStep) else s
                 for s in v]
        base[k] = v
    merged = SocialPost.from_dict(base)
    for k in merge_keys:
        setattr(post, k, getattr(merged, k))
    return post


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
        # Was reading via self._settings (per-instance QSettings cache),
        # then deriving _pad / _pad_lg by hand. Same anti-pattern as the
        # gantt / timeline / health / stats migrations - ui_metrics()
        # already encapsulates the derivation off the process-wide
        # ui_font_size cache.
        _f, _pad, _pad_lg, _ = ui_metrics()

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

        sched_box = QGroupBox("Schedule")
        sched_box.setObjectName("composer_left_schedule")
        sched_lay = QVBoxLayout(sched_box)
        sched_lay.setContentsMargins(_pad, _pad, _pad, _pad)
        self._left_schedule = _NoScrollDateTimeEdit()
        self._left_schedule.setObjectName("composer_left_schedule_edit")
        self._left_schedule.setCalendarPopup(True)
        self._left_schedule.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        tomorrow = datetime.now() + timedelta(days=1)
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
            qt_dt = self._left_schedule.dateTime()
            py_dt = qt_dt.toPython()
            local_tz = datetime.now().astimezone().tzinfo
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
                dt = datetime.fromisoformat(post.scheduled_time)
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

        # Dict-merge save: everything ContentPanel.get_post_data()
        # returns flows into the post via apply_post_data() - there is
        # no hand-copied field list to forget. Direct widget values are
        # folded into the same dict. See the COMPOSER_*_FIELDS
        # constants at module top for field ownership.
        data = self._right_panel.get_post_data()
        data["asset_ids"] = asset_ids
        data["status"] = status
        data["nsfw_platforms"] = self._left_panel.get_nsfw_platforms()
        # sfw_asset_ids not yet wired - keep whatever the post has
        data["sfw_asset_ids"] = (
            getattr(self._editing, 'sfw_asset_ids', [])
            if self._editing else [])
        data["updated_at"] = now

        if self._editing is not None:
            # Mutates the live post in place - timeline/window hold
            # references to it. Pipeline-owned fields (id, created_at,
            # oneup_post_id, posting_log, ...) are preserved verbatim.
            result_post = apply_post_data(self._editing, data)
        else:
            result_post = apply_post_data(
                SocialPost(id=str(uuid.uuid4()), created_at=now), data)

        # Advisory readiness check
        if status == SocialPostStatus.QUEUED and asset_ids:
            from doxyedit.pipeline import check_readiness
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
        _f = ui_font_size()
        self.setMinimumSize(int(_f * self.DIALOG_MIN_WIDTH_RATIO), int(_f * self.DIALOG_MIN_HEIGHT_RATIO))

        # Restore saved geometry
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        geo = self._settings.value("composer_geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            from doxyedit.themes import themed_dialog_size
            self.resize(*themed_dialog_size(91.67, 62.5))

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
