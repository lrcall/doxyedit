"""Batch export — exports all assigned assets with proper naming and sizing."""
from pathlib import Path
from PIL import Image, ImageFilter
from doxyedit.models import (
    Project, Asset, PLATFORMS, PostStatus, CensorRegion, CanvasOverlay,
)


def apply_censors(img: Image.Image, censors: list[CensorRegion]) -> Image.Image:
    """Apply censor regions to a PIL image (returns new image)."""
    img = img.copy()
    for cr in censors:
        box = (
            max(0, cr.x), max(0, cr.y),
            min(img.width, cr.x + cr.w), min(img.height, cr.y + cr.h),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        if cr.style == "black":
            region = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 255))
            img.paste(region, (box[0], box[1]))
        elif cr.style == "blur":
            region = img.crop(box).filter(ImageFilter.GaussianBlur(radius=20))
            img.paste(region, (box[0], box[1]))
        elif cr.style == "pixelate":
            region = img.crop(box)
            small = region.resize((max(1, region.width // 10), max(1, region.height // 10)), Image.NEAREST)
            img.paste(small.resize(region.size, Image.NEAREST), (box[0], box[1]))
    return img


def apply_overlays(img: Image.Image, overlays: list[CanvasOverlay], project_dir: str = "") -> Image.Image:
    """Apply non-destructive overlays (watermark, text, logo) to a PIL image."""
    img = img.copy().convert("RGBA")

    for ov in overlays:
        if not ov.enabled:
            continue
        if ov.type in ("watermark", "logo") and ov.image_path:
            img = _composite_image_overlay(img, ov, project_dir)
        elif ov.type == "text" and ov.text:
            img = _composite_text_overlay(img, ov)
    return img


def _composite_image_overlay(img: Image.Image, ov: CanvasOverlay, project_dir: str) -> Image.Image:
    """Composite a watermark/logo image onto the base image."""
    path = Path(ov.image_path)
    if not path.is_absolute() and project_dir:
        path = Path(project_dir) / path
    if not path.exists():
        return img

    try:
        wm = Image.open(str(path)).convert("RGBA")
        # Scale to fraction of base image width
        target_w = max(10, int(img.width * ov.scale))
        ratio = target_w / wm.width
        target_h = int(wm.height * ratio)
        wm = wm.resize((target_w, target_h), Image.LANCZOS)

        # Apply opacity
        if ov.opacity < 1.0:
            alpha = wm.split()[3]
            alpha = alpha.point(lambda p: int(p * ov.opacity))
            wm.putalpha(alpha)

        # Position
        x, y = _resolve_position(img.size, wm.size, ov.position, ov.x, ov.y)

        # Composite
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(wm, (x, y))
        return Image.alpha_composite(img, layer)
    except Exception:
        return img


def _composite_text_overlay(img: Image.Image, ov: CanvasOverlay) -> Image.Image:
    """Render text overlay onto the base image."""
    from PIL import ImageDraw, ImageFont

    try:
        try:
            font = ImageFont.truetype(ov.font_family + ".ttf", ov.font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("arial.ttf", ov.font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        # Parse color
        color = ov.color.lstrip("#")
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        a = int(255 * ov.opacity)

        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # Get text size
        bbox = draw.textbbox((0, 0), ov.text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        x, y = _resolve_position(img.size, (tw, th), ov.position, ov.x, ov.y)
        draw.text((x, y), ov.text, font=font, fill=(r, g, b, a))

        return Image.alpha_composite(img, layer)
    except Exception:
        return img


def _resolve_position(img_size, overlay_size, position, custom_x=0, custom_y=0):
    """Calculate top-left position for an overlay given a position preset."""
    iw, ih = img_size
    ow, oh = overlay_size
    margin = 20

    positions = {
        "bottom-right": (iw - ow - margin, ih - oh - margin),
        "bottom-left": (margin, ih - oh - margin),
        "top-right": (iw - ow - margin, margin),
        "top-left": (margin, margin),
        "center": ((iw - ow) // 2, (ih - oh) // 2),
        "custom": (custom_x, custom_y),
    }
    return positions.get(position, positions["bottom-right"])


def crop_and_resize(img: Image.Image, crop, target_w: int, target_h: int) -> Image.Image:
    """Crop (if specified) then resize to target dimensions."""
    if crop:
        img = img.crop((crop.x, crop.y, crop.x + crop.w, crop.y + crop.h))
    img = img.resize((target_w, target_h), Image.LANCZOS)
    return img


def export_project(project: Project, output_dir: str) -> dict:
    """Export all assigned assets. Returns a manifest dict."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "project": project.name,
        "exports": [],
        "skipped": [],
        "errors": [],
    }

    for asset in project.assets:
        for pa in asset.assignments:
            if pa.status == PostStatus.SKIP:
                manifest["skipped"].append({
                    "asset": asset.id,
                    "platform": pa.platform,
                    "slot": pa.slot,
                })
                continue

            platform = PLATFORMS.get(pa.platform)
            if not platform:
                continue

            slot = None
            for s in platform.slots:
                if s.name == pa.slot:
                    slot = s
                    break
            if not slot:
                continue

            try:
                img = Image.open(asset.source_path).convert("RGBA")

                # Apply censors if platform requires it
                if platform.needs_censor and asset.censors:
                    img = apply_censors(img, asset.censors)

                # Apply overlays (watermarks, text, logos)
                if asset.overlays:
                    img = apply_overlays(img, asset.overlays)

                # Crop and resize
                img = crop_and_resize(img, pa.crop, slot.width, slot.height)

                # Build filename: prefix_slotname.png
                filename = f"{platform.export_prefix}_{slot.name}.png"
                platform_dir = out / platform.id
                platform_dir.mkdir(exist_ok=True)
                filepath = platform_dir / filename

                img.save(str(filepath), "PNG")

                manifest["exports"].append({
                    "asset": asset.id,
                    "source": asset.source_path,
                    "platform": pa.platform,
                    "slot": pa.slot,
                    "size": f"{slot.width}x{slot.height}",
                    "file": str(filepath),
                    "censored": platform.needs_censor,
                })

            except Exception as e:
                manifest["errors"].append({
                    "asset": asset.id,
                    "platform": pa.platform,
                    "slot": pa.slot,
                    "error": str(e),
                })

    # Write manifest
    import json
    manifest_path = out / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return manifest
