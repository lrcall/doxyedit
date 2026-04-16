"""Unified export pipeline — load, crop, resize, censor, overlay, save."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from PIL import Image

from doxyedit.models import (
    Asset, CropRegion, CensorRegion, CanvasOverlay,
    Platform, PlatformSlot, PLATFORMS, Project,
)
from doxyedit.imaging import load_image_for_export
from doxyedit.exporter import apply_censors, apply_overlays


# ---------------------------------------------------------------------------
# PrepResult
# ---------------------------------------------------------------------------

@dataclass
class PrepResult:
    """Result of preparing an asset for a specific platform slot."""
    success: bool = False
    output_path: str = ""
    width: int = 0
    height: int = 0
    platform_id: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Coordinate transform helpers
# ---------------------------------------------------------------------------

def _transform_region(
    rx: int, ry: int, rw: int, rh: int,
    crop_box: tuple[int, int, int, int],
    output_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Transform absolute pixel coords into cropped+resized space.

    Args:
        rx, ry, rw, rh: region in original image coordinates
        crop_box: (cx, cy, cw, ch) crop applied to original image
        output_size: (out_w, out_h) final resized dimensions

    Returns:
        (x, y, w, h) in output space, or (0, 0, 0, 0) if entirely outside crop.
    """
    cx, cy, cw, ch = crop_box
    out_w, out_h = output_size

    # Clip region to crop bounds
    x1 = max(rx, cx)
    y1 = max(ry, cy)
    x2 = min(rx + rw, cx + cw)
    y2 = min(ry + rh, cy + ch)

    if x2 <= x1 or y2 <= y1:
        return (0, 0, 0, 0)

    # Shift to crop-relative coordinates
    rel_x = x1 - cx
    rel_y = y1 - cy
    rel_w = x2 - x1
    rel_h = y2 - y1

    # Scale to output dimensions
    sx = out_w / cw
    sy = out_h / ch

    return (
        int(rel_x * sx),
        int(rel_y * sy),
        max(1, int(rel_w * sx)),
        max(1, int(rel_h * sy)),
    )


def _auto_crop_for_ratio(
    img_w: int, img_h: int,
    target_w: int, target_h: int,
) -> tuple[int, int, int, int]:
    """Compute a center crop box matching the target aspect ratio.

    Returns:
        (cx, cy, cw, ch) — crop box in original image coordinates.
    """
    target_ratio = target_w / target_h
    img_ratio = img_w / img_h if img_h > 0 else 1.0

    if img_ratio > target_ratio:
        # Image is wider than target — crop sides
        cw = int(img_h * target_ratio)
        ch = img_h
    else:
        # Image is taller than target — crop top/bottom
        cw = img_w
        ch = int(img_w / target_ratio)

    cx = (img_w - cw) // 2
    cy = (img_h - ch) // 2

    return (cx, cy, cw, ch)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def _cache_key(
    asset: Asset,
    platform_id: str,
    slot_name: str,
    censor: bool,
) -> str:
    """Build an MD5 hash key from asset state for export caching."""
    parts = [
        asset.id,
        asset.source_path,
        platform_id,
        slot_name,
        str(censor),
        json.dumps([{"x": c.x, "y": c.y, "w": c.w, "h": c.h, "label": c.label}
                     for c in asset.crops], sort_keys=True),
        json.dumps([{"x": c.x, "y": c.y, "w": c.w, "h": c.h, "style": c.style}
                     for c in asset.censors], sort_keys=True),
        json.dumps([{"type": o.type, "x": o.x, "y": o.y, "scale": o.scale,
                      "opacity": o.opacity, "enabled": o.enabled, "position": o.position}
                     for o in asset.overlays], sort_keys=True),
    ]
    raw = "|".join(parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def prepare_for_platform(
    asset: Asset,
    platform_id: str,
    project: Project,
    *,
    slot_name: str = "",
    censor_override: Optional[bool] = None,
    output_dir: str = "",
) -> PrepResult:
    """Full export pipeline for one asset to one platform slot.

    Steps:
        1. Look up Platform + PlatformSlot
        2. Load image via load_image_for_export()
        3. Find crop: assignment crop -> asset.crops by label -> auto-fit
        4. Apply crop via img.crop()
        5. Resize to slot dimensions
        6. Apply censors with coordinate transform
        7. Apply overlays with coordinate transform
        8. Save to _exports/{asset_id}/{platform_id}_{slot_name}.png
        9. Return PrepResult
    """
    result = PrepResult(platform_id=platform_id)
    warnings: list[str] = []

    # --- 1. Look up platform + slot ---
    platform = PLATFORMS.get(platform_id)
    if not platform:
        result.error = f"Unknown platform: {platform_id}"
        return result

    slot: Optional[PlatformSlot] = None
    if slot_name:
        for s in platform.slots:
            if s.name == slot_name:
                slot = s
                break
        if not slot:
            result.error = f"Unknown slot '{slot_name}' on platform '{platform_id}'"
            return result
    else:
        # Default to first slot
        if platform.slots:
            slot = platform.slots[0]
            slot_name = slot.name
        else:
            result.error = f"Platform '{platform_id}' has no slots"
            return result

    # --- 2. Load image ---
    src = Path(asset.source_path)
    if not src.exists():
        result.error = f"Source file not found: {asset.source_path}"
        return result

    try:
        img = load_image_for_export(asset.source_path)
    except Exception as e:
        result.error = f"Failed to load image: {e}"
        return result

    img_w, img_h = img.size

    # --- 3. Find crop ---
    crop_box: Optional[tuple[int, int, int, int]] = None
    crop_source = ""

    # Check assignment crops first
    for pa in asset.assignments:
        if pa.platform == platform_id and pa.slot == slot_name and pa.crop:
            crop_box = (pa.crop.x, pa.crop.y, pa.crop.w, pa.crop.h)
            crop_source = "assignment"
            break

    # Then check asset.crops by label (flexible matching)
    if crop_box is None:
        for cr in asset.crops:
            lbl = cr.label.strip().lower()
            if (lbl == slot_name.lower()
                    or lbl == platform_id.lower()
                    or slot_name.lower() in lbl
                    or platform_id.lower() in lbl):
                crop_box = (cr.x, cr.y, cr.w, cr.h)
                crop_source = f"label_match ('{cr.label}')"
                break

    # Match by aspect ratio
    if crop_box is None and slot.width and slot.height:
        target_ratio = slot.width / slot.height
        for cr in asset.crops:
            if cr.w > 0 and cr.h > 0:
                cr_ratio = cr.w / cr.h
                if abs(cr_ratio - target_ratio) < 0.02:
                    crop_box = (cr.x, cr.y, cr.w, cr.h)
                    crop_source = f"aspect_match ('{cr.label}', ratio={cr_ratio:.2f})"
                    break

    # If only one crop exists on the asset, use it
    if crop_box is None and len(asset.crops) == 1:
        cr = asset.crops[0]
        crop_box = (cr.x, cr.y, cr.w, cr.h)
        crop_source = f"only_crop ('{cr.label}')"

    # Auto-fit as fallback
    if crop_box is None:
        crop_box = _auto_crop_for_ratio(img_w, img_h, slot.width, slot.height)
        crop_source = "auto"
        warnings.append("No explicit crop found, using auto-fit")

    print(f"[Pipeline] {platform_id}/{slot_name}: crop={crop_source}")

    # --- 4. Apply crop ---
    cx, cy, cw, ch = crop_box
    img = img.crop((cx, cy, cx + cw, cy + ch))

    # --- 5. Resize to slot dimensions ---
    img = img.resize((slot.width, slot.height), Image.LANCZOS)

    # --- 6. Apply censors with coordinate transform ---
    # Censors with platform scope always apply to their designated platforms.
    # Unscoped censors apply when the platform needs_censor flag is set.
    use_censor = censor_override if censor_override is not None else platform.needs_censor
    applicable_censors = []
    for cr in asset.censors:
        if cr.platforms:
            # Scoped censor — apply only to designated platforms
            if platform_id in cr.platforms:
                applicable_censors.append(cr)
        elif use_censor:
            # Unscoped censor — apply when platform requires censoring
            applicable_censors.append(cr)
    if applicable_censors:
        transformed_censors = []
        for cr in applicable_censors:
            tx, ty, tw, th = _transform_region(
                cr.x, cr.y, cr.w, cr.h, crop_box, (slot.width, slot.height)
            )
            if tw > 0 and th > 0:
                new_cr = CensorRegion(x=tx, y=ty, w=tw, h=th, style=cr.style)
                # Carry forward optional fields from older data
                blur_radius = getattr(cr, 'blur_radius', 20)
                pixelate_ratio = getattr(cr, 'pixelate_ratio', 10)
                if hasattr(cr, 'blur_radius'):
                    new_cr.blur_radius = blur_radius
                if hasattr(cr, 'pixelate_ratio'):
                    new_cr.pixelate_ratio = pixelate_ratio
                transformed_censors.append(new_cr)
        if transformed_censors:
            img = apply_censors(img, transformed_censors)

    # --- 7. Apply overlays with coordinate transform ---
    overlays_to_apply: list[CanvasOverlay] = [
        ov for ov in asset.overlays
        if not ov.platforms or platform_id in ov.platforms
    ]
    if overlays_to_apply:
        transformed_overlays = []
        for ov in overlays_to_apply:
            if ov.position == "custom":
                # Transform custom x,y coordinates
                tx, ty, _, _ = _transform_region(
                    ov.x, ov.y, 1, 1, crop_box, (slot.width, slot.height)
                )
                new_ov = replace(ov, x=tx, y=ty)
                transformed_overlays.append(new_ov)
            else:
                # Preset positions (bottom-right, center, etc.) are relative —
                # apply_overlays resolves them based on output image size
                transformed_overlays.append(ov)

        project_dir = str(Path(asset.source_path).parent) if asset.source_path else ""
        img = apply_overlays(img, transformed_overlays, project_dir)

    # --- 8. Save ---
    if output_dir:
        out_base = Path(output_dir)
    else:
        out_base = Path("_exports")

    # Use full source filename (without extension) for the output name
    src = Path(asset.source_path)
    stem = src.stem
    # If stem is generic (all digits), prepend parent folder name for context
    if stem.isdigit() and src.parent.name:
        stem = f"{src.parent.name}_{stem}"
    out_base.mkdir(parents=True, exist_ok=True)
    out_path = out_base / f"{stem}_{platform_id}_{slot_name}.png"
    # Deduplicate if collision with a different asset
    if out_path.exists():
        for i in range(1, 1000):
            candidate = out_base / f"{stem}_{platform_id}_{slot_name}_{i:03d}.png"
            if not candidate.exists():
                out_path = candidate
                break
    img.save(str(out_path), "PNG")

    # --- 9. Return result ---
    result.success = True
    result.output_path = str(out_path)
    result.width = slot.width
    result.height = slot.height
    result.warnings = warnings
    return result


def batch_export_variants(
    asset: Asset,
    project: Project,
    output_dir: str = "",
) -> list[PrepResult]:
    """Export all platform variants for an asset. Populates asset.variant_exports.

    Exports every slot of every platform in the project.
    """
    results = []
    asset.variant_exports.clear()
    for pid in project.platforms:
        platform = PLATFORMS.get(pid)
        if not platform or not platform.slots:
            continue
        for slot in platform.slots:
            r = prepare_for_platform(
                asset, pid, project,
                slot_name=slot.name, output_dir=output_dir,
            )
            results.append(r)
            if r.success:
                key = f"{pid}_{slot.name}"
                asset.variant_exports[key] = r.output_path
    return results


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

def check_readiness(
    asset: Asset,
    platform_id: str,
    project: Optional[Project] = None,
) -> dict:
    """Check whether an asset is ready for a given platform.

    Returns dict with:
        status: "green", "yellow", or "red"
        crop: "explicit" | "auto-fit" | "missing"
        censor: "present" | "not_needed" | "missing"
        overlay: "present" | "none" | "no_defaults"
        issues: list[str]
    """
    issues: list[str] = []
    platform = PLATFORMS.get(platform_id)

    if not platform:
        return {
            "status": "red",
            "crop": "missing",
            "censor": "missing",
            "overlay": "none",
            "issues": [f"Unknown platform: {platform_id}"],
        }

    # Check source file exists
    if not asset.source_path or not Path(asset.source_path).exists():
        return {
            "status": "red",
            "crop": "missing",
            "censor": "missing",
            "overlay": "none",
            "issues": ["Source file not found"],
        }

    # --- Crop status ---
    has_explicit_crop = False
    for pa in asset.assignments:
        if pa.platform == platform_id and pa.crop:
            has_explicit_crop = True
            break
    if not has_explicit_crop:
        for cr in asset.crops:
            if cr.label == platform_id or any(
                s.name == cr.label for s in platform.slots
            ):
                has_explicit_crop = True
                break

    if has_explicit_crop:
        crop_status = "explicit"
    else:
        crop_status = "auto-fit"
        issues.append("No explicit crop — will auto-fit to aspect ratio")

    # --- Censor status ---
    if platform.needs_censor:
        if asset.censors:
            censor_status = "present"
        else:
            censor_status = "missing"
            issues.append("Platform requires censoring but asset has no censor regions")
    else:
        censor_status = "not_needed"

    # --- Overlay status ---
    has_overlay = bool(asset.overlays)
    has_project_defaults = bool(
        project and project.default_overlays
    )

    if has_overlay:
        overlay_status = "present"
    elif has_project_defaults:
        overlay_status = "none"
        issues.append("No overlay set but project has default overlays")
    else:
        overlay_status = "no_defaults"

    # --- Determine overall status ---
    if censor_status == "missing":
        status = "red"
    elif crop_status == "auto-fit" or (not has_overlay and has_project_defaults):
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
