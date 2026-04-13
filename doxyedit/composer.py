from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QCheckBox, QDateTimeEdit, QFrame,
    QScrollArea, QWidget, QSizePolicy, QGroupBox,
)
from PySide6.QtCore import Qt, QDateTime
from doxyedit.models import Project, SocialPost, SocialPostStatus

SOCIAL_PLATFORMS = [
    "twitter", "instagram", "bluesky", "reddit",
    "patreon", "discord", "tiktok", "pinterest",
]


class PostComposer(QDialog):
    def __init__(self, project: Project, post: SocialPost | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Post" if post else "New Post")
        self.setMinimumSize(500, 600)
        self.resize(600, 700)

        self._project = project
        self._editing = post
        self.result_post: SocialPost | None = None

        self._platform_captions: dict[str, QTextEdit] = {}
        self._platform_checks: dict[str, QCheckBox] = {}

        self._build_ui(post)
        self._prefill(post)

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
        images_layout = QVBoxLayout(images_box)
        self._images_edit = QLineEdit()
        self._images_edit.setPlaceholderText("Comma-separated asset IDs")
        images_layout.addWidget(self._images_edit)
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
                      tomorrow.hour, tomorrow.minute)
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
                    QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
                )
            except (ValueError, TypeError):
                pass

        # Reply templates
        if post.reply_templates:
            self._reply_edit.setPlainText("\n".join(post.reply_templates))

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

    def _save(self, status: str) -> None:
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
                created_at=now,
                updated_at=now,
            )

        self.accept()
