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
from PySide6.QtCore import Qt, QDateTime, QSettings, QSize, QRect
from PySide6.QtGui import QPixmap
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


from PySide6.QtWidgets import QLayout


class _FlowLayout(QLayout):
    """Simple flow layout that wraps widgets like text."""

    def __init__(self, parent=None, hspacing=6, vspacing=4):
        super().__init__(parent)
        self._hspacing = hspacing
        self._vspacing = vspacing
        self._items: list = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize(0, 0)
        for item in self._items:
            s = s.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        s += QSize(m.left() + m.right(), m.top() + m.bottom())
        return s

    def _do_layout(self, rect, test_only=False):
        from PySide6.QtCore import QRect as _QRect
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        row_height = 0

        for item in self._items:
            sz = item.sizeHint()
            next_x = x + sz.width() + self._hspacing
            if next_x - self._hspacing > effective.right() and row_height > 0:
                x = effective.x()
                y += row_height + self._vspacing
                next_x = x + sz.width() + self._hspacing
                row_height = 0
            if not test_only:
                item.setGeometry(_QRect(x, y, sz.width(), sz.height()))
            x = next_x
            row_height = max(row_height, sz.height())

        return y + row_height - rect.y() + m.bottom()


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
        self._local_strategy_cache: str = ""
        self._ai_strategy_cache: str = ""
        self._strategy_view: str = ""  # "local" or "ai"

        self._build_ui(post)
        self._prefill(post)

    def _save_geometry(self):
        self._settings.setValue("composer_geometry", self.saveGeometry())
        if hasattr(self, '_composer_split'):
            self._settings.setValue("composer_split", self._composer_split.sizes())

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
        from PySide6.QtWidgets import QSplitter
        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(8, 8, 8, 8)

        # --- Images ---
        images_box = QGroupBox("Images")
        images_outer = QVBoxLayout(images_box)
        images_row = QHBoxLayout()
        self._images_edit = AssetDropLineEdit(self._project)
        self._images_edit.setPlaceholderText("Drag from Work Tray or select in Assets tab → 'Use Selected'")
        images_row.addWidget(self._images_edit, 1)
        self._use_selected_btn = QPushButton("Use Selected")
        self._use_selected_btn.setToolTip("Grab currently selected assets from the browser")
        self._use_selected_btn.clicked.connect(self._use_selected_assets)
        images_row.addWidget(self._use_selected_btn)
        images_outer.addLayout(images_row)

        # Image preview strip
        self._thumb_strip = QHBoxLayout()
        self._thumb_strip.setSpacing(6)
        self._thumb_strip_container = QWidget()
        self._thumb_strip_container.setLayout(self._thumb_strip)
        self._thumb_strip_container.setVisible(False)
        images_outer.addWidget(self._thumb_strip_container)

        self._images_edit.textChanged.connect(self._update_thumb_preview)
        root.addWidget(images_box)

        # --- Platforms (flow layout — wraps when narrow) ---
        platforms_box = QGroupBox("Platforms")
        platforms_flow = _FlowLayout(platforms_box, hspacing=8, vspacing=4)
        for plat in SOCIAL_PLATFORMS:
            cb = QCheckBox(plat)
            self._platform_checks[plat] = cb
            platforms_flow.addWidget(cb)
        root.addWidget(platforms_box)

        # --- Splitter: strategy (top, draggable) / rest (bottom, scrollable) ---
        self._composer_split = QSplitter(Qt.Orientation.Vertical)
        self._composer_split.setObjectName("post_composer")

        # -- Strategy Notes (resizable via splitter drag) --
        strategy_box = QGroupBox("Strategy Notes")
        strategy_layout = QVBoxLayout(strategy_box)
        strategy_btn_row = QHBoxLayout()
        self._strategy_generate_btn = QPushButton("Generate Strategy")
        self._strategy_generate_btn.setObjectName("strategy_generate_btn")
        self._strategy_generate_btn.setToolTip(
            "Local analysis — tags, posting history, calendar gaps, brand identity")
        self._strategy_generate_btn.clicked.connect(self._generate_local_strategy)
        strategy_btn_row.addWidget(self._strategy_generate_btn)

        self._ai_strategy_btn = QPushButton("AI Strategy")
        self._ai_strategy_btn.setObjectName("strategy_generate_btn")
        self._ai_strategy_btn.setToolTip(
            "Claude analyzes the actual image + full context — real strategic insight")
        self._ai_strategy_btn.clicked.connect(self._generate_ai_strategy)
        strategy_btn_row.addWidget(self._ai_strategy_btn)
        self._apply_strategy_btn = QPushButton("Apply")
        self._apply_strategy_btn.setObjectName("strategy_generate_btn")
        self._apply_strategy_btn.setToolTip(
            "Extract captions, links, schedule, reply templates from strategy into post fields")
        self._apply_strategy_btn.clicked.connect(self._apply_strategy)
        strategy_btn_row.addWidget(self._apply_strategy_btn)

        self._strategy_edit_btn = QPushButton("Edit")
        self._strategy_edit_btn.setObjectName("strategy_generate_btn")
        self._strategy_edit_btn.setCheckable(True)
        self._strategy_edit_btn.setToolTip("Toggle between rendered and raw markdown")
        self._strategy_edit_btn.clicked.connect(self._toggle_strategy_edit)
        strategy_btn_row.addWidget(self._strategy_edit_btn)
        strategy_btn_row.addStretch()
        strategy_layout.addLayout(strategy_btn_row)

        # Stacked: rendered HTML view (default) / raw text edit
        from PySide6.QtWidgets import QStackedWidget, QTextBrowser
        self._strategy_stack = QStackedWidget()

        self._strategy_browser = QTextBrowser()
        self._strategy_browser.setObjectName("strategy_browser")
        self._strategy_browser.setOpenExternalLinks(True)
        self._strategy_browser.setPlaceholderText(
            "Click 'Generate Strategy' or 'AI Strategy' to analyze this post")
        self._strategy_stack.addWidget(self._strategy_browser)  # index 0 = rendered

        self._strategy_edit = QTextEdit()
        self._strategy_edit.setPlaceholderText("Raw markdown — edit here, click Edit again to render")
        self._strategy_stack.addWidget(self._strategy_edit)  # index 1 = raw edit

        self._strategy_raw = ""  # cached raw markdown
        strategy_layout.addWidget(self._strategy_stack, 1)
        self._composer_split.addWidget(strategy_box)

        # -- Scrollable bottom: caption, links, schedule, replies --
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(container)
        self._composer_split.addWidget(scroll_area)

        # Restore splitter sizes
        saved = self._settings.value("composer_split", None)
        if saved:
            self._composer_split.setSizes([int(s) for s in saved])
        else:
            self._composer_split.setSizes([250, 350])
        self._composer_split.setStretchFactor(0, 1)
        self._composer_split.setStretchFactor(1, 1)

        root.addWidget(self._composer_split, 1)

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
            te.setMaximumHeight(100)
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
        sched_row = QHBoxLayout()
        self._schedule_edit = QDateTimeEdit()
        self._schedule_edit.setCalendarPopup(True)
        self._schedule_edit.setDisplayFormat("yyyy-MM-dd hh:mm AP")
        tomorrow = datetime.now() + timedelta(days=1)
        self._schedule_edit.setDateTime(
            QDateTime(tomorrow.year, tomorrow.month, tomorrow.day,
                      tomorrow.hour, tomorrow.minute, 0)
        )
        sched_row.addWidget(self._schedule_edit, 1)
        # World clock — show other timezones
        self._tz_label = QLabel()
        self._tz_label.setObjectName("timeline_caption")
        self._update_tz_display()
        self._schedule_edit.dateTimeChanged.connect(lambda _: self._update_tz_display())
        sched_row.addWidget(self._tz_label)
        schedule_layout.addLayout(sched_row)
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
    # Timezone display
    # ------------------------------------------------------------------

    def _update_tz_display(self):
        """Show the scheduled time in key Western timezones."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            self._tz_label.setText("")
            return
        qt_dt = self._schedule_edit.dateTime()
        py_dt = qt_dt.toPython()
        # Assume the local time is what the user entered (their system TZ)
        local_tz = datetime.now().astimezone().tzinfo
        aware = py_dt.replace(tzinfo=local_tz)
        lines = []
        for tz_name, label in [("US/Eastern", "EST"), ("US/Pacific", "PST"), ("Europe/London", "GMT")]:
            try:
                converted = aware.astimezone(ZoneInfo(tz_name))
                lines.append(f"{label}: {converted.strftime('%I:%M%p %a').lstrip('0')}")
            except Exception:
                pass
        self._tz_label.setText("\n".join(lines))

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

        # Strategy notes — seed both caches so toggle works on reload
        if post.strategy_notes:
            self._set_strategy_text(post.strategy_notes)
            self._ai_strategy_cache = post.strategy_notes
            self._strategy_view = "ai"
            self._update_strategy_btn_labels()

    # ------------------------------------------------------------------
    # Image preview
    # ------------------------------------------------------------------

    PREVIEW_THUMB_SIZE = 180

    def _update_thumb_preview(self) -> None:
        """Refresh the thumbnail strip when the asset ID list changes."""
        # Clear existing thumbnails
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
        for i, aid in enumerate(ids[:6]):  # max 6 previews
            # Wrap each thumb in a frame with optional order number
            cell = QFrame()
            cell.setObjectName("composer_thumb_cell")
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)

            # Resolve source path for middle-click preview
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

            # Middle-click hover preview on thumb
            if src_path:
                lbl._src_path = src_path
                lbl.installEventFilter(self)

            # Order label for multi-image posts
            if multi:
                order_lbl = QLabel(f"#{i + 1}" + (" — hero" if i == 0 else ""))
                order_lbl.setObjectName("composer_thumb_order")
                order_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell_layout.addWidget(order_lbl)

            self._thumb_strip.addWidget(cell)
            any_visible = True

        self._thumb_strip.addStretch()
        self._thumb_strip_container.setVisible(any_visible)

    def _load_asset_thumb(self, asset_id: str) -> "QPixmap | None":
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
    # Middle-click hover preview on thumb labels
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
    # Strategy generation
    # ------------------------------------------------------------------

    def _set_strategy_text(self, text: str) -> None:
        """Set strategy content — renders as HTML in browser, caches raw."""
        self._strategy_raw = text
        self._strategy_edit.setPlainText(text)
        if text:
            import markdown
            html = markdown.markdown(text, extensions=["tables", "fenced_code"])
            # Inject minimal styling that respects the theme
            self._strategy_browser.setHtml(html)
        else:
            self._strategy_browser.setHtml("")
        # Show rendered view
        self._strategy_stack.setCurrentIndex(0)
        self._strategy_edit_btn.setChecked(False)

    def _get_strategy_text(self) -> str:
        """Get the current strategy text (raw markdown).
        Returns whichever view is active (local or AI), including edits."""
        if self._strategy_stack.currentIndex() == 1:
            # Currently editing raw — grab from editor
            self._strategy_raw = self._strategy_edit.toPlainText()
        return self._strategy_raw or self._ai_strategy_cache or self._local_strategy_cache

    def _toggle_strategy_edit(self, checked: bool) -> None:
        """Toggle between rendered HTML and raw markdown edit."""
        if checked:
            # Switch to raw edit
            self._strategy_edit.setPlainText(self._strategy_raw)
            self._strategy_stack.setCurrentIndex(1)
            self._strategy_edit_btn.setText("Done")
        else:
            # Switch back to rendered — save edits first
            self._strategy_raw = self._strategy_edit.toPlainText()
            if self._strategy_raw:
                import markdown
                html = markdown.markdown(self._strategy_raw, extensions=["tables", "fenced_code"])
                self._strategy_browser.setHtml(html)
            else:
                self._strategy_browser.setHtml("")
            self._strategy_stack.setCurrentIndex(0)
            self._strategy_edit_btn.setText("Edit")

    def _build_temp_post(self) -> SocialPost:
        """Build a temporary SocialPost from current form state."""
        asset_ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]
        qt_dt = self._schedule_edit.dateTime()
        py_dt = qt_dt.toPython()
        scheduled_time = py_dt.isoformat() if py_dt else ""
        return SocialPost(
            id=self._editing.id if self._editing else "",
            asset_ids=asset_ids,
            platforms=platforms,
            scheduled_time=scheduled_time,
        )

    def _generate_local_strategy(self) -> None:
        """Local data analysis — show cached or generate fresh."""
        # If we're viewing AI and local cache exists, just switch back
        if self._strategy_view == "ai" and self._local_strategy_cache:
            self._set_strategy_text(self._local_strategy_cache)
            self._strategy_view = "local"
            self._update_strategy_btn_labels()
            return

        from doxyedit.strategy import generate_strategy_briefing
        briefing = generate_strategy_briefing(self._project, self._build_temp_post())
        self._local_strategy_cache = briefing
        self._set_strategy_text(briefing)
        self._strategy_view = "local"
        self._update_strategy_btn_labels()

    def _generate_ai_strategy(self) -> None:
        """Show cached AI strategy or generate new one."""
        # If we're viewing local and AI cache exists, just switch
        if self._strategy_view != "ai" and self._ai_strategy_cache:
            self._set_strategy_text(self._ai_strategy_cache)
            self._strategy_view = "ai"
            self._update_strategy_btn_labels()
            return

        from doxyedit.strategy import generate_ai_strategy
        from PySide6.QtCore import QThread, Signal as _Signal

        # Save current text as local cache if we haven't yet
        current = self._get_strategy_text()
        if current and not self._local_strategy_cache:
            self._local_strategy_cache = current

        temp_post = self._build_temp_post()

        # Show loading state (keep existing content visible with append indicator)
        existing = self._ai_strategy_cache
        if existing:
            self._set_strategy_text(existing + "\n\n---\n\n*Generating follow-up...*")
        else:
            self._set_strategy_text("*Analyzing with Claude... 30-60 seconds.*")
        self._ai_strategy_btn.setEnabled(False)
        self._ai_strategy_btn.setText("Generating...")

        class _Worker(QThread):
            finished = _Signal(str)

            def __init__(self, project, post):
                super().__init__()
                self._project = project
                self._post = post

            def run(self):
                result = generate_ai_strategy(self._project, self._post)
                self.finished.emit(result)

        self._strategy_worker = _Worker(self._project, temp_post)
        self._strategy_worker.finished.connect(self._on_ai_strategy_done)
        self._strategy_worker.start()

    def _on_ai_strategy_done(self, result: str) -> None:
        """Handle completed AI strategy generation. Appends to existing."""
        if self._ai_strategy_cache:
            # Append new response below previous with separator
            self._ai_strategy_cache += f"\n\n---\n\n**Follow-up:**\n\n{result}"
        else:
            self._ai_strategy_cache = result
        self._set_strategy_text(self._ai_strategy_cache)
        self._strategy_view = "ai"
        self._ai_strategy_btn.setEnabled(True)
        self._update_strategy_btn_labels()

    def _update_strategy_btn_labels(self) -> None:
        """Update button text to show which view is active."""
        if self._strategy_view == "local":
            self._strategy_generate_btn.setText("Local Strategy ●")
            self._ai_strategy_btn.setText(
                "View AI Strategy" if self._ai_strategy_cache else "AI Strategy"
            )
        elif self._strategy_view == "ai":
            self._strategy_generate_btn.setText(
                "View Local Strategy" if self._local_strategy_cache else "Generate Strategy"
            )
            self._ai_strategy_btn.setText("AI Strategy ●")
        else:
            self._strategy_generate_btn.setText("Generate Strategy")
            self._ai_strategy_btn.setText("AI Strategy")

    # ------------------------------------------------------------------
    # Apply strategy suggestions to post fields
    # ------------------------------------------------------------------

    def _apply_strategy(self) -> None:
        """Extract actionable fields from strategy and apply to post."""
        strategy = self._get_strategy_text()
        if not strategy or strategy.startswith("*Analyzing"):
            return

        from PySide6.QtCore import QThread, Signal as _Signal

        platforms = [p for p, cb in self._platform_checks.items() if cb.isChecked()]

        prompt = f"""Extract actionable post data from this strategy briefing. Return ONLY valid JSON, no markdown fences, no explanation.

Strategy text:
{strategy}

Current platforms selected: {', '.join(platforms) if platforms else 'none'}

Return this exact JSON structure. Only include fields that the strategy explicitly suggests. Omit fields with no clear suggestion:

{{
  "caption_default": "the best general caption from the strategy, ready to copy-paste",
  "captions": {{
    "twitter": "twitter-specific caption if suggested",
    "instagram": "instagram-specific caption if suggested"
  }},
  "links": ["any URLs mentioned"],
  "schedule_suggestion": "YYYY-MM-DD HH:MM if a different time was recommended, or empty",
  "reply_templates": ["suggested replies or CTAs, one per line"],
  "platforms_add": ["platforms the strategy recommends adding"],
  "platforms_remove": ["platforms the strategy recommends removing"]
}}

RULES:
- Only extract what's actually in the strategy. Don't invent.
- Captions must be exact copy-paste ready text, not summaries.
- If the strategy says the current schedule is fine, leave schedule_suggestion empty.
- No em dashes in any text."""

        self._apply_strategy_btn.setEnabled(False)
        self._apply_strategy_btn.setText("Applying...")

        class _Worker(QThread):
            finished = _Signal(str)
            def __init__(self, p):
                super().__init__()
                self._prompt = p
            def run(self):
                import subprocess, sys
                try:
                    print("[Apply Strategy] Calling Claude to extract fields...", file=sys.stderr, flush=True)
                    result = subprocess.run(
                        ["claude", "-p", self._prompt],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=60,
                    )
                    self.finished.emit(result.stdout.strip() if result.returncode == 0 else "")
                except Exception as e:
                    print(f"[Apply Strategy] Error: {e}", file=sys.stderr, flush=True)
                    self.finished.emit("")

        self._apply_worker = _Worker(prompt)
        self._apply_worker.finished.connect(self._on_apply_done)
        self._apply_worker.start()

    def _on_apply_done(self, raw: str) -> None:
        """Parse extracted JSON and fill post fields."""
        import sys
        self._apply_strategy_btn.setEnabled(True)
        self._apply_strategy_btn.setText("Apply")

        if not raw:
            print("[Apply Strategy] No response from Claude", file=sys.stderr, flush=True)
            return

        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            import json
            data = json.loads(text)
        except Exception as e:
            print(f"[Apply Strategy] JSON parse error: {e}", file=sys.stderr, flush=True)
            print(f"[Apply Strategy] Raw: {text[:200]}", file=sys.stderr, flush=True)
            return

        print(f"[Apply Strategy] Extracted: {list(data.keys())}", file=sys.stderr, flush=True)

        # Apply caption
        cap = data.get("caption_default", "")
        if cap and not self._caption_edit.toPlainText().strip():
            self._caption_edit.setPlainText(cap)
        elif cap:
            # Don't overwrite existing caption, append as suggestion
            existing = self._caption_edit.toPlainText()
            self._caption_edit.setPlainText(existing + "\n\n--- AI suggestion ---\n" + cap)

        # Apply per-platform captions
        captions = data.get("captions", {})
        for plat, text in captions.items():
            if plat in self._platform_captions and text:
                te = self._platform_captions[plat]
                if not te.toPlainText().strip():
                    te.setPlainText(text)
                # Show per-platform section
                if not self._per_platform_toggle.isChecked():
                    self._per_platform_toggle.setChecked(True)
                    self._toggle_per_platform(True)

        # Apply links
        links = data.get("links", [])
        if links and not self._links_edit.text().strip():
            self._links_edit.setText(links[0])

        # Apply schedule suggestion
        sched = data.get("schedule_suggestion", "")
        if sched:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(sched)
                self._schedule_edit.setDateTime(
                    QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0)
                )
            except Exception:
                pass

        # Apply reply templates
        replies = data.get("reply_templates", [])
        if replies:
            existing = self._reply_edit.toPlainText()
            new_replies = "\n".join(replies)
            if existing.strip():
                self._reply_edit.setPlainText(existing + "\n" + new_replies)
            else:
                self._reply_edit.setPlainText(new_replies)

        # Apply platform changes
        for plat in data.get("platforms_add", []):
            if plat in self._platform_checks:
                self._platform_checks[plat].setChecked(True)
        for plat in data.get("platforms_remove", []):
            if plat in self._platform_checks:
                self._platform_checks[plat].setChecked(False)

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
        strategy_notes = self._get_strategy_text()

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
