"""Asset browser — QListView with custom delegate for high-performance thumbnail grid."""
import os
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QStyledItemDelegate,
    QLabel, QPushButton, QFileDialog, QFrame, QLineEdit, QComboBox,
    QMenu, QApplication, QSizePolicy, QStyle, QCheckBox,
    QStackedWidget, QScrollArea,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QSettings, QSize, QRect, QPoint,
    QAbstractListModel, QModelIndex,
)
from PySide6.QtGui import (
    QPixmap, QFont, QColor, QCursor, QPainter, QPen, QFontMetrics, QPainterPath,
    QKeySequence, QShortcut,
)

from doxyedit.models import (
    Asset, Project, TAG_PRESETS, TAG_SIZED, TAG_ALL, TAG_SHORTCUTS,
    TagPreset, toggle_tags, next_tag_color, STAR_COLORS, VINIK_COLORS,
)
from doxyedit.preview import HoverPreview, ImagePreviewDialog
from doxyedit.thumbcache import ThumbCache, THUMB_SIZE

from PySide6.QtWidgets import QLayout

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".svg", ".tiff", ".tif",
    ".psd", ".psb", ".sai", ".sai2", ".clip", ".csp", ".kra", ".xcf", ".ora",
    ".ico", ".cur", ".dds", ".tga", ".exr", ".hdr",
}
THUMB_GEN_SIZE = 512
DEFAULT_PAGE_SIZE = 100

AUTO_TAG_PATTERNS = {
    "cover": "cover", "banner": "banner", "hero": "hero",
    "thumb": "thumbnail", "icon": "icon", "avatar": "icon",
    "bg": "bg", "background": "bg", "sketch": "sketch",
    "wip": "wip", "final": "final", "promo": "promo",
    "char": "character", "character": "character",
    "ref": "reference", "reference": "reference",
    "merch": "merch", "page": "page", "panel": "page",
    "asset": "asset", "sprite": "asset",
}


def auto_suggest_tags(filename: str) -> list[str]:
    name = filename.lower()
    tags = []
    for pattern, tag_id in AUTO_TAG_PATTERNS.items():
        if pattern in name and tag_id not in tags:
            tags.append(tag_id)
    return tags


# ---------------------------------------------------------------------------
# FlowLayout for tag bar (kept — only used for pill buttons, not thumbnails)
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), dry_run=True)

    def _do_layout(self, rect, dry_run=False):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        row_height = 0
        max_width = rect.right() - m.right()
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > max_width and x > rect.x() + m.left():
                x = rect.x() + m.left()
                y += row_height + self._spacing
                row_height = 0
            if not dry_run:
                item.setGeometry(QRect(x, y, w, h))
            x += w + self._spacing
            row_height = max(row_height, h)
        return y + row_height - rect.y() + m.bottom()


class FlowWidget(QWidget):
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.layout().heightForWidth(width) if self.layout() else 30

    def sizeHint(self):
        if self.layout():
            w = self.width() if self.width() > 0 else 400
            return QSize(w, max(self.layout().heightForWidth(w), 30))
        return super().sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()


# ---------------------------------------------------------------------------
# Thumbnail Model — data source for QListView
# ---------------------------------------------------------------------------

class _FolderHeader:
    """Sentinel inserted into the model to represent a folder group header."""
    def __init__(self, folder: str, collapsed: bool = False):
        self.folder = folder
        self.collapsed = collapsed
        self.id = None


class ThumbnailModel(QAbstractListModel):
    ThumbnailRole = Qt.ItemDataRole.UserRole + 1
    AssetIdRole = Qt.ItemDataRole.UserRole + 2
    DimsRole = Qt.ItemDataRole.UserRole + 3
    StarRole = Qt.ItemDataRole.UserRole + 4
    TagsRole = Qt.ItemDataRole.UserRole + 5
    AssignmentsRole = Qt.ItemDataRole.UserRole + 6  # list of (platform, status) tuples

    def __init__(self, parent=None):
        super().__init__(parent)
        self._assets: list[Asset] = []
        self._pixmaps: dict[str, QPixmap] = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._assets)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        asset = self._assets[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            p = Path(asset.source_path)
            return p.name
        elif role == self.ThumbnailRole:
            return self._pixmaps.get(asset.id)
        elif role == self.AssetIdRole:
            return asset.id
        elif role == self.DimsRole:
            return None  # filled by thumb cache
        elif role == self.StarRole:
            return asset.starred
        elif role == self.TagsRole:
            return asset.tags
        elif role == self.AssignmentsRole:
            return [(pa.platform, pa.status) for pa in asset.assignments] if asset.assignments else []
        return None

    def set_assets(self, assets: list[Asset]):
        self.beginResetModel()
        self._assets = assets
        self.endResetModel()

    def update_pixmap(self, asset_id: str, pixmap: QPixmap):
        self._pixmaps[asset_id] = pixmap
        for i, a in enumerate(self._assets):
            if a.id == asset_id:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [self.ThumbnailRole])
                return

    def get_asset(self, index: QModelIndex) -> Asset | None:
        if index.isValid() and 0 <= index.row() < len(self._assets):
            return self._assets[index.row()]
        return None


# ---------------------------------------------------------------------------
# Thumbnail Delegate — paints each cell (no widgets)
# ---------------------------------------------------------------------------

class ThumbnailDelegate(QStyledItemDelegate):
    PADDING = 6

    def __init__(self, thumb_size=THUMB_SIZE, parent=None):
        super().__init__(parent)
        self.thumb_size = thumb_size
        self.font_size = 10  # updated by update_font_size
        self.show_dims = True
        self._folder_starts: dict[int, str] = {}  # row_index → folder path
        self._scaled_cache: dict[tuple, QPixmap] = {}

    def sizeHint(self, option, index):
        return QSize(self.thumb_size + 2 * self.PADDING,
                     self.thumb_size + 70)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect

        # Folder label — small tag on the first item of each folder group
        row = index.row()
        if row in self._folder_starts:
            folder = self._folder_starts[row]
            # Show last 2 path components for readability
            parts = Path(folder).parts
            short = str(Path(*parts[-2:])) if len(parts) >= 2 else folder
            painter.save()
            painter.setFont(QFont("Segoe UI", max(6, self.font_size - 3)))
            fm = QFontMetrics(QFont("Segoe UI", max(6, self.font_size - 3)))
            text_w = fm.horizontalAdvance(short) + 10
            tag_rect = QRect(rect.x(), rect.y(), min(text_w, rect.width()), 16)
            painter.fillRect(tag_rect, QColor(128, 128, 128, 60))
            painter.setPen(QColor(200, 200, 200, 200))
            painter.drawText(tag_rect.adjusted(4, 0, -4, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             short)
            painter.restore()

        ts = self.thumb_size

        # Selection / hover background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor(100, 150, 200, 80))
            painter.setPen(QPen(QColor(100, 150, 200, 180), 2))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(128, 128, 128, 30))

        # Thumbnail
        pixmap = index.data(ThumbnailModel.ThumbnailRole)
        if pixmap and not pixmap.isNull():
            cache_key = (pixmap.cacheKey(), ts)
            if cache_key not in self._scaled_cache:
                self._scaled_cache[cache_key] = pixmap.scaled(
                    ts, ts, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            scaled = self._scaled_cache[cache_key]
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + self.PADDING + (ts - scaled.height()) // 2
            # Rounded corners
            path = QPainterPath()
            path.addRoundedRect(float(x), float(y), float(scaled.width()), float(scaled.height()), 3, 3)
            painter.setClipPath(path)
            painter.drawPixmap(x, y, scaled)
            painter.setClipping(False)
        else:
            # Placeholder
            ph_rect = QRect(rect.x() + self.PADDING, rect.y() + self.PADDING, ts, ts)
            painter.fillRect(ph_rect, QColor(128, 128, 128, 25))
            painter.setPen(QColor(128, 128, 128, 60))
            painter.drawText(ph_rect, Qt.AlignmentFlag.AlignCenter, "...")

        # Tag dots
        tags = index.data(ThumbnailModel.TagsRole) or []
        dot_y = rect.y() + self.PADDING + ts + 4
        dot_x = rect.x() + self.PADDING + 2
        for tag_id in tags[:10]:
            preset = TAG_ALL.get(tag_id)
            color = QColor(preset.color) if preset else QColor(VINIK_COLORS[hash(tag_id) % len(VINIK_COLORS)])
            painter.setBrush(color)
            painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
            painter.drawEllipse(QPoint(dot_x + 5, dot_y + 5), 5, 5)
            dot_x += 13

        # Platform assignment status badge (top-right corner of thumbnail)
        assignments = index.data(ThumbnailModel.AssignmentsRole) or []
        if assignments:
            # Pick highest-priority status: posted > ready > pending
            statuses = {s for _, s in assignments}
            if "posted" in statuses:
                badge_color = QColor(110, 170, 120, 220)   # green
                badge_char = "✓"
            elif "ready" in statuses:
                badge_color = QColor(124, 161, 192, 220)   # blue
                badge_char = "R"
            else:
                badge_color = QColor(190, 149, 92, 220)    # amber
                badge_char = "…"
            bx = rect.x() + rect.width() - self.PADDING - 18
            by = rect.y() + self.PADDING + 2
            painter.setBrush(badge_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bx, by, 16, 16, 4, 4)
            painter.setPen(QColor(255, 255, 255, 230))
            painter.setFont(QFont("Segoe UI", max(6, self.font_size - 4), QFont.Weight.Bold))
            painter.drawText(QRect(bx, by, 16, 16), Qt.AlignmentFlag.AlignCenter, badge_char)

        # Dimensions text
        fs = self.font_size
        if self.show_dims:
            dims = index.data(ThumbnailModel.DimsRole)
            dim_text = f"{dims[0]}x{dims[1]}" if dims else ""
            dim_rect = QRect(rect.x(), rect.y() + ts + 22, rect.width(), 16)
            painter.setPen(QColor(128, 128, 128, 150))
            painter.setFont(QFont("Segoe UI", max(6, fs - 3)))
            painter.drawText(dim_rect, Qt.AlignmentFlag.AlignHCenter, dim_text)

        # Filename
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        name_font = QFont("Segoe UI", max(7, fs - 2))
        name_rect = QRect(rect.x() + self.PADDING, rect.y() + ts + 38,
                          rect.width() - 30, 18)
        painter.setPen(option.palette.text().color())
        painter.setFont(name_font)
        fm = QFontMetrics(name_font)
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # Star
        star_val = index.data(ThumbnailModel.StarRole) or 0
        star_char = "\u2605" if star_val else "\u2606"
        if star_val and star_val in STAR_COLORS:
            painter.setPen(QColor(STAR_COLORS[star_val]))
        else:
            painter.setPen(QColor(150, 150, 150, 100))
        painter.setFont(QFont("Segoe UI", fs + 4))
        star_rect = QRect(rect.right() - 24, rect.y() + ts + 34, 22, 22)
        painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, star_char)

        painter.restore()

    def invalidate_cache(self):
        self._scaled_cache.clear()

    def _ensure_cache_limit(self):
        """Evict old entries if cache grows too large."""
        if len(self._scaled_cache) > 500:
            keys = list(self._scaled_cache.keys())
            for k in keys[:200]:
                del self._scaled_cache[k]


# ---------------------------------------------------------------------------
# FolderListView — auto-heights itself to show all items without scrollbar
# ---------------------------------------------------------------------------

class FolderListView(QListView):
    """QListView that reports a sizeHint tall enough to show all items unwrapped."""

    def sizeHint(self):
        m = self.model()
        if not m or m.rowCount() == 0:
            return QSize(200, 0)
        w = max(self.width(), 200)
        grid = self.gridSize()
        if not grid.isValid():
            return super().sizeHint()
        col_w = max(1, grid.width() + self.spacing() * 2)
        cols = max(1, w // col_w)
        rows = (m.rowCount() + cols - 1) // cols
        h = rows * grid.height() + 8
        return QSize(w, h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()


# ---------------------------------------------------------------------------
# FolderSection — header button + FolderListView for one folder group
# ---------------------------------------------------------------------------

class FolderSection(QWidget):
    """One collapsible folder group: header label + FolderListView."""

    collapsed_changed = Signal(str, bool)  # (folder_path, is_collapsed)

    def __init__(self, folder: str, assets: list, delegate, thumb_size: int,
                 collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._thumb_size = thumb_size

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(0)

        # Header
        parts = Path(folder).parts
        short = str(Path(*parts[-2:])) if len(parts) >= 2 else folder
        self._short = short
        self._header = QPushButton()
        self._header.setFlat(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet(
            "QPushButton { text-align: left; padding: 3px 6px; font-weight: bold; }"
        )
        self._header.clicked.connect(self._toggle_collapse)
        layout.addWidget(self._header)

        # QListView
        self._model = ThumbnailModel(self)
        self._model.set_assets(assets)

        self._view = FolderListView()
        self._view.setModel(self._model)
        self._view.setItemDelegate(delegate)
        self._view.setViewMode(QListView.ViewMode.IconMode)
        self._view.setFlow(QListView.Flow.LeftToRight)
        self._view.setWrapping(True)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setMovement(QListView.Movement.Static)
        self._view.setUniformItemSizes(False)
        self._view.setGridSize(QSize(thumb_size + 16, thumb_size + 70))
        self._view.setSpacing(4)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self._view.setMouseTracking(True)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.setStyleSheet("QListView { border: none; }")
        layout.addWidget(self._view)

        self._set_collapsed(collapsed, animate=False)

    @property
    def view(self) -> FolderListView:
        return self._view

    @property
    def folder_model(self) -> "ThumbnailModel":
        return self._model

    @property
    def folder(self) -> str:
        return self._folder

    @property
    def is_collapsed(self) -> bool:
        return not self._view.isVisible()

    def _set_collapsed(self, collapsed: bool, animate=True):
        self._view.setVisible(not collapsed)
        n = self._model.rowCount()
        arrow = "▶" if collapsed else "▼"
        self._header.setText(f"{arrow}  {self._short}  ({n})")

    def _toggle_collapse(self):
        new_state = not self.is_collapsed
        self._set_collapsed(new_state)
        self.collapsed_changed.emit(self._folder, new_state)

    def update_grid_size(self, thumb_size: int):
        self._thumb_size = thumb_size
        self._view.setGridSize(QSize(thumb_size + 16, thumb_size + 70))
        self._view.updateGeometry()


# ---------------------------------------------------------------------------
# Asset Browser — main widget
# ---------------------------------------------------------------------------

class AssetBrowser(QWidget):
    asset_selected = Signal(str)
    asset_preview = Signal(str)
    asset_to_canvas = Signal(str)
    asset_to_censor = Signal(str)
    asset_to_tray = Signal(str)
    thumb_loaded = Signal(str, QPixmap)
    folder_opened = Signal(str)
    tags_modified = Signal()
    selection_changed = Signal(list)
    tag_bar_toggled = Signal(bool)  # emitted when toolbar filter btn changes

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_browser")
        self.project = project
        self._selected_ids: set[str] = set()
        self._thumb_cache = ThumbCache()
        self._thumb_cache.connect_ready(self._on_thumb_ready)
        self._thumb_cache.connect_visual_tags(self._on_visual_tags)
        self._filtered_assets: list[Asset] = []
        settings = QSettings("DoxyEdit", "DoxyEdit")
        self._thumb_size = max(80, min(320, int(settings.value("thumb_size", THUMB_SIZE))))
        self.hover_preview_enabled = True
        self._eye_hidden_tags: set[str] = set()
        self._temp_hidden_ids: set[str] = set()  # Alt+H temporary hide (not saved)
        self._bar_tag_filters: set[str] = set()  # tag bar filter toggles
        self.auto_tag_enabled = False
        self.show_hidden_only = False
        self._collapsed_folders: set[str] = set()
        self._folder_filter: set[str] | None = None  # None = show all
        self._folder_sections: list[FolderSection] = []
        self._current_font_size = 10
        self._hover_id = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(int(settings.value("hover_delay_ms", 400)))
        self._hover_timer.timeout.connect(self._show_hover)
        self._hover_size_pct = int(settings.value("hover_size_pct", 150))
        self._hover_fixed_px = int(settings.value("hover_fixed_px", 0))  # 0 = use pct
        self._cache_all_total = 0
        self._cache_all_done = 0
        self.setAcceptDrops(True)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Row 1: import + filters (FlowLayout so buttons wrap on narrow windows)
        self._toolbar_widget = FlowWidget()
        self._toolbar_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        toolbar = FlowLayout(self._toolbar_widget, spacing=4)
        toolbar.setContentsMargins(0, 0, 0, 0)

        # Tags + Tray toggles — first items
        self._tags_btn = QPushButton("Tags")
        self._tags_btn.setCheckable(True)
        self._tags_btn.setChecked(True)
        self._tags_btn.setStyleSheet(self._btn_style())
        toolbar.addWidget(self._tags_btn)
        self._tray_btn = QPushButton("Tray")
        self._tray_btn.setCheckable(True)
        self._tray_btn.setStyleSheet(self._btn_style())
        toolbar.addWidget(self._tray_btn)

        for label, handler in [("+ Folder", self.open_folder_dialog), ("+ Files", self.add_images_dialog)]:
            btn = QPushButton(label)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)

        self.filter_starred = self._make_filter_btn("Starred")
        self.filter_starred.setToolTip("Show only starred images")
        self.filter_untagged = self._make_filter_btn("Untagged")
        self.filter_untagged.setToolTip("Show only images with no tags")
        self.filter_tagged = self._make_filter_btn("Tagged")
        self.filter_tagged.setToolTip("Show only tagged images")
        self.filter_assigned = self._make_filter_btn("Assigned")
        self.filter_assigned.setToolTip("Show only assets assigned to a platform")
        self.filter_posted = self._make_filter_btn("Posted")
        self.filter_posted.setToolTip("Show only assets with a posted platform status")
        self.filter_needs_censor = self._make_filter_btn("Needs Censor")
        self.filter_needs_censor.setToolTip("Show assets assigned to censor-required platforms with no censor regions")
        toolbar.addWidget(self.filter_starred)
        toolbar.addWidget(self.filter_untagged)
        toolbar.addWidget(self.filter_tagged)
        toolbar.addWidget(self.filter_assigned)
        toolbar.addWidget(self.filter_posted)
        toolbar.addWidget(self.filter_needs_censor)


        self.filter_show_ignored = QPushButton("Show Ignored")
        self.filter_show_ignored.setCheckable(True)
        self.filter_show_ignored.setChecked(False)
        self.filter_show_ignored.setStyleSheet(self._btn_style())
        self.filter_show_ignored.toggled.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_show_ignored)


        self.recursive_check = QCheckBox("Recursive")
        self.recursive_check.setChecked(False)
        toolbar.addWidget(self.recursive_check)

        self.hover_check = QCheckBox("Hover Preview")
        self.hover_check.setChecked(True)
        self.hover_check.toggled.connect(lambda v: setattr(self, 'hover_preview_enabled', v))
        toolbar.addWidget(self.hover_check)

        self.cache_all_check = QCheckBox("Cache All")
        self.cache_all_check.setChecked(False)
        self.cache_all_check.toggled.connect(self._on_cache_all_toggled)
        toolbar.addWidget(self.cache_all_check)

        self.folder_scan_check = QCheckBox("Folder Scan")
        self.folder_scan_check.setChecked(False)
        self.folder_scan_check.setToolTip("Auto-detect new images in imported folders")
        self.folder_scan_check.toggled.connect(self._on_folder_scan_toggled)
        toolbar.addWidget(self.folder_scan_check)
        self._folder_scan_timer = QTimer(self)
        self._folder_scan_timer.setInterval(5000)  # scan every 5 seconds
        self._folder_scan_timer.timeout.connect(self._scan_folders)

        self.count_label = QLabel("0 assets")  # shown in status bar by window

        root.addWidget(self._toolbar_widget)

        # Row 2: search + sort
        row2 = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_filter_changed)
        row2.addWidget(self.search_box, 1)

        self._fold_all_btn = QPushButton("Collapse All")
        self._fold_all_btn.setStyleSheet(self._btn_style())
        self._fold_all_btn.setToolTip("Collapse all folders")
        self._fold_all_btn.clicked.connect(self._collapse_all_folders)
        self._fold_all_btn.setVisible(False)
        row2.addWidget(self._fold_all_btn)
        self._unfold_all_btn = QPushButton("Expand All")
        self._unfold_all_btn.setStyleSheet(self._btn_style())
        self._unfold_all_btn.setToolTip("Expand all folders")
        self._unfold_all_btn.clicked.connect(self._expand_all_folders)
        self._unfold_all_btn.setVisible(False)
        row2.addWidget(self._unfold_all_btn)

        self.search_tags_check = QCheckBox("Tags")
        self.search_tags_check.setChecked(False)
        self.search_tags_check.toggled.connect(self._on_search_mode_changed)
        row2.addWidget(self.search_tags_check)

        self.filter_has_notes = QCheckBox("Notes")
        self.filter_has_notes.setChecked(False)
        self.filter_has_notes.toggled.connect(self._on_filter_changed)
        row2.addWidget(self.filter_has_notes)

        row2.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name A-Z", "Name Z-A", "Newest", "Oldest", "Largest", "Smallest", "Starred First", "Most Tagged", "By Folder"])
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.sort_combo.currentTextChanged.connect(self._on_sort_mode_changed)
        row2.addWidget(self.sort_combo)

        self._tag_bar_toggle_btn = QPushButton("▼ Filters")
        self._tag_bar_toggle_btn.setCheckable(True)
        self._tag_bar_toggle_btn.setChecked(True)
        self._tag_bar_toggle_btn.setStyleSheet(self._btn_style())
        self._tag_bar_toggle_btn.setToolTip("Show/hide the tag filter bar")
        self._tag_bar_toggle_btn.toggled.connect(self._on_tag_bar_toggle)
        row2.addWidget(self._tag_bar_toggle_btn)

        root.addLayout(row2)

        # Row 3: Quick-tag bar
        self._tag_bar_frame = FlowWidget()
        self._tag_bar_frame.setStyleSheet("border-bottom: 1px solid rgba(128,128,128,0.15);")
        self._tag_bar_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._tag_flow = FlowLayout(self._tag_bar_frame, spacing=4)
        self._tag_flow.setContentsMargins(0, 2, 0, 2)
        self._tag_buttons: list[tuple[QPushButton, str]] = []
        self._tag_button_map: dict[str, QPushButton] = {}  # tag_id → button, O(1) lookup
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setToolTip("Add a custom tag")
        self._add_tag_btn.clicked.connect(self._add_custom_tag)
        self._clear_filter_btn = QPushButton("✕ Clear Filters")
        self._clear_filter_btn.setToolTip("Clear all active tag bar filters (Escape)")
        self._clear_filter_btn.setStyleSheet(self._btn_style())
        self._clear_filter_btn.clicked.connect(self.clear_bar_filters)
        self._clear_filter_btn.setVisible(False)
        self._rebuild_tag_buttons()
        self._tag_flow.addWidget(self._add_tag_btn)
        self._tag_flow.addWidget(self._clear_filter_btn)
        self._apply_tag_button_styles()
        root.addWidget(self._tag_bar_frame)

        # QListView — replaces QGridLayout + ThumbnailWidget
        self._model = ThumbnailModel(self)
        self._delegate = ThumbnailDelegate(self._thumb_size, self)
        self._list_view = QListView()
        self._delegate._list_view = self._list_view
        self._list_view.setObjectName("doxyedit_grid")
        self._list_view.setModel(self._model)
        self._list_view.setItemDelegate(self._delegate)
        self._list_view.setViewMode(QListView.ViewMode.IconMode)
        self._list_view.setFlow(QListView.Flow.LeftToRight)
        self._list_view.setWrapping(True)
        self._list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_view.setMovement(QListView.Movement.Static)
        self._list_view.setUniformItemSizes(False)  # True causes paint artifacts in IconMode
        self._list_view.setGridSize(QSize(self._thumb_size + 16, self._thumb_size + 70))
        self._list_view.setSpacing(4)
        self._list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.verticalScrollBar().setSingleStep(20)
        self._list_view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self._list_view.setMouseTracking(True)
        self._list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu_pos)
        self._list_view.doubleClicked.connect(self._on_double_click)
        self._list_view.selectionModel().selectionChanged.connect(self._on_selection_changed_internal)
        self._list_view.setStyleSheet("QListView { border: none; }")
        self._list_view.installEventFilter(self)
        self._list_view.viewport().installEventFilter(self)

        # Folder scroll area (page 1 of the stack) — built lazily in _refresh_grid
        self._folder_container = QWidget()
        self._folder_container_layout = QVBoxLayout(self._folder_container)
        self._folder_container_layout.setContentsMargins(0, 0, 0, 0)
        self._folder_container_layout.setSpacing(4)
        self._folder_container_layout.addStretch()

        self._folder_scroll = QScrollArea()
        self._folder_scroll.setWidget(self._folder_container)
        self._folder_scroll.setWidgetResizable(True)
        self._folder_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._folder_scroll.verticalScrollBar().setSingleStep(20)

        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._list_view)    # page 0: normal view
        self._view_stack.addWidget(self._folder_scroll) # page 1: folder groups
        root.addWidget(self._view_stack)

        # Status line
        status = QHBoxLayout()
        status.addStretch()
        self.page_label = QLabel("")
        status.addWidget(self.page_label)
        status.addStretch()
        root.addLayout(status)

    @property
    def active_view(self) -> QListView:
        """Return the currently active QListView (single view now; per-folder view later)."""
        return self._list_view

    def _btn_style(self):
        f = self._current_font_size
        pad = max(3, f // 3)
        pad_lg = max(6, f // 2)
        return f"QPushButton {{ padding: {pad}px {pad_lg}px; font-size: {f}px; }}"

    def _make_filter_btn(self, label):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setStyleSheet(self._btn_style())
        btn.toggled.connect(self._on_filter_changed)
        return btn

    # --- Tag bar ---

    def _rebuild_tag_buttons(self):
        # Remove all items except _add_tag_btn and _clear_filter_btn (created once in _build)
        keep = {self._add_tag_btn, self._clear_filter_btn}
        i = 0
        while i < self._tag_flow.count():
            item = self._tag_flow.itemAt(i)
            if item and item.widget() and item.widget() not in keep:
                w = self._tag_flow.takeAt(i).widget()
                w.setParent(None)
                w.deleteLater()
            else:
                i += 1
        self._tag_buttons.clear()
        self._tag_button_map.clear()

        all_used = {t for a in self.project.assets for t in a.tags}
        all_tags = self.project.get_tags()
        bar_tags = {}
        for tid, preset in all_tags.items():
            if tid in TAG_PRESETS or tid in TAG_SIZED:
                continue
            if tid in all_used or tid in getattr(self.project, 'tag_definitions', {}):
                bar_tags[tid] = preset
        color_idx = 0
        for t in sorted(all_used):
            if t not in bar_tags and t not in TAG_PRESETS and t not in TAG_SIZED:
                bar_tags[t] = TagPreset(id=t, label=t,
                    color=VINIK_COLORS[color_idx % len(VINIK_COLORS)])
                color_idx += 1

        shortcut_reverse = {v: k for k, v in TAG_SHORTCUTS.items()}
        for tag_id, preset in bar_tags.items():
            key = shortcut_reverse.get(tag_id, "")
            label = f"{preset.label}" + (f" [{key}]" if key else "")
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(tag_id in self._bar_tag_filters)
            btn.setProperty("tag_id", tag_id)
            btn.setToolTip(f"{preset.label} — click to filter view")
            btn.clicked.connect(lambda checked, tid=tag_id: self._toggle_bar_filter(tid))
            self._tag_buttons.append((btn, preset.color))
            self._tag_button_map[tag_id] = btn
            self._tag_flow.addWidget(btn)

    def rebuild_tag_bar(self):
        self._rebuild_tag_buttons()
        # _add_tag_btn and _clear_filter_btn are created once in _build; just re-append
        self._tag_flow.addWidget(self._add_tag_btn)
        self._clear_filter_btn.setVisible(bool(self._bar_tag_filters))
        self._tag_flow.addWidget(self._clear_filter_btn)
        self._apply_tag_button_styles()
        self._tag_flow.invalidate()
        self._tag_bar_frame.updateGeometry()

    def _add_custom_tag(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        parent = self.window()
        name, ok = QInputDialog.getText(parent, "New Tag", "Enter tag name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        tag_id = name  # preserve user's casing and spaces
        try:
            all_tags = self.project.get_tags()
        except Exception:
            all_tags = dict(TAG_ALL)
        if tag_id in all_tags:
            QMessageBox.information(parent, "Tag Exists",
                f"A tag called '{all_tags[tag_id].label}' already exists.")
            return
        color = next_tag_color(all_tags)
        self.project.tag_definitions[tag_id] = {"label": name, "color": color}
        self.project.custom_tags.append({"id": tag_id, "label": name, "color": color})
        self.rebuild_tag_bar()
        self.tags_modified.emit()
        self.window().status.showMessage(f"Added tag: {name}", 2000)

    def _apply_tag_button_styles(self, font_size: int = None):
        if font_size is not None:
            self._current_font_size = font_size
        font_size = self._current_font_size
        h = font_size + 14
        for btn, color in self._tag_buttons:
            btn.setFixedHeight(h)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color};"
                f" border: 1px solid {color}; border-radius: {h // 2}px;"
                f" padding: 2px 8px; font-size: {font_size}px; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {color}; color: rgba(0,0,0,0.8); }}"
                f"QPushButton:checked {{ background: {color}; color: rgba(0,0,0,0.85);"
                f" border-color: {color}; }}"
                f"QPushButton:checked:hover {{ background: {color}; }}")
        self._add_tag_btn.setFixedHeight(h)
        self._add_tag_btn.setFixedWidth(h)
        self._add_tag_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: rgba(128,128,128,0.6);"
            f" border: 1px dashed rgba(128,128,128,0.6); border-radius: {h // 2}px;"
            f" font-size: {font_size + 2}px; font-weight: bold; }}"
            f"QPushButton:hover {{ color: rgba(200,200,200,0.9); border-color: rgba(200,200,200,0.9); }}")

    def update_font_size(self, font_size: int):
        self._apply_tag_button_styles(font_size)
        self._delegate.font_size = font_size
        self._list_view.viewport().update()
        for section in self._folder_sections:
            section.view.viewport().update()

    # --- Filtering / sorting ---

    def _on_sort_mode_changed(self, text):
        is_folder = text == "By Folder"
        self._fold_all_btn.setVisible(is_folder)
        self._unfold_all_btn.setVisible(is_folder)
        self._view_stack.setCurrentIndex(1 if is_folder else 0)

    def _collapse_all_folders(self):
        for section in self._folder_sections:
            self._collapsed_folders.add(section.folder)
            section._set_collapsed(True)

    def _expand_all_folders(self):
        self._collapsed_folders.clear()
        for section in self._folder_sections:
            section._set_collapsed(False)

    def _on_folder_scan_toggled(self, checked):
        if checked:
            self._folder_scan_timer.start()
            self._scan_folders()  # scan immediately
        else:
            self._folder_scan_timer.stop()

    def _scan_folders(self):
        """Scan all known source folders for new images."""
        folders = set()
        for a in self.project.assets:
            folders.add(a.source_folder or str(Path(a.source_path).parent))
        existing = {a.source_path for a in self.project.assets}
        recursive = self.recursive_check.isChecked()
        total_added = 0
        for folder in folders:
            folder_path = Path(folder)
            if not folder_path.exists():
                continue
            files = folder_path.rglob("*") if recursive else folder_path.iterdir()
            for f in files:
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS and str(f) not in existing:
                    self.project.assets.append(Asset(
                        id=f.stem + "_" + str(len(self.project.assets)),
                        source_path=str(f), source_folder=str(f.parent),
                        tags=auto_suggest_tags(f.stem) if self.auto_tag_enabled else []))
                    existing.add(str(f))
                    total_added += 1
        if total_added:
            self._refresh_grid()
            self.tags_modified.emit()
            try:
                self.window().status.showMessage(f"Folder scan: added {total_added} new image(s)", 3000)
            except Exception:
                pass

    def _on_filter_changed(self, *_):
        self._refresh_grid()

    def _on_search_mode_changed(self, checked):
        self.search_box.setPlaceholderText("Search by tags..." if checked else "Search...")
        self._on_filter_changed()

    def _on_tag_bar_toggle(self, checked: bool):
        self._tag_bar_frame.setVisible(checked)
        self._tag_bar_toggle_btn.setText("▼ Filters" if checked else "▶ Filters")
        self.tag_bar_toggled.emit(checked)

    def toggle_tag_bar(self):
        self._tag_bar_toggle_btn.setChecked(not self._tag_bar_toggle_btn.isChecked())

    def _on_cache_all_toggled(self, checked):
        if checked:
            batch = [(a.id, a.source_path) for a in self.project.assets]
            # Count how many actually need caching
            need_cache = sum(1 for aid, _ in batch
                            if self._thumb_cache._gen_sizes.get(aid, 0) < THUMB_GEN_SIZE)
            if need_cache == 0:
                try:
                    self.window().status.showMessage("All thumbnails already cached", 2000)
                except Exception:
                    pass
                return
            self._cache_all_total = need_cache
            self._cache_all_done = 0
            self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)
            try:
                self.window().start_progress("Caching thumbnails", need_cache)
            except Exception:
                pass

    def set_folder_filter(self, folders: list[str] | None):
        """Restrict the grid to assets from specific folders. Pass None to show all."""
        self._folder_filter = set(folders) if folders else None
        self._refresh_grid()

    def _compute_filtered(self) -> list[Asset]:
        assets = list(self.project.assets)
        if self._folder_filter:
            assets = [a for a in assets
                      if (a.source_folder or str(Path(a.source_path).parent)) in self._folder_filter]
        query = self.search_box.text().strip().lower()
        if query:
            if self.search_tags_check.isChecked():
                assets = [a for a in assets if any(query in t.lower() for t in a.tags)]
            elif "*" in query or "?" in query:
                import fnmatch
                assets = [a for a in assets if fnmatch.fnmatch(Path(a.source_path).name.lower(), query)]
            else:
                assets = [a for a in assets if query in Path(a.source_path).name.lower()]
        if self.filter_starred.isChecked():
            assets = [a for a in assets if a.starred > 0]
        if self.filter_untagged.isChecked():
            assets = [a for a in assets if not a.tags]
        if self.filter_tagged.isChecked():
            assets = [a for a in assets if a.tags]
        if not self.filter_show_ignored.isChecked():
            assets = [a for a in assets if "ignore" not in a.tags]
        if self.filter_has_notes.isChecked():
            assets = [a for a in assets if a.notes and a.notes.strip()]
        if self.filter_assigned.isChecked():
            assets = [a for a in assets if a.assignments]
        if self.filter_posted.isChecked():
            assets = [a for a in assets if any(pa.status == "posted" for pa in a.assignments)]
        if self.filter_needs_censor.isChecked():
            from doxyedit.models import PLATFORMS as _PLATS
            censor_platforms = {pid for pid, p in _PLATS.items() if p.needs_censor}
            assets = [a for a in assets
                      if any(pa.platform in censor_platforms for pa in a.assignments)
                      and not a.censors]

        # Tag bar filter — show only assets with at least one active filter tag (OR logic)
        if self._bar_tag_filters:
            assets = [a for a in assets if self._bar_tag_filters & set(a.tags)]

        # Eye filter — hide images with any eye-hidden tags
        if self.show_hidden_only and self._eye_hidden_tags:
            assets = [a for a in assets if set(a.tags) & self._eye_hidden_tags]
        elif self._eye_hidden_tags:
            assets = [a for a in assets if not (set(a.tags) & self._eye_hidden_tags)]
        # Temp hide (Alt+H) — not persisted
        if self._temp_hidden_ids:
            assets = [a for a in assets if a.id not in self._temp_hidden_ids]

        sort_mode = self.sort_combo.currentText()
        if sort_mode == "By Folder":
            assets.sort(key=lambda a: (
                (a.source_folder or Path(a.source_path).parent.as_posix()).lower(),
                Path(a.source_path).stem.lower()))
            return assets  # collapse handled by FolderSection visibility

        # For stat-based sorts, batch all os.stat calls once (O(n)) before sort
        if sort_mode in ("Newest", "Oldest", "Largest", "Smallest"):
            mtime_cache: dict[str, float] = {}
            fsize_cache: dict[str, int] = {}
            for a in assets:
                try:
                    st = os.stat(a.source_path)
                    mtime_cache[a.id] = st.st_mtime
                    fsize_cache[a.id] = st.st_size
                except OSError:
                    mtime_cache[a.id] = 0
                    fsize_cache[a.id] = 0
            stat_funcs = {
                "Newest":   (lambda a: mtime_cache[a.id], True),
                "Oldest":   (lambda a: mtime_cache[a.id], False),
                "Largest":  (lambda a: fsize_cache[a.id], True),
                "Smallest": (lambda a: fsize_cache[a.id], False),
            }
            fn, rev = stat_funcs[sort_mode]
            assets.sort(key=fn, reverse=rev)
            return assets

        if sort_mode == "Starred First":
            assets.sort(key=lambda a: (0 if a.starred > 0 else 1, Path(a.source_path).stem.lower()))
            return assets

        if sort_mode == "Most Tagged":
            assets.sort(key=lambda a: (-len(a.tags), Path(a.source_path).stem.lower()))
            return assets

        key_funcs = {
            "Name A-Z": (lambda a: Path(a.source_path).stem.lower(), False),
            "Name Z-A": (lambda a: Path(a.source_path).stem.lower(), True),
        }
        if sort_mode in key_funcs:
            fn, rev = key_funcs[sort_mode]
            assets.sort(key=fn, reverse=rev)
        return assets

    def _refresh_grid(self):
        saved_ids = set(self._selected_ids)
        self.project.invalidate_index()
        self._filtered_assets = self._compute_filtered()

        if self.sort_combo.currentText() == "By Folder":
            self._rebuild_folder_sections(saved_ids)
        else:
            self._model.set_assets(self._filtered_assets)
            self._delegate._folder_starts = {}

            # Restore selection
            if saved_ids:
                sel = self._list_view.selectionModel()
                sel.blockSignals(True)
                for i in range(self._model.rowCount()):
                    idx = self._model.index(i)
                    asset = self._model.get_asset(idx)
                    if asset and asset.id in saved_ids:
                        sel.select(idx, sel.SelectionFlag.Select)
                sel.blockSignals(False)

            batch = [(a.id, a.source_path) for a in self._filtered_assets]
            self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)

        # Update counts
        total = len(self.project.assets)
        shown = len(self._filtered_assets)
        starred = sum(1 for a in self.project.assets if a.starred > 0)
        tagged = sum(1 for a in self.project.assets if a.tags)
        any_filter = (self._bar_tag_filters or self.search_box.text().strip()
                      or self.filter_starred.isChecked() or self.filter_untagged.isChecked()
                      or self.filter_tagged.isChecked() or self.filter_assigned.isChecked()
                      or self.filter_posted.isChecked() or self.filter_needs_censor.isChecked()
                      or self.filter_has_notes.isChecked())
        filtered_marker = "  ⬡ FILTERED" if (any_filter and shown < total) else ""
        self.count_label.setText(f"{shown}/{total} shown, {starred}★, {tagged} tagged{filtered_marker}")
        self.page_label.setText(f"{shown} images")

    def _rebuild_folder_sections(self, saved_ids=None):
        """Rebuild per-folder QListView sections from current filtered assets."""
        from collections import defaultdict

        # Group assets by folder (order preserved from sorted filtered list)
        groups: dict[str, list] = defaultdict(list)
        for a in self._filtered_assets:
            folder = a.source_folder or Path(a.source_path).parent.as_posix()
            groups[folder].append(a)

        # Remove old sections (keep layout's trailing stretch)
        for section in self._folder_sections:
            self._folder_container_layout.removeWidget(section)
            section.deleteLater()
        self._folder_sections.clear()

        # Build new sections
        for folder, assets in groups.items():
            collapsed = folder in self._collapsed_folders
            section = FolderSection(
                folder=folder,
                assets=assets,
                delegate=self._delegate,
                thumb_size=self._thumb_size,
                collapsed=collapsed,
                parent=self._folder_container,
            )
            section.collapsed_changed.connect(self._on_folder_collapsed)
            section.view.customContextMenuRequested.connect(
                lambda pos, s=section: self._on_folder_context_menu_pos(pos, s))
            section.view.doubleClicked.connect(self._on_folder_double_click)
            section.view.selectionModel().selectionChanged.connect(
                self._on_folder_selection_changed)
            section.view.installEventFilter(self)
            section.view.viewport().installEventFilter(self)

            # Insert before trailing stretch
            idx = max(0, self._folder_container_layout.count() - 1)
            self._folder_container_layout.insertWidget(idx, section)
            self._folder_sections.append(section)

        # Restore selection
        if saved_ids:
            for section in self._folder_sections:
                sel = section.view.selectionModel()
                sel.blockSignals(True)
                for i in range(section.folder_model.rowCount()):
                    idx = section.folder_model.index(i)
                    asset = section.folder_model.get_asset(idx)
                    if asset and asset.id in saved_ids:
                        sel.select(idx, sel.SelectionFlag.Select)
                sel.blockSignals(False)

        # Request thumbnails
        batch = [(a.id, a.source_path) for a in self._filtered_assets]
        self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)

        # Trigger layout recalc once views have been sized
        QTimer.singleShot(0, self._folder_container.adjustSize)

    def _on_folder_collapsed(self, folder: str, is_collapsed: bool):
        if is_collapsed:
            self._collapsed_folders.add(folder)
        else:
            self._collapsed_folders.discard(folder)

    def _on_folder_selection_changed(self):
        self._selected_ids = set()
        for section in self._folder_sections:
            for idx in section.view.selectionModel().selectedIndexes():
                asset = section.folder_model.get_asset(idx)
                if asset:
                    self._selected_ids.add(asset.id)
        id_list = list(self._selected_ids)
        self.selection_changed.emit(id_list)
        if len(id_list) == 1:
            self.asset_selected.emit(id_list[0])

    def _on_folder_double_click(self, index: QModelIndex):
        # Identify which section emitted this
        sender_view = self.sender()
        for section in self._folder_sections:
            if section.view is sender_view:
                asset = section.folder_model.get_asset(index)
                if asset:
                    self.asset_preview.emit(asset.id)
                return

    def _on_folder_context_menu_pos(self, pos, section: "FolderSection"):
        index = section.view.indexAt(pos)
        asset = section.folder_model.get_asset(index) if index.isValid() else None
        if asset:
            self._on_context_menu(asset.id, section.view.viewport().mapToGlobal(pos))

    # --- Thumb cache callbacks ---

    def _on_thumb_ready(self, asset_id: str, pixmap: QPixmap, w: int, h: int, gen_size: int):
        self._thumb_cache.on_ready(asset_id, pixmap, w, h, gen_size)
        self._model.update_pixmap(asset_id, pixmap)
        for section in self._folder_sections:
            section.folder_model.update_pixmap(asset_id, pixmap)
        self.thumb_loaded.emit(asset_id, pixmap)
        # Update progress bar if caching all
        if self._cache_all_total > 0:
            self._cache_all_done += 1
            try:
                self.window().update_progress(self._cache_all_done)
                if self._cache_all_done >= self._cache_all_total:
                    self.window().finish_progress(f"Cached {self._cache_all_total} thumbnails")
                    self._cache_all_total = 0
            except Exception:
                pass

    def _on_visual_tags(self, asset_id: str, vtags: list):
        if not self.auto_tag_enabled:
            return
        asset = self.project.get_asset(asset_id)
        if asset:
            for t in vtags:
                if t not in asset.tags:
                    asset.tags.append(t)

    # --- Selection ---

    def _on_selection_changed_internal(self, selected, deselected):
        indexes = self._list_view.selectionModel().selectedIndexes()
        self._selected_ids = {self._model.get_asset(idx).id
                              for idx in indexes if self._model.get_asset(idx)}
        id_list = list(self._selected_ids)
        self.selection_changed.emit(id_list)
        if len(id_list) == 1:
            self.asset_selected.emit(id_list[0])

    def _on_double_click(self, index: QModelIndex):
        asset = self._model.get_asset(index)
        if asset:
            self.asset_preview.emit(asset.id)

    def get_selected_assets(self) -> list:
        return [a for a in self.project.assets if a.id in self._selected_ids]

    # --- Tag bar filter ---

    def _sync_filter_btn(self, tag_id: str):
        btn = self._tag_button_map.get(tag_id)
        if btn:
            btn.blockSignals(True)
            btn.setChecked(tag_id in self._bar_tag_filters)
            btn.blockSignals(False)

    def _toggle_bar_filter(self, tag_id: str):
        if tag_id in self._bar_tag_filters:
            self._bar_tag_filters.discard(tag_id)
        else:
            self._bar_tag_filters.add(tag_id)
        self._sync_filter_btn(tag_id)
        self._clear_filter_btn.setVisible(bool(self._bar_tag_filters))
        self._refresh_grid()

    def clear_bar_filters(self):
        self._bar_tag_filters.clear()
        for tag_id in self._tag_button_map:
            self._sync_filter_btn(tag_id)
        self._clear_filter_btn.setVisible(False)
        self._refresh_grid()

    def _find_similar(self, asset):
        """Filter grid to assets sharing any tag with the given asset."""
        self._bar_tag_filters = set(asset.tags)
        for tag_id in self._tag_button_map:
            self._sync_filter_btn(tag_id)
        self._clear_filter_btn.setVisible(bool(self._bar_tag_filters))
        self._refresh_grid()

    # --- Public API ---

    def refresh(self):
        self._refresh_grid()

    def scroll_to_asset(self, asset_id: str):
        """Scroll the grid to show the given asset and select it."""
        for i, a in enumerate(self._filtered_assets):
            if a.id == asset_id:
                idx = self._model.index(i)
                self._list_view.scrollTo(idx, self._list_view.ScrollHint.PositionAtCenter)
                self._list_view.setCurrentIndex(idx)
                self._selected_ids = {asset_id}
                break

    def shutdown(self):
        self._thumb_cache.shutdown()

    # --- Import ---

    def open_folder_dialog(self):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        last_dir = settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Open Image Folder", last_dir)
        if folder:
            settings.setValue("last_folder", folder)
            from PySide6.QtWidgets import QMessageBox
            has_subdirs = any(p.is_dir() for p in Path(folder).iterdir())
            if has_subdirs and not self.recursive_check.isChecked():
                reply = QMessageBox.question(
                    self.window(), "Subfolders Found",
                    f"'{Path(folder).name}' contains subfolders.\n\nImport recursively?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                recursive = (reply == QMessageBox.StandardButton.Yes)
            else:
                recursive = self.recursive_check.isChecked()
            self.import_folder(folder, recursive=recursive)
            self.folder_opened.emit(folder)

    def _record_import_source(self, source_type: str, path: str, recursive: bool = False):
        """Record an import source so the project knows where its assets came from."""
        import datetime
        sources = self.project.import_sources
        # Update existing record for same path rather than duplicating
        for rec in sources:
            if rec.get("path") == path and rec.get("type") == source_type:
                rec["recursive"] = recursive
                rec["last_imported"] = datetime.datetime.now().isoformat(timespec="seconds")
                return
        sources.append({
            "type": source_type,
            "path": path,
            "recursive": recursive,
            "added_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "last_imported": datetime.datetime.now().isoformat(timespec="seconds"),
        })

    def import_folder(self, folder: str, recursive: bool = None):
        if recursive is None:
            recursive = self.recursive_check.isChecked()
        folder_path = Path(folder)
        existing = {a.source_path for a in self.project.assets}
        excluded = getattr(self.project, 'excluded_paths', set())
        count = 0
        files = sorted(folder_path.rglob("*") if recursive else folder_path.iterdir())
        for f in files:
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS and str(f) not in existing and str(f) not in excluded:
                self.project.assets.append(Asset(
                    id=f.stem + "_" + str(len(self.project.assets)),
                    source_path=str(f), source_folder=str(f.parent),
                    tags=auto_suggest_tags(f.stem) if self.auto_tag_enabled else []))
                count += 1
        self._record_import_source("folder", str(folder_path), recursive)
        if count:
            self._refresh_grid()
        return count

    def add_images_dialog(self):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        last_dir = settings.value("last_folder", "")
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Images", last_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg *.psd);;All Files (*)")
        self.import_files(files)

    def import_files(self, files: list[str]):
        existing = {a.source_path for a in self.project.assets}
        excluded = getattr(self.project, 'excluded_paths', set())
        added = 0
        first_id = None
        new_files = []
        for f in files:
            if f not in existing and f not in excluded and Path(f).suffix.lower() in IMAGE_EXTS:
                p = Path(f)
                aid = p.stem + "_" + str(len(self.project.assets))
                self.project.assets.append(Asset(
                    id=aid, source_path=f, source_folder=str(p.parent),
                    tags=auto_suggest_tags(p.stem) if self.auto_tag_enabled else []))
                if first_id is None:
                    first_id = aid
                added += 1
                new_files.append(f)
        for f in new_files:
            self._record_import_source("file", f)
        if added:
            self._refresh_grid()
            if first_id:
                self.scroll_to_asset(first_id)
        return added

    # --- Drag and drop ---

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files, folders = [], []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).is_dir():
                folders.append(path)
            elif Path(path).is_file():
                files.append(path)
        for folder in folders:
            self.import_folder(folder)
        if files:
            self.import_files(files)

    # --- Context menu ---

    def _on_context_menu_pos(self, pos):
        index = self._list_view.indexAt(pos)
        asset = self._model.get_asset(index) if index.isValid() else None
        if not asset:
            return
        self._on_context_menu(asset.id, self._list_view.viewport().mapToGlobal(pos))

    def _on_context_menu(self, asset_id: str, pos):
        asset = self.project.get_asset(asset_id)
        if not asset:
            return
        menu = QMenu(self)
        menu.addAction("Preview", lambda: self.asset_preview.emit(asset_id))
        n_sel = len(self._selected_ids)
        if n_sel > 1:
            menu.addAction(f"Send {n_sel} to Tray", lambda: [self.asset_to_tray.emit(aid) for aid in self._selected_ids])
            menu.addAction(f"Export {n_sel} Selected to Folder...", self._export_selected)
        else:
            menu.addAction("Send to Tray", lambda: self.asset_to_tray.emit(asset_id))
        menu.addAction("Send to Canvas", lambda: self.asset_to_canvas.emit(asset_id))
        menu.addAction("Send to Censor", lambda: self.asset_to_censor.emit(asset_id))
        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: _open_explorer(asset))
        menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(asset.source_path))
        menu.addAction("Copy Filename", lambda: QApplication.clipboard().setText(Path(asset.source_path).name))
        menu.addAction("Copy Name (no ext)", lambda: QApplication.clipboard().setText(Path(asset.source_path).stem))
        if n_sel > 1:
            sel_assets = self.get_selected_assets()
            menu.addAction(f"Copy All Paths ({n_sel})", lambda: QApplication.clipboard().setText(
                "\n".join(a.source_path for a in sel_assets)))
        menu.addSeparator()

        if asset.starred > 0:
            menu.addAction("Unstar", lambda: self._unstar(asset))
            menu.addAction("Cycle Star Color", lambda: self._toggle_star(asset))
        else:
            menu.addAction("Star", lambda: self._toggle_star(asset))

        # Current tags across all selected — click to remove (union of all tags)
        selected = self.get_selected_assets() or [asset]
        union_tags = []
        seen = set()
        for a in selected:
            for t in a.tags:
                if t not in seen:
                    union_tags.append(t)
                    seen.add(t)
        if union_tags:
            all_tags = self.project.get_tags()
            cur_menu = menu.addMenu(f"Tags ({len(union_tags)})")
            for t in union_tags:
                label = all_tags[t].label if t in all_tags else t
                cur_menu.addAction(f"\u2212 {label}", lambda tid=t: self._remove_tag_from_selected(tid))

        menu.addSeparator()
        n = len(self._selected_ids)
        if n > 1:
            menu.addAction(f"Star All ({n})", self._star_all_selected)
            menu.addAction(f"Unstar All ({n})", self._unstar_all_selected)
            menu.addSeparator()
        # Quick Tag submenu — all available tags in columns
        all_tags = list(self.project.get_tags().values())
        if all_tags:
            qt_menu = menu.addMenu("Quick Tag")
            MAX_PER_COL = 10
            if len(all_tags) <= MAX_PER_COL:
                for tag in all_tags:
                    checked = tag.id in asset.tags
                    a = qt_menu.addAction(f"{'✓ ' if checked else '   '}{tag.label}")
                    a.triggered.connect(lambda _, tid=tag.id: self._toggle_tag_multi(asset, tid))
            else:
                # Split into column submenus
                for col_start in range(0, len(all_tags), MAX_PER_COL):
                    chunk = all_tags[col_start:col_start + MAX_PER_COL]
                    first, last = chunk[0].label, chunk[-1].label
                    col_menu = qt_menu.addMenu(f"{first} – {last}")
                    for tag in chunk:
                        checked = tag.id in asset.tags
                        a = col_menu.addAction(f"{'✓ ' if checked else '   '}{tag.label}")
                        a.triggered.connect(lambda _, tid=tag.id: self._toggle_tag_multi(asset, tid))

        menu.addAction("Add Tag...", lambda: self._add_tag_dialog(asset))
        if asset.tags:
            menu.addAction("Find Similar Assets", lambda: self._find_similar(asset))
        # Platform status update submenu
        if asset.assignments:
            from doxyedit.models import PostStatus as _PS
            status_menu = menu.addMenu(f"Update Status ({len(asset.assignments)} assignments)")
            for pa in asset.assignments:
                sub = status_menu.addMenu(f"{pa.platform} / {pa.slot} [{pa.status}]")
                for s in (_PS.PENDING, _PS.READY, _PS.POSTED, _PS.SKIP):
                    label = f"{'✓ ' if pa.status == s else ''}{s}"
                    sub.addAction(label, lambda _pa=pa, _s=s: self._set_assignment_status(_pa, _s))

        # Platform assignment submenu
        from doxyedit.models import PLATFORMS as _PLATS, PlatformAssignment, PostStatus
        if self.project.platforms:
            assign_menu = menu.addMenu("Assign to Platform")
            sel_assets = self.get_selected_assets() or [asset]
            for pid in self.project.platforms:
                plat = _PLATS.get(pid)
                if not plat:
                    continue
                p_menu = assign_menu.addMenu(plat.name)
                for slot in plat.slots:
                    def _assign(checked, _pid=pid, _slot=slot.name, _assets=sel_assets):
                        for a in _assets:
                            existing = next((pa for pa in a.assignments
                                            if pa.platform == _pid and pa.slot == _slot), None)
                            if not existing:
                                a.assignments.append(PlatformAssignment(
                                    platform=_pid, slot=_slot, status=PostStatus.PENDING))
                        self._refresh_grid()
                        try:
                            self.window()._dirty = True
                        except Exception:
                            pass
                    already = any(pa.platform == pid and pa.slot == slot.name
                                  for a in sel_assets for pa in a.assignments)
                    p_menu.addAction(f"{'✓ ' if already else ''}{slot.label}", _assign)
        menu.addAction("Remove from Project", lambda: self._remove_asset(asset))
        menu.exec(pos)

    def _set_assignment_status(self, pa, status: str):
        pa.status = status
        self._refresh_grid()
        try:
            self.window()._dirty = True
        except Exception:
            pass

    def _export_selected(self):
        assets = self.get_selected_assets()
        if not assets:
            return
        folder = QFileDialog.getExistingDirectory(self.window(), "Export Selected Assets To...")
        if not folder:
            return
        import shutil
        dest = Path(folder)
        ok, failed = 0, 0
        for a in assets:
            src = Path(a.source_path)
            if src.exists():
                try:
                    shutil.copy2(src, dest / src.name)
                    ok += 1
                except Exception:
                    failed += 1
        try:
            msg = f"Exported {ok} file(s) to {folder}"
            if failed:
                msg += f" ({failed} failed)"
            self.window().status.showMessage(msg, 4000)
        except Exception:
            pass

    def _add_tag_dialog(self, asset):
        from PySide6.QtWidgets import QInputDialog
        tag, ok = QInputDialog.getText(self.window(), "Add Tag", "Tag to add:")
        if ok and tag.strip():
            tag_id = tag.strip()  # preserve user's casing and spaces
            # Apply to all selected if multiple selected
            assets = self.get_selected_assets() or [asset]
            for a in assets:
                if tag_id not in a.tags:
                    a.tags.append(tag_id)
            self.selection_changed.emit(list(self._selected_ids))
            self.tags_modified.emit()

    def _toggle_star(self, asset):
        asset.cycle_star()
        self._refresh_grid()

    def _unstar(self, asset):
        asset.starred = 0
        self._refresh_grid()

    def _toggle_tag(self, asset, tag_id):
        toggle_tags([asset], tag_id)
        self._refresh_grid()
        self.selection_changed.emit(list(self._selected_ids))

    def _remove_tag_from_selected(self, tag_id):
        """Remove a tag from all selected assets."""
        assets = self.get_selected_assets()
        for a in assets:
            if tag_id in a.tags:
                a.tags.remove(tag_id)
        self._refresh_grid()
        self.selection_changed.emit(list(self._selected_ids))
        self.tags_modified.emit()

    def _toggle_tag_multi(self, asset, tag_id):
        """Toggle tag on all selected assets (or just the clicked one)."""
        assets = self.get_selected_assets() or [asset]
        toggle_tags(assets, tag_id)
        self._refresh_grid()
        self.selection_changed.emit(list(self._selected_ids))
        self.tags_modified.emit()

    def _star_all_selected(self):
        for a in self.project.assets:
            if a.id in self._selected_ids:
                a.starred = 1
        self._refresh_grid()

    def _unstar_all_selected(self):
        for a in self.project.assets:
            if a.id in self._selected_ids:
                a.starred = 0
        self._refresh_grid()

    def _remove_asset(self, asset):
        self.project.assets = [a for a in self.project.assets if a.id != asset.id]
        if asset.id in self._selected_ids:
            self._selected_ids.remove(asset.id)
        self._refresh_grid()

    # --- Hover preview ---

    def _hover_px(self) -> int:
        """Return hover preview size in pixels (fixed or pct-based)."""
        if self._hover_fixed_px > 0:
            return self._hover_fixed_px
        return max(300, int(self._thumb_size * self._hover_size_pct / 100))

    def _show_hover(self):
        if not self._hover_id or not self.hover_preview_enabled:
            return
        asset = self.project.get_asset(self._hover_id)
        if asset:
            HoverPreview.instance().PREVIEW_SIZE = self._hover_px()
            HoverPreview.instance().show_for(asset.source_path, QCursor.pos())

    # --- Zoom (event filter intercepts Ctrl+Scroll on the list view) ---

    def _view_for_obj(self, obj):
        """Return (view, model) if obj is a managed view or its viewport, else (None, None)."""
        if obj is self._list_view or obj is self._list_view.viewport():
            return self._list_view, self._model
        for section in self._folder_sections:
            v = section.view
            if obj is v or obj is v.viewport():
                return v, section.folder_model
        return None, None

    def eventFilter(self, obj, event):
        view, model = self._view_for_obj(obj)
        vp = view.viewport() if view is not None else None
        if view is not None:
            # Ctrl+Scroll zoom
            if event.type() == event.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    current = view.currentIndex()
                    delta = event.angleDelta().y()
                    if delta > 0:
                        self._thumb_size = min(320, self._thumb_size + 20)
                    else:
                        self._thumb_size = max(80, self._thumb_size - 20)
                    QSettings("DoxyEdit", "DoxyEdit").setValue("thumb_size", self._thumb_size)
                    self._delegate.thumb_size = self._thumb_size
                    self._delegate.invalidate_cache()  # full clear on zoom change
                    self._list_view.setGridSize(QSize(self._thumb_size + 16, self._thumb_size + 70))
                    for section in self._folder_sections:
                        section.update_grid_size(self._thumb_size)
                    if current.isValid():
                        view.scrollTo(current, QListView.ScrollHint.PositionAtCenter)
                    return True

            # Star click — detect click in star area of a thumbnail
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = view.indexAt(pos)
                if index.isValid():
                    item_rect = view.visualRect(index)
                    ts = self._delegate.thumb_size
                    star_rect = QRect(item_rect.right() - 24, item_rect.y() + ts + 34, 22, 22)
                    if star_rect.contains(pos):
                        asset = model.get_asset(index)
                        if asset:
                            asset.cycle_star()
                            model.dataChanged.emit(index, index)
                        return True

            # Middle-click — instant preview regardless of hover setting
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.MiddleButton:
                    self._hover_timer.stop()
                    self._middle_held = True
                    pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                    index = view.indexAt(pos)
                    asset = model.get_asset(index) if index.isValid() else None
                    if asset:
                        hp = HoverPreview.instance()
                        hp.PREVIEW_SIZE = self._hover_px()
                        hp.show_for(asset.source_path, QCursor.pos())
                    return True

            if event.type() == event.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.MiddleButton:
                    self._middle_held = False
                    HoverPreview.instance().hide_preview()
                    return True

            # Middle-drag — update preview as you drag over thumbnails
            if (event.type() == event.Type.MouseMove
                    and getattr(self, '_middle_held', False)):
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = view.indexAt(pos)
                asset = model.get_asset(index) if index.isValid() else None
                if asset and asset.id != self._hover_id:
                    self._hover_id = asset.id
                    hp = HoverPreview.instance()
                    hp.PREVIEW_SIZE = self._hover_px()
                    hp.show_for(asset.source_path, QCursor.pos())
                return True

            # Hover preview (skip if middle button held)
            if (event.type() == event.Type.MouseMove
                    and self.hover_preview_enabled
                    and not getattr(self, '_middle_held', False)):
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = view.indexAt(pos)
                asset = model.get_asset(index) if index.isValid() else None
                if asset and asset.id != self._hover_id:
                    self._hover_id = asset.id
                    HoverPreview.instance().hide_preview()
                    self._hover_timer.start()
                elif not asset:
                    self._hover_id = None
                    self._hover_timer.stop()
                    HoverPreview.instance().hide_preview()

            if event.type() == event.Type.Leave:
                self._hover_id = None
                self._hover_timer.stop()
                HoverPreview.instance().hide_preview()

            # Delete key — pass to window's handler
            if event.type() == event.Type.KeyPress:
                if event.key() == Qt.Key.Key_Delete:
                    try:
                        self.window()._handle_delete()
                    except Exception:
                        pass
                    return True

        return super().eventFilter(obj, event)

    # --- Keyboard ---

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F5:
            self._thumb_cache.clear()
            self._delegate.invalidate_cache()
            self._refresh_grid()
            self.window().status.showMessage("Recaching thumbnails...", 2000)
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._bar_tag_filters:
                self.clear_bar_filters()
                self.window().status.showMessage("Tag filters cleared", 1500)
                return
        super().keyPressEvent(event)


# --- Helpers ---

def _mtime(asset: Asset) -> float:
    try:
        return os.path.getmtime(asset.source_path)
    except OSError:
        return 0

def _fsize(asset: Asset) -> int:
    try:
        return os.path.getsize(asset.source_path)
    except OSError:
        return 0

def _open_explorer(asset: Asset):
    path = asset.source_path.replace("/", "\\")
    subprocess.Popen(f'explorer /select,"{path}"')
