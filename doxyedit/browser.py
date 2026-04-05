"""Asset browser — QListView with custom delegate for high-performance thumbnail grid."""
import os
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QStyledItemDelegate,
    QLabel, QPushButton, QFileDialog, QFrame, QLineEdit, QComboBox,
    QMenu, QApplication, QSizePolicy, QStyle, QCheckBox,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QSettings, QSize, QRect, QPoint,
    QAbstractListModel, QModelIndex,
)
from PySide6.QtGui import (
    QPixmap, QFont, QColor, QCursor, QPainter, QPen, QFontMetrics, QPainterPath,
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
            return f"{p.stem[:16]}{p.suffix}"
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

    FOLDER_BAR_H = 24

    def sizeHint(self, option, index):
        h = self.thumb_size + 70
        if index.row() in self._folder_starts:
            h += self.FOLDER_BAR_H
        return QSize(self.thumb_size + 2 * self.PADDING, h)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect

        # Folder separator — paint label in the extra top space of this cell
        row = index.row()
        folder_offset = 0
        if row in self._folder_starts:
            folder_offset = self.FOLDER_BAR_H
            view = option.widget
            vw = view.viewport().width() if view else rect.width()
            folder = self._folder_starts[row]
            bar_rect = QRect(0, rect.y(), vw, self.FOLDER_BAR_H)
            painter.fillRect(bar_rect, QColor(128, 128, 128, 40))
            painter.setPen(QColor(200, 200, 200, 180))
            painter.setFont(QFont("Segoe UI", max(7, self.font_size - 2)))
            painter.drawText(bar_rect.adjusted(6, 0, -6, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"\u25BC {folder}")

        # Offset rect down for folder-start items
        if folder_offset:
            rect = QRect(rect.x(), rect.y() + folder_offset,
                         rect.width(), rect.height() - folder_offset)

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
        self.auto_tag_enabled = False
        self.show_hidden_only = False
        self._collapsed_folders: set[str] = set()
        self._current_font_size = 10
        self._hover_id = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(int(settings.value("hover_delay_ms", 400)))
        self._hover_timer.timeout.connect(self._show_hover)
        self._hover_size_pct = int(settings.value("hover_size_pct", 150))
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
        toolbar.addWidget(self.filter_starred)
        toolbar.addWidget(self.filter_untagged)
        toolbar.addWidget(self.filter_tagged)


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
        self.sort_combo.addItems(["Name A-Z", "Name Z-A", "Newest", "Oldest", "Largest", "Smallest", "By Folder"])
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.sort_combo.currentTextChanged.connect(self._on_sort_mode_changed)
        row2.addWidget(self.sort_combo)
        root.addLayout(row2)

        # Row 3: Quick-tag bar
        self._tag_bar_frame = FlowWidget()
        self._tag_bar_frame.setStyleSheet("border-bottom: 1px solid rgba(128,128,128,0.15);")
        self._tag_bar_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._tag_flow = FlowLayout(self._tag_bar_frame, spacing=4)
        self._tag_flow.setContentsMargins(0, 2, 0, 2)
        self._tag_buttons: list[tuple[QPushButton, str]] = []
        self._rebuild_tag_buttons()
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setToolTip("Add a custom tag")
        self._add_tag_btn.clicked.connect(self._add_custom_tag)
        self._tag_flow.addWidget(self._add_tag_btn)
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
        root.addWidget(self._list_view)

        # Status line
        status = QHBoxLayout()
        status.addStretch()
        self.page_label = QLabel("")
        status.addWidget(self.page_label)
        status.addStretch()
        root.addLayout(status)

    def _btn_style(self):
        return "QPushButton { padding: 6px 12px; font-size: 11px; }"

    def _make_filter_btn(self, label):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setStyleSheet(self._btn_style())
        btn.toggled.connect(self._on_filter_changed)
        return btn

    # --- Tag bar ---

    def _rebuild_tag_buttons(self):
        while self._tag_flow.count():
            item = self._tag_flow.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._tag_buttons.clear()

        all_used = {t for a in self.project.assets for t in a.tags}
        all_tags = self.project.get_tags()
        bar_tags = {}
        # Custom/project tags only — skip built-in presets (TAG_PRESETS + TAG_SIZED)
        for tid, preset in all_tags.items():
            if tid in TAG_PRESETS or tid in TAG_SIZED:
                continue
            if tid in all_used or tid in getattr(self.project, 'tag_definitions', {}):
                bar_tags[tid] = preset
        # Tags used in assets but not defined anywhere (also skip built-ins)
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
            btn.setToolTip(f"{preset.label} — click to toggle")
            btn.clicked.connect(lambda checked, tid=tag_id: self._quick_tag(tid))
            self._tag_buttons.append((btn, preset.color))
            self._tag_flow.addWidget(btn)

    def rebuild_tag_bar(self):
        self._rebuild_tag_buttons()
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setToolTip("Add a custom tag")
        self._add_tag_btn.clicked.connect(self._add_custom_tag)
        self._tag_flow.addWidget(self._add_tag_btn)
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
                f"QPushButton:hover {{ background: {color}; color: rgba(0,0,0,0.8); }}")
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

    # --- Filtering / sorting ---

    def _on_sort_mode_changed(self, text):
        is_folder = text == "By Folder"
        self._fold_all_btn.setVisible(is_folder)
        self._unfold_all_btn.setVisible(is_folder)

    def _collapse_all_folders(self):
        for a in self.project.assets:
            folder = a.source_folder or Path(a.source_path).parent.as_posix()
            self._collapsed_folders.add(folder)
        self._refresh_grid()

    def _expand_all_folders(self):
        self._collapsed_folders.clear()
        self._refresh_grid()

    def _on_filter_changed(self, *_):
        self._refresh_grid()

    def _on_search_mode_changed(self, checked):
        self.search_box.setPlaceholderText("Search by tags..." if checked else "Search...")
        self._on_filter_changed()

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

    def _compute_filtered(self) -> list[Asset]:
        assets = list(self.project.assets)
        query = self.search_box.text().strip().lower()
        if query:
            if self.search_tags_check.isChecked():
                assets = [a for a in assets if any(query in t for t in a.tags)]
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
            # Filter out collapsed folders
            if self._collapsed_folders:
                assets = [a for a in assets
                          if (a.source_folder or Path(a.source_path).parent.as_posix())
                          not in self._collapsed_folders]
            return assets

        key_funcs = {
            "Name A-Z": (lambda a: Path(a.source_path).stem.lower(), False),
            "Name Z-A": (lambda a: Path(a.source_path).stem.lower(), True),
            "Newest": (lambda a: _mtime(a), True),
            "Oldest": (lambda a: _mtime(a), False),
            "Largest": (lambda a: _fsize(a), True),
            "Smallest": (lambda a: _fsize(a), False),
        }
        if sort_mode in key_funcs:
            fn, rev = key_funcs[sort_mode]
            assets.sort(key=fn, reverse=rev)
        return assets

    def _refresh_grid(self):
        saved_ids = set(self._selected_ids)
        self.project.invalidate_index()
        self._filtered_assets = self._compute_filtered()
        self._model.set_assets(self._filtered_assets)

        # Compute folder boundaries for delegate overlay painting
        folder_starts = {}
        if self.sort_combo.currentText() == "By Folder":
            prev = None
            for i, a in enumerate(self._filtered_assets):
                folder = a.source_folder or Path(a.source_path).parent.as_posix()
                if folder != prev:
                    folder_starts[i] = folder
                    prev = folder
        self._delegate._folder_starts = folder_starts

        # Restore selection (block signals to avoid N redundant emissions)
        if saved_ids:
            sel = self._list_view.selectionModel()
            sel.blockSignals(True)
            for i in range(self._model.rowCount()):
                idx = self._model.index(i)
                asset = self._model.get_asset(idx)
                if asset and asset.id in saved_ids:
                    sel.select(idx, sel.SelectionFlag.Select)
            sel.blockSignals(False)

        # Request thumbnails for visible items
        batch = [(a.id, a.source_path) for a in self._filtered_assets]
        self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)

        # Update counts
        total = len(self.project.assets)
        shown = len(self._filtered_assets)
        starred = sum(1 for a in self.project.assets if a.starred > 0)
        tagged = sum(1 for a in self.project.assets if a.tags)
        self.count_label.setText(f"{shown}/{total} shown, {starred} starred, {tagged} tagged")
        self.page_label.setText(f"{shown} images")

    # --- Thumb cache callbacks ---

    def _on_thumb_ready(self, asset_id: str, pixmap: QPixmap, w: int, h: int, gen_size: int):
        self._thumb_cache.on_ready(asset_id, pixmap, w, h, gen_size)
        self._model.update_pixmap(asset_id, pixmap)
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

    # --- Quick tag ---

    def _quick_tag(self, tag_id: str):
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Toggle: if already searching this tag, clear it
            if self.search_tags_check.isChecked() and self.search_box.text().strip() == tag_id:
                self.search_box.clear()
                self.search_tags_check.setChecked(False)
            else:
                self.search_tags_check.setChecked(True)
                self.search_box.setText(tag_id)
            return
        assets = self.get_selected_assets()
        if not assets:
            return
        toggle_tags(assets, tag_id)
        self.selection_changed.emit(list(self._selected_ids))
        # If this tag is eye-hidden, refresh to hide newly tagged images
        if tag_id in self._eye_hidden_tags:
            self._refresh_grid()

    # --- Public API ---

    def refresh(self):
        self._refresh_grid()

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

    def import_folder(self, folder: str, recursive: bool = None):
        if recursive is None:
            recursive = self.recursive_check.isChecked()
        folder_path = Path(folder)
        existing = {a.source_path for a in self.project.assets}
        count = 0
        files = sorted(folder_path.rglob("*") if recursive else folder_path.iterdir())
        for f in files:
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS and str(f) not in existing:
                self.project.assets.append(Asset(
                    id=f.stem + "_" + str(len(self.project.assets)),
                    source_path=str(f), source_folder=str(f.parent),
                    tags=auto_suggest_tags(f.stem) if self.auto_tag_enabled else []))
                count += 1
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
        added = 0
        for f in files:
            if f not in existing and Path(f).suffix.lower() in IMAGE_EXTS:
                p = Path(f)
                self.project.assets.append(Asset(
                    id=p.stem + "_" + str(len(self.project.assets)),
                    source_path=f, source_folder=str(p.parent),
                    tags=auto_suggest_tags(p.stem) if self.auto_tag_enabled else []))
                added += 1
        if added:
            self._refresh_grid()
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
        else:
            menu.addAction("Send to Tray", lambda: self.asset_to_tray.emit(asset_id))
        menu.addAction("Send to Canvas", lambda: self.asset_to_canvas.emit(asset_id))
        menu.addAction("Send to Censor", lambda: self.asset_to_censor.emit(asset_id))
        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: _open_explorer(asset))
        menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(asset.source_path))
        menu.addAction("Copy Filename", lambda: QApplication.clipboard().setText(Path(asset.source_path).name))
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
        menu.addAction("Remove from Project", lambda: self._remove_asset(asset))
        menu.exec(pos)

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

    def _show_hover(self):
        if not self._hover_id or not self.hover_preview_enabled:
            return
        asset = self.project.get_asset(self._hover_id)
        if asset:
            size = int(self._thumb_size * self._hover_size_pct / 100)
            HoverPreview.instance().PREVIEW_SIZE = max(300, size)
            HoverPreview.instance().show_for(asset.source_path, QCursor.pos())

    # --- Zoom (event filter intercepts Ctrl+Scroll on the list view) ---



    def eventFilter(self, obj, event):
        vp = self._list_view.viewport()
        if obj is self._list_view or obj is vp:
            # Ctrl+Scroll zoom
            if event.type() == event.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    current = self._list_view.currentIndex()
                    delta = event.angleDelta().y()
                    if delta > 0:
                        self._thumb_size = min(320, self._thumb_size + 20)
                    else:
                        self._thumb_size = max(80, self._thumb_size - 20)
                    QSettings("DoxyEdit", "DoxyEdit").setValue("thumb_size", self._thumb_size)
                    self._delegate.thumb_size = self._thumb_size
                    self._delegate.invalidate_cache()  # full clear on zoom change
                    self._list_view.setGridSize(QSize(self._thumb_size + 16, self._thumb_size + 70))
                    if current.isValid():
                        self._list_view.scrollTo(current, QListView.ScrollHint.PositionAtCenter)
                    return True

            # Star click — detect click in star area of a thumbnail
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = self._list_view.indexAt(pos)
                if index.isValid():
                    item_rect = self._list_view.visualRect(index)
                    ts = self._delegate.thumb_size
                    star_rect = QRect(item_rect.right() - 24, item_rect.y() + ts + 34, 22, 22)
                    if star_rect.contains(pos):
                        asset = self._model.get_asset(index)
                        if asset:
                            asset.cycle_star()
                            self._model.dataChanged.emit(index, index)
                        return True

            # Middle-click — instant preview regardless of hover setting
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.MiddleButton:
                    self._hover_timer.stop()
                    self._middle_held = True
                    pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                    index = self._list_view.indexAt(pos)
                    asset = self._model.get_asset(index) if index.isValid() else None
                    if asset:
                        hp = HoverPreview.instance()
                        hp.PREVIEW_SIZE = max(300, int(self._thumb_size * self._hover_size_pct / 100))
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
                index = self._list_view.indexAt(pos)
                asset = self._model.get_asset(index) if index.isValid() else None
                if asset and asset.id != self._hover_id:
                    self._hover_id = asset.id
                    hp = HoverPreview.instance()
                    hp.PREVIEW_SIZE = max(300, int(self._thumb_size * self._hover_size_pct / 100))
                    hp.show_for(asset.source_path, QCursor.pos())
                return True

            # Hover preview (skip if middle button held)
            if (event.type() == event.Type.MouseMove
                    and self.hover_preview_enabled
                    and not getattr(self, '_middle_held', False)):
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                index = self._list_view.indexAt(pos)
                asset = self._model.get_asset(index) if index.isValid() else None
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
