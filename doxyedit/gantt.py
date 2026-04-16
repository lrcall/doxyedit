"""Gantt chart tab — visual timeline of scheduled posts with stagger lines."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDateEdit, QSlider, QGraphicsScene, QGraphicsView,
    QGraphicsRectItem, QGraphicsLineItem, QSplitter,
    QScrollArea, QFrame, QSizePolicy, QGraphicsItem,
)
from PySide6.QtCore import Signal, Qt, QDate, QRectF, QPointF
from PySide6.QtGui import QPen, QColor, QBrush, QPainter, QPainterPath

from doxyedit.models import Project, SocialPost, SocialPostStatus


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ROW_HEIGHT = 40
_HEADER_HEIGHT = 24
_LABEL_WIDTH = 150
_MIN_BAR_WIDTH = 8  # minimum bar width in pixels so tiny bars are still visible
_BAR_HEIGHT = 14    # height of each individual bar
_BAR_GAP = 2        # gap between stacked bars
_GAP_THRESHOLD_DAYS = 7

_STATUS_COLORS = {
    SocialPostStatus.DRAFT: "post_draft",
    SocialPostStatus.QUEUED: "post_queued",
    SocialPostStatus.POSTED: "post_posted",
    SocialPostStatus.FAILED: "post_failed",
    "draft": "post_draft",
    "queued": "post_queued",
    "posted": "post_posted",
    "failed": "post_failed",
}

def _theme_color(theme, token: str) -> QColor:
    """Resolve a theme token to QColor, using DEFAULT_THEME as fallback."""
    val = getattr(theme, token, None) if theme else None
    if not val:
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        val = getattr(_dt, token, "#888888")
    return QColor(val)


# ---------------------------------------------------------------------------
# GanttBar — individual post rectangle
# ---------------------------------------------------------------------------

class _GanttBar(QGraphicsRectItem):
    """A clickable bar representing one post on one platform."""

    def __init__(self, x: float, y: float, w: float, h: float,
                 post: SocialPost, platform: str, color: QColor,
                 theme=None, thumb_path: str = "",
                 parent=None):
        super().__init__(x, y, w, h, parent)
        self.post_id = post.id
        self._post = post
        self._platform = platform
        self._base_color = color
        self.setBrush(QBrush(color))
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = theme or THEMES[DEFAULT_THEME]
        self._bar_pen_width = _dt.gantt_bar_pen_width
        self._bar_hover_pen_width = _dt.gantt_bar_hover_pen_width
        self.setPen(QPen(color.darker(120), self._bar_pen_width))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

        # Themed HTML tooltip with thumbnail
        status = post.status.upper() if post.status else "DRAFT"
        cap = post.caption_default or "(no caption)"
        if len(cap) > 120:
            cap = cap[:117] + "..."
        cap = cap.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        sched = post.scheduled_time[:16].replace("T", " ") if post.scheduled_time else "unscheduled"
        plats = ", ".join(post.platforms) if post.platforms else platform
        assets_str = ", ".join(post.asset_ids[:3]) if post.asset_ids else "(no assets)"

        bg = _theme_color(theme, "bg_raised").name()
        bg2 = _theme_color(theme, "bg_main").name()
        fg = _theme_color(theme, "text_primary").name()
        fg2 = _theme_color(theme, "text_secondary").name()
        fg_m = _theme_color(theme, "text_muted").name()
        accent = color.name()
        bdr = _theme_color(theme, "border").name()

        chain_html = ""
        if post.release_chain:
            steps = " &rarr; ".join(f"{s.platform} +{s.delay_hours}h" for s in post.release_chain)
            chain_html = f'<tr><td colspan="2" style="color:{fg_m}; padding-top:4px;">Release: {steps}</td></tr>'

        info_rows = (
            f'<tr><td style="font-weight:bold; color:{accent}; padding-bottom:2px;" colspan="2">'
            f'{status} &nbsp; <span style="color:{fg2};">{sched}</span></td></tr>'
            f'<tr><td colspan="2" style="color:{fg2}; padding-bottom:4px;">{plats}</td></tr>'
            f'<tr><td colspan="2" style="color:{fg};">{cap}</td></tr>'
            f'<tr><td colspan="2" style="color:{fg_m}; padding-top:4px;">Assets: {assets_str}</td></tr>'
            f'{chain_html}'
        )

        if thumb_path:
            tip = (
                f'<table cellspacing="0" cellpadding="0" style="background:{bg}; '
                f'border:1px solid {bdr}; border-radius:6px;">'
                f'<tr>'
                f'<td style="padding:8px; background:{bg2}; vertical-align:top; border-right:1px solid {bdr};">'
                f'<img src="file:///{thumb_path}" width="120" /></td>'
                f'<td style="padding:8px; vertical-align:top; max-width:260px;">'
                f'<table cellspacing="0" cellpadding="0">{info_rows}</table>'
                f'</td></tr></table>'
            )
        else:
            tip = (
                f'<table cellspacing="0" cellpadding="0" style="background:{bg}; '
                f'border:1px solid {bdr}; border-radius:6px; max-width:340px;">'
                f'<tr><td style="padding:8px;">'
                f'<table cellspacing="0" cellpadding="0">{info_rows}</table>'
                f'</td></tr></table>'
            )
        self.setToolTip(tip)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene and hasattr(scene, "bar_clicked"):
                scene.bar_clicked.emit(self.post_id)
        super().mousePressEvent(event)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(self._base_color.lighter(140)))
        self.setPen(QPen(self._base_color.lighter(160), self._bar_hover_pen_width))
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(self._base_color))
        self.setPen(QPen(self._base_color.darker(120), self._bar_pen_width))
        self.update()
        super().hoverLeaveEvent(event)


# ---------------------------------------------------------------------------
# GanttScene
# ---------------------------------------------------------------------------

class _GanttScene(QGraphicsScene):
    """Scene that emits bar_clicked when a post bar is pressed."""
    bar_clicked = Signal(str)


# ---------------------------------------------------------------------------
# GanttPanel — main widget
# ---------------------------------------------------------------------------

class GanttPanel(QWidget):
    """Gantt chart visualizing scheduled posts across platforms."""

    post_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("gantt_panel")

        self._project: Optional[Project] = None
        self._theme = None
        self._px_per_day = 60
        self._platform_order: list[str] = []
        self._cross_cache = None
        self._cross_exclude = ""

        self._build_ui()

    # -- public API ---------------------------------------------------------

    def set_project(self, project: Project) -> None:
        self._project = project
        self.refresh()

    def set_cross_project(self, cache, exclude_path: str = "") -> None:
        self._cross_cache = cache
        self._cross_exclude = exclude_path

    def set_theme(self, theme) -> None:
        self._theme = theme
        # Set scene background so the QGraphicsScene matches the view
        self._scene.setBackgroundBrush(QBrush(_theme_color(theme, "bg_deep")))
        self.refresh()

    def refresh(self) -> None:
        self._rebuild_chart()

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        from PySide6.QtCore import QSettings as _QS
        _f = _QS("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- toolbar ---
        toolbar = QWidget()
        toolbar.setObjectName("gantt_toolbar")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(_pad_lg + _pad, _pad, _pad_lg + _pad, _pad)
        tb_lay.setSpacing(_pad_lg + _pad)

        tb_lay.addWidget(QLabel("From:"))
        self._date_start = QDateEdit()
        self._date_start.setObjectName("gantt_date_start")
        self._date_start.setCalendarPopup(True)
        self._date_start.setDate(QDate.currentDate().addDays(-7))
        self._date_start.dateChanged.connect(lambda: self.refresh())
        tb_lay.addWidget(self._date_start)

        tb_lay.addWidget(QLabel("To:"))
        self._date_end = QDateEdit()
        self._date_end.setObjectName("gantt_date_end")
        self._date_end.setCalendarPopup(True)
        self._date_end.setDate(QDate.currentDate().addDays(30))
        self._date_end.dateChanged.connect(lambda: self.refresh())
        tb_lay.addWidget(self._date_end)

        today_btn = QPushButton("Today")
        today_btn.setObjectName("gantt_today_btn")
        today_btn.clicked.connect(self._scroll_to_today)
        tb_lay.addWidget(today_btn)

        tb_lay.addStretch()

        tb_lay.addWidget(QLabel("Zoom:"))
        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setObjectName("gantt_zoom")
        self._zoom_slider.setRange(20, 200)
        self._zoom_slider.setValue(self._px_per_day)
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _gantt_theme = THEMES[DEFAULT_THEME]
        ZOOM_SLIDER_WIDTH_RATIO = 10.0  # zoom slider width relative to font
        self._zoom_slider.setFixedWidth(int(_gantt_theme.font_size * ZOOM_SLIDER_WIDTH_RATIO))
        self._zoom_slider.valueChanged.connect(self._on_zoom)
        tb_lay.addWidget(self._zoom_slider)

        root.addWidget(toolbar)

        # --- body: label column + chart ---
        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # Row labels (scrollable vertically, synced with chart)
        self._label_area = QScrollArea()
        self._label_area.setObjectName("gantt_label_area")
        self._label_area.setFixedWidth(_LABEL_WIDTH)
        self._label_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._label_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._label_area.setWidgetResizable(True)
        self._label_container = QWidget()
        self._label_container.setObjectName("gantt_label_container")
        self._label_layout = QVBoxLayout(self._label_container)
        self._label_layout.setContentsMargins(_pad, _HEADER_HEIGHT, _pad, 0)
        self._label_layout.setSpacing(0)
        self._label_layout.setAlignment(Qt.AlignTop)
        self._label_area.setWidget(self._label_container)
        body_lay.addWidget(self._label_area)

        # Chart view
        self._scene = _GanttScene()
        self._scene.bar_clicked.connect(self.post_selected.emit)
        self._view = QGraphicsView(self._scene)
        self._view.setObjectName("gantt_view")
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        body_lay.addWidget(self._view, 1)

        root.addWidget(body, 1)

        # Sync vertical scrolling between labels and chart
        self._view.verticalScrollBar().valueChanged.connect(
            self._label_area.verticalScrollBar().setValue
        )

    # -- chart rebuild ------------------------------------------------------

    def _rebuild_chart(self) -> None:
        self._scene.clear()

        # Clear row labels
        while self._label_layout.count():
            item = self._label_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._project:
            return

        posts = self._project.posts
        if not posts:
            return

        d_start = self._date_start.date().toPython()
        d_end = self._date_end.date().toPython()
        if d_end <= d_start:
            return

        total_days = (d_end - d_start).days
        ppd = self._px_per_day
        chart_w = total_days * ppd
        theme = self._theme

        # Gather platforms from posts that fall in range
        platform_set: set[str] = set()
        scheduled_posts: list[SocialPost] = []
        for p in posts:
            if not p.scheduled_time:
                continue
            try:
                dt = datetime.fromisoformat(p.scheduled_time)
            except (ValueError, TypeError):
                continue
            if d_start <= dt.date() <= d_end:
                scheduled_posts.append(p)
                # Platforms from direct list
                for plat in p.platforms:
                    platform_set.add(plat)
                # Platforms from release chain
                for step in p.release_chain:
                    if step.platform:
                        platform_set.add(step.platform)

        if not platform_set:
            # Show at least the grid
            self._draw_grid(chart_w, 0, total_days, d_start, theme)
            return

        self._platform_order = sorted(platform_set)
        plat_y: dict[str, float] = {}
        for i, plat in enumerate(self._platform_order):
            y = _HEADER_HEIGHT + i * _ROW_HEIGHT
            plat_y[plat] = y

        num_rows = len(self._platform_order)
        chart_h = _HEADER_HEIGHT + num_rows * _ROW_HEIGHT + 20

        # Row labels
        for plat in self._platform_order:
            lbl = QLabel(plat.replace("_", " ").title())
            lbl.setObjectName("gantt_row_label")
            lbl.setFixedHeight(_ROW_HEIGHT)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._label_layout.addWidget(lbl)

        # Draw grid
        self._draw_grid(chart_w, chart_h, total_days, d_start, theme)

        # Draw today line
        today = date.today()
        if d_start <= today <= d_end:
            tx = (today - d_start).days * ppd
            pen = QPen(_theme_color(theme, "accent"), theme.gantt_today_pen_width)
            self._scene.addLine(tx, 0, tx, chart_h, pen)

        # Draw row separators
        border_pen = QPen(_theme_color(theme, "border"), theme.gantt_row_separator_width)
        for i in range(num_rows + 1):
            y = _HEADER_HEIGHT + i * _ROW_HEIGHT
            self._scene.addLine(0, y, chart_w, y, border_pen)

        # Build per-platform post timeline for gap detection
        plat_dates: dict[str, list[date]] = {p: [] for p in self._platform_order}

        # Build asset-id → thumbnail path lookup
        from pathlib import Path as _Path
        asset_index = {a.id: a for a in self._project.assets} if self._project else {}

        def _thumb_for_post(post: SocialPost) -> str:
            """Return thumbnail path for the first asset, or empty string."""
            for aid in post.asset_ids:
                asset = asset_index.get(aid)
                if not asset or not asset.source_path:
                    continue
                src = _Path(asset.source_path)
                # Check _previews/ cache
                preview = _Path("_previews") / f"{src.stem}.jpg"
                if preview.exists():
                    return str(preview.resolve()).replace("\\", "/")
                # Check _starred_previews/
                starred = _Path("_starred_previews") / f"{src.stem}.jpg"
                if starred.exists():
                    return str(starred.resolve()).replace("\\", "/")
                # Try the source file itself (for jpg/png)
                if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and src.exists():
                    return str(src.resolve()).replace("\\", "/")
            return ""

        # Track bar stacking per (platform, day) to offset overlapping bars
        _bar_stack: dict[tuple[str, int], int] = {}  # (platform, day_offset) -> count

        # Draw posts
        for post in scheduled_posts:
            try:
                dt = datetime.fromisoformat(post.scheduled_time)
            except (ValueError, TypeError):
                continue

            post_date = dt.date()
            day_offset = (post_date - d_start).days
            x = day_offset * ppd

            status_token = _STATUS_COLORS.get(post.status, "post_draft")
            color = _theme_color(theme, status_token)
            thumb = _thumb_for_post(post)

            # If post has release chain, draw per-step
            if post.release_chain and len(post.release_chain) >= 2:
                anchor_bars: list[tuple[float, float, float]] = []  # x, y, mid_y

                for step in post.release_chain:
                    plat = step.platform
                    if plat not in plat_y:
                        continue
                    step_day = day_offset + int(step.delay_hours / 24)
                    step_x = x + (step.delay_hours / 24.0) * ppd
                    bar_w = max(_MIN_BAR_WIDTH, ppd * 0.8)
                    row_y = plat_y[plat]
                    stack_key = (plat, step_day)
                    stack_n = _bar_stack.get(stack_key, 0)
                    _bar_stack[stack_key] = stack_n + 1
                    bar_y = row_y + 3 + stack_n * (_BAR_HEIGHT + _BAR_GAP)
                    bar_h = _BAR_HEIGHT

                    step_color = color
                    if step.status == "posted":
                        step_color = _theme_color(theme, "post_posted")
                    elif step.status == "skipped":
                        step_color = _theme_color(theme, "text_muted")

                    bar = _GanttBar(step_x, bar_y, bar_w, bar_h,
                                    post, plat, step_color,
                                    theme=theme, thumb_path=thumb)
                    self._scene.addItem(bar)
                    anchor_bars.append((step_x + bar_w / 2, bar_y, bar_y + bar_h))
                    plat_dates[plat].append(post_date + timedelta(hours=step.delay_hours))

                # Draw stagger dashed lines connecting the bars
                if len(anchor_bars) >= 2:
                    dash_pen = QPen(_theme_color(theme, "accent_dim"), theme.gantt_bar_pen_width, Qt.DashLine)
                    for i in range(len(anchor_bars) - 1):
                        x1, y1_top, y1_bot = anchor_bars[i]
                        x2, y2_top, y2_bot = anchor_bars[i + 1]
                        # Connect bottom of first to top of second (or vice versa)
                        if y1_top < y2_top:
                            self._scene.addLine(x1, y1_bot, x2, y2_top, dash_pen)
                        else:
                            self._scene.addLine(x1, y1_top, x2, y2_bot, dash_pen)
            else:
                # Simple bar on each platform
                for plat in post.platforms:
                    if plat not in plat_y:
                        continue
                    bar_w = max(_MIN_BAR_WIDTH, ppd * 0.8)
                    row_y = plat_y[plat]
                    stack_key = (plat, day_offset)
                    stack_n = _bar_stack.get(stack_key, 0)
                    _bar_stack[stack_key] = stack_n + 1
                    bar_y = row_y + 3 + stack_n * (_BAR_HEIGHT + _BAR_GAP)
                    bar_h = _BAR_HEIGHT

                    bar = _GanttBar(x, bar_y, bar_w, bar_h,
                                    post, plat, color,
                                    theme=theme, thumb_path=thumb)
                    self._scene.addItem(bar)
                    plat_dates[plat].append(post_date)

        # Campaign milestone markers
        if self._project and self._project.campaigns:
            for campaign in self._project.campaigns:
                cam_color = QColor(campaign.color) if campaign.color else _theme_color(theme, "warning")
                cam_color.setAlpha(theme.gantt_campaign_alpha)
                # Campaign span bar (if launch_date and end_date)
                if campaign.launch_date and campaign.end_date:
                    try:
                        c_start = date.fromisoformat(campaign.launch_date)
                        c_end = date.fromisoformat(campaign.end_date)
                        if c_end >= d_start and c_start <= d_end:
                            cx = max(0, (c_start - d_start).days) * ppd
                            cx2 = min(total_days, (c_end - d_start).days + 1) * ppd
                            span_rect = self._scene.addRect(
                                cx, _HEADER_HEIGHT, cx2 - cx, chart_h - _HEADER_HEIGHT - 20,
                                QPen(Qt.NoPen), QBrush(QColor(cam_color.red(), cam_color.green(), cam_color.blue(), theme.gantt_campaign_span_alpha))
                            )
                            span_rect.setToolTip(f"Campaign: {campaign.name}")
                    except (ValueError, TypeError):
                        pass
                # Launch date marker
                if campaign.launch_date:
                    try:
                        launch = date.fromisoformat(campaign.launch_date)
                        if d_start <= launch <= d_end:
                            lx = (launch - d_start).days * ppd
                            launch_pen = QPen(cam_color, theme.gantt_today_pen_width, Qt.DashDotLine)
                            self._scene.addLine(lx, _HEADER_HEIGHT, lx, chart_h - 20, launch_pen)
                            launch_lbl = self._scene.addSimpleText(f"🚀 {campaign.name}", self._view.font())
                            launch_lbl.setPos(lx + 3, _HEADER_HEIGHT + 2)
                            launch_lbl.setBrush(QBrush(cam_color))
                    except (ValueError, TypeError):
                        pass
                # Milestone markers
                for ms in campaign.milestones:
                    if not ms.due_date:
                        continue
                    try:
                        ms_date = date.fromisoformat(ms.due_date)
                    except (ValueError, TypeError):
                        continue
                    if d_start <= ms_date <= d_end:
                        mx = (ms_date - d_start).days * ppd
                        ms_pen = QPen(cam_color, theme.gantt_bar_pen_width, Qt.DotLine)
                        self._scene.addLine(mx, _HEADER_HEIGHT, mx, chart_h - 20, ms_pen)
                        ms_lbl = self._scene.addSimpleText(ms.label, self._view.font())
                        ms_lbl.setPos(mx + 3, _HEADER_HEIGHT + 14)
                        ms_color = QColor(cam_color)
                        ms_color.setAlpha(theme.gantt_milestone_alpha)
                        ms_lbl.setBrush(QBrush(ms_color))

        # Cross-project ghost bars (muted, translucent)
        if self._cross_cache:
            xp_posts = self._cross_cache.get_all_schedules(exclude_path=self._cross_exclude)
            ghost_color = _theme_color(theme, "text_muted")
            ghost_color.setAlpha(theme.gantt_ghost_alpha)
            ghost_pen = QPen(ghost_color, 0)
            ghost_brush = QBrush(ghost_color)
            for xp in xp_posts:
                try:
                    xp_dt = datetime.fromisoformat(xp.get("scheduled_time", ""))
                except (ValueError, TypeError):
                    continue
                xp_date = xp_dt.date()
                if not (d_start <= xp_date <= d_end):
                    continue
                xp_day = (xp_date - d_start).days
                xp_x = xp_day * ppd
                for xp_plat in xp.get("platforms", []):
                    if xp_plat not in plat_y:
                        continue
                    row_y = plat_y[xp_plat]
                    stack_key = (xp_plat, xp_day)
                    stack_n = _bar_stack.get(stack_key, 0)
                    _bar_stack[stack_key] = stack_n + 1
                    bar_y = row_y + 3 + stack_n * (_BAR_HEIGHT + _BAR_GAP)
                    bar_w = max(_MIN_BAR_WIDTH, ppd * 0.6)
                    rect = self._scene.addRect(xp_x, bar_y, bar_w, _BAR_HEIGHT - 2,
                                               ghost_pen, ghost_brush)
                    proj_name = xp.get("project_name", "?")
                    caption = xp.get("caption_preview", "")
                    rect.setToolTip(f"[{proj_name}] {caption}")

        # Gap detection — hatched regions for 7+ day gaps
        gap_color = _theme_color(theme, "post_failed")
        gap_color.setAlpha(theme.gantt_gap_alpha)
        gap_pen = QPen(gap_color, 0)
        gap_brush = QBrush(gap_color)

        for plat in self._platform_order:
            dates = sorted(set(plat_dates[plat]))
            if len(dates) < 2:
                continue
            row_y = plat_y[plat]
            for i in range(len(dates) - 1):
                gap_days = (dates[i + 1] - dates[i]).days
                if gap_days >= _GAP_THRESHOLD_DAYS:
                    gx = (dates[i] - d_start).days * ppd + ppd
                    gw = (gap_days - 1) * ppd
                    if gw > 0:
                        rect = self._scene.addRect(
                            gx, row_y + 2, gw, _ROW_HEIGHT - 4,
                            gap_pen, gap_brush
                        )
                        rect.setToolTip(f"{gap_days}-day gap on {plat}")

        self._scene.setSceneRect(0, 0, chart_w, chart_h)

    def _draw_grid(self, chart_w: float, chart_h: float,
                   total_days: int, d_start: date, theme) -> None:
        """Draw vertical day/week grid lines and date header labels."""
        ppd = self._px_per_day
        thin_pen = QPen(_theme_color(theme, "border"), theme.gantt_grid_thin_width)
        week_pen = QPen(_theme_color(theme, "border"), theme.gantt_grid_week_width)
        text_color = _theme_color(theme, "text_muted")

        for d in range(total_days + 1):
            x = d * ppd
            cur_date = d_start + timedelta(days=d)
            is_week = cur_date.weekday() == 0  # Monday
            pen = week_pen if is_week else thin_pen
            if chart_h > 0:
                self._scene.addLine(x, _HEADER_HEIGHT, x, chart_h, pen)

            # Date labels in header — show day number, and month on 1st/mondays
            if ppd >= 40 or d % max(1, int(60 / ppd)) == 0:
                label_text = cur_date.strftime("%d")
                if cur_date.day == 1 or (is_week and ppd >= 50):
                    label_text = cur_date.strftime("%b %d")
                txt = self._scene.addSimpleText(label_text)
                txt.setBrush(QBrush(text_color))
                txt.setPos(x + 2, 2)

    # -- controls -----------------------------------------------------------

    def _on_zoom(self, value: int) -> None:
        self._px_per_day = value
        self.refresh()

    def _scroll_to_today(self) -> None:
        """Scroll the view so the today-line is centered horizontally."""
        d_start = self._date_start.date().toPython()
        today = date.today()
        day_offset = (today - d_start).days
        x = day_offset * self._px_per_day
        self._view.centerOn(x, self._view.sceneRect().height() / 2)

    # -- wheel override for horizontal scroll -------------------------------

    def wheelEvent(self, event):
        """Route wheel events to horizontal scroll on the chart view."""
        if self._view.underMouse():
            delta = event.angleDelta().y()
            sb = self._view.horizontalScrollBar()
            sb.setValue(sb.value() - delta)
            event.accept()
        else:
            super().wheelEvent(event)
