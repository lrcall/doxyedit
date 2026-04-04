"""Asset browser — paged thumbnail grid with lazy loading, multi-select, search, sort, drag-drop."""
import os
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QPushButton, QFileDialog, QFrame, QLineEdit, QComboBox,
    QMenu, QApplication, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer, QSettings
from PySide6.QtGui import QPixmap, QFont, QColor, QCursor

from doxyedit.models import Asset, Project, TAG_PRESETS, TAG_SIZED, TAG_ALL, TAG_SHORTCUTS, TagPreset, toggle_tags, next_tag_color, STAR_COLORS, VINIK_COLORS
from doxyedit.preview import HoverPreview, ImagePreviewDialog
from doxyedit.thumbcache import ThumbCache, THUMB_SIZE

from PySide6.QtWidgets import QLayout, QWidgetItem


class FlowLayout(QLayout):
    """Layout that wraps widgets into multiple rows like text word-wrap."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing

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

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        from PySide6.QtCore import QSize
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
        from PySide6.QtCore import QRect as QR
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
                item.setGeometry(QR(x, y, w, h))
            x += w + self._spacing
            row_height = max(row_height, h)

        return y + row_height - rect.y() + m.bottom()


from PySide6.QtCore import QRect


class FlowWidget(QWidget):
    """A QWidget that properly respects FlowLayout's heightForWidth."""

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if self.layout():
            return self.layout().heightForWidth(width)
        return super().heightForWidth(width)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        if self.layout():
            w = self.width() if self.width() > 0 else 400
            h = self.layout().heightForWidth(w)
            return QSize(w, max(h, 30))
        return super().sizeHint()

    def minimumHeight(self):
        if self.layout():
            w = self.width() if self.width() > 0 else 400
            return self.layout().heightForWidth(w)
        return 30

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Force recalc when width changes — triggers parent layout update
        self.updateGeometry()


IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".svg", ".tiff", ".tif",
    ".psd", ".psb",          # Photoshop
    ".sai", ".sai2",         # PaintTool SAI
    ".clip", ".csp",         # Clip Studio Paint
    ".kra",                  # Krita
    ".xcf",                  # GIMP
    ".ora",                  # OpenRaster
    ".ico", ".cur",          # Icons
    ".dds",                  # DirectDraw
    ".tga",                  # Targa
    ".exr", ".hdr",          # HDR formats
}
PAGE_SIZE = 100  # thumbnails per page
THUMB_GEN_SIZE = 512  # generate at high res so they're sharp at any zoom level

# Filename patterns → auto-suggest tags on import
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
# Thumbnail widget — now receives pixmap from cache, not loading itself
# ---------------------------------------------------------------------------

class ThumbnailWidget(QFrame):
    clicked = Signal(str)
    double_clicked = Signal(str)
    star_toggled = Signal(str)
    context_menu_requested = Signal(str, object)

    def __init__(self, asset: Asset, pixmap: QPixmap = None, dims: tuple = None,
                 thumb_size: int = THUMB_SIZE, browser=None, parent=None):
        super().__init__(parent)
        self.asset = asset
        self._dims = dims
        self._browser = browser  # reference to check hover_preview_enabled
        self._thumb_size = thumb_size
        self.selected = False
        self.setFixedSize(thumb_size + 16, thumb_size + 56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(400)
        self._hover_timer.timeout.connect(self._show_hover_preview)
        self._build(pixmap)
        self._update_style()

    def _build(self, pixmap: QPixmap = None):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Thumbnail image
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self._thumb_size, self._thumb_size)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background: rgba(128,128,128,0.1); border-radius: 4px;")
        if pixmap and not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)
        else:
            self.thumb_label.setText("...")
            self.thumb_label.setStyleSheet(
                "background: rgba(128,128,128,0.1); border-radius: 4px; color: rgba(128,128,128,0.4); font-size: 18px;"
            )
        layout.addWidget(self.thumb_label)

        # Tag dots — larger with subtle drop shadow
        tag_row = QHBoxLayout()
        tag_row.setContentsMargins(2, 1, 2, 1)
        tag_row.setSpacing(3)
        for tag_id in self.asset.tags[:10]:
            preset = TAG_ALL.get(tag_id)
            if preset:
                dot = QLabel()
                dot.setFixedSize(12, 12)
                dot.setStyleSheet(
                    f"background: {preset.color}; border-radius: 6px;"
                    f" border: 1px solid rgba(0,0,0,0.3);")
                dot.setToolTip(preset.label)
                tag_row.addWidget(dot)
        tag_row.addStretch()
        layout.addLayout(tag_row)

        # Dimensions
        dim_text = f"{self._dims[0]}x{self._dims[1]}" if self._dims else ""
        dim_label = QLabel(dim_text)
        dim_label.setFont(QFont("Segoe UI", 7))
        dim_label.setStyleSheet("color: rgba(128,128,128,0.6); margin-top: 8px;")
        dim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dim_label)

        # Name + star
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        p = Path(self.asset.source_path)
        name_label = QLabel(f"{p.stem[:16]}{p.suffix}")
        name_label.setFont(QFont("Segoe UI", 8))
        name_label.setStyleSheet("color: rgba(160,160,160,0.9);")
        name_label.setToolTip(self.asset.source_path)
        bottom.addWidget(name_label, 1)

        self.star_btn = QPushButton("\u2605" if self.asset.starred else "\u2606")
        self.star_btn.setObjectName("star_btn")
        self.star_btn.setFixedSize(24, 24)
        self.star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_star_style()
        self.star_btn.clicked.connect(self._toggle_star)
        bottom.addWidget(self.star_btn)
        layout.addLayout(bottom)

    def set_pixmap(self, pixmap: QPixmap):
        """Update thumbnail after async load."""
        if pixmap and not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setStyleSheet("background: rgba(128,128,128,0.1); border-radius: 4px;")

    def _toggle_star(self):
        # Cycle: 0 → 1 → 2 → 3 → 4 → 5 → 0
        self.asset.cycle_star()
        self.star_btn.setText("\u2605" if self.asset.starred else "\u2606")
        self._update_star_style()
        self.star_toggled.emit(self.asset.id)

    def _update_star_style(self):
        s = self.asset.starred
        if s and s in STAR_COLORS:
            color = STAR_COLORS[s]
            self.star_btn.setStyleSheet(
                f"#star_btn {{ background: transparent; color: {color}; border: none; font-size: 18px; padding: 0; }}")
        else:
            self.star_btn.setStyleSheet(
                "#star_btn { background: transparent; color: rgba(150,150,150,0.6); border: none; font-size: 18px; padding: 0; }"
                "#star_btn:hover { color: rgba(220,220,220,0.9); }")

    def set_selected(self, sel: bool):
        self.selected = sel
        self._update_style()

    def _update_style(self):
        if self.selected:
            self.setStyleSheet(
                "ThumbnailWidget { background: rgba(100,150,200,0.3); border: 2px solid rgba(100,150,200,0.7); border-radius: 6px; }")
        else:
            self.setStyleSheet(
                "ThumbnailWidget { background: rgba(128,128,128,0.08); border: 2px solid transparent; border-radius: 6px; }"
                "ThumbnailWidget:hover { border-color: rgba(128,128,128,0.3); }")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.asset.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            HoverPreview.instance().hide_preview()
            self.double_clicked.emit(self.asset.id)

    def contextMenuEvent(self, event):
        self.context_menu_requested.emit(self.asset.id, event.globalPos())

    def enterEvent(self, event):
        if self._browser and self._browser.hover_preview_enabled:
            self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_timer.stop()
        HoverPreview.instance().hide_preview()
        super().leaveEvent(event)

    def _show_hover_preview(self):
        if self._browser and not self._browser.hover_preview_enabled:
            return
        HoverPreview.instance().show_for(self.asset.source_path, QCursor.pos())


# ---------------------------------------------------------------------------
# Asset browser — paged, lazy-loaded, with shift-click and ctrl-click
# ---------------------------------------------------------------------------

class AssetBrowser(QWidget):
    asset_selected = Signal(str)
    asset_preview = Signal(str)
    asset_to_canvas = Signal(str)
    asset_to_censor = Signal(str)
    folder_opened = Signal(str)      # emitted when a folder is imported
    selection_changed = Signal(list)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_browser")
        self.project = project
        self._selected_ids: set[str] = set()
        self._thumbnails: dict[str, ThumbnailWidget] = {}
        self._thumb_cache = ThumbCache()
        self._thumb_cache.connect_ready(self._on_thumb_ready)
        self._thumb_cache.connect_visual_tags(self._on_visual_tags)
        self._current_page = 0
        self._filtered_assets: list[Asset] = []
        self._last_clicked_id: str | None = None
        settings = QSettings("DoxyEdit", "DoxyEdit")
        self._thumb_size = int(settings.value("thumb_size", THUMB_SIZE))
        self.hover_preview_enabled = True
        self._current_font_size = 10
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._rebuild_page)
        self.setAcceptDrops(True)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Row 1: import + filters
        toolbar = QHBoxLayout()
        for label, handler in [("+ Folder", self.open_folder_dialog), ("+ Files", self.add_images_dialog)]:
            btn = QPushButton(label)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)

        toolbar.addSpacing(8)

        self.filter_starred = self._make_filter_btn("Starred")
        self.filter_untagged = self._make_filter_btn("Untagged")
        self.filter_tagged = self._make_filter_btn("Tagged")
        toolbar.addWidget(self.filter_starred)
        toolbar.addWidget(self.filter_untagged)
        toolbar.addWidget(self.filter_tagged)
        toolbar.addSpacing(8)

        # Hover preview toggle
        from PySide6.QtWidgets import QCheckBox
        self.filter_show_ignored = QPushButton("Show Ignored")
        self.filter_show_ignored.setCheckable(True)
        self.filter_show_ignored.setChecked(False)
        self.filter_show_ignored.setStyleSheet(self._btn_style())
        self.filter_show_ignored.toggled.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_show_ignored)

        toolbar.addSpacing(8)

        self.recursive_check = QCheckBox("Recursive")
        self.recursive_check.setChecked(False)
        self.recursive_check.setToolTip("Import subfolders when opening a folder")
        toolbar.addWidget(self.recursive_check)

        self.hover_check = QCheckBox("Hover Preview")
        self.hover_check.setChecked(True)
        self.hover_check.toggled.connect(lambda v: setattr(self, 'hover_preview_enabled', v))
        toolbar.addWidget(self.hover_check)

        toolbar.addStretch()

        self.count_label = QLabel("0 assets")
        toolbar.addWidget(self.count_label)
        root.addLayout(toolbar)

        # Row 2: search + sort
        row2 = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_filter_changed)
        row2.addWidget(self.search_box, 1)

        self.search_tags_check = QCheckBox("Tags")
        self.search_tags_check.setChecked(False)
        self.search_tags_check.setToolTip("Search by tag names instead of filenames")
        self.search_tags_check.toggled.connect(self._on_search_mode_changed)
        row2.addWidget(self.search_tags_check)

        sort_label = QLabel("Sort:")
        row2.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name A-Z", "Name Z-A", "Newest", "Oldest", "Largest", "Smallest"])
        # Inherits from theme stylesheet
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        row2.addWidget(self.sort_combo)
        root.addLayout(row2)

        # Row 3: Quick-tag bar — wrapping flow layout so tags don't force width
        self._tag_bar_frame = FlowWidget()
        self._tag_bar_frame.setStyleSheet(
            "border-bottom: 1px solid rgba(128,128,128,0.15);")
        self._tag_bar_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._tag_flow = FlowLayout(self._tag_bar_frame, spacing=4)
        self._tag_flow.setContentsMargins(0, 2, 0, 2)

        self._tag_buttons: list[tuple[QPushButton, str]] = []
        self._rebuild_tag_buttons()

        # "+" button to add custom tags
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setToolTip("Add a custom tag")
        self._add_tag_btn.clicked.connect(self._add_custom_tag)
        self._tag_flow.addWidget(self._add_tag_btn)
        self._apply_tag_button_styles()
        root.addWidget(self._tag_bar_frame)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setObjectName("doxyedit_grid_scroll")
        self._scroll.setWidgetResizable(True)

        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("doxyedit_grid")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self.grid_widget)
        root.addWidget(self._scroll)

        # Pager row
        pager = QHBoxLayout()
        pager.addStretch()
        self.btn_prev = QPushButton("< Prev")
        self.btn_prev.setStyleSheet(self._btn_style())
        self.btn_prev.clicked.connect(self._prev_page)
        pager.addWidget(self.btn_prev)

        self.page_label = QLabel("Page 1 / 1")
        self.page_label.setStyleSheet("padding: 0 12px;")
        pager.addWidget(self.page_label)

        self.btn_next = QPushButton("Next >")
        self.btn_next.setStyleSheet(self._btn_style())
        self.btn_next.clicked.connect(self._next_page)
        pager.addWidget(self.btn_next)
        pager.addStretch()
        root.addLayout(pager)

    def _btn_style(self):
        # These inherit most colors from the theme's QPushButton style
        # Just add sizing overrides
        return "QPushButton { padding: 6px 12px; font-size: 11px; }"

    def _make_filter_btn(self, label):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setStyleSheet(self._btn_style())
        btn.toggled.connect(self._on_filter_changed)
        return btn

    # --- Filtering / sorting ---

    def _rebuild_tag_buttons(self):
        """Build tag pill buttons from current TAG_PRESETS + project custom tags."""
        # Remove all items — setParent(None) for immediate cleanup
        while self._tag_flow.count():
            item = self._tag_flow.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
        self._tag_buttons.clear()

        # Content/workflow tags only (no platform/sized tags in the bar)
        bar_tags = dict(TAG_PRESETS)
        # Add project custom tags
        if hasattr(self.project, 'get_tags'):
            for tid, preset in self.project.get_tags().items():
                if tid not in TAG_SIZED:
                    bar_tags[tid] = preset
        # Add discovered tags from assets (mood, dimension, etc.)
        color_idx = 0
        for asset in self.project.assets:
            for t in asset.tags:
                if t not in bar_tags and t not in TAG_SIZED:
                    bar_tags[t] = TagPreset(id=t, label=t,
                        color=VINIK_COLORS[color_idx % len(VINIK_COLORS)])
                    color_idx += 1

        shortcut_reverse = {v: k for k, v in TAG_SHORTCUTS.items()}
        for tag_id, preset in bar_tags.items():
            key = shortcut_reverse.get(tag_id, "")
            label = f"{preset.label}" + (f" [{key}]" if key else "")
            btn = QPushButton(label)
            btn.setToolTip(f"{preset.label} — press [{key}] or click" if key else f"{preset.label} — click to toggle")
            btn.clicked.connect(lambda checked, tid=tag_id: self._quick_tag(tid))
            self._tag_buttons.append((btn, preset.color))
            self._tag_flow.addWidget(btn)

    def _add_custom_tag(self):
        """Show a simple dialog to add a new tag."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        parent = self.window()  # use top-level window as parent
        name, ok = QInputDialog.getText(parent, "New Tag", "Enter tag name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        tag_id = name.lower().replace(" ", "_").replace("/", "_")

        try:
            all_tags = self.project.get_tags()
        except Exception:
            all_tags = dict(TAG_ALL)

        if tag_id in all_tags:
            QMessageBox.information(parent, "Tag Exists",
                f"A tag called '{all_tags[tag_id].label}' already exists.")
            return

        color = next_tag_color(all_tags)
        self.project.custom_tags.append({
            "id": tag_id, "label": name, "color": color,
        })

        self._rebuild_tag_bar()

    def _rebuild_tag_bar(self):
        """Rebuild the entire tag bar including the + button."""
        self._rebuild_tag_buttons()
        self._add_tag_btn = QPushButton("+")
        self._add_tag_btn.setToolTip("Add a custom tag")
        self._add_tag_btn.clicked.connect(self._add_custom_tag)
        self._tag_flow.addWidget(self._add_tag_btn)
        self._apply_tag_button_styles()
        self._tag_flow.invalidate()
        self._tag_bar_frame.updateGeometry()

    def _apply_tag_button_styles(self, font_size: int = None):
        """Apply tag pill styles at the given font size."""
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
        # Style the "+" button
        self._add_tag_btn.setFixedHeight(h)
        self._add_tag_btn.setFixedWidth(h)
        self._add_tag_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: rgba(128,128,128,0.6);"
            f" border: 1px dashed rgba(128,128,128,0.6); border-radius: {h // 2}px;"
            f" font-size: {font_size + 2}px; font-weight: bold; }}"
            f"QPushButton:hover {{ color: rgba(200,200,200,0.9); border-color: rgba(200,200,200,0.9); }}")

    def update_font_size(self, font_size: int):
        """Called by the main window when font size changes."""
        self._apply_tag_button_styles(font_size)

    def _on_filter_changed(self, *_):
        self._current_page = 0
        self._refresh_grid()

    def _on_search_mode_changed(self, checked):
        self.search_box.setPlaceholderText("Search by tags..." if checked else "Search...")
        self._on_filter_changed()

    def _compute_filtered(self) -> list[Asset]:
        assets = list(self.project.assets)
        query = self.search_box.text().strip().lower()
        if query:
            if self.search_tags_check.isChecked():
                assets = [a for a in assets if any(query in t for t in a.tags)]
            elif "*" in query or "?" in query:
                # Glob pattern match (e.g. *.png, hero_*)
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

        # Hide ignored/skip unless "Show Ignored" is toggled on
        if not self.filter_show_ignored.isChecked():
            assets = [a for a in assets if "ignore" not in a.tags]

        sort_mode = self.sort_combo.currentText()
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

    # --- Paging ---

    @property
    def _total_pages(self):
        return max(1, (len(self._filtered_assets) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._rebuild_page()
            self._scroll.verticalScrollBar().setValue(0)

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._rebuild_page()
            self._scroll.verticalScrollBar().setValue(0)

    # --- Grid ---

    def _refresh_grid(self):
        """Recompute filtered list and rebuild current page."""
        self._filtered_assets = self._compute_filtered()
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)
        self._rebuild_page()

    def _rebuild_page(self):
        """Build only the current page of thumbnails."""
        # Save scroll position
        scroll_pos = self._scroll.verticalScrollBar().value()

        # Clear existing
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._thumbnails.clear()

        start = self._current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(self._filtered_assets))
        page_assets = self._filtered_assets[start:end]

        ts = self._thumb_size
        cols = max(1, self.width() // (ts + 24)) if self.width() > 0 else 4

        # Always generate at max resolution, downscale for display
        batch = [(a.id, a.source_path) for a in page_assets]
        self._thumb_cache.request_batch(batch, size=THUMB_GEN_SIZE)

        for i, asset in enumerate(page_assets):
            pm = self._thumb_cache.get(asset.id)
            dims = self._thumb_cache.get_dims(asset.id)
            # Scale cached pixmap to current thumb size if needed
            if pm and not pm.isNull() and (pm.width() != ts or pm.height() != ts):
                pm = pm.scaled(ts, ts,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            thumb = ThumbnailWidget(asset, pm, dims, ts, browser=self)
            thumb.clicked.connect(self._on_thumb_clicked)
            thumb.double_clicked.connect(lambda aid: self.asset_preview.emit(aid))
            thumb.star_toggled.connect(lambda _: self._refresh_grid())
            thumb.context_menu_requested.connect(self._on_context_menu)
            if asset.id in self._selected_ids:
                thumb.set_selected(True)
            self.grid_layout.addWidget(thumb, i // cols, i % cols)
            self._thumbnails[asset.id] = thumb

        # Update counts
        total = len(self.project.assets)
        shown = len(self._filtered_assets)
        starred = sum(1 for a in self.project.assets if a.starred > 0)
        tagged = sum(1 for a in self.project.assets if a.tags)
        self.count_label.setText(f"{shown}/{total} shown, {starred} starred, {tagged} tagged")

        # Update pager
        tp = self._total_pages
        self.page_label.setText(f"Page {self._current_page + 1} / {tp}  ({start+1}-{end} of {shown})")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < tp - 1)

        # Restore scroll position
        self._scroll.verticalScrollBar().setValue(scroll_pos)

    def _on_thumb_ready(self, asset_id: str, pixmap: QPixmap, w: int, h: int, gen_size: int):
        """Callback from ThumbCache worker — update cache and widget if visible."""
        self._thumb_cache.on_ready(asset_id, pixmap, w, h, gen_size)
        if asset_id in self._thumbnails:
            self._thumbnails[asset_id].set_pixmap(pixmap)

    def _on_visual_tags(self, asset_id: str, vtags: list):
        """Auto-apply visual property tags from background analysis."""
        asset = self.project.get_asset(asset_id)
        if asset:
            for t in vtags:
                if t not in asset.tags:
                    asset.tags.append(t)

    # --- Selection: click, ctrl-click, shift-click ---

    def _on_thumb_clicked(self, asset_id: str):
        modifiers = QApplication.keyboardModifiers()

        if modifiers & Qt.KeyboardModifier.AltModifier:
            # Alt+click → send to censor tab
            self.asset_to_censor.emit(asset_id)
            return
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+click: toggle in multi-select (standard Windows)
            if asset_id in self._selected_ids:
                self._selected_ids.remove(asset_id)
                if asset_id in self._thumbnails:
                    self._thumbnails[asset_id].set_selected(False)
            else:
                self._selected_ids.add(asset_id)
                if asset_id in self._thumbnails:
                    self._thumbnails[asset_id].set_selected(True)
            self._last_clicked_id = asset_id
            self.selection_changed.emit(list(self._selected_ids))
            if len(self._selected_ids) == 1:
                self.asset_selected.emit(next(iter(self._selected_ids)))
            return
        elif modifiers & Qt.KeyboardModifier.ShiftModifier and self._last_clicked_id:
            # Shift-click: select range
            self._select_range(self._last_clicked_id, asset_id)
        else:
            # Plain click: select one
            for sid in self._selected_ids:
                if sid in self._thumbnails:
                    self._thumbnails[sid].set_selected(False)
            self._selected_ids = {asset_id}
            if asset_id in self._thumbnails:
                self._thumbnails[asset_id].set_selected(True)

        self._last_clicked_id = asset_id
        self.selection_changed.emit(list(self._selected_ids))
        if len(self._selected_ids) == 1:
            self.asset_selected.emit(next(iter(self._selected_ids)))

    def _select_range(self, from_id: str, to_id: str):
        """Select all assets in the filtered list between from_id and to_id (inclusive)."""
        ids = [a.id for a in self._filtered_assets]
        try:
            i1 = ids.index(from_id)
            i2 = ids.index(to_id)
        except ValueError:
            return
        lo, hi = min(i1, i2), max(i1, i2)
        range_ids = set(ids[lo:hi + 1])

        for sid in self._selected_ids:
            if sid in self._thumbnails:
                self._thumbnails[sid].set_selected(False)

        self._selected_ids = range_ids

        for sid in self._selected_ids:
            if sid in self._thumbnails:
                self._thumbnails[sid].set_selected(True)

    def _quick_tag(self, tag_id: str):
        """Toggle a tag on selected assets. Alt+click searches by that tag instead."""
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.AltModifier:
            # Alt+click → search by this tag
            self.search_tags_check.setChecked(True)
            self.search_box.setText(tag_id)
            return
        assets = self.get_selected_assets()
        if not assets:
            return
        toggle_tags(assets, tag_id)
        self.selection_changed.emit(list(self._selected_ids))
        self._rebuild_page()

    def get_selected_assets(self) -> list:
        return [a for a in self.project.assets if a.id in self._selected_ids]

    def refresh(self):
        """Public method — recompute filters and rebuild the current page."""
        self._refresh_grid()

    def shutdown(self):
        """Clean up background threads."""
        self._thumb_cache.shutdown()

    # --- Import ---

    def open_folder_dialog(self):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        last_dir = settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Open Image Folder", last_dir)
        if folder:
            settings.setValue("last_folder", folder)
            self.import_folder(folder)
            self.folder_opened.emit(folder)

    def import_folder(self, folder: str, recursive: bool = None):
        if recursive is None:
            recursive = self.recursive_check.isChecked()
        folder_path = Path(folder)
        existing = {a.source_path for a in self.project.assets}
        count = 0
        if recursive:
            files = sorted(folder_path.rglob("*"))
        else:
            files = sorted(folder_path.iterdir())
        for f in files:
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS and str(f) not in existing:
                self.project.assets.append(Asset(
                    id=f.stem + "_" + str(len(self.project.assets)),
                    source_path=str(f),
                    source_folder=str(f.parent),
                    tags=auto_suggest_tags(f.stem),
                ))
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
                    source_path=f,
                    source_folder=str(p.parent),
                    tags=auto_suggest_tags(p.stem),
                ))
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

    def _on_context_menu(self, asset_id: str, pos):
        asset = self.project.get_asset(asset_id)
        if not asset:
            return

        menu = QMenu(self)

        menu.addAction("Preview", lambda: self.asset_preview.emit(asset_id))
        menu.addAction("Send to Canvas", lambda: self.asset_to_canvas.emit(asset_id))
        menu.addAction("Send to Censor", lambda: self.asset_to_censor.emit(asset_id))
        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: _open_explorer(asset))
        menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(asset.source_path))
        menu.addSeparator()

        menu.addAction("Unstar" if asset.starred > 0 else "Star",
                        lambda: self._toggle_star(asset))

        tag_menu = menu.addMenu("Quick Tag")

        # Content tags
        for tag_id, preset in TAG_PRESETS.items():
            checked = tag_id in asset.tags
            label = f"[x] {preset.label}" if checked else f"[ ] {preset.label}"
            tag_menu.addAction(label, lambda tid=tag_id: self._toggle_tag(asset, tid))

        tag_menu.addSeparator()

        # Platform/sized tags
        for tag_id, preset in TAG_SIZED.items():
            checked = tag_id in asset.tags
            label = f"[x] {preset.label}" if checked else f"[ ] {preset.label}"
            tag_menu.addAction(label, lambda tid=tag_id: self._toggle_tag(asset, tid))

        # Discovered + custom tags
        extra_tags = set(asset.tags) - set(TAG_PRESETS) - set(TAG_SIZED)
        if extra_tags:
            tag_menu.addSeparator()
            for t in sorted(extra_tags):
                tag_menu.addAction(f"[x] {t}", lambda tid=t: self._toggle_tag(asset, tid))

        menu.addSeparator()
        n = len(self._selected_ids)
        if n > 1:
            menu.addAction(f"Star All ({n})", self._star_all_selected)
            menu.addAction(f"Unstar All ({n})", self._unstar_all_selected)
            menu.addSeparator()

        menu.addAction("Remove from Project", lambda: self._remove_asset(asset))
        menu.exec(pos)

    def _toggle_star(self, asset):
        asset.cycle_star()
        self._refresh_grid()

    def _toggle_tag(self, asset, tag_id):
        toggle_tags([asset], tag_id)
        self._refresh_grid()
        self.selection_changed.emit(list(self._selected_ids))

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

    # --- Ctrl+Scroll zoom thumbnails ---

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._thumb_size = min(320, self._thumb_size + 20)
            else:
                self._thumb_size = max(80, self._thumb_size - 20)
            QSettings("DoxyEdit", "DoxyEdit").setValue("thumb_size", self._thumb_size)
            self._rebuild_page()
            event.accept()
            return
        super().wheelEvent(event)

    # --- Resize (debounced) ---

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()


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
