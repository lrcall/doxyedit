"""Batch export — exports all assigned assets with proper naming and sizing."""
from pathlib import Path
from PIL import Image, ImageFilter
from doxyedit.models import (
    Project, Asset, PLATFORMS, PostStatus, CensorRegion,
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
