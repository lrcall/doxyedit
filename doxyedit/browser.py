"""Asset browser — QListView with custom delegate for high-performance thumbnail grid."""
import fnmatch
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QStyledItemDelegate,
    QLabel, QPushButton, QFileDialog, QFrame, QLineEdit, QComboBox,
    QMenu, QApplication, QSizePolicy, QStyle, QCheckBox,
    QStackedWidget, QScrollArea, QSlider, QMessageBox, QInputDialog,
    QDialog,
)
from PySide6.QtCore import (
    Qt, Signal, QThread, QTimer, QSettings, QSize, QRect, QPoint, QPointF,
    QAbstractListModel, QModelIndex, QItemSelectionModel, QMimeData, QUrl, QEvent,
)
from PySide6.QtGui import (
    QPixmap, QFont, QColor, QCursor, QPainter, QPen, QFontMetrics, QPainterPath,
    QDrag, QMouseEvent,
)

from doxyedit.models import (
    Asset, Project, TAG_PRESETS, TAG_SIZED, TAG_ALL, TAG_SHORTCUTS,
    TagPreset, toggle_tags, next_tag_color, STAR_COLORS, VINIK_COLORS,
)
from doxyedit.preview import HoverPreview
from doxyedit.thumbcache import ThumbCache, THUMB_SIZE

from PySide6.QtWidgets import QLayout, QProgressDialog

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".svg", ".tiff", ".tif",
    ".psd", ".psb", ".sai", ".sai2", ".clip", ".csp", ".kra", ".xcf", ".ora",
    ".ico", ".cur", ".dds", ".tga", ".exr", ".hdr",
}
THUMB_GEN_SIZE = 512
DEFAULT_PAGE_SIZE = 100
MIN_THUMB_SIZE = 80
MAX_THUMB_SIZE = 512
DEFAULT_FONT_SIZE = 12

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
# Date-filter dialog shown when adding a folder interactively
# ---------------------------------------------------------------------------

from PySide6.QtWidgets import QDialog, QDateEdit
from PySide6.QtCore import QDate
from doxyedit.themes import ui_font_size


class _ImportOptionsDialog(QDialog):
    """Import options: recursive scan, date filter."""

    def __init__(self, has_subdirs: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Options")
        layout = QVBoxLayout(self)

        self._recursive = QCheckBox("Include subfolders (recursive)")
        self._recursive.setChecked(has_subdirs)
        layout.addWidget(self._recursive)

        self._use_date = QCheckBox("Only import files newer than:")
        layout.addWidget(self._use_date)
        self._date = QDateEdit(QDate.currentDate().addDays(-1))
        self._date.setCalendarPopup(True)
        self._date.setEnabled(False)
        self._use_date.toggled.connect(self._date.setEnabled)
        layout.addWidget(self._date)

        btns = QHBoxLayout()
        ok = QPushButton("Import")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    @property
    def recursive(self) -> bool:
        return self._recursive.isChecked()

    @property
    def filter_date(self) -> str:
        if self._use_date.isChecked():
            return self._date.date().toString("yyyy-MM-dd") + "T00:00:00"
        return ""


class _DateFilterDialog(QDialog):
    """Edit date filter on an existing import source folder."""

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Date Filter")
        layout = QVBoxLayout(self)
        self._use_date = QCheckBox("Only include files newer than:")
        layout.addWidget(self._use_date)
        if current:
            self._date = QDateEdit(QDate.fromString(current[:10], "yyyy-MM-dd"))
            self._use_date.setChecked(True)
        else:
            self._date = QDateEdit(QDate.currentDate().addDays(-1))
        self._date.setCalendarPopup(True)
        self._date.setEnabled(self._use_date.isChecked())
        self._use_date.toggled.connect(self._date.setEnabled)
        layout.addWidget(self._date)
        btns = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    @property
    def filter_date(self) -> str:
        if self._use_date.isChecked():
            return self._date.date().toString("yyyy-MM-dd") + "T00:00:00"
        return ""


# ---------------------------------------------------------------------------
# Background folder scanner — avoids blocking the UI on large folder imports
# ---------------------------------------------------------------------------

class FolderScanWorker(QThread):
    """Discovers image files in a folder tree without blocking the UI."""
    progress = Signal(int)      # running count of files found
    batch_ready = Signal(list)  # list[str] of new file paths, emitted in chunks
    finished = Signal(int)      # total count when scan is done

    BATCH_SIZE = 500

    def __init__(self, folder: str, recursive: bool,
                 existing: frozenset, excluded: frozenset, exts: set, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._recursive = recursive
        self._existing = existing
        self._excluded = excluded
        self._exts = exts
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        folder_path = Path(self._folder)
        it = folder_path.rglob("*") if self._recursive else folder_path.iterdir()
        batch: list[str] = []
        total = 0
        try:
            for f in it:
                if self._cancelled:
                    break
                if (f.is_file()
                        and f.suffix.lower() in self._exts
                        and str(f) not in self._existing
                        and str(f) not in self._excluded
                        and str(f.parent) not in self._excluded):
                    batch.append(str(f))
                    total += 1
                    if len(batch) >= self.BATCH_SIZE:
                        self.batch_ready.emit(list(batch))
                        self.progress.emit(total)
                        batch = []
        except Exception:
            pass
        if batch:
            self.batch_ready.emit(list(batch))
        self.finished.emit(total)


class _ScanWorker(QThread):
    """Generic worker that runs a callable in a thread and emits the result."""
    done = Signal(list)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        result = self._fn()
        self.done.emit(result if result is not None else [])


# ---------------------------------------------------------------------------
# FlowLayout for tag bar (kept — only used for pill buttons, not thumbnails)
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """Simple flow layout that wraps widgets like text.

    Accepts either a single ``spacing`` (used for both axes) or separate
    ``hspacing`` / ``vspacing`` values.
    """

    def __init__(self, parent=None, spacing=4, *, hspacing=None, vspacing=None):
        super().__init__(parent)
        self._items = []
        self._hspacing = hspacing if hspacing is not None else spacing
        self._vspacing = vspacing if vspacing is not None else spacing

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
                y += row_height + self._vspacing
                row_height = 0
            if not dry_run:
                item.setGeometry(QRect(x, y, w, h))
            x += w + self._hspacing
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
    PostStatusRole = Qt.ItemDataRole.UserRole + 7   # social post status: "draft"|"queued"|"posted"|None
    StudioEditedRole = Qt.ItemDataRole.UserRole + 8  # bool: has censors or overlays
    ReadinessRole = Qt.ItemDataRole.UserRole + 9  # dict[str, str] platform_id -> status
    GroupInfoRole = Qt.ItemDataRole.UserRole + 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._assets: list[Asset] = []
        self._pixmaps: dict[str, QPixmap] = {}
        self._id_to_row: dict[str, int] = {}  # O(1) lookup for update_pixmap
        self._post_status_map: dict[str, str] = {}  # asset_id -> best social post status
        self._readiness_cache: dict[str, dict] = {}

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
        elif role == self.PostStatusRole:
            return self._post_status_map.get(asset.id)
        elif role == self.StudioEditedRole:
            return bool(asset.censors or asset.overlays)
        elif role == self.ReadinessRole:
            return self._readiness_cache.get(asset.id)
        elif role == self.GroupInfoRole:
            return (asset.specs.get("duplicate_group", ""),
                    asset.specs.get("variant_set", ""),
                    asset.id)
        return None

    def update_post_status(self, posts):
        """Build asset_id -> best social post status map from project posts."""
        self._post_status_map.clear()
        priority = {"posted": 3, "queued": 2, "draft": 1}
        for p in posts:
            status = p.status if isinstance(p.status, str) else str(p.status)
            for aid in p.asset_ids:
                existing = self._post_status_map.get(aid)
                if not existing or priority.get(status, 0) > priority.get(existing, 0):
                    self._post_status_map[aid] = status

    def update_readiness(self, project, default_platforms: list[str]):
        """Compute readiness for all assets. Call after project changes."""
        from doxyedit.pipeline import check_readiness
        from doxyedit.models import PLATFORMS
        for asset in self._assets:
            if asset.id in self._readiness_cache:
                continue
            readiness = {}
            for pid in default_platforms:
                if pid in PLATFORMS:
                    r = check_readiness(asset, pid, project)
                    readiness[pid] = r["status"]
            if readiness:
                self._readiness_cache[asset.id] = readiness

    def invalidate_readiness(self, asset_id: str = ""):
        if asset_id:
            self._readiness_cache.pop(asset_id, None)
        else:
            self._readiness_cache.clear()

    def set_assets(self, assets: list[Asset]):
        self.beginResetModel()
        self._assets = assets
        self._id_to_row = {a.id: i for i, a in enumerate(assets)}
        self.endResetModel()

    def update_pixmap(self, asset_id: str, pixmap: QPixmap):
        self._pixmaps[asset_id] = pixmap
        row = self._id_to_row.get(asset_id)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [self.ThumbnailRole])

    def get_asset(self, index: QModelIndex) -> Asset | None:
        if index.isValid() and 0 <= index.row() < len(self._assets):
            return self._assets[index.row()]
        return None


# ---------------------------------------------------------------------------
# Thumbnail Delegate — paints each cell (no widgets)
# ---------------------------------------------------------------------------

class ThumbnailDelegate(QStyledItemDelegate):

    def __init__(self, thumb_size=THUMB_SIZE, parent=None):
        super().__init__(parent)
        self.thumb_size = thumb_size
        self.fill_mode = False  # False=fit (keep ratio), True=fill (crop to cover)
        self.font_size = 10  # updated by update_font_size
        self.show_dims = True
        self.show_filenames = "always"  # "always" | "hover" | "never"
        self._folder_starts: dict[int, str] = {}  # row_index → folder path
        from collections import OrderedDict
        self._scaled_cache: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._scaled_cache_max = 2048  # cap to bound QPixmap memory growth
        self._fonts: dict[int, QFont] = {}       # size → QFont (cached to avoid per-paint allocs)
        self._fms: dict[int, QFontMetrics] = {}  # size → QFontMetrics
        from doxyedit.themes import THEMES, DEFAULT_THEME
        self._theme = THEMES[DEFAULT_THEME]
        self._update_metrics()

    def set_theme(self, theme):
        self._theme = theme
        self._update_metrics()

    def _update_metrics(self):
        """Derive all layout measurements from font_size.

        Every visual measurement in the thumbnail grid comes from here.
        Changing font_size rescales the entire layout proportionally.
        """
        font_size = self.font_size

        # ── Minimums (prevent unreadable UI at tiny font sizes) ────────
        MIN_PADDING            = 4       # smallest cell padding in px
        MIN_CORNER             = 2       # smallest rounded corner in px
        MIN_DOT                = 3       # smallest tag dot radius in px
        MIN_READINESS_DOT      = 2       # smallest readiness dot in px
        MIN_FONT               = 6       # smallest font size in px
        MIN_BADGE              = 12      # smallest badge square in px

        # ── Ratios (change these to rescale proportionally) ───────────
        PADDING_RATIO          = 0.5     # cell_padding = fs * this
        THUMB_CORNER_RATIO     = 0.25    # thumbnail rounded corner
        SELECT_BORDER_RATIO    = 0.17    # selection highlight thickness
        TAG_DOT_RATIO          = 0.5     # tag dot radius
        TAG_DOT_SPACING_MULT   = 2.5     # dot spacing = dot_radius * this
        BADGE_RATIO            = 1.2     # badge square size
        BADGE_CORNER_RATIO     = 0.33    # badge rounded corner
        BADGE_FONT_RATIO       = 0.7     # badge label font
        READINESS_DOT_RATIO    = 0.25    # readiness indicator radius
        READINESS_DOT_SPACING_MULT = 3.0 # readiness dot spacing = radius * this
        FOLDER_LABEL_FONT_RATIO = 0.75   # folder group label font
        DIMS_FONT_RATIO        = 0.75    # dimensions text font
        DIMS_HEIGHT_RATIO      = 1.0     # dimensions line height
        NAME_FONT_RATIO        = 0.85    # filename font
        NAME_HEIGHT_RATIO      = 1.2     # filename line height
        STAR_FONT_RATIO        = 1.3     # star icon font
        STAR_SIZE_RATIO        = 1.7     # star hit area
        GROUP_DOT_RATIO        = 0.45
        LINK_BORDER_RATIO      = 0.2

        # ── Derived measurements ──────────────────────────────────────
        # Layout spacing
        self.cell_padding = max(MIN_PADDING, int(font_size * PADDING_RATIO))
        self.badge_corner_inset = self.cell_padding // 2

        # Thumbnail
        self.thumb_corner = max(MIN_CORNER, int(font_size * THUMB_CORNER_RATIO))

        # Selection highlight
        self.selection_border_width = max(1, int(font_size * SELECT_BORDER_RATIO))
        self.selection_fill_alpha = self._theme.grid_selection_alpha
        self.selection_border_alpha = self._theme.grid_selection_border_alpha
        self.hover_fill_alpha = self._theme.grid_hover_alpha

        # Tag dots (colored circles below thumbnail)
        self.tag_dot_radius = max(MIN_DOT, int(font_size * TAG_DOT_RATIO))
        self.tag_dot_spacing = int(self.tag_dot_radius * TAG_DOT_SPACING_MULT)
        self.tag_dot_outline_width = self._theme.grid_dot_outline_width
        self.dot_outline_alpha = self._theme.grid_dot_outline_alpha

        # Status badges (top corners of thumbnail)
        self.badge_size = max(MIN_BADGE, int(font_size * BADGE_RATIO))
        self.badge_corner = max(MIN_CORNER, int(font_size * BADGE_CORNER_RATIO))
        self.badge_font_size = max(MIN_FONT, int(font_size * BADGE_FONT_RATIO))
        self.badge_bg_alpha = self._theme.grid_badge_alpha

        # Readiness dots (tiny platform status indicators)
        self.readiness_dot_radius = max(MIN_READINESS_DOT, int(font_size * READINESS_DOT_RATIO))
        self.readiness_dot_spacing = int(self.readiness_dot_radius * READINESS_DOT_SPACING_MULT)

        # Below-thumbnail text area
        self.below_dots_offset = self.cell_padding + self.tag_dot_radius * 2
        self.folder_label_font_size = max(MIN_FONT, int(font_size * FOLDER_LABEL_FONT_RATIO))
        self.dims_font_size = max(MIN_FONT, int(font_size * DIMS_FONT_RATIO))
        self.dims_line_height = int(font_size * DIMS_HEIGHT_RATIO)
        MIN_NAME_FONT          = 7       # filename needs slightly larger min than badges
        self.name_font_size = max(MIN_NAME_FONT, int(font_size * NAME_FONT_RATIO))
        self.name_line_height = int(font_size * NAME_HEIGHT_RATIO)

        # Star icon
        self.star_font_size = int(font_size * STAR_FONT_RATIO)
        self.star_size = int(font_size * STAR_SIZE_RATIO)
        self.star_empty_alpha = self._theme.grid_star_empty_alpha

        # Group/variant indicators
        MIN_GROUP_DOT        = 3       # smallest group indicator dot
        MIN_LINK_BORDER      = 2       # smallest link mode border
        self.group_dot_radius = max(MIN_GROUP_DOT, int(font_size * GROUP_DOT_RATIO))
        self.link_border_width = max(MIN_LINK_BORDER, int(font_size * LINK_BORDER_RATIO))
        self.group_dot_inset = self._theme.group_dot_inset

        # Placeholder (no thumbnail loaded)
        self.placeholder_bg_alpha = self._theme.grid_placeholder_bg_alpha
        self.placeholder_text_alpha = self._theme.grid_placeholder_text_alpha

    def _font(self, size: int) -> QFont:
        if size not in self._fonts:
            self._fonts[size] = QFont(self._theme.font_family, size)
            self._fms[size] = QFontMetrics(self._fonts[size])
        return self._fonts[size]

    def _fm(self, size: int) -> QFontMetrics:
        if size not in self._fms:
            self._font(size)
        return self._fms[size]

    def _below_height(self) -> int:
        """Total height needed below the thumbnail (dots + dims + name + margins)."""
        return (self.below_dots_offset       # tag dots row
                + self.dims_line_height      # dimensions text
                + self.name_line_height      # filename
                + self.cell_padding // 2)    # bottom margin

    def grid_size_for(self, thumb_size: int) -> QSize:
        """Return the proper grid cell size for a given thumbnail size."""
        return QSize(thumb_size + 2 * self.cell_padding,
                     self.cell_padding + thumb_size + self._below_height())

    def sizeHint(self, option, index):
        return self.grid_size_for(self.thumb_size)

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
            painter.setFont(self._font(self.folder_label_font_size))
            text_w = self._fm(self.folder_label_font_size).horizontalAdvance(short) + self.cell_padding * 2
            FOLDER_TAG_HEIGHT_RATIO = 1.3   # folder label tag height
            _tag_h = max(14, int(self.font_size * FOLDER_TAG_HEIGHT_RATIO))
            tag_rect = QRect(rect.x(), rect.y(), min(text_w, rect.width()), _tag_h)
            _bg = QColor(self._theme.bg_hover)
            _bg.setAlpha(self._theme.grid_folder_tag_alpha)
            painter.fillRect(tag_rect, _bg)
            painter.setPen(QColor(self._theme.text_primary))
            painter.drawText(tag_rect.adjusted(self.cell_padding, 0, -self.cell_padding, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             short)
            painter.restore()

        ts = self.thumb_size

        # Selection / hover background
        if option.state & QStyle.StateFlag.State_Selected:
            _sel_fill = QColor(self._theme.selection_bg)
            _sel_fill.setAlpha(self.selection_fill_alpha)
            painter.fillRect(rect, _sel_fill)
            _sel_border = QColor(self._theme.selection_border)
            _sel_border.setAlpha(self.selection_border_alpha)
            painter.setPen(QPen(_sel_border, self.selection_border_width))
            _sb = self.selection_border_width
            painter.drawRect(rect.adjusted(_sb, _sb, -_sb, -_sb))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            _hover = QColor(self._theme.border)
            _hover.setAlpha(self.hover_fill_alpha)
            painter.fillRect(rect, _hover)

        # Thumbnail
        pixmap = index.data(ThumbnailModel.ThumbnailRole)
        if pixmap and not pixmap.isNull():
            cache_key = (pixmap.cacheKey(), ts, self.fill_mode)
            if cache_key in self._scaled_cache:
                scaled = self._scaled_cache[cache_key]
                self._scaled_cache.move_to_end(cache_key)  # mark as recently used
            else:
                if self.fill_mode:
                    # Fill: scale to cover, then crop center
                    scaled = pixmap.scaled(
                        ts, ts, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
                    cx = (scaled.width() - ts) // 2
                    cy = (scaled.height() - ts) // 2
                    scaled = scaled.copy(cx, cy, ts, ts)
                else:
                    scaled = pixmap.scaled(
                        ts, ts, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                self._scaled_cache[cache_key] = scaled
                if len(self._scaled_cache) > self._scaled_cache_max:
                    self._scaled_cache.popitem(last=False)  # evict oldest
            x = rect.x() + (rect.width() - scaled.width()) // 2
            y = rect.y() + self.cell_padding + (ts - scaled.height()) // 2
            # Rounded corners
            path = QPainterPath()
            path.addRoundedRect(float(x), float(y), float(scaled.width()), float(scaled.height()),
                                self.thumb_corner, self.thumb_corner)
            painter.setClipPath(path)
            painter.drawPixmap(x, y, scaled)
            painter.setClipping(False)
        else:
            # Placeholder
            ph_rect = QRect(rect.x() + self.cell_padding, rect.y() + self.cell_padding, ts, ts)
            _ph_fill = QColor(self._theme.text_muted)
            _ph_fill.setAlpha(self.placeholder_bg_alpha)
            painter.fillRect(ph_rect, _ph_fill)
            _ph_text = QColor(self._theme.text_muted)
            _ph_text.setAlpha(self.placeholder_text_alpha)
            painter.setPen(_ph_text)
            painter.drawText(ph_rect, Qt.AlignmentFlag.AlignCenter, "...")

        # Tag dots
        tags = index.data(ThumbnailModel.TagsRole) or []
        dot_y = rect.y() + self.cell_padding + ts + self.tag_dot_radius
        dot_x = rect.x() + self.cell_padding + self.tag_dot_radius
        for tag_id in tags[:10]:
            preset = TAG_ALL.get(tag_id)
            color = QColor(preset.color) if preset else QColor(VINIK_COLORS[hash(tag_id) % len(VINIK_COLORS)])
            painter.setBrush(color)
            dot_outline = QColor(self._theme.bg_deep)
            dot_outline.setAlpha(self.dot_outline_alpha)
            painter.setPen(QPen(dot_outline, self.tag_dot_outline_width))
            painter.drawEllipse(QPoint(dot_x, dot_y), self.tag_dot_radius, self.tag_dot_radius)
            dot_x += self.tag_dot_spacing

        # Platform assignment status badge (top-right corner of thumbnail)
        assignments = index.data(ThumbnailModel.AssignmentsRole) or []
        if assignments and self._theme:
            t = self._theme
            statuses = {s for _, s in assignments}
            if "posted" in statuses:
                badge_hex, badge_char = t.post_posted, "✓"
            elif "ready" in statuses:
                badge_hex, badge_char = t.accent, "R"
            else:
                badge_hex, badge_char = t.warning, "…"
            badge_color = QColor(badge_hex)
            badge_color.setAlpha(self.badge_bg_alpha)
            bx = rect.x() + rect.width() - self.cell_padding - self.badge_size - self.badge_corner_inset
            by = rect.y() + self.cell_padding + self.badge_corner_inset
            painter.setBrush(badge_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bx, by, self.badge_size, self.badge_size, self.badge_corner, self.badge_corner)
            painter.setPen(QColor(t.text_on_accent))
            if (self.badge_font_size, "bold") not in self._fonts:
                self._fonts[(self.badge_font_size, "bold")] = QFont(t.font_family, self.badge_font_size, QFont.Weight.Bold)
            painter.setFont(self._fonts[(self.badge_font_size, "bold")])
            painter.drawText(QRect(bx, by, self.badge_size, self.badge_size), Qt.AlignmentFlag.AlignCenter, badge_char)

        # Social post status badge (below platform badge, top-right)
        post_status = index.data(ThumbnailModel.PostStatusRole)
        if post_status and self._theme:
            t = self._theme
            _ps_token_map = {
                "draft": (t.post_draft, "D"),
                "queued": (t.post_queued, "Q"),
                "posted": (t.post_posted, "P"),
                "failed": (t.post_failed, "!"),
            }
            ps_hex, ps_char = _ps_token_map.get(post_status, (t.post_draft, "?"))
            ps_color = QColor(ps_hex)
            ps_color.setAlpha(self.badge_bg_alpha)
            ps_x = rect.x() + rect.width() - self.cell_padding - self.badge_size - self.badge_corner_inset
            ps_y = rect.y() + self.cell_padding + (self.badge_size + self.cell_padding if assignments else self.badge_corner_inset)
            painter.setBrush(ps_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(ps_x, ps_y, self.badge_size, self.badge_size, self.badge_corner, self.badge_corner)
            painter.setPen(QColor(t.text_on_accent))
            if (self.badge_font_size, "bold") not in self._fonts:
                self._fonts[(self.badge_font_size, "bold")] = QFont(t.font_family, self.badge_font_size, QFont.Weight.Bold)
            painter.setFont(self._fonts[(self.badge_font_size, "bold")])
            painter.drawText(QRect(ps_x, ps_y, self.badge_size, self.badge_size), Qt.AlignmentFlag.AlignCenter, ps_char)

        # Studio-edited badge (top-left, pencil icon)
        studio_edited = index.data(ThumbnailModel.StudioEditedRole)
        if studio_edited and self._theme:
            t = self._theme
            studio_badge_x = rect.x() + self.cell_padding + self.badge_corner_inset
            studio_badge_y = rect.y() + self.cell_padding + self.badge_corner_inset
            studio_color = QColor(t.accent)
            studio_color.setAlpha(self.badge_bg_alpha)
            painter.setBrush(studio_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(studio_badge_x, studio_badge_y,
                                    self.badge_size, self.badge_size, self.badge_corner, self.badge_corner)
            painter.setPen(QColor(t.text_on_accent))
            if (self.badge_font_size, "bold") not in self._fonts:
                self._fonts[(self.badge_font_size, "bold")] = QFont(t.font_family, self.badge_font_size, QFont.Weight.Bold)
            painter.setFont(self._fonts[(self.badge_font_size, "bold")])
            painter.drawText(QRect(studio_badge_x, studio_badge_y,
                                   self.badge_size, self.badge_size), Qt.AlignmentFlag.AlignCenter, "S")

        # Readiness dots (tiny colored dots below studio badge area)
        readiness = index.data(ThumbnailModel.ReadinessRole)
        if readiness and self._theme:
            t = self._theme
            readiness_colors = {"green": t.success, "yellow": t.warning, "red": t.error}
            readiness_y = rect.y() + self.cell_padding + ts - self.readiness_dot_radius * 2
            readiness_x = rect.x() + self.cell_padding + self.readiness_dot_radius
            for pid, status in list(readiness.items())[:6]:
                dot_color = QColor(readiness_colors.get(status, t.text_muted))
                painter.setBrush(dot_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(readiness_x, readiness_y),
                                    self.readiness_dot_radius, self.readiness_dot_radius)
                readiness_x += self.readiness_dot_spacing

        # Dimensions text
        if self.show_dims:
            dims = index.data(ThumbnailModel.DimsRole)
            dim_text = f"{dims[0]}x{dims[1]}" if dims else ""
            dim_rect = QRect(rect.x(), rect.y() + ts + self.below_dots_offset,
                            rect.width(), self.dims_line_height)
            painter.setPen(QColor(self._theme.text_muted))
            painter.setFont(self._font(self.dims_font_size))
            painter.drawText(dim_rect, Qt.AlignmentFlag.AlignHCenter, dim_text)

        # Filename
        _show_name = (self.show_filenames == "always" or
                      (self.show_filenames == "hover" and
                       option.state & QStyle.StateFlag.State_MouseOver) or
                      option.state & QStyle.StateFlag.State_Selected)
        name_width_px = 0
        if _show_name:
            name = index.data(Qt.ItemDataRole.DisplayRole) or ""
            name_top = self.below_dots_offset + self.dims_line_height
            name_rect = QRect(rect.x() + self.cell_padding, rect.y() + ts + name_top,
                              rect.width() - self.cell_padding * 2 - self.star_size, self.name_line_height)
            painter.setPen(option.palette.text().color())
            painter.setFont(self._font(self.name_font_size))
            fm = self._fm(self.name_font_size)
            elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width())
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
            name_width_px = fm.horizontalAdvance(elided)

        # Star
        star_val = index.data(ThumbnailModel.StarRole) or 0
        star_char = "\u2605" if star_val else "\u2606"
        if star_val and star_val in STAR_COLORS:
            painter.setPen(QColor(STAR_COLORS[star_val]))
        else:
            _star_empty = QColor(self._theme.text_muted)
            _star_empty.setAlpha(self.star_empty_alpha)
            painter.setPen(_star_empty)
        painter.setFont(self._font(self.star_font_size))
        # Hug the star to the right edge of the filename (4 px gap) instead
        # of pinning it to the card's right edge, so short filenames don't
        # leave an ocean of empty space between name and star.
        _star_max_x = rect.right() - self.star_size - self.cell_padding
        if name_width_px > 0:
            star_x = min(
                rect.x() + self.cell_padding + name_width_px + 4,
                _star_max_x)
        else:
            star_x = _star_max_x
        star_rect = QRect(star_x,
                          rect.y() + ts + self.below_dots_offset + self.dims_line_height,
                          self.star_size, self.star_size)
        painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, star_char)

        # Group/variant corner dots (always visible)
        group_info = index.data(ThumbnailModel.GroupInfoRole)
        if group_info:
            dup_group, var_set, asset_id = group_info
            dot_r = self.group_dot_radius
            inset = self.group_dot_inset
            dup_color = QColor(self._theme.group_duplicate_color)
            var_color = QColor(self._theme.group_variant_color)
            if dup_group:
                dx = rect.x() + rect.width() - self.cell_padding - dot_r - inset
                dy = rect.y() + self.cell_padding + dot_r + inset
                painter.setBrush(dup_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(dx, dy), dot_r, dot_r)
            if var_set:
                vx = rect.x() + self.cell_padding + dot_r + inset
                vy = rect.y() + self.cell_padding + dot_r + inset
                painter.setBrush(var_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(vx, vy), dot_r, dot_r)

            browser = self.parent()
            if browser and getattr(browser, '_link_mode', False):
                bw = self.link_border_width
                thumb_rect = QRect(rect.x() + self.cell_padding,
                                   rect.y() + self.cell_padding, ts, ts)
                if asset_id in getattr(browser, '_link_highlight_dupes', set()):
                    painter.setPen(QPen(dup_color, bw))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(thumb_rect.adjusted(bw//2, bw//2, -bw//2, -bw//2),
                                            self.thumb_corner, self.thumb_corner)
                if asset_id in getattr(browser, '_link_highlight_variants', set()):
                    painter.setPen(QPen(var_color, bw))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(thumb_rect.adjusted(bw//2, bw//2, -bw//2, -bw//2),
                                            self.thumb_corner, self.thumb_corner)

        painter.restore()

    def invalidate_cache(self):
        self._scaled_cache.clear()
        self._fonts.clear()
        self._fms.clear()


# ---------------------------------------------------------------------------
# FolderListView — auto-heights itself to show all items without scrollbar
# ---------------------------------------------------------------------------

class FolderListView(QListView):
    """QListView that reports a sizeHint tall enough to show all items unwrapped."""

    def _compute_height(self, available_width: int = 0) -> int:
        m = self.model()
        if not m or m.rowCount() == 0:
            return 0
        grid = self.gridSize()
        if not grid.isValid():
            return 0
        if available_width <= 0:
            vp_w = self.viewport().width()
            available_width = vp_w if vp_w > 0 else (self.width() if self.width() > 0 else 300)
        col_w = max(1, grid.width() + self.spacing() * 2)
        cols = max(1, available_width // col_w)
        rows = (m.rowCount() + cols - 1) // cols
        return rows * grid.height() + 8

    def sizeHint(self):
        return QSize(0, self._compute_height())

    def minimumSizeHint(self):
        h = self._compute_height()
        return QSize(0, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()


# ---------------------------------------------------------------------------
# RootFolderHeader — collapsible parent header for an import-source root
# ---------------------------------------------------------------------------

class RootFolderHeader(QWidget):
    """Non-grid header that groups recursive sub-folder sections under an import root."""

    def __init__(self, root_path: str, total_assets: int, parent=None, on_expand=None):
        super().__init__(parent)
        self._root = root_path
        self._children: list[QWidget] = []
        self._collapsed = False
        self._on_expand = on_expand

        layout = QVBoxLayout(self)
        _f = ui_font_size()
        _pad = max(4, _f // 3)
        layout.setContentsMargins(0, _pad, 0, 0)
        layout.setSpacing(0)

        parts = Path(root_path).parts
        label = parts[-1] if parts else root_path
        self._btn = QPushButton()
        self._btn.setFlat(True)
        self._btn.setObjectName("root_folder_header")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._toggle)
        self._update_text(label, total_assets)
        layout.addWidget(self._btn)

        # Thin separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("card_divider")
        layout.addWidget(line)

    def _update_text(self, label: str, total: int):
        arrow = "▶" if self._collapsed else "▼"
        self._btn.setText(f"{arrow}  {label}  ·  {total} assets")

    def set_children(self, sections: list):
        self._children = sections
        parts = Path(self._root).parts
        label = parts[-1] if parts else self._root
        total = sum(s.folder_model.rowCount() for s in sections if hasattr(s, 'folder_model'))
        self._update_text(label, total)

    def _toggle(self):
        self._collapsed = not self._collapsed
        parts = Path(self._root).parts
        label = parts[-1] if parts else self._root
        total = sum(s.folder_model.rowCount() for s in self._children if hasattr(s, 'folder_model'))
        self._update_text(label, total)
        for child in self._children:
            child.setVisible(not self._collapsed)
        if self._on_expand and not self._collapsed:
            self._on_expand()


# ---------------------------------------------------------------------------
# FolderSection — header button + FolderListView for one folder group
# ---------------------------------------------------------------------------

class FolderSection(QWidget):
    """One collapsible folder group: header label + FolderListView."""

    collapsed_changed = Signal(str, bool)   # (folder_path, is_collapsed)
    remove_requested  = Signal(str)         # (folder_path)
    select_all_requested = Signal(str, bool)  # (folder_path, recursive)
    date_filter_requested = Signal(str)     # (folder_path)
    hide_requested = Signal(str)            # (folder_path)

    def __init__(self, folder: str, assets: list, delegate, thumb_size: int,
                 collapsed: bool = False, depth: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("folder_section")
        self._folder = folder
        self._child_folder_count = 0
        self._highlight_color = None
        self._chip_color = None
        self._thumb_size = thumb_size
        self._depth = depth
        _s = QSettings("DoxyEdit", "DoxyEdit")
        _f = _s.value("font_size", 12, type=int)
        _pad = max(4, _f // 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, max(2, _pad // 2), 0, 0)
        layout.setSpacing(0)

        # Header
        parts = Path(folder).parts
        short = str(Path(*parts[-2:])) if len(parts) >= 2 else folder
        self._short = short
        self._header = QPushButton()
        self._header.setFlat(True)
        self._header.setObjectName("folder_section_header")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self._toggle_collapse)
        self._header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._header.customContextMenuRequested.connect(self._on_header_context)
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
        self._delegate = delegate
        self._view.setGridSize(delegate.grid_size_for(thumb_size))
        self._view.setSpacing(_pad)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self._view.setMouseTracking(True)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.setStyleSheet("QListView { border: none; }")
        self._view.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
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
        self._update_header_text()
        self.updateGeometry()

    def _update_header_text(self):
        collapsed = self.is_collapsed
        n = self._model.rowCount()
        arrow = "▶" if collapsed else "▼"
        indent = "   " * self._depth
        child_count = self._child_folder_count
        if child_count > 0:
            self._header.setText(f"{indent}{arrow}  {self._short}  ({n})  +{child_count} folders")
        else:
            self._header.setText(f"{indent}{arrow}  {self._short}  ({n})")

    collapse_children_requested = Signal(str, bool)  # (folder_path, collapse)

    def _toggle_collapse(self):
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            new_state = not self.is_collapsed
            self._set_collapsed(new_state)
            self.collapsed_changed.emit(self._folder, new_state)
            self.collapse_children_requested.emit(self._folder, new_state)
        else:
            new_state = not self.is_collapsed
            self._set_collapsed(new_state)
            self.collapsed_changed.emit(self._folder, new_state)

    def _on_header_context(self, pos):
        import subprocess, random
        menu = QMenu(self)
        hide_label = "Show Subfolders" if self._child_folder_count > 0 else "Hide Subfolders"
        menu.addAction(hide_label, lambda: self.hide_requested.emit(self._folder))
        menu.addSeparator()
        menu.addAction("Select All in Folder", lambda: self.select_all_requested.emit(self._folder, False))
        menu.addAction("Select All (Recursive)", lambda: self.select_all_requested.emit(self._folder, True))
        menu.addSeparator()
        menu.addAction("Highlight Color", self._set_random_highlight)
        menu.addAction("Chip Color", self._set_random_chip)
        if self._highlight_color or self._chip_color:
            menu.addAction("Clear Color", self._clear_color)
        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: subprocess.Popen(
            ["explorer", self._folder.replace("/", "\\")]))
        menu.addAction("Set Date Filter…", lambda: self.date_filter_requested.emit(self._folder))
        menu.addSeparator()
        menu.addAction("Remove Folder from Project…", lambda: self.remove_requested.emit(self._folder))
        menu.exec(self._header.mapToGlobal(pos))

    def _theme_accent_variant(self) -> QColor:
        """Generate a random color based on the theme's accent hue with random offset."""
        import random
        # Get accent color from the delegate's theme, or fallback
        theme = getattr(getattr(self.parent(), '_delegate', None) if hasattr(self, '_view') else None, '_theme', None)
        if not theme:
            # Try via parent browser
            browser = self.parent()
            while browser and not hasattr(browser, '_delegate'):
                browser = browser.parent()
            if browser:
                theme = getattr(browser._delegate, '_theme', None)
        if theme:
            base = QColor(theme.accent)
            bg = QColor(theme.bg_deep)
            is_dark = bg.lightness() < 128
        else:
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            base = QColor(_dt.accent)
            bg = QColor(_dt.bg_deep)
            is_dark = bg.lightness() < 128
        # Shift hue randomly by ±120 degrees from accent
        h, s, l, _ = base.getHsl()
        offset = random.randint(-120, 120)
        new_hue = (h + offset) % 360
        if is_dark:
            return QColor.fromHsl(new_hue, max(60, s), min(90, max(40, l)), 60)
        else:
            return QColor.fromHsl(new_hue, max(40, s - 20), max(160, min(220, l + 80)), 100)

    def _set_random_highlight(self):
        """Full line background color — theme-aware."""
        color = self._theme_accent_variant()
        self._highlight_color = color.name()
        self._apply_header_colors()
        self._save_folder_colors()

    def _set_random_chip(self):
        """Left border chip indicator — theme-aware."""
        color = self._theme_accent_variant()
        from doxyedit.themes import THEMES, DEFAULT_THEME
        _dt = THEMES[DEFAULT_THEME]
        color.setAlpha(_dt.tag_bar_active_alpha)  # chip needs full opacity
        self._chip_color = color.name()
        self._apply_header_colors()
        self._save_folder_colors()

    def _clear_color(self):
        self._highlight_color = None
        self._chip_color = None
        self._header.setStyleSheet("")
        self._save_folder_colors()

    def _apply_header_colors(self):
        parts = []
        if self._highlight_color:
            parts.append(f"background: {self._highlight_color}")
        if self._chip_color:
            parts.append(f"border-left: 4px solid {self._chip_color}")
        self._header.setStyleSheet("; ".join(parts))

    def _save_folder_colors(self):
        s = QSettings("DoxyEdit", "DoxyEdit")
        key = f"folder_colors/{self._folder.replace('/', '_')}"
        if self._highlight_color or self._chip_color:
            s.setValue(key, {"highlight": self._highlight_color or "",
                            "chip": self._chip_color or ""})
        else:
            s.remove(key)

    def restore_colors(self):
        """Restore saved highlight/chip colors from QSettings."""
        s = QSettings("DoxyEdit", "DoxyEdit")
        key = f"folder_colors/{self._folder.replace('/', '_')}"
        data = s.value(key)
        if data:
            self._highlight_color = data.get("highlight") or None
            self._chip_color = data.get("chip") or None
            if self._highlight_color or self._chip_color:
                self._apply_header_colors()

    def update_view_height(self, available_width: int = 0):
        """Set the view's fixed height based on actual available width.
        Call this after layout settles or when container resizes."""
        if not self._view.isVisible():
            return
        if available_width <= 0:
            available_width = self.width()
        if available_width < 100:  # too small, skip — will be called again on resize
            return
        view_h = self._view._compute_height(available_width)
        max_h = getattr(self, '_max_section_height', 0)
        if max_h > 0 and view_h > max_h:
            view_h = max_h
        self._view.setFixedSize(available_width, view_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_view_height(event.size().width())

    def update_grid_size(self, thumb_size: int):
        self._thumb_size = thumb_size
        self._view.setGridSize(self._delegate.grid_size_for(thumb_size))
        self.update_view_height()
        self._view.updateGeometry()


# ---------------------------------------------------------------------------
# Asset Browser — main widget
# ---------------------------------------------------------------------------

class AssetBrowser(QWidget):
    asset_selected = Signal(str)
    asset_preview = Signal(str)
    asset_to_canvas = Signal(str)
    asset_to_censor = Signal(str)
    asset_to_post = Signal(str)
    asset_to_tray = Signal(str)
    thumb_loaded = Signal(str, QPixmap)
    folder_opened = Signal(str)
    tags_modified = Signal()
    selection_changed = Signal(list)
    tag_bar_toggled = Signal(bool)  # emitted when toolbar filter btn changes

    # ── Layout ratios (change here to rescale browser toolbar) ──
    ZOOM_SLIDER_WIDTH_RATIO = 9.0      # thumbnail size slider
    ZOOM_LABEL_WIDTH_RATIO = 2.8       # "NNpx" label next to slider
    SEARCH_MIN_WIDTH_RATIO = 10.0      # search box minimum width
    files_toggled = Signal(bool)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_browser")
        self.project = project
        self._selected_ids: set[str] = set()
        # Link Mode — highlight duplicate/variant groups
        self._link_mode = False
        self._link_highlight_dupes: set[str] = set()
        self._link_highlight_variants: set[str] = set()
        self._duplicate_groups: dict[str, list[str]] = {}
        self._variant_sets: dict[str, list[str]] = {}
        self._thumb_cache = ThumbCache()
        self._thumb_cache.connect_ready(self._on_thumb_ready)
        self._thumb_cache.connect_visual_tags(self._on_visual_tags)
        self._thumb_cache.connect_palette(self._on_palette_ready)
        self._thumb_cache.connect_phash(self._on_phash_ready)
        self._filtered_assets: list[Asset] = []
        settings = QSettings("DoxyEdit", "DoxyEdit")
        self._thumb_size = max(MIN_THUMB_SIZE, min(MAX_THUMB_SIZE, int(settings.value("thumb_size", THUMB_SIZE))))
        self._font_size = settings.value("font_size", DEFAULT_FONT_SIZE, type=int)
        self.cell_padding = max(4, self._font_size // 3)
        self.cell_padding_lg = max(6, self._font_size // 2)
        self.hover_preview_enabled = settings.value("hover_preview_enabled", "true") == "true"
        self._eye_hidden_tags: set[str] = set()
        self._temp_hidden_ids: set[str] = set()  # Alt+H temporary hide (not saved)
        self._bar_tag_filters: set[str] = set()  # tag bar filter toggles
        self.auto_tag_enabled = False
        self.show_hidden_only = False
        self._collapsed_folders: set[str] = set()
        self._hidden_folders: set[str] = set()
        self._folder_filter: set[str] | None = None  # None = show all
        self._folder_sections: list[FolderSection] = []
        self._prev_sort_mode: str = "Name A-Z"  # last non-folder sort; used as within-folder secondary sort
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
        self._cache_all_remaining: list[tuple[str, str]] = []
        self._active_import_worker = None  # prevents GC during async import
        self._scan_running = False          # guard against concurrent folder scans
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(400)
        self._idle_timer.timeout.connect(self._on_scroll_idle)
        # Debounce selection_changed so rubber-band multi-select doesn't hammer downstream handlers
        self._selection_emit_timer = QTimer(self)
        self._selection_emit_timer.setSingleShot(True)
        self._selection_emit_timer.setInterval(40)
        self._selection_emit_timer.timeout.connect(
            lambda: self.selection_changed.emit(list(self._selected_ids)))
        self.setAcceptDrops(True)
        self._build()

    def _build(self):
        _pad = self.cell_padding
        _pad_lg = self.cell_padding_lg
        root = QVBoxLayout(self)
        root.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)

        # Row 1: import + filters (FlowLayout so buttons wrap on narrow windows)
        self._toolbar_widget = FlowWidget()
        self._toolbar_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        toolbar = FlowLayout(self._toolbar_widget, spacing=4)
        toolbar.setContentsMargins(0, 0, 0, 0)  # nested inside padded root

        # Track all plain toolbar buttons so update_font_size can refresh them
        self._toolbar_plain_btns: list[QPushButton] = []

        # Panel toggles — Files (left panel), Tags (left panel), Tray (right panel)
        self._files_btn = QPushButton("Files")
        self._files_btn.setCheckable(True)
        self._files_btn.setStyleSheet(self._btn_style())
        self._files_btn.setToolTip("Toggle File Browser (Ctrl+B)")
        self._files_btn.clicked.connect(lambda checked: self.files_toggled.emit(checked))
        toolbar.addWidget(self._files_btn)
        self._toolbar_plain_btns.append(self._files_btn)
        self._tags_btn = QPushButton("Tags")
        self._tags_btn.setCheckable(True)
        self._tags_btn.setChecked(True)
        self._tags_btn.setStyleSheet(self._btn_style())
        toolbar.addWidget(self._tags_btn)
        self._toolbar_plain_btns.append(self._tags_btn)
        self._tray_btn = QPushButton("Tray")
        self._tray_btn.setCheckable(True)
        self._tray_btn.setStyleSheet(self._btn_style())
        toolbar.addWidget(self._tray_btn)
        self._toolbar_plain_btns.append(self._tray_btn)

        for label, handler in [("+ Folder", self.open_folder_dialog), ("+ Files", self.add_images_dialog)]:
            btn = QPushButton(label)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)
            self._toolbar_plain_btns.append(btn)

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

        self._link_mode_btn = QPushButton("Link Mode")
        self._link_mode_btn.setCheckable(True)
        self._link_mode_btn.setToolTip("Highlight duplicate groups and variant sets on click")
        self._link_mode_btn.setStyleSheet(self._btn_style())
        self._link_mode_btn.toggled.connect(self._on_link_mode_toggled)
        toolbar.addWidget(self._link_mode_btn)

        for _fb in [self.filter_starred, self.filter_untagged, self.filter_tagged,
                    self.filter_assigned, self.filter_posted, self.filter_needs_censor]:
            self._toolbar_plain_btns.append(_fb)
        self._toolbar_plain_btns.append(self.filter_show_ignored)


        self.recursive_check = QCheckBox("Recursive")
        self.recursive_check.setChecked(False)
        toolbar.addWidget(self.recursive_check)

        self.hover_check = QCheckBox("Hover Preview")
        self.hover_check.setChecked(self.hover_preview_enabled)
        self.hover_check.toggled.connect(self._on_hover_toggled)
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

        # Force toolbar to recalculate height after all buttons added
        self._toolbar_widget.updateGeometry()
        root.addWidget(self._toolbar_widget)

        # Row 2: search + sort (FlowLayout so it wraps at narrow widths)
        self._row2_widget = FlowWidget()
        self._row2_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        row2 = FlowLayout(self._row2_widget, spacing=4)
        row2.setContentsMargins(0, 0, 0, 0)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumWidth(int(self._font_size * self.SEARCH_MIN_WIDTH_RATIO))
        self.search_box.textChanged.connect(self._on_filter_changed)
        self.search_box.installEventFilter(self)
        row2.addWidget(self.search_box)

        self._tag_bar_toggle_btn = QPushButton("▼ Filters")
        self._tag_bar_toggle_btn.setCheckable(True)
        self._tag_bar_toggle_btn.setChecked(True)
        self._tag_bar_toggle_btn.setStyleSheet(self._btn_style())
        self._tag_bar_toggle_btn.setToolTip("Show/hide the tag filter bar")
        self._tag_bar_toggle_btn.toggled.connect(self._on_tag_bar_toggle)
        row2.addWidget(self._tag_bar_toggle_btn)
        self._toolbar_plain_btns.append(self._tag_bar_toggle_btn)

        self._fold_all_btn = QPushButton("Collapse All")
        self._fold_all_btn.setStyleSheet(self._btn_style())
        self._fold_all_btn.setToolTip("Collapse all folders")
        self._fold_all_btn.clicked.connect(self._collapse_all_folders)
        self._fold_all_btn.setVisible(False)
        row2.addWidget(self._fold_all_btn)
        self._toolbar_plain_btns.append(self._fold_all_btn)
        self._unfold_all_btn = QPushButton("Expand All")
        self._unfold_all_btn.setStyleSheet(self._btn_style())
        self._unfold_all_btn.setToolTip("Expand all folders")
        self._unfold_all_btn.clicked.connect(self._expand_all_folders)
        self._unfold_all_btn.setVisible(False)
        row2.addWidget(self._unfold_all_btn)
        self._toolbar_plain_btns.append(self._unfold_all_btn)

        self.search_tags_check = QCheckBox("Tags")
        self.search_tags_check.setChecked(False)
        self.search_tags_check.toggled.connect(self._on_search_mode_changed)
        row2.addWidget(self.search_tags_check)

        self._format_filter = ""
        self._format_combo = QComboBox()
        self._format_combo.addItems(["All", "PSD", "PNG", "JPG", "SAI", "WEBP", "CLIP", "Other", "Ignored",
                                     "Has Notes", "Studio Edited"])
        self._format_combo.setToolTip("Filter by file format")
        self._format_combo.currentTextChanged.connect(self._on_format_filter_changed)
        row2.addWidget(self._format_combo)

        self._sort_label = QLabel("Sort:")
        row2.addWidget(self._sort_label)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["By Folder", "Name A-Z", "Name Z-A", "Newest", "Oldest", "Largest", "Smallest", "Starred First", "Most Tagged"])
        _saved_sort = QSettings("DoxyEdit", "DoxyEdit").value("sort_mode", "By Folder")
        _sort_idx = self.sort_combo.findText(_saved_sort)
        if _sort_idx >= 0:
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(_sort_idx)
            self.sort_combo.blockSignals(False)
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.sort_combo.currentTextChanged.connect(self._on_sort_mode_changed)
        row2.addWidget(self.sort_combo)

        self._row2_widget.updateGeometry()
        root.addWidget(self._row2_widget)

        # Row 3: Quick-tag bar
        self._tag_bar_frame = FlowWidget()
        self._tag_bar_frame.setObjectName("tag_bar_frame")
        self._tag_bar_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._tag_flow = FlowLayout(self._tag_bar_frame, spacing=4)
        self._tag_flow.setContentsMargins(0, max(2, _pad // 2), 0, max(2, _pad // 2))
        self._tag_buttons: list[tuple[QPushButton, str]] = []
        self._tag_button_map: dict[str, QPushButton] = {}  # tag_id → button, O(1) lookup
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setObjectName("add_tag_btn")
        self._add_tag_btn.setToolTip("Add a custom tag")
        self._add_tag_btn.clicked.connect(self._add_custom_tag)
        self._clear_filter_btn = QPushButton("✕ Clear Filters")
        self._clear_filter_btn.setToolTip("Clear all tag filters")
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
        self._list_view.setGridSize(self._delegate.grid_size_for(self._thumb_size))
        self._list_view.setSpacing(_pad)
        self._list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.verticalScrollBar().setSingleStep(20)
        self._list_view.verticalScrollBar().valueChanged.connect(
            lambda _: (self._request_visible_thumbs(), self._idle_timer.start()))
        self._list_view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self._list_view.setMouseTracking(True)
        self._list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu_pos)
        self._list_view.doubleClicked.connect(self._on_double_click)
        self._list_view.selectionModel().selectionChanged.connect(self._on_selection_changed_internal)
        self._list_view.selectionModel().currentChanged.connect(
            lambda cur, _: self._list_view.scrollTo(cur, self._list_view.ScrollHint.EnsureVisible)
            if cur.isValid() else None)
        self._list_view.setStyleSheet("QListView { border: none; }")
        self._list_view.installEventFilter(self)
        self._list_view.viewport().installEventFilter(self)

        # Folder scroll area (page 1 of the stack) — built lazily in _refresh_grid
        self._folder_container = QWidget()
        self._folder_container.setObjectName("folder_container")
        self._folder_container_layout = QVBoxLayout(self._folder_container)
        self._folder_container_layout.setContentsMargins(0, 0, 0, 0)  # scroll area provides framing
        self._folder_container_layout.setSpacing(_pad)
        self._folder_container_layout.addStretch()

        self._folder_scroll = QScrollArea()
        self._folder_scroll.setObjectName("folder_scroll")
        self._folder_scroll.setWidget(self._folder_container)
        self._folder_scroll.setWidgetResizable(True)
        self._folder_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._folder_scroll.verticalScrollBar().setSingleStep(20)
        self._folder_scroll.verticalScrollBar().valueChanged.connect(
            lambda _: (self._request_visible_thumbs(), self._idle_timer.start()))
        self._folder_scroll_vp_installed = False

        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._list_view)    # page 0: normal view
        self._view_stack.addWidget(self._folder_scroll) # page 1: folder groups
        root.addWidget(self._view_stack)

        # Status line — zoom slider on left, page label on right
        status = QHBoxLayout()
        status.setContentsMargins(0, max(2, _pad // 2), 0, 0)
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(80, 512)
        self._zoom_slider.setValue(self._thumb_size)
        self._zoom_slider.setFixedWidth(int(self._current_font_size * self.ZOOM_SLIDER_WIDTH_RATIO))
        self._zoom_slider.setToolTip("Thumbnail size (80–512px)  ·  Ctrl+Scroll")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        self._zoom_label = QLabel(f"{self._thumb_size}px")
        self._zoom_label.setFixedWidth(int(self._current_font_size * self.ZOOM_LABEL_WIDTH_RATIO))
        self._zoom_label.setProperty("role", "muted")
        status.addWidget(self._zoom_slider)
        status.addWidget(self._zoom_label)
        status.addStretch()
        self.page_label = QLabel("")
        self.page_label.setProperty("role", "muted")
        status.addWidget(self.page_label)
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
        # Auto-assign a cycle color to tags that are used but missing from bar_tags,
        # OR whose declared color is the default placeholder ("#888"/"#888888"/empty).
        # Stable order so the same tag gets the same color across sessions.
        PLACEHOLDER_COLORS = {"", "#888", "#888888"}
        for t in sorted(all_used):
            if t in TAG_PRESETS or t in TAG_SIZED:
                continue
            if t not in bar_tags:
                bar_tags[t] = TagPreset(id=t, label=t,
                    color=VINIK_COLORS[color_idx % len(VINIK_COLORS)])
                color_idx += 1
            elif (bar_tags[t].color or "").lower() in PLACEHOLDER_COLORS:
                preset = bar_tags[t]
                bar_tags[t] = TagPreset(id=preset.id, label=preset.label,
                    width=preset.width, height=preset.height, ratio=preset.ratio,
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
            btn.setToolTip(f"Left-click to filter grid by '{tag_id}'")
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
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
        parent = self.window()
        dlg = QInputDialog(parent)
        dlg.setWindowTitle("New Tag")
        dlg.setLabelText("Enter tag name:")
        dlg.setStyleSheet(parent.styleSheet())
        ok = dlg.exec()
        name = dlg.textValue()
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
        TAG_BUTTON_HEIGHT_RATIO = 2.2   # tag bar button height
        h = int(font_size * TAG_BUTTON_HEIGHT_RATIO)
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
        self._add_tag_btn.setObjectName("add_tag_btn")
        self._add_tag_btn.setFixedHeight(h)
        self._add_tag_btn.setFixedWidth(h)

    def update_font_size(self, font_size: int):
        self._apply_tag_button_styles(font_size)
        self._delegate.font_size = font_size
        self._delegate._update_metrics()
        self._list_view.setGridSize(self._delegate.grid_size_for(self._thumb_size))
        self._list_view.viewport().update()
        for section in self._folder_sections:
            section.update_grid_size(self._thumb_size)
            section.view.viewport().update()
        style = self._btn_style()
        for btn in self._toolbar_plain_btns:
            btn.setStyleSheet(style)

    def _set_thumb_size(self, sz: int):
        sz = max(80, min(512, sz))
        self._thumb_size = sz
        self._delegate.thumb_size = sz
        self._delegate.invalidate_cache()
        self._list_view.setGridSize(self._delegate.grid_size_for(sz))
        for section in self._folder_sections:
            section.update_grid_size(sz)
        s = QSettings("DoxyEdit", "DoxyEdit")
        s.setValue("thumb_size", sz)
        s.setValue("thumb_size_user_set", True)
        self._zoom_label.setText(f"{sz}px")
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(sz)
        self._zoom_slider.blockSignals(False)

    def _on_zoom_slider(self, value: int):
        self._set_thumb_size(value)

    # --- Filtering / sorting ---

    def _on_sort_mode_changed(self, text):
        if not hasattr(self, '_view_stack'):
            return  # called during combo init before view stack exists
        QSettings("DoxyEdit", "DoxyEdit").setValue("sort_mode", text)
        is_folder = text == "By Folder"
        if not is_folder:
            self._prev_sort_mode = text
        self._fold_all_btn.setVisible(is_folder)
        self._unfold_all_btn.setVisible(is_folder)
        self._view_stack.setCurrentIndex(1 if is_folder else 0)
        # Re-prioritize cache queue to new sort order without resetting counts
        if self._cache_all_total > 0 and self.cache_all_check.isChecked():
            self._thumb_cache.clear_queue()
            remaining = self._cache_ordered_batch()
            self._cache_all_remaining = remaining
            self._thumb_cache.request_batch(remaining, size=THUMB_GEN_SIZE)

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
        """Scan known source folders for new images (runs in background thread).

        Only folders the user explicitly imported via "Import Folder" or
        folder-drag-drop are scanned. Individual file drops add a
        type='file' import_sources entry that does NOT contribute to the
        scan set — so dropping 7 files from art/ipad won't pull in the
        other 100 files in that folder on the next scan.

        Whether a scanned folder is walked recursively is decided by the
        Recursive checkbox at scan time AND by whether the folder was
        imported with recursive=True in the first place. If the user
        imported a folder non-recursively, we respect that even if the
        Recursive checkbox is on (they chose not to recurse; don't
        override).
        """
        if self._scan_running:
            return
        self._scan_running = True
        import_sources = list(self.project.import_sources)
        recursive_ui = self.recursive_check.isChecked()

        # Build (folder_path, per_folder_recursive) tuples from import_sources
        folder_entries: list[tuple[str, bool]] = []
        seen_folders: set[str] = set()
        for src in import_sources:
            if src.get("type") != "folder":
                continue
            p = src.get("path") or ""
            if not p or p in seen_folders:
                continue
            seen_folders.add(p)
            # Per-folder recursive = original import choice AND UI toggle
            per_recursive = bool(src.get("recursive", False)) and recursive_ui
            folder_entries.append((p, per_recursive))

        existing = frozenset(a.source_path for a in self.project.assets)
        excluded = frozenset(getattr(self.project, 'excluded_paths', set()))

        # Collect all folders into one worker to avoid spawning many threads
        all_new: list[str] = []

        def _do_scan():
            for folder, per_recursive in folder_entries:
                fp = Path(folder)
                if not fp.exists():
                    continue
                # Check date filter from import sources
                folder_norm = str(fp).replace("\\", "/")
                source = next((s for s in import_sources
                               if s.get("path", "").replace("\\", "/") == folder_norm), None)
                cutoff = None
                if source and source.get("filter_newer_than"):
                    from datetime import datetime
                    try:
                        cutoff = datetime.fromisoformat(source["filter_newer_than"]).timestamp()
                    except ValueError:
                        pass
                it = fp.rglob("*") if per_recursive else fp.iterdir()
                try:
                    for f in it:
                        if (f.is_file() and f.suffix.lower() in IMAGE_EXTS
                                and str(f) not in existing
                                and str(f) not in excluded
                                and str(f.parent) not in excluded):
                            if cutoff is not None:
                                try:
                                    if f.stat().st_mtime < cutoff:
                                        continue
                                except OSError:
                                    pass
                            all_new.append(str(f))
                except Exception:
                    pass
            return all_new

        def _on_done(new_files):
            self._scan_running = False
            if not new_files:
                return
            ex = {a.source_path for a in self.project.assets}
            added = 0
            for path_str in new_files:
                if path_str not in ex:
                    p = Path(path_str)
                    self.project.assets.append(Asset(
                        id=p.stem + "_" + str(len(self.project.assets)),
                        source_path=path_str, source_folder=str(p.parent),
                        tags=auto_suggest_tags(p.stem) if self.auto_tag_enabled else []))
                    ex.add(path_str)
                    added += 1
            if added:
                self._refresh_grid()
                self.tags_modified.emit()
                try:
                    self.window().status.showMessage(
                        f"Folder scan: added {added} new image(s)", 3000)
                except Exception:
                    pass

        # Run in QThread to avoid blocking the UI
        worker = _ScanWorker(_do_scan, parent=self)
        worker.done.connect(_on_done, Qt.ConnectionType.QueuedConnection)
        worker.done.connect(lambda _: worker.deleteLater())
        worker.start()

    def _on_format_filter_changed(self, text: str):
        self._format_filter = "" if text == "All" else text.lower()
        self._refresh_grid()

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

    def _mark_dirty(self):
        """Signal the main window that project data changed."""
        self._mark_dirty()

    def _on_link_mode_toggled(self, checked: bool):
        self._link_mode = checked
        if not checked:
            self._link_highlight_dupes.clear()
            self._link_highlight_variants.clear()
        self._list_view.viewport().update()
        for section in self._folder_sections:
            section.view.viewport().update()

    def _update_link_highlights(self):
        """When link mode is active, find groups/variants of selected assets."""
        self._link_highlight_dupes.clear()
        self._link_highlight_variants.clear()
        if not self._link_mode or not self._selected_ids:
            return
        for aid in self._selected_ids:
            asset = self.project.get_asset(aid)
            if not asset:
                continue
            dg = asset.specs.get("duplicate_group")
            if dg and dg in self._duplicate_groups:
                for sibling_id in self._duplicate_groups[dg]:
                    if sibling_id != aid:
                        self._link_highlight_dupes.add(sibling_id)
            vs = asset.specs.get("variant_set")
            if vs and vs in self._variant_sets:
                for sibling_id in self._variant_sets[vs]:
                    if sibling_id != aid:
                        self._link_highlight_variants.add(sibling_id)

    # --- Group / Variant handler methods ---

    def _link_selected_as_variants(self):
        """Link all selected assets as a variant set."""
        assets = self.get_selected_assets()
        if len(assets) < 2:
            return
        existing_set = None
        for a in assets:
            vs = a.specs.get("variant_set")
            if vs:
                existing_set = vs
                break
        set_id = existing_set or ("vs_" + uuid.uuid4().hex[:8])
        for a in assets:
            a.specs["variant_set"] = set_id
        self._refresh_grid()
        self._mark_dirty()

    def _select_ids(self, ids: list[str]):
        """Hard-select a list of asset IDs in the grid."""
        sel = self._list_view.selectionModel()
        sel.clearSelection()
        for i in range(self._model.rowCount()):
            idx = self._model.index(i)
            asset = self._model.get_asset(idx)
            if asset and asset.id in ids:
                sel.select(idx, sel.SelectionFlag.Select)

    def _mark_as_keeper(self, asset):
        dg = asset.specs.get("duplicate_group")
        if not dg:
            return
        for a in self.project.assets:
            if a.specs.get("duplicate_group") == dg:
                a.specs.pop("duplicate_keep", None)
        asset.specs["duplicate_keep"] = True
        self._refresh_grid()
        self._mark_dirty()

    def _unlink_duplicate(self, asset):
        asset.specs.pop("duplicate_group", None)
        asset.specs.pop("duplicate_keep", None)
        self._refresh_grid()
        self._mark_dirty()

    def _dissolve_duplicate_group(self, group_id: str):
        for a in self.project.assets:
            if a.specs.get("duplicate_group") == group_id:
                a.specs.pop("duplicate_group", None)
                a.specs.pop("duplicate_keep", None)
        self._refresh_grid()
        self._mark_dirty()

    def _unlink_variant(self, asset):
        asset.specs.pop("variant_set", None)
        self._refresh_grid()
        self._mark_dirty()

    def _dissolve_variant_set(self, set_id: str):
        for a in self.project.assets:
            if a.specs.get("variant_set") == set_id:
                a.specs.pop("variant_set", None)
        self._refresh_grid()
        self._mark_dirty()

    def _on_scroll_idle(self):
        """400ms after scrolling stops — promote visible items to front of queue."""
        self._thumb_cache.reprioritize(self._visible_asset_ids())

    def _request_visible_thumbs(self):
        """Request thumbnails for visible items + buffer; always re-prioritize to current view."""
        BUFFER = 40  # rows above/below viewport to pre-fetch
        # Always move currently visible items to the front of the worker queue
        self._thumb_cache.reprioritize(self._visible_asset_ids())

        if self._view_stack.currentIndex() == 0:
            # Flat list view
            view = self._list_view
            if not view.isVisible() or self._model.rowCount() == 0:
                return
            vr = view.viewport().rect()
            top = view.indexAt(vr.topLeft())
            bot = view.indexAt(QPoint(vr.center().x(), vr.bottom()))
            r0 = max(0, (top.row() if top.isValid() else 0) - BUFFER)
            r1 = min(self._model.rowCount() - 1,
                     (bot.row() if bot.isValid() else r0 + BUFFER) + BUFFER)
            batch = []
            for i in range(r0, r1 + 1):
                a = self._model.get_asset(self._model.index(i))
                if a:
                    batch.append((a.id, a.source_path))
            if batch:
                self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)
        else:
            # Folder sections — find which sections overlap the visible viewport
            sb = self._folder_scroll.verticalScrollBar()
            vp_top = sb.value()
            vp_bot = vp_top + self._folder_scroll.viewport().height()
            batch = []
            for section in self._folder_sections:
                if section.isHidden():
                    continue
                sec_top = section.mapTo(self._folder_container, QPoint(0, 0)).y()
                sec_bot = sec_top + section.height()
                # Include sections within viewport + buffer
                if sec_bot < vp_top - BUFFER * (self._thumb_size + 70):
                    continue
                if sec_top > vp_bot + BUFFER * (self._thumb_size + 70):
                    break
                for i in range(section.folder_model.rowCount()):
                    a = section.folder_model.get_asset(section.folder_model.index(i))
                    if a:
                        batch.append((a.id, a.source_path))
            # Fallback: layout not settled yet (all sections report height=0) —
            # request first BUFFER items from first few sections so something loads
            if not batch and self._folder_sections:
                count = 0
                for section in self._folder_sections:
                    for i in range(section.folder_model.rowCount()):
                        a = section.folder_model.get_asset(section.folder_model.index(i))
                        if a:
                            batch.append((a.id, a.source_path))
                            count += 1
                    if count >= BUFFER * 2:
                        break
            if batch:
                self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)

    def _cache_ordered_batch(self) -> list[tuple[str, str]]:
        """Build the full ordered cache list: visible first, then filtered view, then rest."""
        visible_ids = self._visible_asset_ids()
        ordered: list[tuple[str, str]] = []
        seen: set[str] = set()
        for a in self._filtered_assets:
            if a.id in visible_ids:
                ordered.append((a.id, a.source_path))
                seen.add(a.id)
        for a in self._filtered_assets:
            if a.id not in seen:
                ordered.append((a.id, a.source_path))
                seen.add(a.id)
        for a in self.project.assets:
            if a.id not in seen:
                ordered.append((a.id, a.source_path))
                seen.add(a.id)
        return ordered

    def _on_hover_toggled(self, checked):
        self.hover_preview_enabled = checked
        QSettings("DoxyEdit", "DoxyEdit").setValue("hover_preview_enabled", "true" if checked else "false")

    def _on_cache_all_toggled(self, checked):
        if not checked:
            # Pause: clear queue and remember remaining work
            self._thumb_cache.clear_queue()
            remaining = [(aid, path) for aid, path in self._cache_all_remaining
                         if self._thumb_cache._gen_sizes.get(aid, 0) < THUMB_GEN_SIZE]
            self._cache_all_remaining = remaining
            self._cache_all_total = 0
            self._cache_all_done = 0
            try:
                self.window().finish_progress("")
            except Exception:
                pass
            return

        # Resume if we have a saved queue, otherwise build fresh
        if self._cache_all_remaining:
            ordered = [(aid, path) for aid, path in self._cache_all_remaining
                       if self._thumb_cache._gen_sizes.get(aid, 0) < THUMB_GEN_SIZE]
            # Re-insert visible items at front without changing the overall order
            visible_ids = self._visible_asset_ids()
            front = [(a, p) for a, p in ordered if a in visible_ids]
            rest  = [(a, p) for a, p in ordered if a not in visible_ids]
            ordered = front + rest
        else:
            ordered = self._cache_ordered_batch()

        need_cache = sum(1 for aid, _ in ordered
                         if self._thumb_cache._gen_sizes.get(aid, 0) < THUMB_GEN_SIZE)
        if need_cache == 0:
            self._cache_all_remaining = []
            try:
                self.window().status.showMessage("All thumbnails already cached", 2000)
            except Exception:
                pass
            self.cache_all_check.blockSignals(True)
            self.cache_all_check.setChecked(False)
            self.cache_all_check.blockSignals(False)
            return

        self._cache_all_remaining = ordered
        self._cache_all_total = need_cache
        self._cache_all_done = 0
        self._thumb_cache.request_batch(ordered, size=THUMB_GEN_SIZE)
        try:
            self.window().start_progress("Caching thumbnails", need_cache)
        except Exception:
            pass

    def _visible_asset_ids(self) -> set[str]:
        """Return the set of asset IDs currently visible in the viewport."""
        ids: set[str] = set()
        if self._view_stack.currentIndex() == 0:
            view = self._list_view
            vr = view.viewport().rect()
            top = view.indexAt(vr.topLeft())
            bot = view.indexAt(QPoint(vr.center().x(), vr.bottom()))
            r0 = top.row() if top.isValid() else 0
            r1 = bot.row() if bot.isValid() else r0
            for i in range(r0, r1 + 1):
                a = self._model.get_asset(self._model.index(i))
                if a:
                    ids.add(a.id)
        else:
            sb = self._folder_scroll.verticalScrollBar()
            vp_top = sb.value()
            vp_bot = vp_top + self._folder_scroll.viewport().height()
            for section in self._folder_sections:
                if section.isHidden():
                    continue
                sec_top = section.mapTo(self._folder_container, QPoint(0, 0)).y()
                sec_bot = sec_top + section.height()
                if sec_bot < vp_top or sec_top > vp_bot:
                    continue
                for i in range(section.folder_model.rowCount()):
                    a = section.folder_model.get_asset(section.folder_model.index(i))
                    if a:
                        ids.add(a.id)
        return ids

    def set_folder_filter(self, folders: list[str] | None):
        """Restrict the grid to assets from specific folders. Pass None to show all."""
        self._folder_filter = set(folders) if folders else None
        self._refresh_grid()

    def get_filter_state(self) -> dict:
        """Capture the current filter state as a serializable dict."""
        return {
            "search_text": self.search_box.text(),
            "search_tags": self.search_tags_check.isChecked(),
            "starred": self.filter_starred.isChecked(),
            "untagged": self.filter_untagged.isChecked(),
            "tagged": self.filter_tagged.isChecked(),
            "assigned": self.filter_assigned.isChecked(),
            "posted": self.filter_posted.isChecked(),
            "needs_censor": self.filter_needs_censor.isChecked(),
            "show_ignored": self.filter_show_ignored.isChecked(),
            "format": self._format_filter,
            "tag_filters": sorted(self._bar_tag_filters),
            "folders": sorted(self._folder_filter) if self._folder_filter else None,
        }

    def set_filter_state(self, state: dict):
        """Restore a previously captured filter state."""
        self.search_box.setText(state.get("search_text", ""))
        self.search_tags_check.setChecked(state.get("search_tags", False))
        self.filter_starred.setChecked(state.get("starred", False))
        self.filter_untagged.setChecked(state.get("untagged", False))
        self.filter_tagged.setChecked(state.get("tagged", False))
        self.filter_assigned.setChecked(state.get("assigned", False))
        self.filter_posted.setChecked(state.get("posted", False))
        self.filter_needs_censor.setChecked(state.get("needs_censor", False))
        self.filter_show_ignored.setChecked(state.get("show_ignored", False))
        # Format filter
        fmt = state.get("format", "")
        self._format_filter = fmt
        if hasattr(self, '_format_combo'):
            # Match by case-insensitive search — handles "PSD", "Has Notes", etc.
            lookup = "All" if not fmt else fmt.title() if " " in fmt else fmt.upper()
            idx = self._format_combo.findText(lookup, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self._format_combo.setCurrentIndex(idx)
            else:
                self._format_combo.setCurrentIndex(0)
        # Tag bar filters
        self._bar_tag_filters = set(state.get("tag_filters", []))
        self._rebuild_tag_buttons()
        # Folder filter
        folders = state.get("folders")
        self._folder_filter = set(folders) if folders else None
        # Refresh
        self._refresh_grid()

    def _compute_filtered(self) -> list[Asset]:
        # Build predicates, then do ONE pass over all assets (avoids 11+ list copies).
        preds = []

        if self._folder_filter:
            _ff = {p.replace("\\", "/") for p in self._folder_filter}
            preds.append(lambda a, ff=_ff:
                         (a.source_folder or str(Path(a.source_path).parent)).replace("\\", "/") in ff)

        query = self.search_box.text().strip().lower()
        if query:
            if self.search_tags_check.isChecked():
                preds.append(lambda a, q=query: any(q in t.lower() for t in a.tags))
            elif "*" in query or "?" in query:
                preds.append(lambda a, q=query:
                             fnmatch.fnmatch(Path(a.source_path).name.lower(), q) or
                             fnmatch.fnmatch((a.source_folder or str(Path(a.source_path).parent)).lower(), q))
            else:
                preds.append(lambda a, q=query:
                             q in Path(a.source_path).name.lower() or
                             q in (a.source_folder or str(Path(a.source_path).parent)).lower())

        if self.filter_starred.isChecked():
            preds.append(lambda a: a.starred > 0)
        if self.filter_untagged.isChecked():
            preds.append(lambda a: not a.tags)
        if self.filter_tagged.isChecked():
            preds.append(lambda a: bool(a.tags))
        if self._format_filter == "ignored":
            preds.append(lambda a: "ignore" in a.tags)
        elif not self.filter_show_ignored.isChecked():
            preds.append(lambda a: "ignore" not in a.tags)
        if self._format_filter == "has notes":
            preds.append(lambda a: bool(a.notes and a.notes.strip()))
        if self._format_filter == "studio edited":
            preds.append(lambda a: bool(a.censors or a.overlays))
        if self.filter_assigned.isChecked():
            preds.append(lambda a: bool(a.assignments))
        if self.filter_posted.isChecked():
            preds.append(lambda a: any(pa.status == "posted" for pa in a.assignments))
        if self.filter_needs_censor.isChecked():
            from doxyedit.models import PLATFORMS as _PLATS
            _cp = {pid for pid, p in _PLATS.items() if p.needs_censor}
            preds.append(lambda a, cp=_cp:
                         any(pa.platform in cp for pa in a.assignments) and not a.censors)

        _special_filters = {"ignored", "has notes", "studio edited"}
        if self._format_filter and self._format_filter not in _special_filters:
            _known = {".psd", ".png", ".jpg", ".jpeg", ".sai", ".sai2", ".webp", ".clip", ".csp"}
            _ff = self._format_filter
            if _ff == "other":
                preds.append(lambda a: Path(a.source_path).suffix.lower() not in _known)
            elif _ff == "jpg":
                preds.append(lambda a: Path(a.source_path).suffix.lower() in (".jpg", ".jpeg"))
            elif _ff == "sai":
                preds.append(lambda a: Path(a.source_path).suffix.lower() in (".sai", ".sai2"))
            else:
                preds.append(lambda a, ext="." + _ff: Path(a.source_path).suffix.lower() == ext)

        if self._bar_tag_filters:
            _btf = self._bar_tag_filters
            preds.append(lambda a, btf=_btf: btf.intersection(a.tags))

        if self.show_hidden_only and self._eye_hidden_tags:
            _eht = self._eye_hidden_tags
            preds.append(lambda a, eht=_eht: eht.intersection(a.tags))
        elif self._eye_hidden_tags:
            _eht = self._eye_hidden_tags
            preds.append(lambda a, eht=_eht: not eht.intersection(a.tags))

        if self._temp_hidden_ids:
            _thi = self._temp_hidden_ids
            preds.append(lambda a, thi=_thi: a.id not in thi)

        if preds:
            assets = [a for a in self.project.assets if all(p(a) for p in preds)]
        else:
            assets = list(self.project.assets)

        sort_mode = self.sort_combo.currentText()
        if sort_mode == "By Folder":
            secondary = self._prev_sort_mode
            # Apply secondary sort first (stable), then stable-sort by folder
            if secondary in ("Newest", "Oldest", "Largest", "Smallest"):
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
                sec_funcs = {
                    "Newest":   (lambda a: mtime_cache[a.id], True),
                    "Oldest":   (lambda a: mtime_cache[a.id], False),
                    "Largest":  (lambda a: fsize_cache[a.id], True),
                    "Smallest": (lambda a: fsize_cache[a.id], False),
                }
                fn, rev = sec_funcs[secondary]
                assets.sort(key=fn, reverse=rev)
            elif secondary == "Name Z-A":
                assets.sort(key=lambda a: Path(a.source_path).stem.lower(), reverse=True)
            elif secondary == "Starred First":
                assets.sort(key=lambda a: (0 if a.starred > 0 else 1,
                                           Path(a.source_path).stem.lower()))
            elif secondary == "Most Tagged":
                assets.sort(key=lambda a: (-len(a.tags), Path(a.source_path).stem.lower()))
            else:  # Name A-Z (default)
                assets.sort(key=lambda a: Path(a.source_path).stem.lower())
            # Stable sort by folder groups each section while preserving within-folder order
            assets.sort(key=lambda a: (a.source_folder or
                                       Path(a.source_path).parent.as_posix()).lower())
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
        # Auto-reduce thumb size for large projects so the initial load is fast
        n = len(self.project.assets)
        if n >= 10_000 and self._thumb_size > 64:
            settings = QSettings("DoxyEdit", "DoxyEdit")
            if not settings.value("thumb_size_user_set"):
                self._thumb_size = 64
                self._delegate.thumb_size = 64
                self._delegate.invalidate_cache()
                self._list_view.setGridSize(self._delegate.grid_size_for(64))
                for section in self._folder_sections:
                    section.update_grid_size(64)

        saved_ids = set(self._selected_ids)
        self.project.invalidate_index()
        self._filtered_assets = self._compute_filtered()

        is_folder_sort = self.sort_combo.currentText() == "By Folder"
        self._view_stack.setCurrentIndex(1 if is_folder_sort else 0)
        self._fold_all_btn.setVisible(is_folder_sort)
        self._unfold_all_btn.setVisible(is_folder_sort)

        if is_folder_sort:
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

            QTimer.singleShot(50, self._request_visible_thumbs)

        # Update counts
        total = len(self.project.assets)
        shown = len(self._filtered_assets)
        starred = sum(1 for a in self.project.assets if a.starred > 0)
        tagged = sum(1 for a in self.project.assets if a.tags)
        any_filter = (self._bar_tag_filters or self.search_box.text().strip()
                      or self.filter_starred.isChecked() or self.filter_untagged.isChecked()
                      or self.filter_tagged.isChecked() or self.filter_assigned.isChecked()
                      or self.filter_posted.isChecked() or self.filter_needs_censor.isChecked()
                      or self._format_filter in ("has notes", "studio edited"))
        filtered_marker = "  ⬡ FILTERED" if (any_filter and shown < total) else ""
        self.count_label.setText(f"{shown}/{total} shown, {starred}★, {tagged} tagged{filtered_marker}")
        self.page_label.setText(f"{shown} images")

        # Rebuild group/variant lookup indexes + used tag cache
        self._duplicate_groups.clear()
        self._variant_sets.clear()
        used_tags: set[str] = set()
        for a in self.project.assets:
            used_tags.update(a.tags)
            dg = a.specs.get("duplicate_group")
            if dg:
                self._duplicate_groups.setdefault(dg, []).append(a.id)
            vs = a.specs.get("variant_set")
            if vs:
                self._variant_sets.setdefault(vs, []).append(a.id)
        self._used_tag_ids = used_tags

    def _rebuild_folder_sections(self, saved_ids=None):
        """Rebuild per-folder QListView sections, grouped under import-source roots."""
        from collections import defaultdict

        # Group assets by folder (order preserved from sorted filtered list)
        groups: dict[str, list] = defaultdict(list)
        for a in self._filtered_assets:
            folder = a.source_folder or Path(a.source_path).parent.as_posix()
            groups[folder].append(a)

        # Remove old sections and root headers
        for section in self._folder_sections:
            self._folder_container_layout.removeWidget(section)
            section.deleteLater()
        self._folder_sections.clear()
        for hdr in getattr(self, '_root_headers', []):
            self._folder_container_layout.removeWidget(hdr)
            hdr.deleteLater()
        self._root_headers = []

        # Build import-source → child-folders map
        import_roots: list[str] = [
            src["path"] for src in self.project.import_sources
            if src.get("type") == "folder"
        ]

        def find_root(folder: str) -> str | None:
            """Return the deepest import_root that is an ancestor of folder."""
            fp = Path(folder)
            best = None
            best_len = 0
            for root in import_roots:
                rp = Path(root)
                try:
                    fp.relative_to(rp)
                    if len(rp.parts) > best_len:
                        best = root
                        best_len = len(rp.parts)
                except ValueError:
                    pass
            return best

        # Build ordered groups: root → [(folder, assets, depth)]
        root_groups: dict[str | None, list] = defaultdict(list)
        root_order: list[str | None] = []
        seen_roots: set = set()
        for folder, assets in groups.items():
            root = find_root(folder)
            if root not in seen_roots:
                root_order.append(root)
                seen_roots.add(root)
            if root:
                rel_depth = len(Path(folder).parts) - len(Path(root).parts)
            else:
                # No import root — compute depth from shallowest folder in project
                all_parts = [len(Path(f).parts) for f in groups]
                min_depth = min(all_parts) if all_parts else 0
                rel_depth = len(Path(folder).parts) - min_depth
            root_groups[root].append((folder, assets, rel_depth))

        def _make_section(folder, assets, depth):
            fn = folder.replace("\\", "/")
            if fn in self._hidden_folders:
                return None
            collapsed = fn in self._collapsed_folders
            section = FolderSection(
                folder=folder, assets=assets, delegate=self._delegate,
                thumb_size=self._thumb_size, collapsed=collapsed,
                depth=depth, parent=self._folder_container,
            )
            section.collapsed_changed.connect(self._on_folder_collapsed)
            section.remove_requested.connect(self._on_folder_remove_requested)
            section.select_all_requested.connect(self._on_folder_select_all)
            section.collapse_children_requested.connect(self._on_collapse_children)
            section.date_filter_requested.connect(self._on_folder_date_filter)
            section.hide_requested.connect(self._on_folder_hide)
            section.restore_colors()
            section.view.customContextMenuRequested.connect(
                lambda pos, s=section: self._on_folder_context_menu_pos(pos, s))
            section.view.doubleClicked.connect(
                lambda idx, s=section: self._on_folder_double_click(idx, s))
            section.view.selectionModel().selectionChanged.connect(
                lambda _sel, _des, s=section: self._on_folder_selection_changed(s))
            section.view.selectionModel().currentChanged.connect(
                lambda cur, _, v=section.view: v.scrollTo(cur, v.ScrollHint.EnsureVisible)
                if cur.isValid() else None)
            section.view.installEventFilter(self)
            section.view.viewport().installEventFilter(self)
            return section

        insert_before_stretch = lambda w: self._folder_container_layout.insertWidget(
            max(0, self._folder_container_layout.count() - 1), w)

        for root in root_order:
            entries = root_groups[root]
            has_multiple = len(entries) > 1

            if root and has_multiple:
                # Root header + indented child sections
                total = sum(len(a) for _, a, _ in entries)
                hdr = RootFolderHeader(root, total, parent=self._folder_container,
                                      on_expand=self._request_visible_thumbs)
                insert_before_stretch(hdr)
                self._root_headers.append(hdr)

                child_sections = []
                for folder, assets, depth in entries:
                    section = _make_section(folder, assets, depth + 1)
                    if section is None:
                        continue
                    insert_before_stretch(section)
                    self._folder_sections.append(section)
                    child_sections.append(section)
                hdr.set_children(child_sections)
            else:
                # Single folder or no matching root — show flat at depth 0
                for folder, assets, depth in entries:
                    section = _make_section(folder, assets, 0)
                    if section is None:
                        continue
                    insert_before_stretch(section)
                    self._folder_sections.append(section)


        # Re-apply hidden subfolders from right-click Hide Subfolders
        for folder_norm in list(self._hidden_folders):
            prefix = folder_norm + "/"
            child_count = 0
            for section in self._folder_sections:
                sf = section.folder.replace("\\", "/")
                if sf.startswith(prefix):
                    section.setVisible(False)
                    child_count += 1
            if child_count:
                source = next((s for s in self._folder_sections
                               if s.folder.replace("\\", "/") == folder_norm), None)
                if source:
                    source._child_folder_count = child_count
                    source._update_header_text()

        # Backfill cached pixmaps into new model instances so thumbs don't vanish on rebuild
        cached = self._thumb_cache._pixmaps
        for section in self._folder_sections:
            m = section.folder_model
            for i in range(m.rowCount()):
                a = m.get_asset(m.index(i))
                if a and a.id in cached:
                    m._pixmaps[a.id] = cached[a.id]

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

        # Trigger layout recalc once views have been sized, then request thumbs
        QTimer.singleShot(0, self._finalize_folder_layout)
        QTimer.singleShot(200, self._finalize_folder_layout)  # second pass after layout settles
        QTimer.singleShot(500, self._finalize_folder_layout)

        if not self._folder_scroll_vp_installed:
            self._folder_scroll.viewport().installEventFilter(self)
            self._folder_scroll_vp_installed = True

    def _finalize_folder_layout(self):
        """One-shot layout finalization after folder sections are created."""
        vp_w = self._folder_scroll.viewport().width()
        vp_h = self._folder_scroll.viewport().height()
        for section in self._folder_sections:
            if vp_h > 100:
                section._max_section_height = vp_h
            section.update_view_height(vp_w)
        self._folder_container.adjustSize()
        self._request_visible_thumbs()

    def _on_folder_collapsed(self, folder: str, is_collapsed: bool):
        norm = folder.replace("\\", "/")
        if is_collapsed:
            self._collapsed_folders.add(norm)
        else:
            self._collapsed_folders.discard(norm)
            self._request_visible_thumbs()

    def _on_collapse_children(self, folder: str, collapse: bool):
        """Ctrl+click: collapse/expand all child folder sections under this one."""
        folder_norm = folder.replace("\\", "/")
        prefix = folder_norm + "/"
        for section in self._folder_sections:
            sf = section.folder.replace("\\", "/")
            if sf.startswith(prefix):
                section._set_collapsed(collapse)
                if collapse:
                    self._collapsed_folders.add(section.folder)
                else:
                    self._collapsed_folders.discard(section.folder)
        if not collapse:
            self._request_visible_thumbs()



    def _on_folder_hide(self, folder: str):
        """Toggle hide/show child folder sections under this folder."""
        folder_norm = folder.replace("\\", "/")
        prefix = folder_norm + "/"
        show = folder_norm in self._hidden_folders  # toggle
        if show:
            self._hidden_folders.discard(folder_norm)
        else:
            self._hidden_folders.add(folder_norm)
        # Single pass: find source and toggle children
        source = None
        child_count = 0
        for section in self._folder_sections:
            sf = section.folder.replace("\\", "/")
            if sf == folder_norm:
                source = section
            elif sf.startswith(prefix):
                section.setVisible(show)
                child_count += 1
        if source:
            source._child_folder_count = 0 if show else child_count
            source._update_header_text()
        if show:
            self._request_visible_thumbs()

    def _on_folder_select_all(self, folder: str, recursive: bool):
        """Select all assets in a folder (optionally recursive)."""
        folder_norm = folder.replace("\\", "/")
        ids = []
        for a in self.project.assets:
            af = (a.source_folder or str(Path(a.source_path).parent)).replace("\\", "/")
            if recursive:
                if af == folder_norm or af.startswith(folder_norm + "/"):
                    ids.append(a.id)
            else:
                if af == folder_norm:
                    ids.append(a.id)
        self._selected_ids = set(ids)
        self.selection_changed.emit(list(self._selected_ids))
        if len(ids) == 1:
            self.asset_selected.emit(ids[0])
        self._refresh_grid()

    def _on_folder_remove_requested(self, folder: str):
        n = sum(1 for a in self.project.assets if a.source_folder == folder)
        reply = QMessageBox.question(
            self, "Remove Folder",
            f"Permanently remove {n} asset record{'s' if n != 1 else ''} from:\n{folder}\n\n"
            "The folder will never be re-scanned. Source files are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.project.assets = [a for a in self.project.assets if a.source_folder != folder]
        self.project.excluded_paths.add(folder)
        self.project.invalidate_index()
        self._refresh_grid()

    def _on_folder_date_filter(self, folder: str):
        """Right-click → Set Date Filter on a folder header."""
        norm = folder.replace("\\", "/")
        source = next((s for s in self.project.import_sources
                       if s.get("path", "").replace("\\", "/") == norm), None)
        dlg = _DateFilterDialog(current=source.get("filter_newer_than", "") if source else "",
                                parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        date_val = dlg.filter_date
        if source:
            source["filter_newer_than"] = date_val
        else:
            self._record_import_source("folder", folder, recursive=False)
            for s in self.project.import_sources:
                if s.get("path", "").replace("\\", "/") == norm:
                    s["filter_newer_than"] = date_val
                    break
        if date_val:
            self.window().status.showMessage(f"Date filter set: only files after {date_val[:10]}", 3000)
        else:
            self.window().status.showMessage("Date filter cleared", 3000)

    def _on_folder_selection_changed(self, active_section=None):
        # Clear other sections so cross-folder sticky selection doesn't accumulate
        if active_section is not None:
            for section in self._folder_sections:
                if section is not active_section:
                    section.view.selectionModel().blockSignals(True)
                    section.view.clearSelection()
                    section.view.selectionModel().blockSignals(False)
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
        self._update_link_highlights()

    def _on_folder_double_click(self, index: QModelIndex, section: "FolderSection"):
        asset = section.folder_model.get_asset(index)
        if asset:
            self.asset_preview.emit(asset.id)

    def _on_folder_context_menu_pos(self, pos, section: "FolderSection"):
        index = section.view.indexAt(pos)
        asset = section.folder_model.get_asset(index) if index.isValid() else None
        if asset:
            self._on_context_menu(asset.id, section.view.viewport().mapToGlobal(pos))

    # --- Thumb cache callbacks ---

    def _on_thumb_ready(self, asset_id: str, img, w: int, h: int, gen_size: int):
        if not self._thumb_cache.on_ready(asset_id, img, w, h, gen_size):
            return  # lower-res than what we already have — skip update
        pixmap = self._thumb_cache.get(asset_id)
        if pixmap is None:
            return
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
                    self._cache_all_remaining = []
                    self.cache_all_check.blockSignals(True)
                    self.cache_all_check.setChecked(False)
                    self.cache_all_check.blockSignals(False)
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

    def _on_palette_ready(self, asset_id: str, colors: list):
        """Store extracted palette colors in asset specs."""
        if not self.project:
            return
        asset = self.project.get_asset(asset_id)
        if asset:
            asset.specs["palette"] = colors

    def _on_phash_ready(self, asset_id: str, phash_hex: str):
        """Store computed perceptual hash in asset specs."""
        if not self.project:
            return
        asset = self.project.get_asset(asset_id)
        if asset:
            asset.specs["phash"] = int(phash_hex, 16)

    # --- Selection ---

    def _on_selection_changed_internal(self, selected, deselected):
        indexes = self._list_view.selectionModel().selectedIndexes()
        self._selected_ids = {a.id for idx in indexes
                              if (a := self._model.get_asset(idx)) is not None}
        # Emit single-select immediately; debounce multi-select for rubber-band drag performance
        if len(self._selected_ids) == 1:
            self._selection_emit_timer.stop()
            self.selection_changed.emit(list(self._selected_ids))
            self.asset_selected.emit(next(iter(self._selected_ids)))
        else:
            self._selection_emit_timer.start()
        self._update_link_highlights()

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
        self._selected_ids = {asset_id}
        flag = QItemSelectionModel.SelectionFlag.ClearAndSelect
        if self._view_stack.currentIndex() == 0:
            # Flat view
            for i, a in enumerate(self._filtered_assets):
                if a.id == asset_id:
                    idx = self._model.index(i)
                    self._list_view.scrollTo(idx, self._list_view.ScrollHint.PositionAtCenter)
                    self._list_view.selectionModel().setCurrentIndex(idx, flag)
                    break
        else:
            # Folder view — find the section and row
            for section in self._folder_sections:
                for i in range(section.folder_model.rowCount()):
                    a = section.folder_model.get_asset(section.folder_model.index(i))
                    if a and a.id == asset_id:
                        idx = section.folder_model.index(i)
                        section.view.scrollTo(idx, section.view.ScrollHint.PositionAtCenter)
                        section.view.selectionModel().setCurrentIndex(idx, flag)
                        # Scroll the outer scroll area to the section
                        section_y = section.mapTo(self._folder_container, QPoint(0, 0)).y()
                        self._folder_scroll.verticalScrollBar().setValue(section_y)
                        break
        self.selection_changed.emit([asset_id])

    def shutdown(self):
        self._thumb_cache.shutdown()

    # --- Import ---

    def open_folder_dialog(self):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        last_dir = settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Open Image Folder", last_dir)
        if folder:
            settings.setValue("last_folder", folder)
            has_subdirs = any(p.is_dir() for p in Path(folder).iterdir())
            opts = _ImportOptionsDialog(has_subdirs=has_subdirs, parent=self)
            if opts.exec() != QDialog.DialogCode.Accepted:
                return
            recursive = opts.recursive
            date_filter = opts.filter_date
            # Pre-create the import source record so the date filter is
            # available immediately (the async worker will update it later).
            self._record_import_source("folder", folder, recursive)
            if date_filter:
                norm = folder.replace("\\", "/")
                for source in self.project.import_sources:
                    if source.get("path", "").replace("\\", "/") == norm:
                        source["filter_newer_than"] = date_filter
                        break
            self._import_folder_async(folder, recursive=recursive)

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
            "filter_newer_than": "",
        })

    def import_folder(self, folder: str, recursive: bool = None):
        """Synchronous folder import — used for auto-load, presets, drag-drop.
        For interactive folder picker use _import_folder_async instead."""
        if recursive is None:
            recursive = self.recursive_check.isChecked()
        folder_path = Path(folder)
        existing = {a.source_path for a in self.project.assets}
        excluded = getattr(self.project, 'excluded_paths', set())
        count = 0
        it = folder_path.rglob("*") if recursive else folder_path.iterdir()
        for f in it:
            if (f.is_file() and f.suffix.lower() in IMAGE_EXTS
                    and str(f) not in existing
                    and str(f) not in excluded
                    and str(f.parent) not in excluded):
                # Date filter: skip files older than the source's filter date
                source_entry = next((s for s in self.project.import_sources
                                     if s.get("path", "").replace("\\", "/") == str(f.parent).replace("\\", "/")
                                     or s.get("path", "").replace("\\", "/") == folder.replace("\\", "/")), None)
                if source_entry and source_entry.get("filter_newer_than"):
                    from datetime import datetime
                    try:
                        cutoff = datetime.fromisoformat(source_entry["filter_newer_than"]).timestamp()
                        if f.stat().st_mtime < cutoff:
                            continue
                    except (ValueError, OSError):
                        pass
                self.project.assets.append(Asset(
                    id=f.stem + "_" + str(len(self.project.assets)),
                    source_path=str(f), source_folder=str(f.parent),
                    tags=auto_suggest_tags(f.stem) if self.auto_tag_enabled else []))
                count += 1
        self._record_import_source("folder", str(folder_path), recursive)
        if count:
            self._refresh_grid()
        return count

    def _import_folder_async(self, folder: str, recursive: bool):
        """Non-blocking folder import with progress dialog — use for interactive picker."""
        existing = frozenset(a.source_path for a in self.project.assets)
        excluded = frozenset(getattr(self.project, 'excluded_paths', set()))

        dlg = QProgressDialog(
            f"Scanning {Path(folder).name}...", "Cancel", 0, 0, self.window())
        dlg.setWindowTitle("Importing Folder")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)
        dlg.show()

        added = [0]

        def _on_batch(paths: list):
            for path_str in paths:
                p = Path(path_str)
                self.project.assets.append(Asset(
                    id=p.stem + "_" + str(len(self.project.assets)),
                    source_path=path_str,
                    source_folder=str(p.parent),
                    tags=auto_suggest_tags(p.stem) if self.auto_tag_enabled else []))
                added[0] += 1
            dlg.setLabelText(
                f"Scanning {Path(folder).name}...\n{added[0]:,} files found")

        def _on_finished(_total: int):
            dlg.close()
            if added[0]:
                self._record_import_source("folder", folder, recursive)
                self._refresh_grid()
            self.folder_opened.emit(folder)
            self._active_import_worker = None

        worker = FolderScanWorker(
            folder, recursive, existing, excluded, IMAGE_EXTS, parent=self)
        worker.batch_ready.connect(_on_batch, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(_on_finished, Qt.ConnectionType.QueuedConnection)
        dlg.canceled.connect(worker.cancel)
        self._active_import_worker = worker  # prevent GC
        worker.start()

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
        if event.mimeData().hasUrls() and event.source() is None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and event.source() is None:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() is not None:
            event.ignore()
            return
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

    # --- Drag fix (F8 cycles methods) ---

    _drag_fix = 1  # default: method 1
    _last_press_pos = QPointF(0, 0)
    _DRAG_FIXES = [
        "pass press (blocked) + re-select",
        "pass press (blocked) + setState + re-select",
        "pass press (blocked) + fake release + re-select",
        "consume press + fake release",
        "consume press + setState",
        "consume press + fake press+release at pos + re-select",
    ]

    def cycle_drag_fix(self):
        self._drag_fix = (self._drag_fix + 1) % len(self._DRAG_FIXES)
        try:
            self.window().status.showMessage(
                f"Drag fix: {self._DRAG_FIXES[self._drag_fix]} ({self._drag_fix})", 3000)
        except Exception:
            pass

    def _should_consume_press(self):
        return self._drag_fix >= 3

    def _pre_drag_setup(self, view):
        if self._drag_fix < 3:
            view.selectionModel().blockSignals(True)

    def _post_press_restore(self, view):
        if self._drag_fix < 3:
            view.selectionModel().blockSignals(False)

    @staticmethod
    def _fake_release(pos=QPointF(0, 0)):
        return QMouseEvent(QEvent.Type.MouseButtonRelease, pos,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)

    def _reselect_items(self, view, model, saved_sel):
        """Restore selection from saved IDs using model's id→index map."""
        if not saved_sel:
            return
        sm = view.selectionModel()
        sm.blockSignals(True)
        # Use asset index if model has one, else linear scan
        id_map = getattr(model, '_id_to_row', None)
        if id_map:
            for aid in saved_sel:
                row = id_map.get(aid)
                if row is not None:
                    sm.select(model.index(row), QItemSelectionModel.SelectionFlag.Select)
        else:
            for i in range(model.rowCount()):
                idx = model.index(i)
                a = model.get_asset(idx)
                if a and a.id in saved_sel:
                    sm.select(idx, QItemSelectionModel.SelectionFlag.Select)
        sm.blockSignals(False)
        view.viewport().update()

    def _post_drag_cleanup(self, view, model, saved_sel):
        m = self._drag_fix
        if m == 0:
            self._reselect_items(view, model, saved_sel)
        elif m == 1:
            view.setState(QListView.State.NoState)
            self._reselect_items(view, model, saved_sel)
        elif m == 2:
            QApplication.sendEvent(view.viewport(), self._fake_release())
            self._reselect_items(view, model, saved_sel)
        elif m == 3:
            QApplication.sendEvent(view.viewport(), self._fake_release())
        elif m == 4:
            view.setState(QListView.State.NoState)
        elif m == 5:
            sm = view.selectionModel()
            sm.blockSignals(True)
            fake_p = QMouseEvent(QEvent.Type.MouseButtonPress, self._last_press_pos,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(view.viewport(), fake_p)
            QApplication.sendEvent(view.viewport(), self._fake_release(self._last_press_pos))
            sm.blockSignals(False)
            self._reselect_items(view, model, saved_sel)

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
        menu.addAction("Send to Studio", lambda: self.asset_to_canvas.emit(asset_id))
        menu.addAction("Prepare for Posting...", lambda: self.asset_to_post.emit(asset_id))
        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: _open_explorer(asset))
        # Open in Editor submenu
        editor_menu = menu.addMenu("Open in Editor")
        editor_menu.addAction("Native Editor\tF3", lambda: self._open_in_native_editor())
        editor_menu.addSeparator()
        # Add ALL configured editors (multiple per extension supported)
        s = QSettings("DoxyEdit", "DoxyEdit")
        all_keys = [k for k in s.allKeys() if k.startswith("native_editor/")]
        for key in sorted(all_keys):
            editor_path = s.value(key, "")
            if not editor_path:
                continue
            ext = key.replace("native_editor/", "").split("/")[0]
            name = Path(editor_path).stem
            editor_menu.addAction(f"{name} ({ext})",
                lambda p=editor_path: [subprocess.Popen([p, a.source_path]) for a in self.get_selected_assets()])
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
        # Quick Tag submenu — used/custom tags flat at top, unused presets in "More Tags"
        all_tags_map = self.project.get_tags()
        custom_tag_ids = set(self.project.tag_definitions.keys())
        used_tag_ids = getattr(self, '_used_tag_ids', set())
        # "Active" = custom-defined OR actually used on assets — shown flat
        active_tags = [t for t in all_tags_map.values()
                       if t.id in custom_tag_ids or t.id in used_tag_ids]
        # "Other" = preset tags not used and not custom — buried in More Tags
        other_tags = [t for t in all_tags_map.values()
                      if t.id not in custom_tag_ids and t.id not in used_tag_ids]
        if all_tags_map:
            qt_menu = menu.addMenu("Quick Tag")
            MAX_PER_COL = 10

            def _add_tag_action(parent_menu, tag):
                checked = tag.id in asset.tags
                a = parent_menu.addAction(f"{'✓ ' if checked else '   '}{tag.label}")
                a.triggered.connect(lambda _, tid=tag.id: self._toggle_tag_multi(asset, tid))

            # Active tags — flat, always first
            for tag in active_tags:
                _add_tag_action(qt_menu, tag)

            # Unused preset tags — in "More Tags" submenu if any
            if other_tags:
                if active_tags:
                    qt_menu.addSeparator()
                if len(other_tags) <= MAX_PER_COL:
                    for tag in other_tags:
                        _add_tag_action(qt_menu, tag)
                else:
                    presets_menu = qt_menu.addMenu("More Tags")
                    for col_start in range(0, len(other_tags), MAX_PER_COL):
                        chunk = other_tags[col_start:col_start + MAX_PER_COL]
                        first, last = chunk[0].label, chunk[-1].label
                        col_menu = presets_menu.addMenu(f"{first} – {last}")
                        for tag in chunk:
                            _add_tag_action(col_menu, tag)

        # --- Group / Variant linking ---
        menu.addSeparator()
        dup_grp = asset.specs.get("duplicate_group")
        var_set = asset.specs.get("variant_set")

        if dup_grp and dup_grp in self._duplicate_groups:
            grp_ids = self._duplicate_groups[dup_grp]
            dup_menu = menu.addMenu(f"Duplicate Group ({len(grp_ids)})")
            dup_menu.addAction(f"Select All ({len(grp_ids)})", lambda: self._select_ids(grp_ids))
            is_keeper = asset.specs.get("duplicate_keep", False)
            if not is_keeper:
                dup_menu.addAction("Mark as Keeper", lambda a=asset: self._mark_as_keeper(a))
            dup_menu.addAction("Remove from Group", lambda a=asset: self._unlink_duplicate(a))
            dup_menu.addAction("Dissolve Group", lambda gid=dup_grp: self._dissolve_duplicate_group(gid))

        if var_set and var_set in self._variant_sets:
            set_ids = self._variant_sets[var_set]
            var_menu = menu.addMenu(f"Variant Set ({len(set_ids)})")
            var_menu.addAction(f"Select All ({len(set_ids)})", lambda: self._select_ids(set_ids))
            if n_sel > 1:
                var_menu.addAction(f"Add {n_sel} Selected to This Set", self._link_selected_as_variants)
            var_menu.addSeparator()
            var_menu.addAction("Remove from Set", lambda a=asset: self._unlink_variant(a))
            var_menu.addAction("Dissolve Set", lambda sid=var_set: self._dissolve_variant_set(sid))
        elif n_sel > 1:
            # No existing set — offer to create one
            menu.addAction(f"Link {n_sel} as Variants", self._link_selected_as_variants)

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
        if n_sel > 1:
            menu.addAction(f"Remove {n_sel} from Project", lambda: self._remove_selected())
        else:
            menu.addAction("Remove from Project", lambda: self._remove_asset(asset))
        if self._format_filter == "ignored" or self.filter_show_ignored.isChecked():
            menu.addSeparator()
            if n_sel > 1:
                menu.addAction(f"Delete {n_sel} from Disk (permanent)",
                    lambda: self._delete_selected_from_disk())
            else:
                menu.addAction("Delete from Disk (permanent)",
                    lambda: self._delete_from_disk(asset))
        menu.exec(pos)

    def _set_assignment_status(self, pa, status: str):
        pa.status = status
        self._refresh_grid()
        self._mark_dirty()

    def _delete_from_disk(self, asset):
        """Permanently delete file from disk + remove from project. Requires confirmation."""
        path = asset.source_path
        name = Path(path).name
        reply = QMessageBox.warning(
            self, "Delete from Disk",
            f"Permanently delete this file?\n\n{name}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Delete file
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            QMessageBox.critical(self, "Delete Failed", f"Could not delete:\n{e}")
            return
        # Remove from project
        self._remove_asset(asset)

    def _export_selected(self):
        assets = self.get_selected_assets()
        if not assets:
            return
        folder = QFileDialog.getExistingDirectory(self.window(), "Export Selected Assets To...")
        if not folder:
            return
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
        dlg = QInputDialog(self.window())
        dlg.setWindowTitle("Add Tag")
        dlg.setLabelText("Tag to add:")
        dlg.setStyleSheet(self.window().styleSheet())
        ok = dlg.exec()
        tag = dlg.textValue()
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

    def _remove_selected(self):
        """Remove all selected assets from project."""
        n = len(self._selected_ids)
        if QMessageBox.question(self, "Remove from Project",
            f"Remove {n} assets from project?") != QMessageBox.StandardButton.Yes:
            return
        ids = set(self._selected_ids)
        self.project.assets = [a for a in self.project.assets if a.id not in ids]
        self._selected_ids.clear()
        self._refresh_grid()
        self._mark_dirty()

    def _delete_selected_from_disk(self):
        """Permanently delete all selected files from disk + remove from project."""
        assets = self.get_selected_assets()
        n = len(assets)
        reply = QMessageBox.warning(
            self, "Delete from Disk",
            f"Permanently delete {n} files?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = 0
        for asset in assets:
            try:
                if os.path.exists(asset.source_path):
                    os.remove(asset.source_path)
                    deleted += 1
            except OSError:
                pass
        # Remove from project
        ids = {a.id for a in assets}
        self.project.assets = [a for a in self.project.assets if a.id not in ids]
        self._selected_ids.clear()
        self._refresh_grid()
        self._mark_dirty()

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
        if not hasattr(self, '_list_view'):
            return None, None
        if obj is self._list_view or obj is self._list_view.viewport():
            return self._list_view, self._model
        for section in self._folder_sections:
            v = section.view
            if obj is v or obj is v.viewport():
                return v, section.folder_model
        return None, None

    def eventFilter(self, obj, event):
        # Folder scroll viewport resize → recalculate section heights
        if hasattr(self, '_folder_scroll') and obj is self._folder_scroll.viewport() and event.type() == event.Type.Resize:
            vp_w = self._folder_scroll.viewport().width()
            vp_h = self._folder_scroll.viewport().height()
            for section in self._folder_sections:
                section._max_section_height = vp_h if vp_h > 100 else 0
                section.update_view_height(vp_w)
            self._folder_container.adjustSize()
            return False

        view, model = self._view_for_obj(obj)
        vp = view.viewport() if view is not None else None
        if view is not None:
            # Ctrl+Scroll zoom
            if event.type() == event.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    # Anchor to item under the mouse, fall back to viewport center
                    mouse_vp = view.mapFromGlobal(
                        event.globalPosition().toPoint()
                        if hasattr(event, 'globalPosition') else event.globalPos())
                    anchor = view.indexAt(mouse_vp)
                    if not anchor.isValid():
                        anchor = view.indexAt(view.viewport().rect().center())
                    if not anchor.isValid():
                        anchor = view.currentIndex()

                    delta = event.angleDelta().y()
                    self._set_thumb_size(self._thumb_size + (20 if delta > 0 else -20))
                    if anchor.isValid():
                        if view is self._list_view:
                            QTimer.singleShot(0, lambda v=view, c=anchor: v.scrollTo(c, QListView.ScrollHint.PositionAtCenter))
                        else:
                            def _scroll_to_item(v=view, c=anchor):
                                for section in self._folder_sections:
                                    if section.view is v:
                                        ir = v.visualRect(c)
                                        if ir.isValid():
                                            item_y = v.mapTo(self._folder_container, ir.topLeft()).y() + ir.height() // 2
                                            vp_h = self._folder_scroll.viewport().height()
                                            sb = self._folder_scroll.verticalScrollBar()
                                            sb.setValue(max(0, min(item_y - vp_h // 2, sb.maximum())))
                                        break
                            QTimer.singleShot(0, _scroll_to_item)
                    return True

            # Alt+Scroll — jump between folder section headers (folder view only)
            if event.type() == event.Type.Wheel:
                if (event.modifiers() & Qt.KeyboardModifier.AltModifier
                        and self._view_stack.currentIndex() == 1):
                    delta = event.angleDelta().y()
                    sb = self._folder_scroll.verticalScrollBar()
                    current_y = sb.value()
                    headers_y = sorted(
                        section.mapTo(self._folder_container, QPoint(0, 0)).y()
                        for section in self._folder_sections
                        if not section.isHidden()
                    )
                    if delta > 0:
                        # Scroll up — jump to previous section above current position
                        candidates = [y for y in headers_y if y < current_y - 4]
                        target = candidates[-1] if candidates else (headers_y[0] if headers_y else current_y)
                    else:
                        # Scroll down — jump to next section below current position
                        candidates = [y for y in headers_y if y > current_y + 4]
                        target = candidates[0] if candidates else (headers_y[-1] if headers_y else current_y)
                    sb.setValue(max(0, min(target, sb.maximum())))
                    return True

            # Star click — detect click in star area of a thumbnail.
            # The delegate now hugs the star to the right edge of the name;
            # we re-compute the same x here so clicks land on target.
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = view.indexAt(pos)
                if index.isValid():
                    item_rect = view.visualRect(index)
                    ts = self._delegate.thumb_size
                    d = self._delegate
                    # Replicate the delegate's star_x placement
                    name_text = index.data(Qt.ItemDataRole.DisplayRole) or ""
                    fm = d._fm(d.name_font_size)
                    max_w = item_rect.width() - d.cell_padding * 2 - d.star_size
                    elided = fm.elidedText(
                        name_text, Qt.TextElideMode.ElideRight, max_w)
                    name_w = fm.horizontalAdvance(elided) if elided else 0
                    star_max_x = item_rect.right() - d.star_size - d.cell_padding
                    star_x = (
                        min(item_rect.x() + d.cell_padding + name_w + 4,
                            star_max_x)
                        if name_w > 0 else star_max_x)
                    star_rect = QRect(
                        star_x,
                        item_rect.y() + ts + d.below_dots_offset + d.dims_line_height,
                        d.star_size, d.star_size)
                    if star_rect.contains(pos):
                        asset = model.get_asset(index)
                        if asset:
                            asset.cycle_star()
                            model.dataChanged.emit(index, index)
                        return True

            # Left press — record drag start for click+drag to external/tray
            if (event.type() == event.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = view.indexAt(pos)
                asset = model.get_asset(index) if index.isValid() else None
                if asset:
                    self._drag_start_pos = view.mapToGlobal(pos)
                    if asset.id in self._selected_ids:
                        self._drag_snapshot_ids = set(self._selected_ids)
                        self._last_press_pos = QPointF(pos)
                        if self._should_consume_press():
                            return True
                        else:
                            # Let Qt process press (resets anchor) but block deselect
                            self._pre_drag_setup(view)
                    else:
                        self._drag_snapshot_ids = set()
                else:
                    self._drag_start_pos = None
                    self._drag_snapshot_ids = set()

            # Left move — initiate drag-out after threshold
            if (event.type() == event.Type.MouseMove
                    and event.buttons() & Qt.MouseButton.LeftButton
                    and getattr(self, '_drag_start_pos', None) is not None
                    and not getattr(self, '_middle_held', False)):
                cur_global = view.mapToGlobal(
                    event.position().toPoint() if hasattr(event, 'position') else event.pos())
                if (cur_global - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                    self._drag_start_pos = None
                    self._post_press_restore(view)
                    snap_ids = getattr(self, '_drag_snapshot_ids', set())
                    assets = [a for a in self.project.assets if a.id in snap_ids] if snap_ids else self.get_selected_assets()
                    urls = [QUrl.fromLocalFile(a.source_path) for a in assets
                            if Path(a.source_path).exists()]
                    if urls:
                        mime = QMimeData()
                        mime.setUrls(urls)
                        drag = QDrag(view)
                        drag.setMimeData(mime)
                        icon_px = self._model._pixmaps.get(assets[0].id) if assets else None
                        if isinstance(icon_px, QPixmap) and not icon_px.isNull():
                            drag.setPixmap(icon_px.scaled(64, 64,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
                        saved_sel = set(self._selected_ids)
                        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
                        self._drag_start_pos = None
                        self._drag_snapshot_ids = set()
                        self._post_drag_cleanup(view, model, saved_sel)
                        return True

            if (event.type() == event.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton):
                self._post_press_restore(view)
                # If we armed for drag but no drag happened,
                # treat as normal click — deselect to just this item
                if self._drag_snapshot_ids and self._drag_start_pos is not None:
                    pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                    index = view.indexAt(pos)
                    if index.isValid():
                        sm = view.selectionModel()
                        sm.select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self._drag_start_pos = None
                self._drag_snapshot_ids = set()

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

            # Key events — pass special keys to browser handlers
            if event.type() == event.Type.KeyPress:
                if event.key() == Qt.Key.Key_Delete:
                    try:
                        self.window()._handle_delete()
                    except Exception:
                        pass
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if self._selected_ids:
                        aid = next(iter(self._selected_ids))
                        self.asset_preview.emit(aid)
                    return True
                if event.key() == Qt.Key.Key_F3:
                    self._open_in_native_editor()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    if self._bar_tag_filters:
                        self.clear_bar_filters()
                        try:
                            self.window().status.showMessage("Tag filters cleared", 1500)
                        except Exception:
                            pass
                    self._list_view.clearSelection()
                    for section in self._folder_sections:
                        section.view.selectionModel().blockSignals(True)
                        section.view.clearSelection()
                        section.view.selectionModel().blockSignals(False)
                    self._selected_ids.clear()
                    self.selection_changed.emit([])
                    return True

        # Esc from search box — deselect without clearing search text
        if obj is self.search_box and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._list_view.clearSelection()
                for section in self._folder_sections:
                    section.view.selectionModel().blockSignals(True)
                    section.view.clearSelection()
                    section.view.selectionModel().blockSignals(False)
                self._selected_ids.clear()
                self.selection_changed.emit([])
                self._list_view.setFocus()
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
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Open preview for the currently selected asset
            if self._selected_ids:
                aid = next(iter(self._selected_ids))
                self.asset_preview.emit(aid)
                return
        if event.key() == Qt.Key.Key_Escape:
            if self._bar_tag_filters:
                self.clear_bar_filters()
                self.window().status.showMessage("Tag filters cleared", 1500)
            self._list_view.clearSelection()
            for section in self._folder_sections:
                section.view.clearSelection()
            self._selected_ids.clear()
            self.selection_changed.emit([])
            return
        super().keyPressEvent(event)

    def _open_in_native_editor(self):
        """Open selected assets in their native editor (os.startfile = system default)."""
        assets = self.get_selected_assets()
        if not assets:
            return
        s = QSettings("DoxyEdit", "DoxyEdit")
        for asset in assets:
            ext = Path(asset.source_path).suffix.lower()
            custom = s.value(f"native_editor/{ext}", "")
            if custom and os.path.exists(custom):
                subprocess.Popen([custom, asset.source_path])
            else:
                try:
                    os.startfile(asset.source_path)
                except Exception:
                    pass


# --- Helpers ---

def _mtime(asset: Asset) -> float:
    try:
        return os.path.getmtime(asset.source_path)
    except OSError:
        return 0

def _open_explorer(asset: Asset):
    path = asset.source_path.replace("/", "\\")
    subprocess.Popen(f'explorer /select,"{path}"')
