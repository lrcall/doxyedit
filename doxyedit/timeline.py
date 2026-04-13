"""timeline.py — Scrollable post feed grouped by day with gap markers."""

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QPixmap

from doxyedit.models import Project, SocialPost, SocialPostStatus


# Status icon map
_STATUS_ICONS = {
    "draft":   "○",
    "queued":  "◷",
    "posted":  "✓",
    "failed":  "✗",
    "partial": "◑",
}


class PlatformBadge(QLabel):
    """Small pill showing a platform name."""

    def __init__(self, platform: str, parent=None):
        super().__init__(platform, parent)
        self.setObjectName("platform_badge")


class StatusBadge(QLabel):
    """Post status label with icon, styled via QSS property selector."""

    def __init__(self, status: str, parent=None):
        # Normalize: enum value or raw string → plain lowercase
        status_str = status.value if hasattr(status, 'value') else str(status)
        icon = _STATUS_ICONS.get(status_str, _STATUS_ICONS.get(status, "○"))
        super().__init__(f"{icon} {status_str}", parent)
        self.setObjectName("post_status_badge")
        self.setProperty("status", status_str)


THUMB_SIZE = 64


class PostCard(QFrame):
    """Single post card in the timeline feed."""

    clicked = Signal(str)  # emits post_id

    def __init__(self, post: SocialPost, project: "Project | None" = None,
                 thumb_cache=None, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_post_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._post_id = post.id

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(8)

        # Thumbnails (left side)
        if post.asset_ids and project:
            thumb_col = QHBoxLayout()
            thumb_col.setSpacing(4)
            for aid in post.asset_ids[:4]:  # max 4 thumbs
                pm = None
                # Try thumb cache first
                if thumb_cache:
                    pm = thumb_cache.get(aid)
                # Fallback: load directly from source file
                if (not pm or pm.isNull()) and project:
                    pm = self._load_thumb_direct(aid, project)
                if pm and not pm.isNull():
                    scaled = pm.scaled(QSize(THUMB_SIZE, THUMB_SIZE),
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                    lbl = QLabel()
                    lbl.setPixmap(scaled)
                    lbl.setFixedSize(THUMB_SIZE, THUMB_SIZE)
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    thumb_col.addWidget(lbl)
                else:
                    # Placeholder
                    lbl = QLabel("?")
                    lbl.setFixedSize(THUMB_SIZE, THUMB_SIZE)
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    lbl.setObjectName("timeline_thumb_placeholder")
                    thumb_col.addWidget(lbl)
            outer.addLayout(thumb_col)

        # Right side: text info
        info = QVBoxLayout()
        info.setSpacing(2)

        # Row 1: asset names (bold) + status badge + time
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        asset_names = self._resolve_names(post, project)
        name_label = QLabel(", ".join(asset_names) if asset_names else "(no assets)")
        name_label.setStyleSheet("font-weight: bold;")
        row1.addWidget(name_label, 1)

        status_badge = StatusBadge(post.status)
        row1.addWidget(status_badge)

        time_str = post.scheduled_time[11:16] if len(post.scheduled_time) > 10 else ""
        if time_str:
            time_label = QLabel(time_str)
            row1.addWidget(time_label)

        info.addLayout(row1)

        # Row 2: platform badges
        if post.platforms:
            row2 = QHBoxLayout()
            row2.setSpacing(4)
            for plat in post.platforms:
                row2.addWidget(PlatformBadge(plat))
            row2.addStretch()
            info.addLayout(row2)

        # Row 3: caption preview (italic, max 80 chars)
        caption = post.caption_default or next(iter(post.captions.values()), "")
        if caption:
            preview = caption[:80] + ("..." if len(caption) > 80 else "")
            cap_label = QLabel(preview)
            cap_label.setObjectName("timeline_caption")
            font = cap_label.font()
            font.setItalic(True)
            cap_label.setFont(font)
            info.addWidget(cap_label)

        # Row 4: links
        if post.links:
            links_label = QLabel("  ".join(post.links))
            links_label.setObjectName("timeline_links")
            info.addWidget(links_label)

        outer.addLayout(info, 1)

    @staticmethod
    def _load_thumb_direct(asset_id: str, project) -> "QPixmap | None":
        """Load a thumbnail directly from the asset's source file."""
        asset = project.get_asset(asset_id)
        if not asset or not asset.source_path:
            return None
        src = Path(asset.source_path)
        if not src.exists():
            return None
        try:
            ext = src.suffix.lower()
            if ext in (".psd", ".psb"):
                from doxyedit.imaging import load_psd_thumb
                result = load_psd_thumb(str(src), min_size=0)
                if result:
                    from doxyedit.imaging import pil_to_qpixmap
                    return pil_to_qpixmap(result[0])
                return None
            pm = QPixmap(str(src))
            if pm.isNull():
                return None
            return pm
        except Exception:
            return None

    @staticmethod
    def _resolve_names(post: SocialPost, project: "Project | None") -> list[str]:
        names = []
        for aid in post.asset_ids:
            if project:
                asset = project.get_asset(aid)
                if asset and asset.source_path:
                    names.append(Path(asset.source_path).stem)
                    continue
            # Fallback: use raw id
            names.append(aid)
        return names

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._post_id)
        super().mousePressEvent(event)


class GapMarker(QFrame):
    """Dashed warning shown for days with no posts scheduled."""

    fill_requested = Signal(str)  # date string

    def __init__(self, date_str: str, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_gap")
        self._date_str = date_str

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        label = QLabel(f"⚠ {date_str} — no posts scheduled")
        layout.addWidget(label, 1)

        fill_btn = QPushButton("Fill")
        fill_btn.setObjectName("timeline_gap_fill_btn")
        fill_btn.clicked.connect(lambda: self.fill_requested.emit(self._date_str))
        layout.addWidget(fill_btn)


class TimelineStream(QWidget):
    """Scrollable post feed grouped by day with gap markers."""

    post_selected = Signal(str)
    new_post_requested = Signal()
    sync_requested = Signal()
    fill_gaps_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_stream")
        self._project: "Project | None" = None
        self._thumb_cache = None

        # ---- Outer layout ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ---- Toolbar ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._btn_new = QPushButton("+ New Post")
        self._btn_new.setObjectName("timeline_btn_new")
        self._btn_new.clicked.connect(lambda: self.new_post_requested.emit())
        toolbar.addWidget(self._btn_new)

        self._btn_sync = QPushButton("Sync OneUp")
        self._btn_sync.setObjectName("timeline_btn_sync")
        self._btn_sync.clicked.connect(lambda: self.sync_requested.emit())
        toolbar.addWidget(self._btn_sync)

        self._btn_fill = QPushButton("Fill Gaps")
        self._btn_fill.setObjectName("timeline_btn_fill")
        self._btn_fill.clicked.connect(lambda: self.fill_gaps_requested.emit())
        toolbar.addWidget(self._btn_fill)

        toolbar.addStretch()

        self._filter_combo = QComboBox()
        self._filter_combo.setObjectName("timeline_filter_combo")
        self._filter_combo.addItems(["All", "Drafts", "Queued", "Posted", "Failed"])
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_combo)

        outer.addLayout(toolbar)

        # ---- Summary label ----
        self._summary_label = QLabel("")
        self._summary_label.setObjectName("timeline_summary")
        outer.addWidget(self._summary_label)

        # ---- Scroll area ----
        self._scroll = QScrollArea()
        self._scroll.setObjectName("timeline_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._content.setObjectName("timeline_content")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(4)
        self._content_layout.addStretch()  # trailing stretch always at end

        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_thumb_cache(self, cache):
        self._thumb_cache = cache

    def set_project(self, project: "Project") -> None:
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        self._clear_content()

        if not self._project:
            self._summary_label.setText("No project loaded")
            return

        posts = list(self._project.posts)

        # Apply status filter
        filter_text = self._filter_combo.currentText()
        if filter_text != "All":
            # "Drafts" → "draft", "Queued" → "queued", etc.
            target_status = filter_text.rstrip("s").lower()
            posts = [p for p in posts if p.status == target_status]

        # Sort by scheduled_time (empty times sort to end)
        posts.sort(key=lambda p: p.scheduled_time or "9999")

        # Partition: scheduled vs unscheduled
        scheduled = [p for p in posts if p.scheduled_time]
        unscheduled = [p for p in posts if not p.scheduled_time]

        # Group scheduled posts by day
        by_day: dict[str, list[SocialPost]] = {}
        for p in scheduled:
            day = p.scheduled_time[:10]
            by_day.setdefault(day, []).append(p)

        # Summary counts (always over all posts, not filtered)
        all_posts = self._project.posts
        n_queued = sum(1 for p in all_posts if p.status == SocialPostStatus.QUEUED)
        n_posted = sum(1 for p in all_posts if p.status == SocialPostStatus.POSTED)

        # Count gaps in the 14-day window
        today = datetime.now().date()
        idx = 0  # insertion index (before trailing stretch)
        gap_count = 0

        for i in range(14):
            day = today + timedelta(days=i)
            day_str = day.isoformat()

            if day_str in by_day:
                # Day header
                header = self._make_day_header(day, today)
                self._content_layout.insertWidget(idx, header)
                idx += 1
                for post in by_day[day_str]:
                    card = PostCard(post, self._project, self._thumb_cache)
                    card.clicked.connect(self.post_selected)
                    self._content_layout.insertWidget(idx, card)
                    idx += 1
            else:
                # Gap marker
                gap = GapMarker(day_str)
                gap.fill_requested.connect(lambda d: self.fill_gaps_requested.emit())
                self._content_layout.insertWidget(idx, gap)
                idx += 1
                gap_count += 1

        # Posts scheduled beyond the 14-day window
        cutoff = (today + timedelta(days=14)).isoformat()
        future_posts = [p for p in scheduled if p.scheduled_time[:10] >= cutoff]
        if future_posts:
            future_by_day: dict[str, list[SocialPost]] = {}
            for p in future_posts:
                d = p.scheduled_time[:10]
                future_by_day.setdefault(d, []).append(p)
            for day_str in sorted(future_by_day):
                day = datetime.fromisoformat(day_str).date()
                header = self._make_day_header(day, today)
                self._content_layout.insertWidget(idx, header)
                idx += 1
                for post in future_by_day[day_str]:
                    card = PostCard(post, self._project, self._thumb_cache)
                    card.clicked.connect(self.post_selected)
                    self._content_layout.insertWidget(idx, card)
                    idx += 1

        # Unscheduled posts at end
        if unscheduled:
            unsched_header = QLabel("Unscheduled")
            unsched_header.setObjectName("timeline_day_header")
            self._content_layout.insertWidget(idx, unsched_header)
            idx += 1
            for post in unscheduled:
                card = PostCard(post, self._project, self._thumb_cache)
                card.clicked.connect(self.post_selected)
                self._content_layout.insertWidget(idx, card)
                idx += 1

        total = len(posts)
        self._summary_label.setText(
            f"{total} posts · {n_queued} queued · {n_posted} posted · {gap_count} gaps"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_content(self) -> None:
        """Remove all widgets from content layout except the trailing stretch."""
        layout = self._content_layout
        # Remove all items except the last (stretch)
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _make_day_header(day, today) -> QLabel:
        delta = (day - today).days
        if delta == 0:
            text = f"Today — {day.strftime('%A, %B %d')}"
        elif delta == 1:
            text = f"Tomorrow — {day.strftime('%A, %B %d')}"
        else:
            text = day.strftime("%A, %B %d")
        label = QLabel(text)
        label.setObjectName("timeline_day_header")
        return label

    def _on_filter_changed(self, _text: str) -> None:
        self.refresh()
