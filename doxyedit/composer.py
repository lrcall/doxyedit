from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QCheckBox, QDateTimeEdit, QFrame,
    QScrollArea, QWidget, QSizePolicy, QGroupBox,
)
from PySide6.QtCore import Qt, QDateTime, QSettings
from doxyedit.models import Project, SocialPost, SocialPostStatus

class AssetDropLineEdit(QLineEdit):
    """QLineEdit that accepts file drops and resolves to asset IDs."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._project = project
        self._path_index: dict[str, str] = {}  # normalized path → asset id
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


SOCIAL_PLATFORMS = [
    "twitter", "instagram", "bluesky", "reddit",
    "patreon", "discord", "tiktok", "pinterest",
]


class PostComposer(QDialog):
    def __init__(self, project: Project, post: SocialPost | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("post_composer")
        self.setWindowTitle("Edit Post" if post else "New Post")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(500, 600)

        # Restore saved geometry
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        geo = self._settings.value("composer_geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(600, 700)

        self._project = project
        self._editing = post
        self.result_post: SocialPost | None = None

        self._platform_captions: dict[str, QTextEdit] = {}
        self._platform_checks: dict[str, QCheckBox] = {}

        self._build_ui(post)
        self._prefill(post)

    def _save_geometry(self):
        self._settings.setValue("composer_geometry", self.saveGeometry())

    def closeEvent(self, event):
        self._save_geometry()
        super().closeEvent(event)

    def accept(self):
        self._save_geometry()
        super().accept()

    def reject(self):
        self._save_geometry()
        super().reject()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self, post: SocialPost | None) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(container)
        root.addWidget(scroll_area)

        # --- Images ---
        images_box = QGroupBox("Images")
        images_layout = QHBoxLayout(images_box)
        self._images_edit = AssetDropLineEdit(self._project)
        self._images_edit.setPlaceholderText("Drag from Work Tray or select in Assets tab → 'Use Selected'")
        images_layout.addWidget(self._images_edit, 1)
        self._use_selected_btn = QPushButton("Use Selected")
        self._use_selected_btn.setToolTip("Grab currently selected assets from the browser")
        self._use_selected_btn.clicked.connect(self._use_selected_assets)
        images_layout.addWidget(self._use_selected_btn)
        layout.addWidget(images_box)

        # --- Platforms ---
        platforms_box = QGroupBox("Platforms")
        platforms_layout = QHBoxLayout(platforms_box)
        platforms_layout.setSpacing(6)
        for plat in SOCIAL_PLATFORMS:
            cb = QCheckBox(plat)
            self._platform_checks[plat] = cb
            platforms_layout.addWidget(cb)
        platforms_layout.addStretch()
        layout.addWidget(platforms_box)

        # --- Caption ---
        caption_box = QGroupBox("Caption")
        caption_layout = QVBoxLayout(caption_box)
        self._caption_edit = QTextEdit()
        self._caption_edit.setMaximumHeight(120)
        self._caption_edit.setPlaceholderText("Default caption for all platforms")
        caption_layout.addWidget(self._caption_edit)

        self._per_platform_toggle = QPushButton("Per-platform captions \u25bc")
        self._per_platform_toggle.setCheckable(True)
        self._per_platform_toggle.setChecked(False)
        self._per_platform_toggle.clicked.connect(self._toggle_per_platform)
        caption_layout.addWidget(self._per_platform_toggle)

        self._per_platform_container = QWidget()
        pp_layout = QVBoxLayout(self._per_platform_container)
        pp_layout.setSpacing(4)
        pp_layout.setContentsMargins(0, 0, 0, 0)
        for plat in SOCIAL_PLATFORMS:
            lbl = QLabel(plat)
            lbl.setStyleSheet("font-weight: bold;")
            te = QTextEdit()
            te.setMaximumHeight(60)
            te.setPlaceholderText(f"Caption for {plat} (leave blank to use default)")
            self._platform_captions[plat] = te
            pp_layout.addWidget(lbl)
            pp_layout.addWidget(te)

        self._per_platform_container.setVisible(False)
        caption_layout.addWidget(self._per_platform_container)
        layout.addWidget(caption_box)

        # --- Links ---
        links_box = QGroupBox("Links")
        links_layout = QVBoxLayout(links_box)
        self._links_edit = QLineEdit()
        self._links_edit.setPlaceholderText("URL")
        links_layout.addWidget(self._links_edit)
        layout.addWidget(links_box)

        # --- Schedule ---
        schedule_box = QGroupBox("Schedule")
        schedule_layout = QVBoxLayout(schedule_box)
        self._schedule_edit = QDateTimeEdit()
        self._schedule_edit.setCalendarPopup(True)
        self._schedule_edit.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        tomorrow = datetime.now() + timedelta(days=1)
        self._schedule_edit.setDateTime(
            QDateTime(tomorrow.year, tomorrow.month, tomorrow.day,
                      tomorrow.hour, tomorrow.minute, 0)
        )
        schedule_layout.addWidget(self._schedule_edit)
        layout.addWidget(schedule_box)

        # --- Reply Templates ---
        reply_box = QGroupBox("Reply Templates")
        reply_layout = QVBoxLayout(reply_box)
        self._reply_edit = QTextEdit()
        self._reply_edit.setMaximumHeight(80)
        self._reply_edit.setPlaceholderText("One reply per line")
        reply_layout.addWidget(self._reply_edit)
        layout.addWidget(reply_box)

        # --- AI Strategy Notes ---
        strategy_box = QGroupBox("Strategy Notes")
        strategy_layout = QVBoxLayout(strategy_box)
        self._strategy_edit = QTextEdit()
        self._strategy_edit.setPlaceholderText(
            "Claude fills this in — posting strategy, best times, hashtags, "
            "platform-specific advice, engagement tips, long-term vision notes")
        strategy_layout.addWidget(self._strategy_edit)
        layout.addWidget(strategy_box)

        layout.addStretch()

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_draft = QPushButton("Save Draft")
        btn_draft.clicked.connect(lambda: self._save(SocialPostStatus.DRAFT))
        btn_queue = QPushButton("Queue to OneUp")
        btn_queue.clicked.connect(lambda: self._save(SocialPostStatus.QUEUED))
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_draft)
        btn_layout.addWidget(btn_queue)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        root.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Pre-fill from existing post or project defaults
    # ------------------------------------------------------------------

    def _prefill(self, post: SocialPost | None) -> None:
        if post is None:
            # Default platform selection from project identity
            try:
                identity = self._project.get_identity()
                defaults = identity.default_platforms if identity else []
            except Exception:
                defaults = []
            for plat, cb in self._platform_checks.items():
                cb.setChecked(plat in defaults)
            return

        # Images
        self._images_edit.setText(", ".join(post.asset_ids))

        # Platforms
        for plat, cb in self._platform_checks.items():
            cb.setChecked(plat in post.platforms)

        # Captions
        self._caption_edit.setPlainText(post.caption_default)
        has_per_platform = bool(post.captions)
        if has_per_platform:
            self._per_platform_toggle.setChecked(True)
            self._per_platform_container.setVisible(True)
            self._per_platform_toggle.setText("Per-platform captions \u25b2")
        for plat, te in self._platform_captions.items():
            te.setPlainText(post.captions.get(plat, ""))

        # Links
        if post.links:
            self._links_edit.setText(post.links[0])

        # Schedule
        if post.scheduled_time:
            try:
                dt = datetime.fromisoformat(post.scheduled_time)
                self._schedule_edit.setDateTime(
                    QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0)
                )
            except (ValueError, TypeError):
                pass

        # Reply templates
        if post.reply_templates:
            self._reply_edit.setPlainText("\n".join(post.reply_templates))

        # Strategy notes
        if post.strategy_notes:
            self._strategy_edit.setPlainText(post.strategy_notes)

    # ------------------------------------------------------------------
    # Image picker
    # ------------------------------------------------------------------

    def _use_selected_assets(self):
        """Grab selected asset IDs from the main window's browser."""
        parent = self.parent()
        if parent and hasattr(parent, 'browser'):
            selected = list(parent.browser._selected_ids)
            if selected:
                # Show filenames instead of raw IDs for readability
                names = []
                for aid in selected:
                    asset = self._project.get_asset(aid)
                    if asset:
                        names.append(Path(asset.source_path).stem)
                    else:
                        names.append(aid)
                self._images_edit.setText(", ".join(selected))
                self._images_edit.setToolTip("Selected: " + ", ".join(names))
                self._images_edit.setPlaceholderText(", ".join(names))
            else:
                self._images_edit.setPlaceholderText("No assets selected — select in Assets tab first")

    # ------------------------------------------------------------------
    # Toggle per-platform captions
    # ------------------------------------------------------------------

    def _toggle_per_platform(self, checked: bool) -> None:
        self._per_platform_container.setVisible(checked)
        self._per_platform_toggle.setText(
            "Per-platform captions \u25b2" if checked else "Per-platform captions \u25bc"
        )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self, status) -> None:
        # Normalize enum to string value
        status = status.value if hasattr(status, 'value') else str(status)
        now = datetime.now().isoformat()

        # Gather fields
        asset_ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]
        caption_default = self._caption_edit.toPlainText()
        captions = {
            plat: te.toPlainText()
            for plat, te in self._platform_captions.items()
            if te.toPlainText()
        }
        link = self._links_edit.text().strip()
        links = [link] if link else []

        qt_dt = self._schedule_edit.dateTime()
        py_dt = qt_dt.toPython()
        scheduled_time = py_dt.isoformat() if py_dt else ""

        reply_text = self._reply_edit.toPlainText()
        reply_templates = [line for line in reply_text.splitlines() if line.strip()]
        strategy_notes = self._strategy_edit.toPlainText()

        if self._editing is not None:
            # Update in place
            p = self._editing
            p.asset_ids = asset_ids
            p.platforms = platforms
            p.caption_default = caption_default
            p.captions = captions
            p.links = links
            p.scheduled_time = scheduled_time
            p.status = status
            p.reply_templates = reply_templates
            p.strategy_notes = strategy_notes
            p.updated_at = now
            self.result_post = p
        else:
            self.result_post = SocialPost(
                id=str(uuid.uuid4()),
                asset_ids=asset_ids,
                platforms=platforms,
                caption_default=caption_default,
                captions=captions,
                links=links,
                scheduled_time=scheduled_time,
                status=status,
                reply_templates=reply_templates,
                strategy_notes=strategy_notes,
                created_at=now,
                updated_at=now,
            )

        self.accept()
