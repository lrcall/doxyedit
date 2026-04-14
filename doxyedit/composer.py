"""composer.py -- Post composer dialog (thin shell).

Two-column layout:
  Left:  ImagePreviewPanel (from composer_left.py)
  Right: ContentPanel (from composer_right.py)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSplitter, QWidget, QSizePolicy, QGroupBox,
)
from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QPixmap

from doxyedit.models import Project, SocialPost, SocialPostStatus
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


class PostComposer(QDialog):
    """Two-column post composer dialog."""

    PREVIEW_THUMB_SIZE = 180

    def __init__(self, project: Project, post: SocialPost | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("post_composer")
        self.setWindowTitle("Edit Post" if post else "New Post")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(900, 600)

        # Restore saved geometry
        self._settings = QSettings("DoxyEdit", "DoxyEdit")
        geo = self._settings.value("composer_geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1100, 750)

        self._project = project
        self._editing = post
        self.result_post: SocialPost | None = None

        self._build_ui()
        self._prefill(post)

    # ------------------------------------------------------------------
    # Geometry persistence
    # ------------------------------------------------------------------

    def _save_geometry(self):
        self._settings.setValue("composer_geometry", self.saveGeometry())
        if hasattr(self, '_composer_split'):
            self._settings.setValue("composer_hsplit", self._composer_split.sizes())
        if hasattr(self, '_right_panel'):
            self._settings.setValue("composer_content_split",
                                    self._right_panel.get_splitter_sizes())

    def closeEvent(self, event):
        self._save_geometry()
        self._right_panel.disconnect_workers()
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

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(8, 8, 8, 8)

        # --- Images row (full width, top) ---
        images_box = QGroupBox("Images")
        images_outer = QVBoxLayout(images_box)
        images_row = QHBoxLayout()
        self._images_edit = AssetDropLineEdit(self._project)
        self._images_edit.setPlaceholderText(
            "Drag from Work Tray or select in Assets tab \u2192 'Use Selected'")
        images_row.addWidget(self._images_edit, 1)
        self._use_selected_btn = QPushButton("Use Selected")
        self._use_selected_btn.setToolTip("Grab currently selected assets from the browser")
        self._use_selected_btn.clicked.connect(self._use_selected_assets)
        images_row.addWidget(self._use_selected_btn)
        images_outer.addLayout(images_row)

        # Thumbnail strip
        self._thumb_strip = QHBoxLayout()
        self._thumb_strip.setSpacing(6)
        self._thumb_strip_container = QWidget()
        self._thumb_strip_container.setLayout(self._thumb_strip)
        self._thumb_strip_container.setVisible(False)
        images_outer.addWidget(self._thumb_strip_container)

        self._images_edit.textChanged.connect(self._update_thumb_preview)
        root.addWidget(images_box)

        # --- Two-column splitter ---
        self._composer_split = QSplitter(Qt.Orientation.Horizontal)
        self._composer_split.setObjectName("composer_hsplit")

        # Left panel — image preview
        self._left_panel = ImagePreviewPanel(self._project)
        self._composer_split.addWidget(self._left_panel)

        # Right panel — content
        self._right_panel = ContentPanel(self._project)
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

        # --- Button bar ---
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
    # Signal handlers
    # ------------------------------------------------------------------

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

        # Left panel NSFW
        if post.nsfw_platforms:
            self._left_panel.set_nsfw_platforms(post.nsfw_platforms)

    # ------------------------------------------------------------------
    # Image preview (thumbs in top row)
    # ------------------------------------------------------------------

    def _update_thumb_preview(self) -> None:
        """Refresh the thumbnail strip when the asset ID list changes."""
        while self._thumb_strip.count():
            item = self._thumb_strip.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        if not ids:
            self._thumb_strip_container.setVisible(False)
            return

        multi = len(ids) > 1
        any_visible = False
        for i, aid in enumerate(ids[:6]):
            cell = QFrame()
            cell.setObjectName("composer_thumb_cell")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)

            asset = self._project.get_asset(aid)
            src_path = asset.source_path if asset else None

            pm = self._load_asset_thumb(aid)
            if pm and not pm.isNull():
                scaled = pm.scaled(
                    QSize(self.PREVIEW_THUMB_SIZE, self.PREVIEW_THUMB_SIZE),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                lbl = QLabel()
                lbl.setPixmap(scaled)
                lbl.setFixedSize(self.PREVIEW_THUMB_SIZE, self.PREVIEW_THUMB_SIZE)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell_layout.addWidget(lbl)
            else:
                lbl = QLabel("?")
                lbl.setFixedSize(self.PREVIEW_THUMB_SIZE, self.PREVIEW_THUMB_SIZE)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setObjectName("timeline_thumb_placeholder")
                cell_layout.addWidget(lbl)

            # Middle-click hover preview
            if src_path:
                lbl._src_path = src_path
                lbl.installEventFilter(self)

            if multi:
                order_lbl = QLabel(f"#{i + 1}" + (" \u2014 hero" if i == 0 else ""))
                order_lbl.setObjectName("composer_thumb_order")
                order_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell_layout.addWidget(order_lbl)

            self._thumb_strip.addWidget(cell)
            any_visible = True

        self._thumb_strip.addStretch()
        self._thumb_strip_container.setVisible(any_visible)

    def _load_asset_thumb(self, asset_id: str) -> QPixmap | None:
        """Load a thumbnail from the asset's source file."""
        asset = self._project.get_asset(asset_id)
        if not asset or not asset.source_path:
            return None
        src = Path(asset.source_path)
        if not src.exists():
            return None
        try:
            ext = src.suffix.lower()
            if ext in (".psd", ".psb"):
                from doxyedit.imaging import load_psd_thumb, pil_to_qpixmap
                result = load_psd_thumb(str(src), min_size=0)
                if result:
                    return pil_to_qpixmap(result[0])
                return None
            pm = QPixmap(str(src))
            return pm if not pm.isNull() else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Image picker
    # ------------------------------------------------------------------

    def _use_selected_assets(self):
        """Grab selected asset IDs from the main window's browser."""
        parent = self.parent()
        if parent and hasattr(parent, 'browser'):
            selected = list(parent.browser._selected_ids)
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
                self._images_edit.setPlaceholderText(", ".join(names))
            else:
                self._images_edit.setPlaceholderText(
                    "No assets selected \u2014 select in Assets tab first")

    # ------------------------------------------------------------------
    # Middle-click hover preview
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.MiddleButton:
                path = getattr(obj, '_src_path', None)
                if path:
                    from doxyedit.preview import HoverPreview
                    from PySide6.QtGui import QCursor
                    HoverPreview.instance().show_for(path, QCursor.pos())
                    return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton:
                from doxyedit.preview import HoverPreview
                HoverPreview.instance().hide_preview()
                return True
        return super().eventFilter(obj, event)

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
            p.updated_at = now
            self.result_post = p
        else:
            self.result_post = SocialPost(
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
                created_at=now,
                updated_at=now,
            )

        self.accept()
