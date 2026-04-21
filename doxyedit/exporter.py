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
            radius = cr.blur_radius or 20
            region = img.crop(box).filter(ImageFilter.GaussianBlur(radius=radius))
            img.paste(region, (box[0], box[1]))
        elif cr.style == "pixelate":
            ratio = cr.pixelate_ratio or 10
            region = img.crop(box)
            small = region.resize((max(1, region.width // ratio), max(1, region.height // ratio)), Image.NEAREST)
            img.paste(small.resize(region.size, Image.NEAREST), (box[0], box[1]))
    return img


def apply_overlays(img: Image.Image, overlays: list[CanvasOverlay], project_dir: str = "") -> Image.Image:
    """Apply non-destructive overlays (watermark, text, logo, arrow)."""
    img = img.copy().convert("RGBA")

    for ov in overlays:
        if not ov.enabled:
            continue
        if ov.type in ("watermark", "logo") and ov.image_path:
            img = _composite_image_overlay(img, ov, project_dir)
        elif ov.type == "text" and ov.text:
            img = _composite_text_overlay(img, ov)
        elif ov.type == "arrow":
            img = _composite_arrow_overlay(img, ov)
    return img


def _composite_arrow_overlay(img: Image.Image, ov: CanvasOverlay) -> Image.Image:
    """Render an arrow annotation onto the base image."""
    from PIL import ImageDraw
    import math

    try:
        def _hex(s):
            c = s.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        r, g, b = _hex(ov.color)
        a = int(255 * ov.opacity)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x1, y1 = ov.x, ov.y
        x2, y2 = ov.end_x, ov.end_y
        width = max(1, ov.stroke_width or 4)
        draw.line([(x1, y1), (x2, y2)], fill=(r, g, b, a), width=width)
        # Arrowhead triangle at the tip
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length > 1:
            ux, uy = dx / length, dy / length
            hs = max(ov.arrowhead_size, 6)
            px, py = -uy, ux
            base_x = x2 - ux * hs
            base_y = y2 - uy * hs
            p1 = (base_x + px * hs * 0.5, base_y + py * hs * 0.5)
            p2 = (base_x - px * hs * 0.5, base_y - py * hs * 0.5)
            draw.polygon([(x2, y2), p1, p2], fill=(r, g, b, a))
        return Image.alpha_composite(img, layer)
    except Exception:
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

        # Flip (horizontal / vertical) before rotation/compositing
        if getattr(ov, "flip_h", False):
            wm = wm.transpose(Image.FLIP_LEFT_RIGHT)
        if getattr(ov, "flip_v", False):
            wm = wm.transpose(Image.FLIP_TOP_BOTTOM)

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


def _wrap_text_to_width(text: str, font, max_width: int, draw) -> str:
    """Word-wrap text so each line fits within max_width px. Matches Studio's
    QTextDocument.setTextWidth behavior: wrap at word boundaries, preserve
    explicit newlines, single words longer than max_width stay on their own
    line."""
    if max_width <= 0 or not text:
        return text
    out_lines: list[str] = []
    for src_line in text.split("\n"):
        if not src_line:
            out_lines.append("")
            continue
        words = src_line.split(" ")
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                current = candidate
            else:
                out_lines.append(current)
                current = word
        out_lines.append(current)
    return "\n".join(out_lines)


def _composite_text_overlay(img: Image.Image, ov: CanvasOverlay) -> Image.Image:
    """Render text overlay onto the base image."""
    from PIL import ImageDraw, ImageFont

    try:
        import os
        _winfonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        font = None
        _family = ov.font_family
        # Build style suffix for bold/italic variants
        _style = ""
        if getattr(ov, 'bold', False) and getattr(ov, 'italic', False):
            _style = "bi"
        elif getattr(ov, 'bold', False):
            _style = "bd"
        elif getattr(ov, 'italic', False):
            _style = "i"
        # Try candidates in order
        _names = [
            _family + _style,
            _family.replace(" ", "") + _style,
            _family.lower().replace(" ", "") + _style,
            _family,
            _family.replace(" ", ""),
            _family.lower().replace(" ", ""),
        ]
        for name in _names:
            for ext in (".ttf", ".otf"):
                for base in ["", _winfonts]:
                    path = os.path.join(base, name + ext) if base else name + ext
                    try:
                        font = ImageFont.truetype(path, ov.font_size)
                        break
                    except (OSError, IOError):
                        pass
                if font:
                    break
            if font:
                break
        if font is None:
            try:
                font = ImageFont.truetype("arial.ttf", ov.font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        def _hex(s):
            c = s.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

        r, g, b = _hex(ov.color)
        a = int(255 * ov.opacity)

        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        spacing = int(ov.font_size * (ov.line_height - 1.0))
        # Honor text_width from Studio: wrap at word boundaries so export
        # matches the on-canvas rendering.
        render_text = _wrap_text_to_width(ov.text, font, ov.text_width, draw)
        bbox = draw.textbbox((0, 0), render_text, font=font, spacing=spacing)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        x, y = _resolve_position(img.size, (tw, th), ov.position, ov.x, ov.y)

        # Optional background fill behind the text (callout/pill style)
        bg_hex = getattr(ov, "background_color", "") or ""
        if bg_hex:
            try:
                br, bgc, bbc = _hex(bg_hex)
                pad = max(4, int(ov.font_size * 0.2))
                bg_bbox = (x - pad, y - pad, x + tw + pad, y + th + pad)
                draw.rounded_rectangle(bg_bbox, radius=pad,
                                        fill=(br, bgc, bbc, a))
            except Exception:
                pass

        # Drop shadow (tight crop for performance)
        if ov.shadow_color and ov.shadow_offset:
            sr, sg, sb = _hex(ov.shadow_color)
            sa = int(255 * ov.opacity * 0.6)
            sx, sy = x + ov.shadow_offset, y + ov.shadow_offset
            if ov.shadow_blur > 0:
                margin = ov.shadow_blur * 3
                crop_x = max(0, int(sx) - margin)
                crop_y = max(0, int(sy) - margin)
                crop_w = min(img.width, int(sx + tw) + margin) - crop_x
                crop_h = min(img.height, int(sy + th) + margin) - crop_y
                shadow_crop = Image.new("RGBA", (crop_w, crop_h), (0, 0, 0, 0))
                shadow_draw = ImageDraw.Draw(shadow_crop)
                shadow_draw.text((sx - crop_x, sy - crop_y), render_text, font=font,
                                 fill=(sr, sg, sb, sa), spacing=spacing)
                shadow_crop = shadow_crop.filter(ImageFilter.GaussianBlur(ov.shadow_blur))
                layer.paste(shadow_crop, (crop_x, crop_y))
                draw = ImageDraw.Draw(layer)
            else:
                draw.text((sx, sy), render_text, font=font, fill=(sr, sg, sb, sa), spacing=spacing)

        # Text outline/stroke
        if ov.stroke_color and ov.stroke_width > 0:
            or_, og, ob = _hex(ov.stroke_color)
            draw.text((x, y), render_text, font=font,
                       fill=(r, g, b, a), stroke_width=ov.stroke_width,
                       stroke_fill=(or_, og, ob, a), spacing=spacing)
        else:
            draw.text((x, y), render_text, font=font, fill=(r, g, b, a), spacing=spacing)

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
