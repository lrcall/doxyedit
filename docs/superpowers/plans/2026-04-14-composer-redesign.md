# Composer Two-Column Redesign + SFW/NSFW + Platform Crops

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the PostComposer dialog as a two-column layout with left-side image preview, SFW/NSFW censored variants tied to the Censor tab, per-platform crop status from the Platforms tab, and a cleaner right-side content area.

**Architecture:** Split the 1000-line `composer.py` into focused modules. Left column handles visual pipeline (image preview, SFW/NSFW toggle, platform crop status). Right column handles content pipeline (strategy, captions, schedule, links). The SocialPost model gains `nsfw_platforms` and `sfw_asset_ids` fields to track which platforms get censored versions.

**Tech Stack:** PySide6 (QSplitter, QStackedWidget, QGraphicsView), PIL/Pillow for censored preview generation, existing `exporter.apply_censors()` for preview rendering.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `doxyedit/composer.py` | Modify (slim down) | Top-level PostComposer dialog, two-column splitter, save/load, button bar |
| `doxyedit/composer_left.py` | Create | Left column: ImagePreviewPanel (large preview, SFW/NSFW, crop status) |
| `doxyedit/composer_right.py` | Create | Right column: StrategyPanel + ContentPanel (caption, schedule, links, replies) |
| `doxyedit/models.py` | Modify | Add `nsfw_platforms`, `sfw_asset_ids` to SocialPost |
| `doxyedit/themes.py` | Modify | Add QSS selectors for new objectNames |
| `doxyedit/exporter.py` | Read only | Use `apply_censors()` for preview generation |

---

### Task 1: Add SFW/NSFW fields to SocialPost model

**Files:**
- Modify: `doxyedit/models.py:200-245`

- [ ] **Step 1: Add fields to SocialPost**

Add two new fields after `strategy_notes`:

```python
# In SocialPost dataclass, after strategy_notes:
    nsfw_platforms: list[str] = field(default_factory=list)  # platforms that get NSFW version
    sfw_asset_ids: list[str] = field(default_factory=list)   # alternate censored asset IDs (or empty = auto-censor)
```

- [ ] **Step 2: Update to_dict()**

Add to the return dict:
```python
"nsfw_platforms": self.nsfw_platforms,
"sfw_asset_ids": self.sfw_asset_ids,
```

- [ ] **Step 3: Update from_dict()**

Add to the constructor:
```python
nsfw_platforms=d.get("nsfw_platforms", []),
sfw_asset_ids=d.get("sfw_asset_ids", []),
```

- [ ] **Step 4: Verify import**

Run: `python -c "from doxyedit.models import SocialPost; p = SocialPost(nsfw_platforms=['twitter']); print(p.to_dict()['nsfw_platforms'])"`
Expected: `['twitter']`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/models.py
git commit -m "feat: add nsfw_platforms and sfw_asset_ids to SocialPost model"
```

---

### Task 2: Create ImagePreviewPanel (left column)

**Files:**
- Create: `doxyedit/composer_left.py`

- [ ] **Step 1: Create the left column widget**

```python
"""composer_left.py -- Left column of the post composer.

Shows large image preview, SFW/NSFW toggle with censored preview,
and per-platform crop status.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QCheckBox, QSizePolicy, QScrollArea,
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap

from doxyedit.models import Project, SocialPost, Asset, PLATFORMS


PREVIEW_SIZE = 300


class ImagePreviewPanel(QWidget):
    """Left column: image preview + SFW/NSFW + crop status."""

    assets_changed = Signal()  # emitted when SFW toggle changes

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.setObjectName("composer_preview_panel")
        self._project = project
        self._assets: list[Asset] = []
        self._censored_pm: QPixmap | None = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # -- Large image preview --
        self._preview_label = QLabel()
        self._preview_label.setObjectName("composer_main_preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._preview_label, 1)

        # -- Image order strip (for multi-image posts) --
        self._order_strip = QHBoxLayout()
        self._order_strip.setSpacing(4)
        self._order_container = QWidget()
        self._order_container.setLayout(self._order_strip)
        self._order_container.setVisible(False)
        layout.addWidget(self._order_container)

        # -- SFW / NSFW section --
        nsfw_frame = QFrame()
        nsfw_frame.setObjectName("composer_nsfw_frame")
        nsfw_layout = QVBoxLayout(nsfw_frame)
        nsfw_layout.setContentsMargins(6, 6, 6, 6)
        nsfw_layout.setSpacing(4)

        nsfw_header = QHBoxLayout()
        nsfw_lbl = QLabel("Content Rating")
        nsfw_lbl.setObjectName("composer_section_header")
        nsfw_header.addWidget(nsfw_lbl)
        nsfw_header.addStretch()

        self._nsfw_toggle = QPushButton("Show Censored")
        self._nsfw_toggle.setObjectName("composer_nsfw_toggle")
        self._nsfw_toggle.setCheckable(True)
        self._nsfw_toggle.clicked.connect(self._toggle_censored_preview)
        nsfw_header.addWidget(self._nsfw_toggle)
        nsfw_layout.addLayout(nsfw_header)

        self._censor_info = QLabel("No censor regions defined")
        self._censor_info.setObjectName("composer_censor_info")
        nsfw_layout.addWidget(self._censor_info)

        # Per-platform NSFW checkboxes (populated by set_platforms)
        self._nsfw_checks: dict[str, QCheckBox] = {}
        self._nsfw_platform_container = QWidget()
        self._nsfw_plat_layout = QHBoxLayout(self._nsfw_platform_container)
        self._nsfw_plat_layout.setContentsMargins(0, 0, 0, 0)
        self._nsfw_plat_layout.setSpacing(6)
        nsfw_layout.addWidget(self._nsfw_platform_container)

        layout.addWidget(nsfw_frame)

        # -- Platform crop status --
        crop_frame = QFrame()
        crop_frame.setObjectName("composer_crop_frame")
        crop_layout = QVBoxLayout(crop_frame)
        crop_layout.setContentsMargins(6, 6, 6, 6)
        crop_layout.setSpacing(2)

        crop_header = QLabel("Platform Crops")
        crop_header.setObjectName("composer_section_header")
        crop_layout.addWidget(crop_header)

        self._crop_status_layout = QVBoxLayout()
        self._crop_status_layout.setSpacing(2)
        crop_layout.addLayout(self._crop_status_layout)

        layout.addWidget(crop_frame)

    # -- Public API --

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
        self._nsfw_plat_layout.addStretch()

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
        """Show the first asset as a large preview."""
        if not self._assets:
            self._preview_label.setText("No image selected")
            return

        asset = self._assets[0]
        pm = self._load_pixmap(asset)
        if pm and not pm.isNull():
            scaled = pm.scaled(
                self._preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview_label.setPixmap(scaled)
            self._censored_pm = None  # invalidate censored cache
        else:
            self._preview_label.setText("Cannot load image")

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
                scaled = pm.scaled(QSize(48, 48),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                cell.setPixmap(scaled)
            else:
                cell.setText("?")
            cell.setFixedSize(48, 48)
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
            icon = QLabel("✓" if has_crop else "○")
            icon.setObjectName("composer_crop_icon")
            icon.setFixedWidth(16)
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
                    scaled = self._censored_pm.scaled(
                        self._preview_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                    self._preview_label.setPixmap(scaled)
                    return
            self._preview_label.setText("No censor regions to preview")
        else:
            self._nsfw_toggle.setText("Show Censored")
            self._update_preview()

    def _generate_censored_preview(self, asset: Asset) -> QPixmap | None:
        """Apply censors to asset image and return as QPixmap."""
        try:
            from PIL import Image
            from doxyedit.exporter import apply_censors
            from doxyedit.imaging import pil_to_qpixmap

            src = Path(asset.source_path)
            if not src.exists():
                return None

            ext = src.suffix.lower()
            if ext in (".psd", ".psb"):
                from doxyedit.imaging import load_psd
                img, _, _ = load_psd(str(src))
            else:
                img = Image.open(str(src)).convert("RGBA")

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
```

- [ ] **Step 2: Verify import**

Run: `python -c "from doxyedit.composer_left import ImagePreviewPanel; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/composer_left.py
git commit -m "feat: ImagePreviewPanel — left column with SFW/NSFW and crop status"
```

---

### Task 3: Extract strategy + content into right column module

**Files:**
- Create: `doxyedit/composer_right.py`

This extracts the FlowLayout, strategy panel, and content fields from composer.py into a standalone right-column widget. The strategy generation methods (local, AI, apply) stay in this module.

- [ ] **Step 1: Create composer_right.py**

Move these from `composer.py` into a new `ContentPanel(QWidget)`:
- `_FlowLayout` class (the flow layout for platform checkboxes)
- Platform checkboxes (flow layout)
- Strategy notes section (generate, AI, apply, edit buttons + stacked browser/editor)
- Caption section (default + per-platform)
- Links, Schedule, Reply Templates
- All strategy generation methods (`_generate_local_strategy`, `_generate_ai_strategy`, `_on_ai_strategy_done`, `_apply_strategy`, `_on_apply_done`, `_build_temp_post`, etc.)
- All strategy caching (`_local_strategy_cache`, `_ai_strategy_cache`, `_strategy_raw`)

Signals exposed: `save_requested(str)` (status), `cancel_requested()`

Public API:
- `set_post(post: SocialPost | None)` — prefill from existing post
- `get_post_data() -> dict` — return all field values as a dict
- `set_platforms(connected: list[dict])` — populate platform checkboxes
- `set_nsfw_platforms(platforms: list[str])` — used by left panel to update

Note: This is a large extraction (500+ lines). The key architectural point is that `composer.py` becomes a thin shell that creates the two-column splitter, wires signals between left and right, and handles save/close.

- [ ] **Step 2: Verify import**

Run: `python -c "from doxyedit.composer_right import ContentPanel; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/composer_right.py
git commit -m "feat: ContentPanel — right column with strategy, captions, schedule"
```

---

### Task 4: Rebuild composer.py as two-column shell

**Files:**
- Modify: `doxyedit/composer.py` (major rewrite, ~200 lines target)

- [ ] **Step 1: Rewrite _build_ui as two-column layout**

The new composer structure:

```python
def _build_ui(self, post):
    root = QVBoxLayout(self)
    root.setSpacing(4)
    root.setContentsMargins(8, 8, 8, 8)

    # --- Asset ID input row (spans full width) ---
    images_row = QHBoxLayout()
    self._images_edit = AssetDropLineEdit(self._project)
    # ... (same as before)
    root.addLayout(images_row)

    # --- Two-column splitter ---
    self._main_split = QSplitter(Qt.Orientation.Horizontal)

    # Left: image preview + SFW/NSFW + crop status
    self._left_panel = ImagePreviewPanel(self._project)
    self._main_split.addWidget(self._left_panel)

    # Right: strategy + content
    self._right_panel = ContentPanel(self._project)
    self._main_split.addWidget(self._right_panel)

    self._main_split.setSizes([350, 550])
    self._main_split.setStretchFactor(0, 0)
    self._main_split.setStretchFactor(1, 1)

    # Restore saved splitter
    saved = self._settings.value("composer_main_split", None)
    if saved:
        self._main_split.setSizes([int(s) for s in saved])

    root.addWidget(self._main_split, 1)

    # --- Button bar (spans full width) ---
    btn_layout = QHBoxLayout()
    # Save Draft, Queue, Cancel
    root.addLayout(btn_layout)
```

- [ ] **Step 2: Wire signals between panels**

```python
# When asset IDs change, update left panel preview
self._images_edit.textChanged.connect(self._on_assets_changed)

# When left panel NSFW toggles change, notify right panel
self._left_panel.assets_changed.connect(self._sync_nsfw)

# When right panel platform checkboxes change, update left panel
self._right_panel.platforms_changed.connect(self._on_platforms_changed)
```

- [ ] **Step 3: Wire save to collect from both panels**

```python
def _save(self, status):
    data = self._right_panel.get_post_data()
    data["asset_ids"] = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
    data["nsfw_platforms"] = self._left_panel.get_nsfw_platforms()
    data["status"] = status
    # Build SocialPost from data dict...
```

- [ ] **Step 4: Verify import and basic functionality**

Run: `python -c "from doxyedit.composer import PostComposer; print('OK')"`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/composer.py
git commit -m "feat: two-column composer — image/SFW left, strategy/content right"
```

---

### Task 5: Add theme tokens for new panels

**Files:**
- Modify: `doxyedit/themes.py`

- [ ] **Step 1: Add QSS selectors**

Add after the existing composer section:

```python
/* -- Composer left panel -- */
QWidget#composer_preview_panel {{
    background: {theme.bg_main};
}}
QLabel#composer_main_preview {{
    background: {theme.bg_deep};
    border: 1px solid {theme.border};
    border-radius: {rad}px;
}}
QLabel#composer_section_header {{
    color: {theme.text_primary};
    font-weight: bold;
    font-size: {fs}px;
}}
QFrame#composer_nsfw_frame,
QFrame#composer_crop_frame {{
    background: {theme.bg_raised};
    border: 1px solid {theme.border};
    border-radius: {rad}px;
}}
QPushButton#composer_nsfw_toggle {{
    background: {theme.bg_input};
    color: {theme.text_primary};
    border: 1px solid {theme.border};
    border-radius: {rad}px;
    padding: {pad}px {pad_lg}px;
}}
QPushButton#composer_nsfw_toggle:checked {{
    background: {theme.warning};
    color: {theme.text_on_accent};
    border-color: {theme.warning};
}}
QLabel#composer_censor_info {{
    color: {theme.text_secondary};
    font-size: {fs}px;
}}
QLabel#composer_crop_icon {{
    font-size: {fl}px;
}}
QLabel#composer_crop_label {{
    color: {theme.text_secondary};
    font-size: {fs}px;
}}
QLabel#composer_order_thumb {{
    background: {theme.bg_input};
    border: 1px solid {theme.border};
    border-radius: {rad}px;
}}
```

- [ ] **Step 2: Verify**

Run: `python -c "from doxyedit.themes import generate_stylesheet, BONE; generate_stylesheet(BONE); print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add doxyedit/themes.py
git commit -m "feat: theme tokens for composer left panel — preview, NSFW, crop status"
```

---

### Task 6: Wire left panel to censor tab data

**Files:**
- Modify: `doxyedit/window.py` (where composer is opened)

- [ ] **Step 1: Pass censor data through to composer**

When opening the composer, the left panel already reads `asset.censors` from the project model. But we need to make sure that if the user edits censors in the Censor tab and then opens the composer, the latest censors are reflected.

The censor editor's `_sync_to_asset()` writes directly to the Asset object in memory. Since the composer reads from the same Project instance, censors are already in sync. No additional wiring needed — this is a verification step.

- [ ] **Step 2: Verify censor → composer flow**

Manual test:
1. Select an asset in the Assets tab
2. Go to Censor tab, add a censor region, save
3. Open the composer for a post with that asset
4. Left panel should show "1 censor region: 1x black"
5. Click "Show Censored" — should show the censored preview

- [ ] **Step 3: Commit (if any changes needed)**

```bash
git commit -m "verify: censor tab data flows through to composer left panel"
```

---

### Task 7: Integration test and cleanup

**Files:**
- All modified files

- [ ] **Step 1: Full import test**

```bash
python -c "
from doxyedit.window import MainWindow
from doxyedit.composer import PostComposer
from doxyedit.composer_left import ImagePreviewPanel
from doxyedit.composer_right import ContentPanel
print('All OK')
"
```

- [ ] **Step 2: Manual UI test checklist**

- [ ] Open new post — two columns visible, left shows "No image selected"
- [ ] Select an asset, type ID in images field — left panel shows preview
- [ ] Check platforms — left panel shows crop status per platform
- [ ] Generate local strategy — right panel shows rendered markdown
- [ ] Generate AI strategy — right panel shows Claude response
- [ ] Toggle "Show Censored" — left panel shows censored version (if asset has censors)
- [ ] Check NSFW per-platform — checkboxes work
- [ ] Save draft — all fields persist
- [ ] Reopen saved post — all fields restored including strategy and NSFW selections
- [ ] Resize left/right splitter — persists after close/reopen
- [ ] Test on Bone and Soot themes — all elements themed correctly

- [ ] **Step 3: Final commit and push**

```bash
git add -A
git commit -m "feat: two-column composer with SFW/NSFW toggle and platform crop status"
git push
```
