"""Tag checklist panel — assign use-case tags to selected asset(s) with fitness indicators."""
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QFrame, QScrollArea, QTextEdit, QPushButton, QSplitter, QColorDialog,
    QMenu, QInputDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from doxyedit.themes import ui_font_size, THEMES, DEFAULT_THEME

from doxyedit.models import (
    Asset, TAG_PRESETS, TAG_SIZED, TAG_SHORTCUTS, TagPreset,
    check_fitness, VINIK_COLORS, VISUAL_TAGS,
)


FITNESS_COLORS = {
    "green": "#44cc44",
    "yellow": "#ffa500",
    "red": "#ff4444",
}


def _apply_menu_theme(menu: QMenu) -> None:
    """Wrapper around themes.apply_menu_theme. Kept as a name so the
    rest of tagpanel.py call sites stay short; reads the user's saved
    theme from QSettings each call so menus track theme switches."""
    from doxyedit.themes import apply_menu_theme
    apply_menu_theme(menu)


class _TagContainer(QWidget):
    """Inner scroll widget that handles drag-to-select and drag-to-reorder tag rows."""

    def __init__(self, panel):
        super().__init__()
        self._panel = panel           # TagPanel reference
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self._drag_mode = "none"      # "select" | "reorder" | "none"
        self._reorder_tag_id: str | None = None
        self._drop_indicator_y = -1
        self.setMouseTracking(True)

    # ── rubber-band drag-select ─────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
            self._drag_current = event.pos()
            # Check if click lands on a selected row → drag-reorder
            tag_id = self._tag_id_at(event.pos())
            if tag_id and tag_id in self._panel._selected_tag_rows:
                self._drag_mode = "reorder"
                self._reorder_tag_id = tag_id
            else:
                self._drag_mode = "select"
                self._reorder_tag_id = None
            # Grab mouse so we get the release even if it happens outside this widget
            self.grabMouse()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        self._drag_current = event.pos()
        if self._drag_mode == "select":
            self._update_drag_selection()
            self.update()
        elif self._drag_mode == "reorder":
            self._drop_indicator_y = event.pos().y()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.releaseMouse()
            if self._drag_mode == "reorder" and self._reorder_tag_id:
                self._finish_reorder(event.pos())
            self._drag_start = None
            self._drag_current = None
            self._drag_mode = "none"
            self._reorder_tag_id = None
            self._drop_indicator_y = -1
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        _dt = THEMES[DEFAULT_THEME]
        p = QPainter(self)
        # Rubber-band rectangle
        if self._drag_mode == "select" and self._drag_start and self._drag_current:
            rect = QRect(self._drag_start, self._drag_current).normalized()
            sel_color = QColor(_dt.selection_bg)
            sel_color.setAlpha(_dt.tag_row_active_alpha)
            p.setPen(QPen(sel_color, _dt.tag_selection_pen_width))
            sel_fill = QColor(_dt.selection_bg)
            sel_fill.setAlpha(_dt.tag_row_dim_alpha)
            p.setBrush(QBrush(sel_fill))
            p.drawRect(rect)
        # Drop indicator line
        if self._drag_mode == "reorder" and self._drop_indicator_y >= 0:
            accent_color = QColor(_dt.accent_bright)
            accent_color.setAlpha(_dt.tag_row_hover_alpha)
            p.setPen(QPen(accent_color, _dt.tag_drop_indicator_pen_width))
            p.drawLine(0, self._drop_indicator_y, self.width(), self._drop_indicator_y)
        p.end()

    # ── helpers ────────────────────────────────────────────────────────────

    def _tag_id_at(self, pos: QPoint) -> str | None:
        """Return the tag_id of the row widget under pos, or None."""
        for tag_id, row in self._panel._rows.items():
            if row.isVisible() and row.geometry().contains(pos):
                return tag_id
        return None

    def _update_drag_selection(self):
        if not self._drag_start or not self._drag_current:
            return
        rect = QRect(self._drag_start, self._drag_current).normalized()
        new_sel: set[str] = set()
        for tag_id, row in self._panel._rows.items():
            if not row.isVisible():
                continue
            hit = row.geometry().intersects(rect)
            was = tag_id in self._panel._selected_tag_rows
            if hit != was:
                row.set_row_selected(hit)
            if hit:
                new_sel.add(tag_id)
        self._panel._selected_tag_rows = new_sel

    def _finish_reorder(self, pos: QPoint):
        """Drop the dragged tag row to the position nearest the cursor.
        Supports cross-section moves — dragging a tag into a different section
        updates its section assignment."""
        tag_id = self._reorder_tag_id
        if not tag_id:
            return
        old_section = self._panel._tag_sections.get(tag_id)
        widget_to_tid = {row: tid for tid, row in self._panel._rows.items()}

        # Collect ALL visible tag rows across all sections
        all_rows: list[tuple[int, str, int]] = []  # (y_mid, tag_id, layout_idx)
        # Track section separator positions to determine target section
        sep_positions: list[tuple[int, str]] = []  # (y_mid, section_id)
        for i in range(self._panel._tag_layout.count()):
            item = self._panel._tag_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            if not w or not w.isVisible():
                continue
            tid = widget_to_tid.get(w)
            if tid:
                all_rows.append((w.geometry().center().y(), tid, i))
            # Check if this is a section separator
            for sid, (sep_label, _) in self._panel._section_btns.items():
                if w is sep_label:
                    sep_positions.append((w.geometry().center().y(), sid))

        if not all_rows:
            return
        ids_in_order = [tid for _, tid, _ in all_rows]
        if tag_id not in ids_in_order:
            return
        cur_idx = ids_in_order.index(tag_id)

        # Find target index based on drop position
        drop_y = pos.y()
        new_idx = len(ids_in_order) - 1
        for i, (mid_y, tid, _) in enumerate(all_rows):
            if drop_y < mid_y:
                new_idx = i if i <= cur_idx else i - 1
                break
        if new_idx == cur_idx:
            return

        # Determine which section the drop lands in
        target_tid = ids_in_order[new_idx]
        new_section = self._panel._tag_sections.get(target_tid, old_section)

        # Direct layout swap: take the dragged widget and re-insert at target
        src_li = all_rows[cur_idx][2]
        dst_li = all_rows[new_idx][2]
        dragged_w = self._panel._tag_layout.takeAt(src_li).widget()
        insert_at = dst_li if src_li > dst_li else dst_li - 1
        self._panel._tag_layout.insertWidget(insert_at, dragged_w)

        # Update section if it changed
        if new_section != old_section:
            self._panel._tag_sections[tag_id] = new_section
            self._panel.tag_section_changed.emit(tag_id, new_section)

        # Emit reorder for all tags in the target section
        section_ids = [tid for tid in ids_in_order if
                       self._panel._tag_sections.get(tid) == new_section]
        # Re-insert tag_id at its new position within the section
        if tag_id in section_ids:
            section_ids.remove(tag_id)
        # Find where it should be relative to other section tags
        target_section_idx = 0
        for i, (_, tid, _) in enumerate(all_rows):
            if self._panel._tag_sections.get(tid) == new_section and tid != tag_id:
                if i <= new_idx:
                    target_section_idx = section_ids.index(tid) + 1
        section_ids.insert(min(target_section_idx, len(section_ids)), tag_id)
        for order_i, tid in enumerate(section_ids):
            self._panel.tag_reordered.emit(tid, order_i)


class TagRow(QFrame):
    """One tag checkbox with fitness indicator dot."""
    toggled = Signal(str, bool)
    hide_requested = Signal(str)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)
    pin_requested = Signal(str)
    shortcut_requested = Signal(str)
    parent_changed = Signal(str, str)  # tag_id, new_parent_id ("" = top-level)
    visibility_toggled = Signal(str, bool)
    row_clicked = Signal(str, bool)  # tag_id, ctrl_held
    select_all_requested = Signal(str)  # tag_id
    color_changed = Signal(str, str)   # tag_id, new_hex_color
    reorder_requested = Signal(str, int)  # tag_id, direction (-1=up, +1=down)

    def __init__(self, tag: TagPreset, parent=None):
        super().__init__(parent)
        self.tag = tag
        self._pinned = False
        self._row_selected = False
        _f = ui_font_size()
        _cb = max(14, _f + 2)
        _pad = max(4, _f // 3)
        self._f = _f
        self._cb = _cb
        self.setObjectName("tag_row")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_pad, max(2, _pad // 2), _pad, max(2, _pad // 2))
        layout.setSpacing(_pad)

        # Eye toggle — hide/show images with this tag
        self.eye_btn = QPushButton("\u25C9")  # ◉ when visible
        self.eye_btn.setObjectName("tag_eye_btn")
        self.eye_btn.setFixedSize(_cb, _cb)
        self.eye_btn.setCheckable(True)
        self.eye_btn.setChecked(True)
        self.eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.eye_btn.setToolTip("Toggle visibility — hide/show images with this tag")
        self.eye_btn.toggled.connect(self._on_eye_click)
        layout.addWidget(self.eye_btn)

        # Tag color dot (shows the tag's own color)
        self.dot = QLabel()
        _dot = max(8, _f)
        self._dot_size = _dot
        self.dot.setFixedSize(_dot, _dot)
        self.dot.setStyleSheet(
            f"background: {tag.color}; border-radius: {_dot // 2}px;"
            f" border: 1px solid rgba(0,0,0,0.3);")
        layout.addWidget(self.dot)

        # Checkbox — bold text in tag color
        # Object name scopes the rule so it beats the global theme QCheckBox selector
        self.checkbox = QCheckBox(tag.label)
        self.checkbox.setObjectName("tag_checkbox")
        _bold = self.checkbox.font(); _bold.setBold(True); self.checkbox.setFont(_bold)
        self.checkbox.setStyleSheet(
            f"QCheckBox#tag_checkbox {{ color: {tag.color}; }}"
            f"QCheckBox#tag_checkbox::indicator {{ width: {_cb-2}px; height: {_cb-2}px; }}")
        self.checkbox.setToolTip("Check to apply this tag to selected assets")
        self.checkbox.toggled.connect(lambda checked: self.toggled.emit(tag.id, checked))
        layout.addWidget(self.checkbox, 1)

        # Keyboard shortcut hint
        shortcut_key = ""
        for k, v in TAG_SHORTCUTS.items():
            if v == tag.id:
                shortcut_key = k
                break

        # Size + shortcut hint
        hints = []
        if tag.width and tag.height:
            hints.append(f"{tag.width}x{tag.height}")
        elif tag.width:
            hints.append(f"{tag.width}xflex")
        if shortcut_key:
            hints.append(f"[{shortcut_key}]")

        hint_label = QLabel("  ".join(hints) if hints else "any")
        hint_label.setObjectName("tag_hint")
        layout.addWidget(hint_label)

        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("tag_count")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._count_lbl)

    def _set_fitness(self, level: str):
        color = FITNESS_COLORS.get(level, "#888")
        self.dot.setStyleSheet(
            f"background: {color}; border-radius: 6px; border: 1px solid rgba(0,0,0,0.3);"
        )
        self.dot.setToolTip(f"Fitness: {level}")

    def update_fitness(self, img_w: int, img_h: int):
        level = check_fitness(img_w, img_h, self.tag)
        self._set_fitness(level)

    def _on_eye_click(self, visible: bool):
        self.eye_btn.setText("\u25C9" if visible else "\u25CB")
        self.visibility_toggled.emit(self.tag.id, visible)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            self.row_clicked.emit(self.tag.id, bool(ctrl))
        super().mousePressEvent(event)

    def set_row_selected(self, selected: bool):
        self._row_selected = selected
        _dt = THEMES[DEFAULT_THEME]
        _bw = max(2, self._f // 4)
        if selected:
            _c = QColor(_dt.selection_bg); _c.setAlpha(_dt.tag_row_dim_alpha)
            self.setStyleSheet(f"background: rgba({_c.red()},{_c.green()},{_c.blue()},{_c.alpha() / 255:.2f}); border-radius: {_bw}px;")
        else:
            if self._pinned:
                _p = QColor(_dt.accent_dim); _p.setAlpha(_dt.composer_status_hover_alpha)
                base = f"border-left: {_bw}px solid rgba({_p.red()},{_p.green()},{_p.blue()},{_p.alpha() / 255:.2f});"
            else:
                base = ""
            self.setStyleSheet(base)

    def set_checked(self, checked: bool, block_signals=True):
        if block_signals:
            self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        if block_signals:
            self.checkbox.blockSignals(False)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        _apply_menu_theme(menu)
        pin_label = "Unpin from top" if getattr(self, '_pinned', False) else "Pin to top"
        menu.addAction(pin_label, lambda: self.pin_requested.emit(self.tag.id))
        menu.addAction("Set Shortcut Key", lambda: self.shortcut_requested.emit(self.tag.id))
        menu.addSeparator()
        menu.addAction("Move Up", lambda: self.reorder_requested.emit(self.tag.id, -1))
        menu.addAction("Move Down", lambda: self.reorder_requested.emit(self.tag.id, 1))
        menu.addSeparator()
        menu.addAction(f"Rename '{self.tag.label}'", self._request_rename)
        menu.addAction(f"Hide '{self.tag.label}'", lambda: self.hide_requested.emit(self.tag.id))
        menu.addAction(f"Delete '{self.tag.label}' from project", lambda: self.delete_requested.emit(self.tag.id))
        menu.addSeparator()
        menu.addAction(f"Change Color...", self._pick_color)
        menu.addAction("Set Parent Tag...", self._pick_parent)
        menu.addSeparator()
        menu.addAction(f"Select all with '{self.tag.label}'", lambda: self.select_all_requested.emit(self.tag.id))
        menu.exec(event.globalPos())

    def _pick_parent(self):
        """Pick a parent tag from the project's existing tags. Selecting
        '(none)' clears the parent. The widget itself doesn't know the
        full tag list — emit parent_changed with an empty string so the
        TagPanel can pop the actual selector and route the result back."""
        from PySide6.QtWidgets import QInputDialog
        # Walk up to TagPanel to read available tag ids
        panel = self.parent()
        while panel is not None and not hasattr(panel, "_get_all_tag_ids"):
            panel = panel.parent()
        if panel is None or not hasattr(panel, "_get_all_tag_ids"):
            # Fallback: just take a free-text id
            text, ok = QInputDialog.getText(
                self.window(), "Set Parent Tag",
                f"Parent for '{self.tag.label}' (empty = top-level):",
                text=getattr(self.tag, "parent_id", "") or "")
            if ok:
                self.parent_changed.emit(self.tag.id, text.strip())
            return
        candidates = [
            ("(none — top level)", "")
        ] + [(tid, tid) for tid in panel._get_all_tag_ids()
             if tid != self.tag.id]
        labels = [c[0] for c in candidates]
        current = getattr(self.tag, "parent_id", "") or ""
        cur_idx = next(
            (i for i, c in enumerate(candidates) if c[1] == current), 0)
        choice, ok = QInputDialog.getItem(
            self.window(), "Set Parent Tag",
            f"Parent for '{self.tag.label}':",
            labels, current=cur_idx, editable=False)
        if not ok:
            return
        new_parent = next(c[1] for c in candidates if c[0] == choice)
        if new_parent != current:
            self.parent_changed.emit(self.tag.id, new_parent)

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self.tag.color), self.window(), "Tag Color")
        if color.isValid():
            hex_color = color.name()
            self.tag = type(self.tag)(id=self.tag.id, label=self.tag.label,
                                      color=hex_color, width=self.tag.width,
                                      height=self.tag.height, ratio=self.tag.ratio)
            self.dot.setStyleSheet(f"background: {hex_color}; border-radius: {self._dot_size // 2}px; border: 1px solid rgba(0,0,0,0.3);")
            self.checkbox.setStyleSheet(
                f"QCheckBox#tag_checkbox {{ color: {hex_color}; }}"
                f"QCheckBox#tag_checkbox::indicator {{ width: {self._cb - 2}px; height: {self._cb - 2}px; }}")
            self.color_changed.emit(self.tag.id, hex_color)

    def _request_rename(self):
        dlg = QInputDialog(self.window())
        dlg.setWindowTitle("Rename Tag")
        dlg.setLabelText(f"New name for '{self.tag.label}':")
        dlg.setTextValue(self.tag.label)
        from doxyedit.themes import themed_dialog_size
        dlg.resize(*themed_dialog_size(33.33, 11.67))
        if dlg.exec():
            new_name = dlg.textValue().strip()
            if new_name and new_name != self.tag.label:
                self.rename_requested.emit(self.tag.id, new_name)


class TagPanel(QWidget):
    """Tag checklist for the currently selected asset(s)."""
    tags_changed = Signal()
    tag_deleted = Signal(str)
    tag_renamed = Signal(str, str, str)
    shortcut_changed = Signal(str, str)
    hidden_changed = Signal(list)
    filter_by_eye = Signal(list)  # list of tag_ids to HIDE from grid
    select_all_with_tag = Signal(str)  # select all assets with this tag
    tag_color_changed = Signal(str, str)  # tag_id, new_hex_color
    tag_reordered = Signal(str, int)  # tag_id, new_order_index
    tag_section_changed = Signal(str, str)  # tag_id, new_section_id
    batch_apply_tags = Signal(list)  # list of tag_ids to apply to selected assets

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("doxyedit_tagpanel")
        self._assets: list[Asset] = []
        self._img_dims: dict[str, tuple[int, int]] = {}
        self._rows: dict[str, TagRow] = {}
        self._tag_sections: dict[str, str] = {}  # tag_id → section name
        self._section_starts: dict[str, int] = {}  # section → layout index of first tag
        self._hidden_tags: set[str] = set()
        self._eye_hidden: set[str] = set()
        self._custom_shortcuts: dict[str, str] = {}
        self._selected_tag_rows: set[str] = set()  # multi-selected tag ids  # tag_id → key
        self._build()

    def _build(self):
        _f = ui_font_size()
        _pad = max(4, _f // 3)
        root = QVBoxLayout(self)
        root.setContentsMargins(_pad, _pad, _pad, _pad)

        # Header
        self.header = QLabel("Select an image to tag it")
        self.header.setObjectName("tagpanel_header")
        _bold = self.header.font(); _bold.setBold(True); self.header.setFont(_bold)
        self.header.setWordWrap(True)
        # Filenames have no spaces, so QLabel's word-wrap can't break them
        # and the long token forces the whole panel wider. Allow the label
        # to shrink below its natural sizeHint so wrapping (with the
        # zero-width-space insertions in _refresh) actually kicks in.
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored,
                                  QSizePolicy.Policy.Preferred)
        self.header.setMinimumWidth(0)
        self.header.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.header)

        self.hint_label = QLabel("Click an image on the left, then check tags below")
        self.hint_label.setObjectName("tagpanel_hint")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.dim_label = QLabel("")
        self.dim_label.setObjectName("tagpanel_dim")
        root.addWidget(self.dim_label)

        # Batch buttons - short labels so the whole panel can collapse narrow
        batch_row = QHBoxLayout()
        btn_ignore = QPushButton("Ignore")
        btn_ignore.setObjectName("tagpanel_action_btn")
        btn_ignore.setToolTip("Mark Ignore")
        btn_ignore.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn_ignore.setMinimumWidth(0)
        btn_ignore.clicked.connect(lambda: self._batch_tag("ignore", True))
        batch_row.addWidget(btn_ignore)

        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("tagpanel_action_btn")
        btn_clear.setToolTip("Clear All")
        btn_clear.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn_clear.setMinimumWidth(0)
        btn_clear.clicked.connect(self._clear_all_tags)
        batch_row.addWidget(btn_clear)

        self._btn_show_all = QPushButton("Show")
        self._btn_show_all.setObjectName("tagpanel_action_btn")
        self._btn_show_all.setToolTip("Show All")
        self._btn_show_all.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._btn_show_all.setMinimumWidth(0)
        self._btn_show_all.clicked.connect(self._show_all_tags)
        self._btn_show_all.setVisible(False)
        batch_row.addWidget(self._btn_show_all)

        self._collapse_all_btn = QPushButton("Collapse")
        self._collapse_all_btn.setObjectName("tagpanel_action_btn")
        self._collapse_all_btn.setToolTip("Collapse / expand all tag sections")
        self._collapse_all_btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._collapse_all_btn.setMinimumWidth(0)
        self._collapse_all_btn.clicked.connect(self._toggle_all_sections)
        batch_row.addWidget(self._collapse_all_btn)

        batch_row.addStretch()
        root.addLayout(batch_row)

        # Tag checkboxes
        scroll = QScrollArea()
        scroll.setObjectName("tag_scroll")
        scroll.setWidgetResizable(True)
        tag_widget = _TagContainer(self)
        tag_layout = QVBoxLayout(tag_widget)
        tag_layout.setSpacing(max(2, _pad // 2))
        tag_layout.setContentsMargins(0, 0, 0, 0)

        self._tag_layout = tag_layout
        self._tag_scroll_widget = tag_widget
        self._tag_scroll = scroll

        self._collapsed_sections: set[str] = set()

        def _make_section_label(text, section_id):
            btn = QPushButton(f"\u25BC {text}")  # ▼ expanded
            btn.setObjectName("tag_section_btn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: self._toggle_section(section_id, btn, text))
            return btn

        def _make_sep(label_text, section_id, visible=True):
            sep = QFrame()
            sep.setObjectName("tag_separator")
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setVisible(visible)
            tag_layout.addWidget(sep)
            lbl = _make_section_label(label_text, section_id)
            lbl.setVisible(visible)
            tag_layout.addWidget(lbl)
            return sep, lbl

        # Map section_id → (btn, label_text) for collapse-all
        self._section_btns: dict[str, tuple] = {}

        # "Default" section label (no separator line above — it's the first section)
        self._default_lbl = _make_section_label("Default", "content")
        self._section_btns["content"] = (self._default_lbl, "Default")
        tag_layout.addWidget(self._default_lbl)

        # Content/workflow tags
        self._section_starts["content"] = tag_layout.count()
        for tag_id, tag in TAG_PRESETS.items():
            self._add_tag_row(tag_id, tag, section="content")

        self._sep1, self._sep1_label = _make_sep("Platform / Size targets", "sized")
        self._section_btns["sized"] = (self._sep1_label, "Platform / Size targets")

        self._section_starts["sized"] = tag_layout.count()
        for tag_id, tag in TAG_SIZED.items():
            self._add_tag_row(tag_id, tag, section="sized")

        self._sep2, self._sep2_label = _make_sep("Custom / Project tags", "custom", visible=False)
        self._section_btns["custom"] = (self._sep2_label, "Custom / Project tags")
        self._sep3, self._sep3_label = _make_sep("Visual / Mood / Dimension", "visual", visible=False)
        self._section_btns["visual"] = (self._sep3_label, "Visual / Mood / Dimension")

        self._stretch = tag_layout.addStretch()
        scroll.setWidget(tag_widget)

        # Notes panel
        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(max(2, _pad // 2))
        notes_label = QLabel("Notes:")
        notes_layout.addWidget(notes_label)
        self.notes_edit = QTextEdit()
        _f_notes = ui_font_size()
        self.notes_edit.setMinimumHeight(max(30, _f_notes * 2))
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        notes_layout.addWidget(self.notes_edit)

        # Splitter between tags and notes — draggable boundary
        self._tag_notes_split = QSplitter(Qt.Orientation.Vertical)
        self._tag_notes_split.addWidget(scroll)
        self._tag_notes_split.addWidget(notes_widget)
        self._tag_notes_split.setStretchFactor(0, 1)
        self._tag_notes_split.setStretchFactor(1, 0)
        self._tag_notes_split.setSizes([400, 80])
        root.addWidget(self._tag_notes_split)

    def _add_tag_row(self, tag_id: str, tag: TagPreset, section: str = "discovered", insert_after=None):
        row = TagRow(tag)
        row.toggled.connect(self._on_tag_toggled)
        row.hide_requested.connect(self._hide_tag)
        row.delete_requested.connect(self._delete_tag)
        row.rename_requested.connect(self._rename_tag)
        row.pin_requested.connect(self._pin_tag)
        row.shortcut_requested.connect(self._set_shortcut)
        row.visibility_toggled.connect(self._on_eye_toggled)
        row.row_clicked.connect(self._on_row_clicked)
        row.select_all_requested.connect(lambda tid: self.select_all_with_tag.emit(tid))
        row.color_changed.connect(self._on_tag_color_changed)
        row.reorder_requested.connect(self._reorder_tag)
        row.parent_changed.connect(self._on_tag_parent_changed)
        if tag_id in self._hidden_tags or section in self._collapsed_sections:
            row.setVisible(False)
        if insert_after is not None:
            # Find the widget index and insert after it
            for i in range(self._tag_layout.count()):
                item = self._tag_layout.itemAt(i)
                if item and item.widget() is insert_after:
                    self._tag_layout.insertWidget(i + 1, row)
                    break
            else:
                self._tag_layout.addWidget(row)
        else:
            self._tag_layout.addWidget(row)
        self._rows[tag_id] = row
        self._tag_sections[tag_id] = section

    def refresh_discovered_tags(self, assets: list, project=None):
        """Add rows for tags found in assets and custom_tags, sorted into sections."""
        existing_ids = set(self._rows.keys())
        # Un-hide any previously deleted rows whose tag has reappeared in assets.
        # Prefer the inverted index when we have a project — O(tags) vs O(assets).
        if project is not None and hasattr(project, "tag_users"):
            tags_in_assets = set(project.tag_users.keys())
        else:
            tags_in_assets = {t for a in assets for t in a.tags}
        for tid in list(self._hidden_tags):
            if tid in existing_ids and tid in tags_in_assets:
                self._hidden_tags.discard(tid)
                self._rows[tid].setVisible(True)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        color_idx = 0
        custom_tags = {}
        visual_tags = {}

        # From tag_definitions (preferred) and legacy custom_tags
        if project:
            all_project_tags = project.get_tags() if hasattr(project, 'get_tags') else {}
            for tid, preset in all_project_tags.items():
                if tid not in existing_ids and tid not in TAG_PRESETS and tid not in TAG_SIZED:
                    custom_tags[tid] = preset

        # From asset tags - use the inverted index when we have it (O(tags))
        if project is not None and hasattr(project, "tag_users"):
            tag_iter = iter(project.tag_users.keys())
        else:
            tag_iter = (t for asset in assets for t in asset.tags)
        for t in tag_iter:
            if t not in existing_ids and t not in custom_tags and t not in visual_tags:
                preset = TagPreset(id=t, label=t,
                    color=VINIK_COLORS[color_idx % len(VINIK_COLORS)])
                color_idx += 1
                if t in VISUAL_TAGS:
                    visual_tags[t] = preset
                else:
                    custom_tags[t] = preset

        # Add custom/project tags — insert after _sep2_label, ordered by "order" field then label
        if custom_tags:
            self._sep2.setVisible(True)
            self._sep2_label.setVisible(True)
            last_custom = self._sep2_label
            tag_defs = project.tag_definitions if project else {}
            def _custom_sort_key(item):
                tid, preset = item
                order = tag_defs.get(tid, {}).get("order", 9999)
                return (order, preset.label.lower())
            for tid, preset in sorted(custom_tags.items(), key=_custom_sort_key):
                # Respect persisted section override from cross-section drag
                saved_section = tag_defs.get(tid, {}).get("section", "custom")
                self._add_tag_row(tid, preset, section=saved_section, insert_after=last_custom)
                last_custom = self._rows[tid]
                existing_ids.add(tid)

        # Add visual property tags — insert after _sep3_label (always last), sorted
        if visual_tags:
            self._sep3.setVisible(True)
            self._sep3_label.setVisible(True)
            last_visual = self._sep3_label
            tag_defs_v = project.tag_definitions if project else {}
            for tid, preset in sorted(visual_tags.items(), key=lambda x: x[1].label.lower()):
                saved_section = tag_defs_v.get(tid, {}).get("section", "visual")
                self._add_tag_row(tid, preset, section=saved_section, insert_after=last_visual)
                last_visual = self._rows[tid]
                existing_ids.add(tid)

    def apply_collapsed_state(self):
        """Apply saved _collapsed_sections to the UI — update arrows and row visibility."""
        for sid, (btn, label) in self._section_btns.items():
            if sid in self._collapsed_sections:
                btn.setText(f"\u25B6 {label}")  # ▶ collapsed
            else:
                btn.setText(f"\u25BC {label}")  # ▼ expanded
        for tag_id, row in self._rows.items():
            sid = self._tag_sections.get(tag_id)
            row.setVisible(sid not in self._collapsed_sections
                           and tag_id not in self._hidden_tags)

    def _toggle_section(self, section_id: str, btn, label_text: str):
        """Collapse/expand a tag section."""
        if section_id in self._collapsed_sections:
            self._collapsed_sections.discard(section_id)
            btn.setText(f"\u25BC {label_text}")  # ▼ expanded
        else:
            self._collapsed_sections.add(section_id)
            btn.setText(f"\u25B6 {label_text}")  # ▶ collapsed
        for tag_id, row in self._rows.items():
            if self._tag_sections.get(tag_id) == section_id:
                row.setVisible(section_id not in self._collapsed_sections
                               and tag_id not in self._hidden_tags)

    def _toggle_all_sections(self):
        """Collapse all sections if any are expanded, otherwise expand all."""
        all_section_ids = [sid for sid in self._section_btns if sid in
                           {self._tag_sections.get(tid) for tid in self._rows}]
        any_expanded = any(sid not in self._collapsed_sections for sid in all_section_ids)
        for sid, (btn, label) in self._section_btns.items():
            if any_expanded:
                self._collapsed_sections.add(sid)
                btn.setText(f"\u25B6 {label}")
            else:
                self._collapsed_sections.discard(sid)
                btn.setText(f"\u25BC {label}")
        for tag_id, row in self._rows.items():
            sid = self._tag_sections.get(tag_id)
            row.setVisible(sid not in self._collapsed_sections and tag_id not in self._hidden_tags)
        self._collapse_all_btn.setText("Expand" if any_expanded else "Collapse")

    def _btn_style(self):
        return "QPushButton { padding: 3px 8px; }"

    def update_font_size(self, font_size: int):
        """Scale all fonts in the tag panel."""
        f = font_size
        for row in self._rows.values():
            _bold = row.checkbox.font(); _bold.setBold(True); row.checkbox.setFont(_bold)
            if hasattr(row, '_hint_label'):
                pass  # hint_label inherits font from stylesheet
        _bold = self.header.font(); _bold.setBold(True); self.header.setFont(_bold)

    def set_assets(self, assets: list[Asset]):
        """Set which asset(s) the tag panel is editing."""
        self._assets = assets

        if not assets:
            self.header.setText("Select an image to tag it")
            self.header.setProperty("state", "empty")
            self.header.style().unpolish(self.header)
            self.header.style().polish(self.header)
            self.hint_label.setText("Click an image on the left, then check tags below")
            self.hint_label.show()
            self.dim_label.setText("")
            for row in self._rows.values():
                row.set_checked(False)
            return

        # Active state — highlight the panel
        self.header.setProperty("state", "active")
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        self.hint_label.setText("Check the boxes below to tag this image for use")

        if len(assets) == 1:
            a = assets[0]
            name = Path(a.source_path).stem
            # Insert zero-width-spaces at common token boundaries so
            # QLabel can wrap long filenames instead of forcing the
            # whole panel wider than the user-set width.
            ZWSP = "​"
            wrappable = name
            for ch in ("_", "-", ".", "(", ")", "@"):
                wrappable = wrappable.replace(ch, ch + ZWSP)
            self.header.setText(wrappable)
            self.header.setToolTip(name)
            if a.tags:
                self.hint_label.hide()
            else:
                self.hint_label.hide()
            w, h = self._get_dims(a)
            if w and h:
                ratio = f"{w/h:.2f}" if h else "?"
                self.dim_label.setText(f"{w} x {h} px  (ratio {ratio})")
            else:
                self.dim_label.setText("dimensions unknown")

            # Update checkboxes
            for tag_id, row in self._rows.items():
                row.set_checked(tag_id in a.tags)

            self.notes_edit.blockSignals(True)
            self.notes_edit.setPlainText(a.notes)
            self.notes_edit.blockSignals(False)
        else:
            self.header.setText(f"{len(assets)} assets selected")
            self.dim_label.setText("batch mode — tags applied to all")
            # Show intersection of tags
            common_tags = set(assets[0].tags)
            for a in assets[1:]:
                common_tags &= set(a.tags)
            for tag_id, row in self._rows.items():
                row.set_checked(tag_id in common_tags)
            self.notes_edit.blockSignals(True)
            self.notes_edit.setPlainText("")
            self.notes_edit.blockSignals(False)

    def _get_dims(self, asset: Asset) -> tuple[int, int]:
        if asset.id in self._img_dims:
            return self._img_dims[asset.id]
        try:
            with Image.open(asset.source_path) as img:
                w, h = img.size
                self._img_dims[asset.id] = (w, h)
                return w, h
        except Exception:
            return 0, 0

    def _pin_tag(self, tag_id: str):
        """Pin/unpin a tag to the top of its own section."""
        if tag_id not in self._rows:
            return
        row = self._rows[tag_id]
        pinned = row._pinned
        row._pinned = not pinned

        if row._pinned:
            # Find the section start index
            section = self._tag_sections.get(tag_id, "content")
            # Find first row in this section
            target_idx = 0
            for i in range(self._tag_layout.count()):
                item = self._tag_layout.itemAt(i)
                if item and item.widget():
                    w = item.widget()
                    if isinstance(w, TagRow):
                        wid = w.tag.id
                        if self._tag_sections.get(wid) == section:
                            target_idx = i
                            break
            self._tag_layout.removeWidget(row)
            self._tag_layout.insertWidget(target_idx, row)
            _dt = THEMES[DEFAULT_THEME]
            _p = QColor(_dt.accent_dim); _p.setAlpha(_dt.composer_status_hover_alpha)
            _bw = max(2, row._f // 4)
            row.setStyleSheet(f"border-left: {_bw}px solid rgba({_p.red()},{_p.green()},{_p.blue()},{_p.alpha() / 255:.2f});")
        else:
            row.setStyleSheet("")

    def _set_shortcut(self, tag_id: str):
        """Let user assign (or clear) a keyboard shortcut key for a tag."""
        current = self._custom_shortcuts.get(tag_id, "")
        current_hint = f" (current: {current})" if current else ""
        key, ok = QInputDialog.getText(
            self.window(), "Set Shortcut",
            f"Enter a single key for '{self._rows[tag_id].tag.label}'{current_hint}:\n"
            "Leave blank to clear the shortcut.")
        if not ok:
            return
        key = key.strip()
        if not key:
            # Clear shortcut
            self._custom_shortcuts.pop(tag_id, None)
            if tag_id in self._rows:
                row = self._rows[tag_id]
                row.checkbox.setText(row.tag.label)
            self.shortcut_changed.emit(tag_id, "")
            return
        key = key.upper()[0]
        self._custom_shortcuts[tag_id] = key
        if tag_id in self._rows:
            row = self._rows[tag_id]
            row.checkbox.setText(f"{row.tag.label} [{key}]")
        self.shortcut_changed.emit(tag_id, key)

    def _on_row_clicked(self, tag_id: str, ctrl_held: bool):
        """Ctrl+click to multi-select tag rows for batch operations."""
        if ctrl_held:
            if tag_id in self._selected_tag_rows:
                self._selected_tag_rows.discard(tag_id)
                if tag_id in self._rows:
                    self._rows[tag_id].set_row_selected(False)
            else:
                self._selected_tag_rows.add(tag_id)
                if tag_id in self._rows:
                    self._rows[tag_id].set_row_selected(True)
        else:
            # Clear previous, select this one
            for tid in self._selected_tag_rows:
                if tid in self._rows:
                    self._rows[tid].set_row_selected(False)
            self._selected_tag_rows = {tag_id}
            if tag_id in self._rows:
                self._rows[tag_id].set_row_selected(True)

        # If multiple selected, show batch context menu on right-click
        if len(self._selected_tag_rows) > 1:
            self.status_hint = f"{len(self._selected_tag_rows)} tags selected — right-click for batch actions"

    def contextMenuEvent(self, event):
        """Batch context menu when multiple tag rows are selected."""
        if len(self._selected_tag_rows) > 1:
            menu = QMenu(self)
            _apply_menu_theme(menu)
            n = len(self._selected_tag_rows)
            menu.addAction(f"Apply Selected Tags to Assets", self._batch_apply_to_assets)
            menu.addSeparator()
            menu.addAction(f"Hide All ({n})", self._batch_hide_selected)
            menu.addAction(f"Show All ({n})", self._batch_show_selected)
            menu.addAction(f"Delete All ({n})", self._batch_delete_selected)
            menu.addSeparator()
            menu.addAction("Clear Selection", self._clear_row_selection)
            menu.exec(event.globalPos())

    def _batch_hide_selected(self):
        for tid in list(self._selected_tag_rows):
            self._hide_tag(tid)
        self._clear_row_selection()

    def _batch_show_selected(self):
        for tid in list(self._selected_tag_rows):
            if tid in self._hidden_tags:
                self._hidden_tags.discard(tid)
            if tid in self._rows:
                self._rows[tid].setVisible(True)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        self.hidden_changed.emit(list(self._hidden_tags))
        self._clear_row_selection()

    def _batch_delete_selected(self):
        for tid in list(self._selected_tag_rows):
            self._delete_tag(tid)
        self._clear_row_selection()

    def _batch_apply_to_assets(self):
        """Apply all selected tags to currently selected assets in the browser."""
        self.batch_apply_tags.emit(list(self._selected_tag_rows))
        self._clear_row_selection()

    def _reorder_tag(self, tag_id: str, direction: int):
        """Move a tag row up (-1) or down (+1) within its section."""
        if tag_id not in self._rows:
            return
        section = self._tag_sections.get(tag_id)
        # Single pass: collect section order AND layout indices together
        row_widget = self._rows[tag_id]
        widget_to_tid = {row: tid for tid, row in self._rows.items()}
        section_ids: list[str] = []
        layout_indices: dict[str, int] = {}
        for i in range(self._tag_layout.count()):
            item = self._tag_layout.itemAt(i)
            if not item:
                continue
            w = item.widget()
            tid = widget_to_tid.get(w)
            if tid and self._tag_sections.get(tid) == section:
                section_ids.append(tid)
                layout_indices[tid] = i

        if tag_id not in layout_indices:
            return
        idx = section_ids.index(tag_id)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(section_ids):
            return

        swap_id = section_ids[new_idx]
        row_li = layout_indices[tag_id]
        swap_li = layout_indices[swap_id]
        # Remove higher index first to avoid shifting
        hi, lo = (row_li, swap_li) if row_li > swap_li else (swap_li, row_li)
        hi_w = self._tag_layout.takeAt(hi).widget()
        lo_w = self._tag_layout.takeAt(lo).widget()
        self._tag_layout.insertWidget(lo, hi_w)
        self._tag_layout.insertWidget(hi, lo_w)

        new_section_ids = list(section_ids)
        new_section_ids[idx], new_section_ids[new_idx] = new_section_ids[new_idx], new_section_ids[idx]
        for order_i, tid in enumerate(new_section_ids):
            self.tag_reordered.emit(tid, order_i)

    def _clear_row_selection(self):
        for tid in list(self._selected_tag_rows):
            if tid in self._rows:
                self._rows[tid].set_row_selected(False)
        self._selected_tag_rows.clear()

    def _on_eye_toggled(self, tag_id: str, visible: bool):
        """Eye button toggled — hide/show images tagged with this tag."""
        if visible:
            self._eye_hidden.discard(tag_id)
        else:
            self._eye_hidden.add(tag_id)
        self.filter_by_eye.emit(list(self._eye_hidden))

    def _hide_tag(self, tag_id: str):
        self._hidden_tags.add(tag_id)
        if tag_id in self._rows:
            self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        self.hidden_changed.emit(list(self._hidden_tags))

    def _show_all_tags(self):
        self._hidden_tags.clear()
        for row in self._rows.values():
            row.setVisible(True)
        self._btn_show_all.setVisible(False)
        self.hidden_changed.emit([])

    def load_hidden_tags(self, hidden: list[str]):
        """Restore hidden tags from project."""
        self._hidden_tags = set(hidden)
        for tag_id in hidden:
            if tag_id in self._rows:
                self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)

    def _rename_tag(self, old_id: str, new_label: str):
        """Rename a tag — updates the label in the row and the checkbox."""
        new_id = new_label.lower().replace(" ", "_").replace("/", "_")
        # Update all assets
        for asset in self._assets:
            if old_id in asset.tags:
                asset.tags.remove(old_id)
                if new_id not in asset.tags:
                    asset.tags.append(new_id)
        # Update the row widget
        if old_id in self._rows:
            row = self._rows.pop(old_id)
            row.tag = TagPreset(id=new_id, label=new_label, color=row.tag.color,
                                width=row.tag.width, height=row.tag.height, ratio=row.tag.ratio)
            row.checkbox.setText(new_label)
            self._rows[new_id] = row
        self.tag_renamed.emit(old_id, new_id, new_label)
        self.tags_changed.emit()

    def _delete_tag(self, tag_id: str):
        """Remove a tag from all assets and permanently hide the row."""
        for asset in self._assets:
            if tag_id in asset.tags:
                asset.tags.remove(tag_id)
        self._hidden_tags.add(tag_id)
        if tag_id in self._rows:
            self._rows[tag_id].setVisible(False)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)
        self.hidden_changed.emit(list(self._hidden_tags))
        self.tag_deleted.emit(tag_id)
        self.tags_changed.emit()

    def remove_tag_rows(self, tag_ids: list[str]):
        """Remove tag rows entirely from the panel (used after bulk unused-tag cleanup)."""
        for tag_id in tag_ids:
            row = self._rows.pop(tag_id, None)
            if row:
                row.setParent(None)
                row.deleteLater()
            self._tag_sections.pop(tag_id, None)
            self._hidden_tags.discard(tag_id)
            self._selected_tag_rows.discard(tag_id)
        self._btn_show_all.setVisible(len(self._hidden_tags) > 0)

    def _set_tag(self, tag_id: str, checked: bool):
        for asset in self._assets:
            if checked and tag_id not in asset.tags:
                asset.tags.append(tag_id)
            elif not checked and tag_id in asset.tags:
                asset.tags.remove(tag_id)

    def _on_tag_toggled(self, tag_id: str, checked: bool):
        self._set_tag(tag_id, checked)
        self.tags_changed.emit()

    def _batch_tag(self, tag_id: str, checked: bool):
        self._set_tag(tag_id, checked)
        self._rows[tag_id].set_checked(checked)
        self.tags_changed.emit()

    def _clear_all_tags(self):
        for asset in self._assets:
            asset.tags.clear()
        for row in self._rows.values():
            row.set_checked(False)
        self.tags_changed.emit()

    def update_tag_counts(self, all_assets: list, project=None):
        """Update the usage count badge on each tag row.

        Uses Project.tag_users (inverted index) when available — O(tags)
        instead of O(assets x tags_per_asset). Falls back to the scan
        when called without a project (legacy callers / tests).
        """
        if project is not None and hasattr(project, "tag_users"):
            tu = project.tag_users
            for tag_id, row in self._rows.items():
                n = len(tu.get(tag_id, ()))
                row._count_lbl.setText(str(n) if n else "")
            return
        counts: dict[str, int] = {}
        for a in all_assets:
            for t in a.tags:
                counts[t] = counts.get(t, 0) + 1
        for tag_id, row in self._rows.items():
            n = counts.get(tag_id, 0)
            row._count_lbl.setText(str(n) if n else "")

    def _on_tag_color_changed(self, tag_id: str, hex_color: str):
        """Propagate color change to window for persistence."""
        self.tag_color_changed.emit(tag_id, hex_color)
        self.tags_changed.emit()

    def _get_all_tag_ids(self) -> list[str]:
        """Used by TagRow's Set Parent dialog to populate the picker.
        Returns every tag id known to the active project + the row
        registry so a freshly-created custom tag is selectable too."""
        out = list(self._rows.keys())
        if self._project is not None:
            for tid in self._project.tag_definitions.keys():
                if tid not in out:
                    out.append(tid)
            for ct in self._project.custom_tags:
                if isinstance(ct, dict):
                    tid = ct.get("id", "")
                    if tid and tid not in out:
                        out.append(tid)
        return sorted(out)

    def _on_tag_parent_changed(self, tag_id: str, new_parent_id: str):
        """Persist the new parent into project.tag_definitions and emit
        tags_changed so the project becomes dirty + saves on next tick.

        Cycle guard: if assigning new_parent_id would create a cycle
        (e.g. tag is already an ancestor of new_parent_id) we silently
        decline rather than corrupting the project. The per-row
        QInputDialog the user just confirmed is gone, so the easiest
        feedback channel is the panel's status logger if present."""
        if self._project is None:
            return
        # Cycle check
        if new_parent_id and tag_id in self._project.get_tag_ancestors(
                new_parent_id):
            return
        if new_parent_id == tag_id:
            return  # no-op
        defn = self._project.tag_definitions.get(tag_id)
        if not isinstance(defn, dict):
            self._project.tag_definitions[tag_id] = {
                "label": tag_id, "color": "#888",
            }
            defn = self._project.tag_definitions[tag_id]
        if new_parent_id:
            defn["parent_id"] = new_parent_id
        else:
            defn.pop("parent_id", None)
        self.tags_changed.emit()

    def _on_notes_changed(self):
        if len(self._assets) == 1:
            self._assets[0].notes = self.notes_edit.toPlainText()
            self.tags_changed.emit()
