# Unified Content Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified asset→platform-ready→post→live pipeline with readiness indicators, coordinate-correct exports, and advisory prep gates.

**Architecture:** New `pipeline.py` module handles the full export chain (load→crop→resize→censor→overlay→save) with coordinate transforms. Readiness checks are computed lazily and displayed in the asset grid + composer. All gates are advisory — user can always bypass.

**Tech Stack:** PySide6 (Qt), PIL/Pillow, existing models/exporter infrastructure.

**Branch:** `feature/unified-pipeline`

**Spec:** `docs/superpowers/specs/2026-04-14-unified-pipeline-design.md`

---

### Task 1: Model Additions (SocialPost censor fields)

**Files:**
- Modify: `doxyedit/models.py` — SocialPost dataclass (~line 405)

- [ ] **Step 1: Add censor_mode and platform_censor fields to SocialPost**

In `doxyedit/models.py`, find the SocialPost dataclass (line ~405) and add after `engagement_checks`:

```python
    censor_mode: str = "auto"  # "auto" | "uncensored" | "custom"
    platform_censor: dict[str, bool] = field(default_factory=dict)  # platform_id -> should_censor
```

- [ ] **Step 2: Update SocialPost.to_dict()**

Find `to_dict()` (line ~437) and add to the return dict:

```python
            "censor_mode": self.censor_mode,
            "platform_censor": self.platform_censor,
```

- [ ] **Step 3: Update SocialPost.from_dict()**

Find `from_dict()` (line ~454) and add to the constructor:

```python
            censor_mode=d.get("censor_mode", "auto"),
            platform_censor=d.get("platform_censor", {}),
```

- [ ] **Step 4: Verify roundtrip**

```bash
python -c "from doxyedit.models import SocialPost; p=SocialPost(censor_mode='custom', platform_censor={'patreon': False}); d=p.to_dict(); p2=SocialPost.from_dict(d); print(p2.censor_mode, p2.platform_censor)"
```

Expected: `custom {'patreon': False}`

- [ ] **Step 5: Commit**

```bash
git add doxyedit/models.py
git commit -m "feat: add censor_mode and platform_censor fields to SocialPost"
```

---

### Task 2: PrepResult Dataclass + Coordinate Transform

**Files:**
- Create: `doxyedit/pipeline.py`

- [ ] **Step 1: Create pipeline.py with PrepResult and coordinate transform**

```python
"""pipeline.py — Unified asset→platform export pipeline.

Handles: load → crop → resize → censor → overlay → save.
Transforms censor/overlay coordinates when images are cropped.
"""
from __future__ import annotations
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from doxyedit.models import (
    Asset, CropRegion, CensorRegion, CanvasOverlay,
    Platform, PlatformSlot, PLATFORMS, Project,
)


@dataclass
class PrepResult:
    """Result of preparing an asset for a specific platform."""
    success: bool = False
    output_path: str = ""
    width: int = 0
    height: int = 0
    platform_id: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def _transform_region(rx: int, ry: int, rw: int, rh: int,
                       crop_box: tuple[int, int, int, int],
                       output_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Transform absolute coords to cropped+resized space.
    
    Args:
        rx, ry, rw, rh: region in original image coords
        crop_box: (cx, cy, cw, ch) crop applied to original
        output_size: (out_w, out_h) final dimensions after resize
    
    Returns:
        (new_x, new_y, new_w, new_h) in output image coords.
        Returns (0,0,0,0) if region is entirely outside crop.
    """
    cx, cy, cw, ch = crop_box
    # Check if region overlaps crop at all
    if rx + rw <= cx or ry + rh <= cy or rx >= cx + cw or ry >= cy + ch:
        return (0, 0, 0, 0)  # entirely outside crop
    
    # Clip to crop bounds
    clipped_x = max(rx, cx) - cx
    clipped_y = max(ry, cy) - cy
    clipped_r = min(rx + rw, cx + cw) - cx
    clipped_b = min(ry + rh, cy + ch) - cy
    
    # Scale to output dimensions
    sx = output_size[0] / cw
    sy = output_size[1] / ch
    return (
        int(clipped_x * sx),
        int(clipped_y * sy),
        int((clipped_r - clipped_x) * sx),
        int((clipped_b - clipped_y) * sy),
    )


def _auto_crop_for_ratio(img_w: int, img_h: int,
                          target_w: int, target_h: int) -> tuple[int, int, int, int]:
    """Compute a center crop box that matches target aspect ratio.
    
    Returns (cx, cy, cw, ch) in source image coords.
    """
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h
    
    if img_ratio > target_ratio:
        # Image is wider — crop sides
        new_w = int(img_h * target_ratio)
        return ((img_w - new_w) // 2, 0, new_w, img_h)
    else:
        # Image is taller — crop top/bottom
        new_h = int(img_w / target_ratio)
        return (0, (img_h - new_h) // 2, img_w, new_h)


def _cache_key(asset: Asset, platform_id: str, slot_name: str,
                censor: bool) -> str:
    """Build a hash key for the export cache based on asset state."""
    parts = [
        asset.source_path,
        platform_id,
        slot_name,
        str(censor),
        str(len(asset.censors)),
        str(len(asset.overlays)),
    ]
    # Include crop/censor/overlay config in hash
    for cr in asset.censors:
        parts.append(f"c{cr.x},{cr.y},{cr.w},{cr.h},{cr.style}")
    for ov in asset.overlays:
        if ov.enabled:
            parts.append(f"o{ov.type},{ov.x},{ov.y},{ov.scale},{ov.opacity}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]
```

- [ ] **Step 2: Verify import**

```bash
python -c "from doxyedit.pipeline import PrepResult, _transform_region, _auto_crop_for_ratio; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/pipeline.py
git commit -m "feat: pipeline.py with PrepResult, coordinate transform, auto-crop"
```

---

### Task 3: prepare_for_platform() Core Function

**Files:**
- Modify: `doxyedit/pipeline.py`

- [ ] **Step 1: Add prepare_for_platform function**

Append to `doxyedit/pipeline.py`:

```python
def prepare_for_platform(
    asset: Asset,
    platform_id: str,
    project: Project,
    *,
    slot_name: str = "",
    censor_override: bool | None = None,
    output_dir: str = "",
) -> PrepResult:
    """Full pipeline: load → crop → resize → censor → overlay → save.
    
    Args:
        asset: The source asset
        platform_id: Key from PLATFORMS dict (e.g. "twitter", "instagram")
        project: Project for overlay paths and default_overlays
        slot_name: Specific slot (e.g. "post", "header"). Empty = first slot
        censor_override: None = use platform default, True/False = force
        output_dir: Where to save. Empty = _exports/{asset_id}/
    """
    from PIL import Image
    from doxyedit.imaging import load_image_for_export
    from doxyedit.exporter import apply_censors, apply_overlays
    
    platform = PLATFORMS.get(platform_id)
    if not platform:
        return PrepResult(error=f"Unknown platform: {platform_id}")
    
    # Pick slot
    slot = None
    if slot_name:
        slot = next((s for s in platform.slots if s.name == slot_name), None)
    if not slot and platform.slots:
        slot = platform.slots[0]
    if not slot:
        return PrepResult(error=f"No slots defined for {platform_id}")
    
    # Load image
    src = Path(asset.source_path)
    if not src.exists():
        return PrepResult(error=f"Source not found: {src}")
    
    try:
        img = load_image_for_export(str(src))
    except Exception as e:
        return PrepResult(error=f"Failed to load: {e}")
    
    warnings = []
    orig_w, orig_h = img.size
    
    # Determine crop box
    # Priority: assignment crop > asset crop matching label > auto-fit
    crop_box = None
    for pa in asset.assignments:
        if pa.platform == platform_id and pa.crop:
            crop_box = (pa.crop.x, pa.crop.y, pa.crop.w, pa.crop.h)
            break
    
    if not crop_box:
        for cr in asset.crops:
            if cr.label and cr.label.lower() == slot.name.lower():
                crop_box = (cr.x, cr.y, cr.w, cr.h)
                break
    
    if not crop_box and slot.width and slot.height:
        crop_box = _auto_crop_for_ratio(orig_w, orig_h, slot.width, slot.height)
        warnings.append(f"Auto-cropped to {slot.width}:{slot.height} ratio")
    
    # Apply crop
    if crop_box:
        cx, cy, cw, ch = crop_box
        img = img.crop((cx, cy, cx + cw, cy + ch))
    else:
        crop_box = (0, 0, orig_w, orig_h)
    
    # Resize to slot dimensions
    target_w, target_h = slot.width, slot.height
    if target_w and target_h and img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    
    output_size = img.size
    
    # Determine censor behavior
    should_censor = platform.needs_censor if censor_override is None else censor_override
    
    # Apply censors with coordinate transform
    if should_censor and asset.censors:
        transformed = []
        for cr in asset.censors:
            nx, ny, nw, nh = _transform_region(
                cr.x, cr.y, cr.w, cr.h, crop_box, output_size)
            if nw > 0 and nh > 0:
                transformed.append(CensorRegion(
                    x=nx, y=ny, w=nw, h=nh, style=cr.style,
                    blur_radius=getattr(cr, 'blur_radius', 20),
                    pixelate_ratio=getattr(cr, 'pixelate_ratio', 10),
                ))
        if transformed:
            img = apply_censors(img, transformed)
    elif should_censor and not asset.censors:
        warnings.append("Platform requires censor but asset has no censor regions")
    
    # Apply overlays with coordinate transform
    if asset.overlays:
        transformed_overlays = []
        for ov in asset.overlays:
            if not ov.enabled:
                continue
            if ov.position == "custom":
                nx, ny, nw, nh = _transform_region(
                    ov.x, ov.y, 1, 1, crop_box, output_size)
                from dataclasses import replace
                ov_copy = replace(ov, x=nx, y=ny)
                transformed_overlays.append(ov_copy)
            else:
                transformed_overlays.append(ov)
        if transformed_overlays:
            project_dir = str(Path(asset.source_path).parent)
            img = apply_overlays(img, transformed_overlays, project_dir)
    
    # Save
    if not output_dir:
        output_dir = str(Path("_exports") / asset.id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    filename = f"{platform_id}_{slot.name}.png"
    out_path = str(Path(output_dir) / filename)
    img.save(out_path, "PNG")
    
    return PrepResult(
        success=True,
        output_path=out_path,
        width=img.size[0],
        height=img.size[1],
        platform_id=platform_id,
        warnings=warnings,
    )
```

- [ ] **Step 2: Verify import**

```bash
python -c "from doxyedit.pipeline import prepare_for_platform; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/pipeline.py
git commit -m "feat: prepare_for_platform() — full export pipeline with coord transform"
```

---

### Task 4: check_readiness() Function

**Files:**
- Modify: `doxyedit/pipeline.py`

- [ ] **Step 1: Add check_readiness function**

Append to `doxyedit/pipeline.py`:

```python
def check_readiness(asset: Asset, platform_id: str, project: Project = None) -> dict:
    """Check if an asset is ready for a specific platform.
    
    Returns dict with:
        status: "green" | "yellow" | "red"
        crop: "ok" | "missing" | "auto_fit"
        censor: "ok" | "not_needed" | "missing"
        overlay: "ok" | "none"
        issues: list of human-readable issue strings
    """
    platform = PLATFORMS.get(platform_id)
    if not platform:
        return {"status": "red", "issues": [f"Unknown platform: {platform_id}"]}
    
    slot = platform.slots[0] if platform.slots else None
    issues = []
    
    # Check source exists
    if not asset.source_path or not Path(asset.source_path).exists():
        return {"status": "red", "issues": ["Source file not found"]}
    
    # Crop check
    has_explicit_crop = False
    for pa in asset.assignments:
        if pa.platform == platform_id and pa.crop:
            has_explicit_crop = True
            break
    if not has_explicit_crop:
        for cr in asset.crops:
            if cr.label and slot and cr.label.lower() == slot.name.lower():
                has_explicit_crop = True
                break
    
    if has_explicit_crop:
        crop_status = "ok"
    elif slot and slot.width and slot.height:
        crop_status = "auto_fit"
        issues.append(f"No crop defined — will auto-fit to {slot.width}x{slot.height}")
    else:
        crop_status = "ok"  # platform has no size requirement
    
    # Censor check
    if platform.needs_censor:
        if asset.censors:
            censor_status = "ok"
        else:
            censor_status = "missing"
            issues.append(f"{platform.name} requires censor but asset has none")
    else:
        censor_status = "not_needed"
    
    # Overlay check
    has_overlays = any(ov.enabled for ov in asset.overlays)
    has_project_overlays = bool(project and project.default_overlays)
    if has_overlays:
        overlay_status = "ok"
    elif has_project_overlays:
        overlay_status = "none"
        issues.append("No watermark — project has default overlays available")
    else:
        overlay_status = "ok"  # no overlays configured, that's fine
    
    # Overall status
    if censor_status == "missing":
        status = "red"
    elif crop_status == "auto_fit" or overlay_status == "none":
        status = "yellow"
    else:
        status = "green"
    
    return {
        "status": status,
        "crop": crop_status,
        "censor": censor_status,
        "overlay": overlay_status,
        "issues": issues,
    }
```

- [ ] **Step 2: Verify**

```bash
python -c "from doxyedit.pipeline import check_readiness; from doxyedit.models import Asset; a=Asset(source_path='test.png'); r=check_readiness(a, 'twitter'); print(r['status'], r['crop'])"
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/pipeline.py
git commit -m "feat: check_readiness() — per-asset per-platform readiness scoring"
```

---

### Task 5: Composer Prep Strip UI

**Files:**
- Modify: `doxyedit/composer_left.py` (~line 23, ImagePreviewPanel class)

- [ ] **Step 1: Add PrepStrip widget to composer_left.py**

Add after the existing NSFW section (after line ~123). The prep strip shows one row per checked platform with a readiness dot + preview + fix button:

```python
        # -- Platform Prep Strip (below NSFW section) --
        self._prep_strip = QWidget()
        self._prep_strip.setObjectName("composer_prep_strip")
        self._prep_strip_layout = QVBoxLayout(self._prep_strip)
        self._prep_strip_layout.setContentsMargins(4, 4, 4, 4)
        self._prep_strip_layout.setSpacing(2)
        self._prep_strip.setVisible(False)
        layout.addWidget(self._prep_strip)
```

Add the rebuild method:

```python
    def rebuild_prep_strip(self, asset_ids: list[str], platform_ids: list[str],
                            project: "Project") -> None:
        """Rebuild the prep strip showing readiness per platform."""
        # Clear existing rows
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
        
        header = QLabel(f"Platform Prep ({len(platform_ids)} platforms)")
        header.setObjectName("composer_prep_header")
        self._prep_strip_layout.addWidget(header)
        
        all_green = True
        for pid in platform_ids:
            platform = PLATFORMS.get(pid)
            if not platform:
                continue
            
            readiness = check_readiness(asset, pid, project)
            status = readiness["status"]
            if status != "green":
                all_green = False
            
            row = QHBoxLayout()
            row.setSpacing(6)
            
            # Status dot
            dot_colors = {"green": "#6eaa78", "yellow": "#be955c", "red": "#9a4f50"}
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {dot_colors.get(status, '#888')};")
            dot.setFixedWidth(16)
            row.addWidget(dot)
            
            # Platform name
            name = platform.name if platform else pid
            lbl = QLabel(name)
            row.addWidget(lbl, 1)
            
            # Issues
            issues = readiness.get("issues", [])
            if issues:
                issue_lbl = QLabel(issues[0])
                issue_lbl.setObjectName("composer_prep_issue")
                row.addWidget(issue_lbl)
                
                fix_btn = QPushButton("Fix")
                fix_btn.setFixedWidth(36)
                fix_btn.setObjectName("composer_prep_fix_btn")
                row.addWidget(fix_btn)
            else:
                ok_lbl = QLabel("Ready")
                ok_lbl.setObjectName("composer_prep_ok")
                row.addWidget(ok_lbl)
            
            self._prep_strip_layout.addWidget(self._make_row_widget(row))
        
        self._prep_strip.setVisible(True)
    
    def _make_row_widget(self, layout):
        w = QWidget()
        w.setLayout(layout)
        return w
```

- [ ] **Step 2: Verify import**

```bash
python -c "from doxyedit.composer_left import ImagePreviewPanel; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add doxyedit/composer_left.py
git commit -m "feat: prep strip UI in composer — per-platform readiness with fix buttons"
```

---

### Task 6: Wire Prep Strip to Composer + Advisory Queue Gate

**Files:**
- Modify: `doxyedit/composer.py` (~line 357, _save method)

- [ ] **Step 1: Add advisory warning before queuing**

In `composer.py`, modify the `_save()` method. Before `self.save_requested.emit(result_post)`, add:

```python
        # Advisory readiness check before queuing
        if status == SocialPostStatus.QUEUED and asset_ids:
            from doxyedit.pipeline import check_readiness
            from doxyedit.models import PLATFORMS
            issues = []
            for aid in asset_ids[:1]:  # check first asset
                asset = self._project.get_asset(aid)
                if not asset:
                    continue
                for pid in data["platforms"]:
                    if pid not in PLATFORMS:
                        continue
                    r = check_readiness(asset, pid, self._project)
                    if r["status"] == "red":
                        issues.extend(r["issues"])
            
            if issues:
                from PySide6.QtWidgets import QMessageBox
                msg = "Some platforms need prep:\n\n" + "\n".join(f"• {i}" for i in issues[:5])
                msg += "\n\nPost anyway?"
                reply = QMessageBox.question(
                    self, "Platform Prep",
                    msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
```

- [ ] **Step 2: Wire prep strip rebuild to platform toggle**

In `composer.py` `_build_ui()`, after wiring `platforms_changed`:

```python
        self._right_panel.platforms_changed.connect(self._update_prep_strip)
```

Add the handler:

```python
    def _update_prep_strip(self, platforms: list[str]) -> None:
        """Rebuild prep strip when platforms change."""
        ids = [s.strip() for s in self._images_edit.text().split(",") if s.strip()]
        self._left_panel.rebuild_prep_strip(ids, platforms, self._project)
```

- [ ] **Step 3: Verify import**

```bash
python -c "from doxyedit.composer import PostComposerWidget; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add doxyedit/composer.py
git commit -m "feat: advisory queue gate + prep strip wiring in composer"
```

---

### Task 7: Export-on-Queue

**Files:**
- Modify: `doxyedit/window.py` — `_push_post_to_oneup` and `_on_docked_save`

- [ ] **Step 1: Add _export_post_assets helper to window.py**

Add near `_push_post_to_oneup`:

```python
    def _export_post_assets(self, post):
        """Export platform-ready images for all platforms in a post."""
        from doxyedit.pipeline import prepare_for_platform
        from doxyedit.models import PLATFORMS
        
        if not post.asset_ids:
            return {}
        
        exports = {}  # platform_id -> output_path
        project_dir = str(Path(self._project_path).parent) if self._project_path else "."
        output_base = str(Path(project_dir) / "_exports" / post.id[:8])
        
        for aid in post.asset_ids[:1]:
            asset = self.project.get_asset(aid)
            if not asset:
                continue
            for pid in post.platforms:
                if pid not in PLATFORMS:
                    continue
                
                # Determine censor behavior from post
                censor_override = None
                if post.censor_mode == "uncensored":
                    censor_override = False
                elif post.censor_mode == "custom":
                    censor_override = post.platform_censor.get(pid)
                
                result = prepare_for_platform(
                    asset, pid, self.project,
                    censor_override=censor_override,
                    output_dir=output_base,
                )
                if result.success:
                    exports[pid] = result.output_path
                    print(f"[Export] {pid}: {result.width}x{result.height} → {result.output_path}")
                    for w in result.warnings:
                        print(f"[Export]   ⚠ {w}")
                else:
                    print(f"[Export] {pid}: FAILED — {result.error}")
        
        return exports
```

- [ ] **Step 2: Call export before pushing in sync flow**

In `_on_sync_oneup`, before the OneUp push loop, add:

```python
                    # Export platform-ready images before pushing
                    self._export_post_assets(post)
```

- [ ] **Step 3: Verify**

```bash
python -c "from doxyedit.window import MainWindow; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add doxyedit/window.py
git commit -m "feat: export-on-queue — prepare platform images before pushing"
```

---

### Task 8: Censor Mode UI in Composer

**Files:**
- Modify: `doxyedit/composer_right.py` — platforms section

- [ ] **Step 1: Add censor mode radio buttons after subscription checkboxes**

In `_build_ui()`, after the subscription platform section (after `platforms_layout.addWidget(sub_container)`), add:

```python
        # Censor mode
        from PySide6.QtWidgets import QRadioButton, QButtonGroup
        censor_label = QLabel("Censor Mode:")
        censor_label.setObjectName("composer_censor_mode_label")
        platforms_layout.addWidget(censor_label)
        
        self._censor_group = QButtonGroup(self)
        self._censor_auto = QRadioButton("Auto (platform default)")
        self._censor_uncensored = QRadioButton("Uncensored everywhere")
        self._censor_custom = QRadioButton("Custom per-platform")
        self._censor_auto.setChecked(True)
        self._censor_group.addButton(self._censor_auto, 0)
        self._censor_group.addButton(self._censor_uncensored, 1)
        self._censor_group.addButton(self._censor_custom, 2)
        platforms_layout.addWidget(self._censor_auto)
        platforms_layout.addWidget(self._censor_uncensored)
        platforms_layout.addWidget(self._censor_custom)
```

- [ ] **Step 2: Include censor_mode in get_post_data()**

In `get_post_data()`, add:

```python
        censor_mode = "auto"
        if self._censor_uncensored.isChecked():
            censor_mode = "uncensored"
        elif self._censor_custom.isChecked():
            censor_mode = "custom"
```

And add to the return dict:

```python
            "censor_mode": censor_mode,
```

- [ ] **Step 3: Restore censor mode in set_post()**

In `set_post()`, add:

```python
        if hasattr(post, 'censor_mode'):
            if post.censor_mode == "uncensored":
                self._censor_uncensored.setChecked(True)
            elif post.censor_mode == "custom":
                self._censor_custom.setChecked(True)
            else:
                self._censor_auto.setChecked(True)
```

- [ ] **Step 4: Wire to composer save**

In `composer.py` `_save()`, add after other field assignments:

```python
            p.censor_mode = data.get("censor_mode", "auto")
```

And in the new SocialPost constructor:

```python
                censor_mode=data.get("censor_mode", "auto"),
```

- [ ] **Step 5: Verify**

```bash
python -c "from doxyedit.composer_right import ContentPanel; print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add doxyedit/composer_right.py doxyedit/composer.py
git commit -m "feat: censor mode UI — auto/uncensored/custom radio buttons"
```

---

### Task 9: Entry Points (Right-click + Studio Queue)

**Files:**
- Modify: `doxyedit/browser.py` — right-click menu
- Modify: `doxyedit/studio.py` — toolbar
- Modify: `doxyedit/window.py` — handlers

- [ ] **Step 1: Add "Prepare for Posting" to browser right-click**

In `browser.py`, find the right-click menu (search for `"Send to Studio"`), add below it:

```python
        menu.addAction("Prepare for Posting...", lambda: self.asset_to_post.emit(asset_id))
```

Add the signal to the browser class:

```python
    asset_to_post = Signal(str)  # emits asset_id
```

- [ ] **Step 2: Add "Queue This" button to Studio toolbar**

In `studio.py`, find the toolbar section and add:

```python
        btn_queue = QPushButton("Queue This")
        btn_queue.setObjectName("studio_queue_btn")
        btn_queue.clicked.connect(self._queue_current)
        toolbar.addWidget(btn_queue)
```

Add the signal and handler:

```python
    queue_requested = Signal(str)  # emits asset_id
    
    def _queue_current(self):
        if self._asset:
            self.queue_requested.emit(self._asset.id)
```

- [ ] **Step 3: Wire in window.py**

In `window.py`, after wiring `asset_to_canvas`:

```python
        self.browser.asset_to_post.connect(self._prepare_for_posting)
        self.studio.queue_requested.connect(self._prepare_for_posting)
```

Add handler:

```python
    def _prepare_for_posting(self, asset_id: str):
        """Open composer with asset pre-loaded for posting."""
        asset = self.project.get_asset(asset_id)
        if not asset:
            return
        from doxyedit.models import SocialPost
        post = SocialPost(asset_ids=[asset_id])
        self._float_composer_dialog(post=post, is_new=True)
```

- [ ] **Step 4: Verify**

```bash
python -c "from doxyedit.window import MainWindow; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add doxyedit/browser.py doxyedit/studio.py doxyedit/window.py
git commit -m "feat: entry points — right-click Prepare for Posting + Studio Queue This"
```

---

### Task 10: Asset Grid Readiness Dots

**Files:**
- Modify: `doxyedit/browser.py` — ThumbnailModel + delegate paint

- [ ] **Step 1: Add ReadinessRole to ThumbnailModel**

After `StudioEditedRole`:

```python
    ReadinessRole = Qt.ItemDataRole.UserRole + 9  # dict[str, str] platform_id -> "green"|"yellow"|"red"
```

In `data()`, add:

```python
        elif role == self.ReadinessRole:
            return self._readiness_cache.get(asset.id)
```

Add cache:

```python
    def __init__(self, parent=None):
        super().__init__(parent)
        ...
        self._readiness_cache: dict[str, dict] = {}
    
    def update_readiness(self, project, default_platforms: list[str]):
        """Compute readiness for visible assets (call lazily)."""
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
            self._readiness_cache[asset.id] = readiness
    
    def invalidate_readiness(self, asset_id: str = ""):
        if asset_id:
            self._readiness_cache.pop(asset_id, None)
        else:
            self._readiness_cache.clear()
```

- [ ] **Step 2: Paint readiness dots in delegate**

In the `paint()` method, after the studio-edited badge block, before "# Dimensions text":

```python
        # Readiness dots (below thumbnail, above tag dots)
        readiness = index.data(ThumbnailModel.ReadinessRole)
        if readiness and self._theme:
            _r_colors = {"green": "#6eaa78", "yellow": "#be955c", "red": "#9a4f50"}
            r_y = rect.y() + self.PADDING + ts + 1
            r_x = rect.x() + self.PADDING + 2
            for pid, status in readiness.items():
                c = QColor(_r_colors.get(status, "#888"))
                painter.setBrush(c)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPoint(r_x + 3, r_y + 3), 3, 3)
                r_x += 9
```

- [ ] **Step 3: Verify**

```bash
python -c "from doxyedit.browser import ThumbnailModel; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add doxyedit/browser.py
git commit -m "feat: readiness dots on asset grid thumbnails"
```

---

### Task 11: Final Integration + Verify

**Files:**
- All previously modified files

- [ ] **Step 1: Full import check**

```bash
python -c "
from doxyedit.pipeline import prepare_for_platform, check_readiness, PrepResult
from doxyedit.models import SocialPost, Asset, PLATFORMS
from doxyedit.composer import PostComposerWidget
from doxyedit.composer_left import ImagePreviewPanel
from doxyedit.composer_right import ContentPanel
from doxyedit.browser import ThumbnailModel
from doxyedit.studio import StudioEditor
from doxyedit.window import MainWindow
print('ALL IMPORTS OK')
"
```

- [ ] **Step 2: Test pipeline with mock data**

```bash
python -c "
from doxyedit.pipeline import check_readiness, _auto_crop_for_ratio, _transform_region
from doxyedit.models import Asset, CensorRegion

# Test auto-crop
crop = _auto_crop_for_ratio(2000, 1000, 1200, 675)
print(f'Auto-crop 2000x1000 -> 16:9: {crop}')

# Test coordinate transform
nx, ny, nw, nh = _transform_region(500, 200, 100, 100, (0, 0, 2000, 1000), (1200, 675))
print(f'Transform (500,200,100,100) with full crop: ({nx},{ny},{nw},{nh})')

# Test readiness
a = Asset(source_path='nonexistent.png')
r = check_readiness(a, 'twitter')
print(f'Readiness (missing file): {r[\"status\"]}')
print('ALL TESTS OK')
"
```

- [ ] **Step 3: Commit and tag**

```bash
git add -A
git commit -m "feat: unified content pipeline — complete implementation

- pipeline.py: prepare_for_platform() with coordinate transform
- check_readiness() with green/yellow/red scoring
- Composer prep strip with per-platform readiness
- Advisory queue gate (warns but doesn't block)
- Export-on-queue (caches to _exports/)
- Censor mode UI (auto/uncensored/custom)
- Entry points: right-click, Studio Queue This
- Asset grid readiness dots"
```
