"""composer_left.py -- Left column of the post composer.

Shows large image preview, SFW/NSFW toggle with censored preview,
and per-platform crop status.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QCheckBox, QSizePolicy, QScrollArea, QMenu,
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap

from doxyedit.models import Project, SocialPost, Asset, PLATFORMS


PREVIEW_SIZE = 300


class ImagePreviewPanel(QWidget):
    """Left column: image preview + SFW/NSFW + crop status."""

    assets_changed = Signal()  # emitted when SFW toggle changes
    open_in_studio = Signal(str)   # asset_id
    open_in_preview = Signal(str)  # asset_id

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("composer_preview_panel")
        from PySide6.QtCore import QSettings as _QS
        _f = _QS("DoxyEdit", "DoxyEdit").value("font_size", 12, type=int)
        _cb = max(14, int(_f * 1.17))
        self._f = _f  # stash for methods
        self._project = project
        self._assets: list[Asset] = []
        self._censored_pm: QPixmap | None = None
        self._raw_pm: QPixmap | None = None  # unscaled source pixmap
        self._showing_censored = False

        self._build_ui()

    # ── Layout ratios (change here to rescale all composer-left widgets) ──
    MODE_BUTTON_HEIGHT_RATIO = 1.8     # Raw/Studio/Platform toggle height
    STATUS_DOT_WIDTH_RATIO = 1.17      # readiness dot width
    ORDER_CELL_SIZE_RATIO = 4.0        # image order strip cell
    CROP_ICON_WIDTH_RATIO = 1.33       # crop status checkmark icon
    CROP_LABEL_FONT_RATIO = 0.83      # crop label text on preview
    MIN_CROP_LABEL_FONT = 7           # crop label minimum readable size

    def _build_ui(self):
        _f = self._f
        _pad = max(4, _f // 3)
        _pad_lg = max(6, _f // 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_pad_lg)

        # -- Preview mode toggle --
        mode_row = QHBoxLayout()
        mode_row.setSpacing(max(2, _pad // 2))
        self._mode_raw = QPushButton("Raw")
        self._mode_raw.setObjectName("composer_preview_mode_btn")
        self._mode_raw.setCheckable(True)
        self._mode_raw.setChecked(True)
        self._mode_raw.clicked.connect(lambda: self._set_preview_mode("raw"))

        self._mode_studio = QPushButton("Studio")
        self._mode_studio.setObjectName("composer_preview_mode_btn")
        self._mode_studio.setCheckable(True)
        self._mode_studio.clicked.connect(lambda: self._set_preview_mode("studio"))

        self._mode_platform = QPushButton("Platform")
        self._mode_platform.setObjectName("composer_preview_mode_btn")
        self._mode_platform.setCheckable(True)
        self._mode_platform.clicked.connect(lambda: self._set_preview_mode("platform"))

        for btn in (self._mode_raw, self._mode_studio, self._mode_platform):
            btn.setFixedHeight(int(self._f * self.MODE_BUTTON_HEIGHT_RATIO))
            mode_row.addWidget(btn)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self._preview_mode = "raw"

        # -- Large image preview --
        self._preview_label = QLabel()
        self._preview_label.setObjectName("composer_main_preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._preview_label.customContextMenuRequested.connect(self._preview_context_menu)
        layout.addWidget(self._preview_label, 1)

        # -- Image order strip (for multi-image posts) --
        self._order_strip = QHBoxLayout()
        self._order_strip.setSpacing(_pad)
        self._order_container = QWidget()
        self._order_container.setLayout(self._order_strip)
        self._order_container.setVisible(False)
        layout.addWidget(self._order_container)

        # -- SFW / NSFW section (collapsed by default) --
        self._nsfw_header_btn = QPushButton("Content Rating \u25bc")
        self._nsfw_header_btn.setObjectName("composer_section_header")
        self._nsfw_header_btn.setCheckable(True)
        self._nsfw_header_btn.setChecked(False)
        self._nsfw_header_btn.clicked.connect(self._toggle_nsfw_section)
        layout.addWidget(self._nsfw_header_btn)

        self._nsfw_body = QFrame()
        self._nsfw_body.setObjectName("composer_nsfw_frame")
        nsfw_layout = QVBoxLayout(self._nsfw_body)
        nsfw_layout.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)
        nsfw_layout.setSpacing(_pad)

        nsfw_row = QHBoxLayout()
        self._nsfw_toggle = QPushButton("Show Censored")
        self._nsfw_toggle.setObjectName("composer_nsfw_toggle")
        self._nsfw_toggle.setCheckable(True)
        self._nsfw_toggle.clicked.connect(self._toggle_censored_preview)
        nsfw_row.addWidget(self._nsfw_toggle)
        nsfw_row.addStretch()
        nsfw_layout.addLayout(nsfw_row)

        self._censor_info = QLabel("No censor regions defined")
        self._censor_info.setObjectName("composer_censor_info")
        nsfw_layout.addWidget(self._censor_info)

        self._nsfw_checks: dict[str, QCheckBox] = {}
        self._nsfw_platform_container = QWidget()
        from doxyedit.browser import FlowLayout
        self._nsfw_plat_layout = FlowLayout(hspacing=8, vspacing=4)
        self._nsfw_platform_container.setLayout(self._nsfw_plat_layout)
        nsfw_layout.addWidget(self._nsfw_platform_container)

        self._nsfw_body.setVisible(False)
        layout.addWidget(self._nsfw_body)

        # -- Platform Prep Strip --
        self._prep_strip = QWidget()
        self._prep_strip.setObjectName("composer_prep_strip")
        self._prep_strip_layout = QVBoxLayout(self._prep_strip)
        self._prep_strip_layout.setContentsMargins(_pad, _pad, _pad, _pad)
        self._prep_strip_layout.setSpacing(max(2, _pad // 2))
        self._prep_strip.setVisible(False)
        layout.addWidget(self._prep_strip)

        # -- Platform crop status (collapsed by default) --
        self._crop_header_btn = QPushButton("Platform Crops \u25bc")
        self._crop_header_btn.setObjectName("composer_section_header")
        self._crop_header_btn.setCheckable(True)
        self._crop_header_btn.setChecked(False)
        self._crop_header_btn.clicked.connect(self._toggle_crop_section)
        layout.addWidget(self._crop_header_btn)

        self._crop_body = QFrame()
        self._crop_body.setObjectName("composer_crop_frame")
        crop_layout = QVBoxLayout(self._crop_body)
        crop_layout.setContentsMargins(_pad_lg, _pad_lg, _pad_lg, _pad_lg)
        crop_layout.setSpacing(max(2, _pad // 2))

        self._crop_status_layout = QVBoxLayout()
        self._crop_status_layout.setSpacing(max(2, _pad // 2))
        crop_layout.addLayout(self._crop_status_layout)

        self._crop_body.setVisible(False)
        layout.addWidget(self._crop_body)

    def rebuild_prep_strip(self, asset_ids: list[str], platform_ids: list[str],
                            project) -> None:
        """Rebuild the prep strip showing readiness per platform."""
        while self._prep_strip_layout.count():
            item = self._prep_strip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not asset_ids or not platform_ids:
            self._prep_strip.setVisible(False)
            return

        from doxyedit.pipeline import check_readiness
        from doxyedit.models import PLATFORMS

        asset = project.get_asset(asset_ids[0]) if asset_ids else None
        if not asset:
            self._prep_strip.setVisible(False)
            return

        header = QLabel("Platform Prep")
        header.setObjectName("composer_prep_header")
        self._prep_strip_layout.addWidget(header)

        for pid in platform_ids:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue

            readiness = check_readiness(asset, pid, project)
            status = readiness["status"]

            row_w = QWidget()
            _pad = max(4, self._f // 3)
            _pad_lg = max(6, self._f // 2)
            row = QHBoxLayout(row_w)
            row.setContentsMargins(max(2, _pad // 2), max(1, _pad // 4), max(2, _pad // 2), max(1, _pad // 4))
            row.setSpacing(_pad_lg)

            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            dot_colors = {"green": _dt.success, "yellow": _dt.warning, "red": _dt.error}
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {dot_colors.get(status, _dt.text_muted)};")
            dot.setFixedWidth(int(self._f * self.STATUS_DOT_WIDTH_RATIO))
            row.addWidget(dot)

            lbl = QLabel(platform.name)
            row.addWidget(lbl, 1)

            issues = readiness.get("issues", [])
            if issues:
                issue_lbl = QLabel(issues[0])
                issue_lbl.setStyleSheet(f"color: {_dt.error}; font-size: {_dt.font_size}px;")
                row.addWidget(issue_lbl)
            else:
                ok_lbl = QLabel("Ready")
                ok_lbl.setStyleSheet(f"color: {_dt.success}; font-size: {_dt.font_size}px;")
                row.addWidget(ok_lbl)

            self._prep_strip_layout.addWidget(row_w)

        self._prep_strip.setVisible(True)

    # -- Public API --

    def _set_preview_mode(self, mode: str):
        """Switch between raw, studio, and platform preview modes."""
        self._preview_mode = mode
        for btn, m in [(self._mode_raw, "raw"), (self._mode_studio, "studio"), (self._mode_platform, "platform")]:
            btn.setChecked(m == mode)
        self._update_preview()

    def _generate_studio_preview(self) -> "QPixmap | None":
        """Generate preview with censors + overlays applied."""
        if not self._assets:
            return None
        asset = self._assets[0]
        try:
            from doxyedit.imaging import load_image_for_export, pil_to_qpixmap
            from doxyedit.exporter import apply_censors, apply_overlays
            img = load_image_for_export(asset.source_path)
            if asset.censors:
                img = apply_censors(img, asset.censors)
            if asset.overlays:
                project_dir = str(Path(asset.source_path).parent)
                img = apply_overlays(img, asset.overlays, project_dir)
            return pil_to_qpixmap(img)
        except Exception:
            return None

    def _generate_platform_preview(self) -> "QPixmap | None":
        """Generate preview cropped to the first selected platform's dimensions."""
        if not self._assets:
            return None
        asset = self._assets[0]
        from doxyedit.models import PLATFORMS
        # Find the first platform that has a "post" slot
        for pa in asset.assignments:
            plat = PLATFORMS.get(pa.platform)
            if not plat:
                continue
            for slot in plat.slots:
                if "post" in slot.name.lower() or slot == plat.slots[0]:
                    try:
                        from doxyedit.imaging import load_image_for_export, pil_to_qpixmap
                        from doxyedit.exporter import apply_censors, apply_overlays
                        img = load_image_for_export(asset.source_path)
                        if asset.censors:
                            img = apply_censors(img, asset.censors)
                        if asset.overlays:
                            img = apply_overlays(img, asset.overlays, str(Path(asset.source_path).parent))
                        # Crop/resize to slot dimensions
                        if pa.crop and pa.crop.w > 0:
                            img = img.crop((pa.crop.x, pa.crop.y, pa.crop.x + pa.crop.w, pa.crop.y + pa.crop.h))
                        if slot.width and slot.height:
                            img = img.resize((slot.width, slot.height))
                        return pil_to_qpixmap(img)
                    except Exception:
                        return None
                    break
        # No platform assignment — just show studio version
        return self._generate_studio_preview()

    def _toggle_nsfw_section(self, checked: bool):
        self._nsfw_body.setVisible(checked)
        self._nsfw_header_btn.setText(
            "Content Rating \u25b2" if checked else "Content Rating \u25bc")

    def _toggle_crop_section(self, checked: bool):
        self._crop_body.setVisible(checked)
        self._crop_header_btn.setText(
            "Platform Crops \u25b2" if checked else "Platform Crops \u25bc")

    def set_assets(self, asset_ids: list[str]) -> None:
        """Load assets and update preview."""
        self._assets = []
        for aid in asset_ids:
            a = self._project.get_asset(aid)
            if a:
                self._assets.append(a)

        self._update_preview()
        self._update_order_strip()
        self._update_censor_info()

    def set_platforms(self, platform_ids: list[str]) -> None:
        """Update NSFW checkboxes and crop status for selected platforms."""
        # Rebuild NSFW per-platform checkboxes
        while self._nsfw_plat_layout.count():
            item = self._nsfw_plat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._nsfw_checks.clear()

        for pid in platform_ids:
            cb = QCheckBox(f"NSFW: {pid}")
            cb.setObjectName("composer_nsfw_plat_check")
            self._nsfw_checks[pid] = cb
            self._nsfw_plat_layout.addWidget(cb)
        # FlowLayout doesn't support addStretch — skip

        # Update crop status
        self._update_crop_status(platform_ids)

    def get_nsfw_platforms(self) -> list[str]:
        """Return list of platforms marked as NSFW."""
        return [pid for pid, cb in self._nsfw_checks.items() if cb.isChecked()]

    def set_nsfw_platforms(self, platforms: list[str]) -> None:
        """Check the NSFW boxes for given platforms."""
        for pid, cb in self._nsfw_checks.items():
            cb.setChecked(pid in platforms)

    # -- Internal --

    def _update_preview(self) -> None:
        """Show the first asset based on current preview mode."""
        if not self._assets:
            self._preview_label.setText("No image selected")
            self._raw_pm = None
            return

        asset = self._assets[0]

        if self._preview_mode == "studio":
            pm = self._generate_studio_preview()
            if pm and not pm.isNull():
                self._raw_pm = pm
                self._apply_scaled_pixmap()
                return
        elif self._preview_mode == "platform":
            pm = self._generate_platform_preview()
            if pm and not pm.isNull():
                self._raw_pm = pm
                self._apply_scaled_pixmap()
                return

        # Raw mode (default)
        pm = self._load_pixmap(asset)
        if pm and not pm.isNull():
            self._raw_pm = pm
            self._censored_pm = None
            self._showing_censored = False
            self._apply_scaled_pixmap()
        else:
            self._raw_pm = None
            self._preview_label.setText("Cannot load image")

    def _apply_scaled_pixmap(self) -> None:
        """Scale the current pixmap (raw or censored) to fill the preview label.
        Draws crop/note overlays on the scaled result."""
        pm = self._censored_pm if self._showing_censored else self._raw_pm
        if not pm or pm.isNull():
            return
        size = self._preview_label.size()
        if size.width() < 10 or size.height() < 10:
            size = QSize(PREVIEW_SIZE, PREVIEW_SIZE)
        scaled = pm.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Draw crop/note overlays if asset has them
        if self._assets and (self._assets[0].crops or self._assets[0].notes):
            from PySide6.QtGui import QPainter, QPen, QColor, QFont as _QFont
            from PySide6.QtCore import QRectF
            asset = self._assets[0]
            sx = scaled.width() / pm.width() if pm.width() else 1
            sy = scaled.height() / pm.height() if pm.height() else 1
            result = QPixmap(scaled)  # copy
            painter = QPainter(result)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Draw crops
            from doxyedit.themes import THEMES, DEFAULT_THEME
            _dt = THEMES[DEFAULT_THEME]
            _cc = QColor(_dt.crop_border); _cc.setAlpha(_dt.composer_status_active_alpha)
            crop_pen = QPen(_cc, max(1, _dt.crop_border_width - 1))
            for crop in asset.crops:
                r = QRectF(crop.x * sx, crop.y * sy, crop.w * sx, crop.h * sy)
                painter.setPen(crop_pen)
                painter.drawRect(r)
                _lc = QColor(_dt.crop_border); _lc.setAlpha(_dt.composer_status_dim_alpha)
                painter.setPen(_lc)
                font = painter.font()
                font.setPointSize(max(self.MIN_CROP_LABEL_FONT, int(_dt.font_size * self.CROP_LABEL_FONT_RATIO)))
                painter.setFont(font)
                painter.drawText(r.adjusted(3, 2, 0, 0), Qt.AlignmentFlag.AlignTop, crop.label)
            # Draw note markers
            _nc = QColor(_dt.note_border); _nc.setAlpha(_dt.composer_status_hover_alpha)
            note_pen = QPen(_nc, max(1, _dt.crop_border_width - 1))
            import re
            pattern = re.compile(r'\[(\d+),(\d+)\s+(\d+)x(\d+)\]\s*(.*)')
            for line in (asset.notes or "").split("\n"):
                m = pattern.match(line.strip())
                if m:
                    x, y, w, h = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    r = QRectF(x * sx, y * sy, w * sx, h * sy)
                    painter.setPen(note_pen)
                    painter.drawRect(r)
            painter.end()
            scaled = result
        self._preview_label.setPixmap(scaled)

    def _preview_context_menu(self, pos):
        """Right-click menu on the preview thumbnail."""
        if not self._assets:
            return
        asset = self._assets[0]
        menu = QMenu(self)
        menu.addAction("Open in Studio", lambda: self.open_in_studio.emit(asset.id))
        menu.addAction("Open in Preview", lambda: self.open_in_preview.emit(asset.id))
        menu.addSeparator()
        menu.addAction(f"Copy Path", lambda: (
            __import__('PySide6.QtWidgets', fromlist=['QApplication']).QApplication.clipboard().setText(asset.source_path)
        ))
        if asset.notes:
            menu.addSeparator()
            notes_short = asset.notes[:60].replace('\n', ' ')
            note_act = menu.addAction(f"Notes: {notes_short}...")
            note_act.setEnabled(False)
        if asset.crops:
            menu.addSeparator()
            for crop in asset.crops:
                crop_act = menu.addAction(f"Crop: {crop.label} ({crop.w}x{crop.h})")
                crop_act.setEnabled(False)
        menu.exec(self._preview_label.mapToGlobal(pos))

    def resizeEvent(self, event):
        """Re-scale preview when panel is resized."""
        super().resizeEvent(event)
        self._apply_scaled_pixmap()

    def _update_order_strip(self) -> None:
        """Show small numbered thumbnails for multi-image posts."""
        while self._order_strip.count():
            item = self._order_strip.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if len(self._assets) <= 1:
            self._order_container.setVisible(False)
            return

        for i, asset in enumerate(self._assets[:6]):
            pm = self._load_pixmap(asset)
            cell = QLabel()
            if pm and not pm.isNull():
                _order_thumb = int(self._f * self.ORDER_CELL_SIZE_RATIO)
                scaled = pm.scaled(QSize(_order_thumb, _order_thumb),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                cell.setPixmap(scaled)
            else:
                cell.setText("?")
            _cell_size = int(self._f * self.ORDER_CELL_SIZE_RATIO)
            cell.setFixedSize(_cell_size, _cell_size)
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setObjectName("composer_order_thumb")
            cell.setToolTip(f"#{i+1}" + (" (hero)" if i == 0 else ""))
            self._order_strip.addWidget(cell)

        self._order_strip.addStretch()
        self._order_container.setVisible(True)

    def _update_censor_info(self) -> None:
        """Show censor region count for the first asset."""
        if not self._assets:
            self._censor_info.setText("No image selected")
            return
        asset = self._assets[0]
        n = len(asset.censors)
        if n == 0:
            self._censor_info.setText("No censor regions (set in Censor tab)")
        else:
            styles = {}
            for c in asset.censors:
                styles[c.style] = styles.get(c.style, 0) + 1
            parts = [f"{v}x {k}" for k, v in styles.items()]
            self._censor_info.setText(f"{n} censor region{'s' if n != 1 else ''}: {', '.join(parts)}")

    def _update_crop_status(self, platform_ids: list[str]) -> None:
        """Show which platforms have crops set for the first asset."""
        while self._crop_status_layout.count():
            item = self._crop_status_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._assets:
            return

        asset = self._assets[0]
        # Build map of existing assignments
        assigned = {}
        for pa in asset.assignments:
            assigned[(pa.platform, pa.slot)] = pa

        for pid in platform_ids:
            plat = PLATFORMS.get(pid)
            if not plat:
                continue
            # Use the first "post" slot or the first slot
            post_slot = None
            for s in plat.slots:
                if "post" in s.name.lower() or post_slot is None:
                    post_slot = s
            if not post_slot:
                continue

            pa = assigned.get((pid, post_slot.name))
            has_crop = pa and pa.crop and pa.crop.w > 0

            row = QHBoxLayout()
            icon = QLabel("\u2713" if has_crop else "\u25CB")
            icon.setObjectName("composer_crop_icon")
            icon.setFixedWidth(int(self._f * self.CROP_ICON_WIDTH_RATIO))
            row.addWidget(icon)

            label = QLabel(f"{plat.name}: {post_slot.width}x{post_slot.height}")
            label.setObjectName("composer_crop_label")
            row.addWidget(label, 1)

            wrapper = QWidget()
            wrapper.setLayout(row)
            self._crop_status_layout.addWidget(wrapper)

    def _toggle_censored_preview(self, checked: bool) -> None:
        """Toggle between normal and censored preview."""
        if not self._assets:
            return

        if checked:
            self._nsfw_toggle.setText("Show Original")
            asset = self._assets[0]
            if asset.censors:
                if not self._censored_pm:
                    self._censored_pm = self._generate_censored_preview(asset)
                if self._censored_pm:
                    self._showing_censored = True
                    self._apply_scaled_pixmap()
                    return
            self._preview_label.setText("No censor regions to preview")
        else:
            self._nsfw_toggle.setText("Show Censored")
            self._showing_censored = False
            self._apply_scaled_pixmap()

    def _generate_censored_preview(self, asset: Asset) -> QPixmap | None:
        """Apply censors to asset image and return as QPixmap."""
        try:
            from PIL import Image
            from doxyedit.exporter import apply_censors
            from doxyedit.imaging import pil_to_qpixmap

            src = Path(asset.source_path)
            if not src.exists():
                return None

            from doxyedit.imaging import load_image_for_export
            img = load_image_for_export(str(src))

            censored = apply_censors(img, asset.censors)
            return pil_to_qpixmap(censored)
        except Exception:
            return None

    @staticmethod
    def _load_pixmap(asset: Asset) -> QPixmap | None:
        """Load a pixmap from an asset's source file."""
        if not asset.source_path:
            return None
        src = Path(asset.source_path)
        if not src.exists():
            return None
        ext = src.suffix.lower()
        if ext in (".psd", ".psb"):
            try:
                from doxyedit.imaging import load_psd_thumb, pil_to_qpixmap
                result = load_psd_thumb(str(src), min_size=0)
                if result:
                    return pil_to_qpixmap(result[0])
            except Exception:
                pass
            return None
        pm = QPixmap(str(src))
        return pm if not pm.isNull() else None
