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

from doxyedit.models import Asset, Project, TAG_PRESETS, toggle_tags
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
        if self.layout():
            # Return hint based on current width
            w = self.width() if self.width() > 0 else 400
            h = self.layout().heightForWidth(w)
            from PySide6.QtCore import QSize
            return QSize(w, h)
        return super().sizeHint()


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
PAGE_SIZE = 60  # thumbnails per page

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
        self.thumb_label.setStyleSheet("background: rgba(255,255,255,0.05); border-radius: 4px;")
        if pixmap and not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)
        else:
            self.thumb_label.setText("...")
            self.thumb_label.setStyleSheet(
                "background: rgba(255,255,255,0.05); border-radius: 4px; color: rgba(255,255,255,0.2); font-size: 18px;"
            )
        layout.addWidget(self.thumb_label)

        # Tag dots
        tag_row = QHBoxLayout()
        tag_row.setContentsMargins(2, 0, 2, 0)
        tag_row.setSpacing(2)
        for tag_id in self.asset.tags[:8]:
            preset = TAG_PRESETS.get(tag_id)
            if preset:
                dot = QLabel()
                dot.setFixedSize(8, 8)
                dot.setStyleSheet(f"background: {preset.color}; border-radius: 4px;")
                dot.setToolTip(preset.label)
                tag_row.addWidget(dot)
        tag_row.addStretch()
        layout.addLayout(tag_row)

        # Dimensions + tag count
        dim_parts = []
        if self._dims:
            dim_parts.append(f"{self._dims[0]}x{self._dims[1]}")
        if self.asset.tags:
            dim_parts.append(f"[{len(self.asset.tags)}]")
        dim_label = QLabel(" ".join(dim_parts))
        dim_label.setFont(QFont("Segoe UI", 7))
        dim_label.setStyleSheet("color: #666;")
        dim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dim_label)

        # Name + star
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        name = Path(self.asset.source_path).stem
        name_label = QLabel(name[:18])
        name_label.setFont(QFont("Segoe UI", 8))
        name_label.setStyleSheet("color: #aaa;")
        name_label.setToolTip(self.asset.source_path)
        bottom.addWidget(name_label, 1)

        self.star_btn = QPushButton("*" if self.asset.starred else ".")
        self.star_btn.setFixedSize(20, 20)
        self.star_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_star_style()
        self.star_btn.clicked.connect(self._toggle_star)
        bottom.addWidget(self.star_btn)
        layout.addLayout(bottom)

    def set_pixmap(self, pixmap: QPixmap):
        """Update thumbnail after async load."""
        if pixmap and not pixmap.isNull():
            self.thumb_label.setPixmap(pixmap)
            self.thumb_label.setStyleSheet("background: #2d2d2d; border-radius: 4px;")

    def _toggle_star(self):
        self.asset.starred = not self.asset.starred
        self.star_btn.setText("*" if self.asset.starred else ".")
        self._update_star_style()
        self.star_toggled.emit(self.asset.id)

    def _update_star_style(self):
        if self.asset.starred:
            self.star_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #ffd700; border: none; font-size: 14px; }")
        else:
            self.star_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #555; border: none; font-size: 14px; }"
                "QPushButton:hover { color: #ffd700; }")

    def set_selected(self, sel: bool):
        self.selected = sel
        self._update_style()

    def _update_style(self):
        if self.selected:
            self.setStyleSheet(
                "ThumbnailWidget { background: #094771; border: 2px solid #0078d4; border-radius: 6px; }")
        else:
            self.setStyleSheet(
                "ThumbnailWidget { background: #252526; border: 2px solid transparent; border-radius: 6px; }"
                "ThumbnailWidget:hover { border-color: #444; }")

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
    asset_to_canvas = Signal(str)    # Ctrl+click → send to canvas
    asset_to_censor = Signal(str)    # Alt+click → send to censor
    selection_changed = Signal(list)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self._selected_ids: set[str] = set()
        self._thumbnails: dict[str, ThumbnailWidget] = {}
        self._thumb_cache = ThumbCache()
        self._thumb_cache.connect_ready(self._on_thumb_ready)
        self._current_page = 0
        self._filtered_assets: list[Asset] = []
        self._last_clicked_id: str | None = None
        self._thumb_size = THUMB_SIZE  # dynamic — Ctrl+scroll changes this
        self.hover_preview_enabled = True
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
        for label, handler in [("+ Folder", self._open_folder), ("+ Files", self._add_images)]:
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
        self.search_box.setPlaceholderText("Search by filename...")
        self.search_box.setClearButtonEnabled(True)
        # Inherits from theme stylesheet
        self.search_box.textChanged.connect(self._on_filter_changed)
        row2.addWidget(self.search_box, 1)

        sort_label = QLabel("Sort:")
        row2.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name A-Z", "Name Z-A", "Newest", "Oldest", "Largest", "Smallest"])
        # Inherits from theme stylesheet
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        row2.addWidget(self.sort_combo)
        root.addLayout(row2)

        # Row 3: Quick-tag bar — wrapping flow layout so tags don't force width
        from doxyedit.models import TAG_SHORTCUTS
        self._tag_bar_frame = FlowWidget()
        self._tag_bar_frame.setStyleSheet(
            "FlowWidget { border-bottom: 1px solid rgba(255,255,255,0.08); }")
        self._tag_bar_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._tag_flow = FlowLayout(self._tag_bar_frame, spacing=4)
        self._tag_flow.setContentsMargins(0, 2, 0, 2)

        self._tag_buttons: list[tuple[QPushButton, str]] = []
        shortcut_reverse = {v: k for k, v in TAG_SHORTCUTS.items()}
        for tag_id, preset in TAG_PRESETS.items():
            key = shortcut_reverse.get(tag_id, "")
            label = f"{preset.label}" + (f" [{key}]" if key else "")
            btn = QPushButton(label)
            btn.setToolTip(f"{preset.label} — press [{key}] or click to toggle")
            btn.clicked.connect(lambda checked, tid=tag_id: self._quick_tag(tid))
            self._tag_buttons.append((btn, preset.color))
            self._tag_flow.addWidget(btn)
        self._apply_tag_button_styles()
        root.addWidget(self._tag_bar_frame)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # Inherits from theme

        self.grid_widget = QWidget()
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
        self.page_label.setStyleSheet("color: #888; font-size: 11px; padding: 0 12px;")
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

    def _apply_tag_button_styles(self, font_size: int = 10):
        """Apply tag pill styles at the given font size."""
        for btn, color in self._tag_buttons:
            h = font_size + 14
            btn.setFixedHeight(h)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color};"
                f" border: 1px solid {color}; border-radius: {h // 2}px;"
                f" padding: 2px 8px; font-size: {font_size}px; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {color}; color: #000; }}")

    def update_font_size(self, font_size: int):
        """Called by the main window when font size changes."""
        self._apply_tag_button_styles(font_size)

    def _on_filter_changed(self, *_):
        self._current_page = 0
        self._refresh_grid()

    def _compute_filtered(self) -> list[Asset]:
        assets = list(self.project.assets)
        query = self.search_box.text().strip().lower()
        if query:
            assets = [a for a in assets if query in Path(a.source_path).stem.lower()]
        if self.filter_starred.isChecked():
            assets = [a for a in assets if a.starred]
        if self.filter_untagged.isChecked():
            assets = [a for a in assets if not a.tags]
        if self.filter_tagged.isChecked():
            assets = [a for a in assets if a.tags]

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

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._rebuild_page()

    # --- Grid ---

    def _refresh_grid(self):
        """Recompute filtered list and rebuild current page."""
        self._filtered_assets = self._compute_filtered()
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)
        self._rebuild_page()

    def _rebuild_page(self):
        """Build only the current page of thumbnails."""
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

        # Request thumbnails at current zoom size
        batch = [(a.id, a.source_path) for a in page_assets]
        self._thumb_cache.request_batch(batch, size=ts)

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
        starred = sum(1 for a in self.project.assets if a.starred)
        tagged = sum(1 for a in self.project.assets if a.tags)
        self.count_label.setText(f"{shown}/{total} shown, {starred} starred, {tagged} tagged")

        # Update pager
        tp = self._total_pages
        self.page_label.setText(f"Page {self._current_page + 1} / {tp}  ({start+1}-{end} of {shown})")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < tp - 1)

        # Scroll to top
        self._scroll.verticalScrollBar().setValue(0)

    def _on_thumb_ready(self, asset_id: str, pixmap: QPixmap, w: int, h: int, gen_size: int):
        """Callback from ThumbCache worker — update cache and widget if visible."""
        self._thumb_cache.on_ready(asset_id, pixmap, w, h, gen_size)
        if asset_id in self._thumbnails:
            self._thumbnails[asset_id].set_pixmap(pixmap)

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
        """Toggle a tag on all selected assets via the quick-tag bar."""
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

    def _open_folder(self):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        last_dir = settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(self, "Open Image Folder", last_dir)
        if folder:
            settings.setValue("last_folder", folder)
            self._import_folder(folder)

    def _import_folder(self, folder: str):
        folder_path = Path(folder)
        existing = {a.source_path for a in self.project.assets}
        count = 0
        for f in sorted(folder_path.iterdir()):
            if f.suffix.lower() in IMAGE_EXTS and str(f) not in existing:
                self.project.assets.append(Asset(
                    id=f.stem + "_" + str(len(self.project.assets)),
                    source_path=str(f),
                    source_folder=str(folder_path),
                    tags=auto_suggest_tags(f.stem),
                ))
                count += 1
        if count:
            self._refresh_grid()
        return count

    def _add_images(self):
        settings = QSettings("DoxyEdit", "DoxyEdit")
        last_dir = settings.value("last_folder", "")
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Images", last_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg *.psd);;All Files (*)")
        self._import_files(files)

    def _import_files(self, files: list[str]):
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
            self._import_folder(folder)
        if files:
            self._import_files(files)

    # --- Context menu ---

    def _on_context_menu(self, asset_id: str, pos):
        asset = self.project.get_asset(asset_id)
        if not asset:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #252526; color: #ccc; border: 1px solid #444; }"
            "QMenu::item:selected { background: #094771; }"
            "QMenu::separator { background: #444; height: 1px; }")

        menu.addAction("Preview", lambda: self.asset_preview.emit(asset_id))
        menu.addAction("Send to Canvas", lambda: self.asset_to_canvas.emit(asset_id))
        menu.addAction("Send to Censor", lambda: self.asset_to_censor.emit(asset_id))
        menu.addSeparator()
        menu.addAction("Open in Explorer", lambda: _open_explorer(asset))
        menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(asset.source_path))
        menu.addSeparator()

        menu.addAction("Unstar" if asset.starred else "Star",
                        lambda: self._toggle_star(asset))

        tag_menu = menu.addMenu("Quick Tag")
        for tag_id, preset in TAG_PRESETS.items():
            checked = tag_id in asset.tags
            label = f"[x] {preset.label}" if checked else f"[ ] {preset.label}"
            tag_menu.addAction(label, lambda tid=tag_id: self._toggle_tag(asset, tid))

        menu.addSeparator()
        n = len(self._selected_ids)
        if n > 1:
            menu.addAction(f"Star All ({n})", self._star_all_selected)
            menu.addAction(f"Unstar All ({n})", self._unstar_all_selected)
            menu.addSeparator()

        menu.addAction("Remove from Project", lambda: self._remove_asset(asset))
        menu.exec(pos)

    def _toggle_star(self, asset):
        asset.starred = not asset.starred
        self._refresh_grid()

    def _toggle_tag(self, asset, tag_id):
        if tag_id in asset.tags:
            asset.tags.remove(tag_id)
        else:
            asset.tags.append(tag_id)
        self._refresh_grid()
        self.selection_changed.emit(list(self._selected_ids))

    def _star_all_selected(self):
        for a in self.project.assets:
            if a.id in self._selected_ids:
                a.starred = True
        self._refresh_grid()

    def _unstar_all_selected(self):
        for a in self.project.assets:
            if a.id in self._selected_ids:
                a.starred = False
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
