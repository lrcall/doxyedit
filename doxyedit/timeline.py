"""timeline.py — Scrollable post feed grouped by day with gap markers."""

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QPixmap

from doxyedit.models import Project, SocialPost, SocialPostStatus, EngagementWindow


def _resolve_chrome_profile(project, collection: str, account_id: str) -> str:
    """Look up the Chrome profile for an account from the identity config."""
    if not project or not collection:
        return "Default"
    identity = project.identities.get(collection, {})
    return identity.get("chrome_profiles", {}).get(account_id, "Default")


def _open_with_profile(url: str, profile_dir: str = "Default"):
    """Open a URL with a Chrome profile, falling back to webbrowser."""
    from doxyedit.composer_right import open_chrome_with_profile
    open_chrome_with_profile(url, profile_dir)


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
    """Post status label with icon, styled via distinct objectName per status."""

    def __init__(self, status: str, parent=None):
        status_str = status.value if hasattr(status, 'value') else str(status)
        icon = _STATUS_ICONS.get(status_str, _STATUS_ICONS.get(status, "○"))
        super().__init__(f"{icon} {status_str}", parent)
        self.setObjectName(f"post_badge_{status_str}")


THUMB_SIZE = 64


class PostCard(QFrame):
    """Single post card in the timeline feed."""

    clicked = Signal(str)  # emits post_id
    engagement_changed = Signal()  # emitted when done/snooze clicked

    def __init__(self, post: SocialPost, project: "Project | None" = None,
                 thumb_cache=None, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_post_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._post_id = post.id
        self._post = post
        self._asset_ids = post.asset_ids
        self._project = project

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        outer = QHBoxLayout()
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(8)
        root.addLayout(outer)

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
        name_label.setObjectName("timeline_asset_name")
        row1.addWidget(name_label, 1)

        status_badge = StatusBadge(post.status)
        row1.addWidget(status_badge)

        time_str = post.scheduled_time[11:16] if len(post.scheduled_time) > 10 else ""
        if time_str:
            tz_parts = [time_str]
            try:
                from datetime import datetime as _dt
                from zoneinfo import ZoneInfo
                local_dt = _dt.fromisoformat(post.scheduled_time)
                local_tz = _dt.now().astimezone().tzinfo
                aware = local_dt.replace(tzinfo=local_tz)
                for tz_name, tz_label in [("US/Eastern", "EST"), ("US/Pacific", "PST"), ("Asia/Tokyo", "JST")]:
                    conv = aware.astimezone(ZoneInfo(tz_name))
                    tz_parts.append(f"{tz_label} {conv.strftime('%H:%M')}")
            except Exception:
                pass
            time_label = QLabel("  ".join(tz_parts))
            time_label.setObjectName("post_time_label")
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

        # Inline engagement checks (collapsible, styled like original panel)
        if hasattr(post, 'engagement_checks') and post.engagement_checks:
            now = datetime.now()
            pending = []
            for i, check_dict in enumerate(post.engagement_checks):
                check = EngagementWindow.from_dict(check_dict)
                if check.done:
                    continue
                try:
                    check_time = datetime.fromisoformat(check.check_at)
                except (ValueError, TypeError):
                    continue
                mins = (check_time - now).total_seconds() / 60
                if mins <= 60:
                    pending.append((i, check, mins))

            if pending:
                pending.sort(key=lambda x: x[2])

                eng_container = QFrame()
                eng_container.setObjectName("engagement_panel")
                eng_layout = QVBoxLayout(eng_container)
                eng_layout.setContentsMargins(6, 4, 6, 4)
                eng_layout.setSpacing(3)
                eng_container.setVisible(False)

                for idx, check, mins in pending:
                    row = QFrame()
                    row.setObjectName("engagement_row")
                    row_lay = QHBoxLayout(row)
                    row_lay.setContentsMargins(4, 2, 4, 2)
                    row_lay.setSpacing(6)

                    icon = "!!" if mins < 0 else ("!" if mins < 5 else "~")
                    icon_lbl = QLabel(icon)
                    icon_lbl.setFixedWidth(20)
                    row_lay.addWidget(icon_lbl)

                    desc = QLabel(f"{check.platform} — {check.notes}")
                    desc.setWordWrap(True)
                    row_lay.addWidget(desc, 1)

                    if check.url:
                        _open = QPushButton("Open")
                        _open.setObjectName("engagement_open_btn")
                        _prof = _resolve_chrome_profile(self._project, post.collection, check.account_id)
                        _open.clicked.connect(lambda _=False, u=check.url, p=_prof: _open_with_profile(u, p))
                        row_lay.addWidget(_open)

                    # Capture the check dict directly (not index) to avoid stale refs
                    _check_dict = post.engagement_checks[idx]

                    _done = QPushButton("Done")
                    _done.setObjectName("engagement_done_btn")
                    _done.clicked.connect(lambda _=False, cd=_check_dict, r=row: self._eng_done_direct(cd, r))
                    row_lay.addWidget(_done)

                    _snz = QPushButton("Snooze")
                    _snz.setObjectName("engagement_snooze_btn")
                    _snz.clicked.connect(lambda _=False, cd=_check_dict: self._eng_snooze_direct(cd))
                    row_lay.addWidget(_snz)

                    eng_layout.addWidget(row)

                toggle = QPushButton(f"Engagement ({len(pending)}) \u25bc")
                toggle.setObjectName("engagement_toggle_btn")
                toggle.setCheckable(True)
                toggle.setChecked(False)
                toggle.clicked.connect(lambda c: (
                    eng_container.setVisible(c),
                    toggle.setText(f"Engagement ({len(pending)}) \u25b2" if c
                                   else f"Engagement ({len(pending)}) \u25bc"),
                ))
                root.addWidget(toggle)
                root.addWidget(eng_container)

    def _eng_done_direct(self, check_dict: dict, row_widget):
        """Mark engagement check as done via direct dict reference."""
        check_dict["done"] = True
        try:
            row_widget.deleteLater()
        except RuntimeError:
            pass
        self.engagement_changed.emit()

    def _eng_snooze_direct(self, check_dict: dict):
        """Snooze engagement check by 30 minutes via direct dict reference."""
        try:
            old = datetime.fromisoformat(check_dict.get("check_at", ""))
            check_dict["check_at"] = (old + timedelta(minutes=30)).isoformat()
        except (ValueError, TypeError, KeyError):
            pass
        self.engagement_changed.emit()

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
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._show_hover_preview()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            from doxyedit.preview import HoverPreview
            HoverPreview.instance().hide_preview()
        super().mouseReleaseEvent(event)

    def _show_hover_preview(self):
        """Show hover preview of the first asset on middle-click."""
        if not self._asset_ids:
            return
        from doxyedit.preview import HoverPreview
        from PySide6.QtGui import QCursor
        for aid in self._asset_ids:
            asset = self._project.get_asset(aid) if self._project else None
            if asset and asset.source_path:
                hp = HoverPreview.instance()
                hp.show_for(asset.source_path, QCursor.pos())
                return


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
    engagement_changed = Signal()  # emitted when a check is done/snoozed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timeline_stream")
        self._project: "Project | None" = None
        self._thumb_cache = None
        self._day_filter: str | None = None

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

        self._btn_engagement = QPushButton("Engagement")
        self._btn_engagement.setObjectName("timeline_btn_engagement")
        self._btn_engagement.clicked.connect(self._show_engagement_popup)
        toolbar.addWidget(self._btn_engagement)

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

    def set_oneup_label(self, label: str) -> None:
        """Update the Sync button to show which OneUp account is active."""
        if label:
            self._btn_sync.setText(f"Sync OneUp ({label})")
        else:
            self._btn_sync.setText("Sync OneUp")

    def set_thumb_cache(self, cache):
        self._thumb_cache = cache

    def set_project(self, project: "Project") -> None:
        self._project = project
        self.refresh()

    def set_day_filter(self, iso_date: str | None) -> None:
        """Filter timeline to a single day, or clear filter (None)."""
        self._day_filter = iso_date
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

        # Apply calendar day filter
        if self._day_filter:
            posts = [p for p in posts if p.scheduled_time and p.scheduled_time[:10] == self._day_filter]

        # Sort by scheduled_time (normalize to YYYY-MM-DDTHH:MM for consistent ordering)
        def _sort_key(p):
            t = p.scheduled_time or ""
            return t[:16] if t else "9999"
        posts.sort(key=_sort_key)

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

        today = datetime.now().date()
        idx = 0  # insertion index (before trailing stretch)

        # Show posts grouped by day — no gap markers for empty days
        for day_str in sorted(by_day):
            day = datetime.fromisoformat(day_str).date()
            header = self._make_day_header(day, today)
            self._content_layout.insertWidget(idx, header)
            idx += 1
            for post in by_day[day_str]:
                card = PostCard(post, self._project, self._thumb_cache)
                card.clicked.connect(self.post_selected)
                card.engagement_changed.connect(self._on_engagement_changed)
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
                card.engagement_changed.connect(self._on_engagement_changed)
                self._content_layout.insertWidget(idx, card)
                idx += 1

        total = len(posts)
        self._summary_label.setText(
            f"{total} posts · {n_queued} queued · {n_posted} posted"
        )

        # Update engagement button badge (don't auto-show the popup)
        if self._project:
            from datetime import datetime as _dt
            now = _dt.now()
            eng_count = 0
            for p in self._project.posts:
                for cd in getattr(p, 'engagement_checks', []):
                    check = EngagementWindow.from_dict(cd)
                    if check.done:
                        continue
                    try:
                        ct = _dt.fromisoformat(check.check_at)
                        if (ct - now).total_seconds() / 60 <= 60:
                            eng_count += 1
                    except Exception:
                        pass
            if eng_count:
                self._btn_engagement.setText(f"Engagement ({eng_count})")
            else:
                self._btn_engagement.setText("Engagement")

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

    def _show_engagement_popup(self):
        """Refresh the timeline to update engagement badges on PostCards."""
        self.refresh()

    def _on_engagement_changed(self) -> None:
        """Engagement check was marked done or snoozed — bubble up for save."""
        self.engagement_changed.emit()

    def _on_filter_changed(self, _text: str) -> None:
        self.refresh()
