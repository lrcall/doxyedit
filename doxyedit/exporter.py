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
    """Apply non-destructive overlays (watermark, text, logo, arrow, shape)."""
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
        elif ov.type == "shape":
            img = _composite_shape_overlay(img, ov)
    return img


def _composite_shape_overlay(img: Image.Image, ov: CanvasOverlay) -> Image.Image:
    """Render a rectangle / ellipse / gradient / bubble annotation."""
    from PIL import ImageDraw
    import math
    if ov.shape_kind in ("gradient_linear", "gradient_radial"):
        return _composite_gradient_overlay(img, ov)
    if ov.shape_kind in ("speech_bubble", "thought_bubble", "burst"):
        return _composite_bubble_overlay(img, ov)
    # Non-zero rotation: render the shape onto its own transparent tile,
    # rotate around its center, paste back. Keeps the main path simple.
    if getattr(ov, "rotation", 0):
        try:
            tile = Image.new("RGBA", (max(1, int(ov.shape_w)),
                                        max(1, int(ov.shape_h))),
                              (0, 0, 0, 0))
            # Build a flat copy of the overlay at origin so we can reuse
            # the straight rendering path
            import copy as _cp
            flat = _cp.copy(ov)
            flat.rotation = 0
            flat.x = 0
            flat.y = 0
            tile_img = _composite_shape_overlay(tile, flat)
            rotated = tile_img.rotate(-ov.rotation, resample=Image.BICUBIC,
                                        expand=True)
            # Center the rotated tile at the original rect center
            cx = ov.x + ov.shape_w / 2
            cy = ov.y + ov.shape_h / 2
            paste_x = int(cx - rotated.width / 2)
            paste_y = int(cy - rotated.height / 2)
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.paste(rotated, (paste_x, paste_y), rotated)
            return Image.alpha_composite(img, layer)
        except Exception:
            return img
    try:
        def _hex(s):
            c = s.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        stroke_hex = ov.stroke_color or ov.color
        sr, sg, sb = _hex(stroke_hex)
        a = int(255 * ov.opacity)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x0, y0 = ov.x, ov.y
        x1, y1 = ov.x + ov.shape_w, ov.y + ov.shape_h
        fill = None
        if ov.fill_color:
            fr, fg, fb = _hex(ov.fill_color)
            fill = (fr, fg, fb, a)
        width = max(1, ov.stroke_width or 2)
        style = getattr(ov, "line_style", "solid")
        if ov.shape_kind == "ellipse":
            # Fill pass (always solid since dashed fills look wrong)
            if fill:
                draw.ellipse([(x0, y0), (x1, y1)], fill=fill)
            # Stroke pass — PIL has no dashed ellipse so fall back to solid
            if style == "solid":
                draw.ellipse([(x0, y0), (x1, y1)],
                              outline=(sr, sg, sb, a), width=width)
            else:
                # Trace an elliptical arc as segmented line points
                import math as _m
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                rx, ry = (x1 - x0) / 2.0, (y1 - y0) / 2.0
                on_len, off_len = (12, 6) if style == "dash" else (2, 4)
                period = on_len + off_len
                # Approximate circumference for step count
                circ = 2 * _m.pi * _m.hypot(rx, ry) / 2
                steps = max(64, int(circ))
                points = [(cx + rx * _m.cos(2 * _m.pi * i / steps),
                           cy + ry * _m.sin(2 * _m.pi * i / steps))
                          for i in range(steps + 1)]
                acc = 0.0
                prev = points[0]
                drawing = True
                for pt in points[1:]:
                    seg = _m.hypot(pt[0] - prev[0], pt[1] - prev[1])
                    if drawing:
                        draw.line([prev, pt], fill=(sr, sg, sb, a), width=width)
                    acc += seg
                    if acc >= (on_len if drawing else off_len):
                        drawing = not drawing
                        acc = 0.0
                    prev = pt
        else:
            radius = max(0, getattr(ov, "corner_radius", 0))
            if radius > 0 and hasattr(draw, "rounded_rectangle"):
                if fill:
                    draw.rounded_rectangle([(x0, y0), (x1, y1)],
                                             radius=radius, fill=fill)
                if style == "solid":
                    draw.rounded_rectangle([(x0, y0), (x1, y1)],
                                             radius=radius,
                                             outline=(sr, sg, sb, a),
                                             width=width)
                # Dashed/dotted rounded corners fall back to solid for simplicity
                return Image.alpha_composite(img, layer)
            if fill:
                draw.rectangle([(x0, y0), (x1, y1)], fill=fill)
            if style == "solid":
                draw.rectangle([(x0, y0), (x1, y1)],
                                outline=(sr, sg, sb, a), width=width)
            else:
                # Four sides as dashed/dotted segments
                on_len, off_len = (12, 6) if style == "dash" else (2, 4)
                def _dashed(p1, p2):
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    total = math.hypot(dx, dy)
                    if total == 0:
                        return
                    ux, uy = dx / total, dy / total
                    t = 0.0
                    while t < total:
                        e = min(t + on_len, total)
                        draw.line([
                            (p1[0] + ux * t, p1[1] + uy * t),
                            (p1[0] + ux * e, p1[1] + uy * e),
                        ], fill=(sr, sg, sb, a), width=width)
                        t = e + off_len
                _dashed((x0, y0), (x1, y0))
                _dashed((x1, y0), (x1, y1))
                _dashed((x1, y1), (x0, y1))
                _dashed((x0, y1), (x0, y0))
        return Image.alpha_composite(img, layer)
    except Exception:
        return img


def _composite_bubble_overlay(img: Image.Image, ov: CanvasOverlay) -> Image.Image:
    """Render a speech_bubble / thought_bubble / burst into the export PNG.

    Uses PIL ImageDraw primitives (rounded_rectangle, ellipse, polygon) to
    match the Studio canvas rendering paths as closely as possible.
    """
    from PIL import ImageDraw
    import math
    try:
        def _hex(s):
            c = (s or "#000000").lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        stroke_rgb = _hex(ov.stroke_color or ov.color or "#000000")
        a = int(255 * ov.opacity)
        stroke_rgba = (*stroke_rgb, a)
        if ov.fill_color:
            fill_rgb = _hex(ov.fill_color)
            fill_rgba = (*fill_rgb, a)
        else:
            fill_rgba = None
        width = max(1, ov.stroke_width or 2)
        x, y = int(ov.x), int(ov.y)
        w, h = int(ov.shape_w), int(ov.shape_h)
        if w < 2 or h < 2:
            return img
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        kind = ov.shape_kind
        if kind == "speech_bubble":
            pad = int(min(w, h) * 0.18)
            body = (x, y, x + w, y + h)
            draw.rounded_rectangle(
                body, radius=pad, fill=fill_rgba, outline=stroke_rgba,
                width=width)
            # Tail. Overlap the base into the body interior so the tail
            # polygon's fill covers the body outline at the attachment
            # point (seamless outline). Only the two diagonal tail
            # sides get drawn as lines, so there's no explicit base line
            # crossing the body.
            tx = ov.tail_x or (x - int(w * 0.15))
            ty = ov.tail_y or (y + h + int(h * 0.35))
            cx, cy = x + w / 2, y + h / 2
            dx, dy = tx - cx, ty - cy
            horiz = abs(dx) > abs(dy)
            base_len = int(min(w, h) * 0.25)
            overlap = max(4, int(min(w, h) * 0.08))
            if horiz:
                if dx > 0:
                    edge_x = (x + w) - overlap
                else:
                    edge_x = x + overlap
                mid_y = int(max(y + pad,
                                 min(y + h - pad, ty * 0.5 + cy * 0.5)))
                b1 = (edge_x, mid_y - base_len // 2)
                b2 = (edge_x, mid_y + base_len // 2)
            else:
                if dy > 0:
                    edge_y = (y + h) - overlap
                else:
                    edge_y = y + overlap
                mid_x = int(max(x + pad,
                                 min(x + w - pad, tx * 0.5 + cx * 0.5)))
                b1 = (mid_x - base_len // 2, edge_y)
                b2 = (mid_x + base_len // 2, edge_y)
            tri = [b1, (int(tx), int(ty)), b2]
            if fill_rgba is not None:
                draw.polygon(tri, fill=fill_rgba)
            draw.line([b1, (int(tx), int(ty))], fill=stroke_rgba, width=width)
            draw.line([(int(tx), int(ty)), b2], fill=stroke_rgba, width=width)
        elif kind == "thought_bubble":
            cx, cy = x + w / 2, y + h / 2
            rx, ry = w / 2, h / 2
            # Central ellipse
            inner = (int(cx - rx * 0.78), int(cy - ry * 0.78),
                      int(cx + rx * 0.78), int(cy + ry * 0.78))
            if fill_rgba is not None:
                draw.ellipse(inner, fill=fill_rgba)
            draw.ellipse(inner, outline=stroke_rgba, width=width)
            # 10 edge puffs
            puff_r = int(min(rx, ry) * 0.28)
            for i in range(10):
                ang = (2 * math.pi * i) / 10
                px = cx + math.cos(ang) * (rx - puff_r * 0.4)
                py = cy + math.sin(ang) * (ry - puff_r * 0.4)
                bbox = (int(px - puff_r), int(py - puff_r),
                         int(px + puff_r), int(py + puff_r))
                if fill_rgba is not None:
                    draw.ellipse(bbox, fill=fill_rgba)
                draw.ellipse(bbox, outline=stroke_rgba, width=width)
            # Trailing puff circles toward the tail
            tx = ov.tail_x or int(x - w * 0.3)
            ty = ov.tail_y or int(y + h + h * 0.5)
            dx, dy = tx - cx, ty - cy
            length = math.hypot(dx, dy)
            if length > 4:
                ux, uy = dx / length, dy / length
                start_offset = min(rx, ry) * 0.85
                for i, frac in enumerate((0.25, 0.55, 0.85)):
                    pr = max(2, int(puff_r * (0.55 - i * 0.15)))
                    cxp = int(cx + ux * (start_offset + length * frac * 0.6))
                    cyp = int(cy + uy * (start_offset + length * frac * 0.6))
                    bbox = (cxp - pr, cyp - pr, cxp + pr, cyp + pr)
                    if fill_rgba is not None:
                        draw.ellipse(bbox, fill=fill_rgba)
                    draw.ellipse(bbox, outline=stroke_rgba, width=width)
        elif kind == "burst":
            cx, cy = x + w / 2, y + h / 2
            rx, ry = w / 2, h / 2
            points = []
            n_points = 14
            inner_scale = 0.62
            for i in range(n_points * 2):
                frac = (2 * math.pi * i) / (n_points * 2)
                s = 1.0 if i % 2 == 0 else inner_scale
                px = cx + math.cos(frac - math.pi / 2) * rx * s
                py = cy + math.sin(frac - math.pi / 2) * ry * s
                points.append((int(px), int(py)))
            if fill_rgba is not None:
                draw.polygon(points, fill=fill_rgba)
            # Draw outline as consecutive line segments (polygon outline on
            # PIL ≥ 9.4 but ``width`` kw on polygon is iffy; manual is safe)
            for i in range(len(points)):
                p1 = points[i]
                p2 = points[(i + 1) % len(points)]
                draw.line([p1, p2], fill=stroke_rgba, width=width)
        return Image.alpha_composite(img, layer)
    except Exception:
        return img


def _composite_gradient_overlay(img: Image.Image, ov: CanvasOverlay) -> Image.Image:
    """Render a linear or radial gradient into a rect region using numpy."""
    try:
        import numpy as _np
        import math as _m
        w, h = int(ov.shape_w), int(ov.shape_h)
        if w < 1 or h < 1:
            return img

        def _parse(s, default):
            s = s or default
            h2 = s.lstrip("#")
            if len(h2) == 8:
                return (int(h2[0:2], 16), int(h2[2:4], 16),
                        int(h2[4:6], 16), int(h2[6:8], 16))
            if len(h2) == 6:
                return (int(h2[0:2], 16), int(h2[2:4], 16),
                        int(h2[4:6], 16), 255)
            return (0, 0, 0, 255)

        c0 = _parse(ov.gradient_start_color, "#000000")
        c1 = _parse(ov.gradient_end_color, "#ffffff")
        base_opac = ov.opacity
        # Grid of normalized positions in [0,1] across the rect
        ys, xs = _np.mgrid[0:h, 0:w].astype(_np.float32)
        if ov.shape_kind == "gradient_radial":
            cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
            max_r = _m.hypot(cx, cy)
            if max_r == 0:
                max_r = 1
            t = _np.clip(_np.hypot(xs - cx, ys - cy) / max_r, 0, 1)
        else:
            ang = _m.radians(ov.gradient_angle or 0)
            dx, dy = _m.cos(ang), _m.sin(ang)
            # Project each pixel onto the direction vector; normalize 0..1
            proj = (xs * dx + ys * dy)
            pmin = float(proj.min())
            pmax = float(proj.max())
            rng = (pmax - pmin) or 1.0
            t = (proj - pmin) / rng
        t3 = t[..., None]
        rgba = _np.zeros((h, w, 4), dtype=_np.float32)
        c0a = _np.array(c0, dtype=_np.float32)
        c1a = _np.array(c1, dtype=_np.float32)
        rgba = c0a * (1 - t3) + c1a * t3
        rgba[..., 3] = rgba[..., 3] * base_opac
        layer_np = rgba.clip(0, 255).astype(_np.uint8)
        from PIL import Image as _Im
        grad_tile = _Im.fromarray(layer_np, "RGBA")
        layer = _Im.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(grad_tile, (int(ov.x), int(ov.y)))
        return Image.alpha_composite(img, layer)
    except Exception:
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
        style = getattr(ov, "line_style", "solid")
        if style == "solid":
            draw.line([(x1, y1), (x2, y2)], fill=(r, g, b, a), width=width)
        else:
            # Dashed / dotted — walk the line segmenting by (on, off) pattern
            on_len, off_len = (12, 6) if style == "dash" else (2, 4)
            dx = x2 - x1
            dy = y2 - y1
            total = math.hypot(dx, dy)
            if total > 0:
                ux, uy = dx / total, dy / total
                t = 0.0
                while t < total:
                    seg_end = min(t + on_len, total)
                    sx = x1 + ux * t
                    sy = y1 + uy * t
                    ex = x1 + ux * seg_end
                    ey = y1 + uy * seg_end
                    draw.line([(sx, sy), (ex, ey)],
                              fill=(r, g, b, a), width=width)
                    t = seg_end + off_len
        # Arrowhead triangle at the tip — filled / outline / none
        head_style = getattr(ov, "arrowhead_style", "filled")
        if head_style != "none":
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length > 1:
                ux, uy = dx / length, dy / length
                hs = max(ov.arrowhead_size, 6)
                px, py = -uy, ux

                def _draw_head(tip_x, tip_y, direction):
                    base_x = tip_x - direction * ux * hs
                    base_y = tip_y - direction * uy * hs
                    p1 = (base_x + px * hs * 0.5, base_y + py * hs * 0.5)
                    p2 = (base_x - px * hs * 0.5, base_y - py * hs * 0.5)
                    if head_style == "outline":
                        draw.polygon([(tip_x, tip_y), p1, p2],
                                       outline=(r, g, b, a), width=width)
                    else:
                        draw.polygon([(tip_x, tip_y), p1, p2],
                                       fill=(r, g, b, a))

                _draw_head(x2, y2, 1)
                if getattr(ov, "double_headed", False):
                    _draw_head(x1, y1, -1)
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

        # Rotation (in-place around the image center, expand to fit)
        if getattr(ov, "rotation", 0):
            wm = wm.rotate(-ov.rotation, resample=Image.BICUBIC, expand=True)

        # Filter (grayscale / invert / blur) — before opacity / composite
        mode = getattr(ov, "filter_mode", "") or ""
        if mode == "grayscale":
            from PIL import ImageOps
            gray = ImageOps.grayscale(wm.convert("RGB")).convert("RGBA")
            # Keep original alpha so transparent edges stay transparent
            gray.putalpha(wm.split()[3])
            wm = gray
        elif mode == "invert":
            from PIL import ImageOps
            inv = ImageOps.invert(wm.convert("RGB")).convert("RGBA")
            inv.putalpha(wm.split()[3])
            wm = inv
        elif mode in ("blur3", "blur8"):
            from PIL import ImageFilter as _PF
            radius = 3 if mode == "blur3" else 8
            wm = wm.filter(_PF.GaussianBlur(radius=radius))

        # Apply opacity
        if ov.opacity < 1.0:
            alpha = wm.split()[3]
            alpha = alpha.point(lambda p: int(p * ov.opacity))
            wm.putalpha(alpha)

        # Position
        x, y = _resolve_position(img.size, wm.size, ov.position, ov.x, ov.y)

        # Composite — honor blend_mode if set. PIL's ImageChops ops expect
        # matched-size images, so extract the base region first, blend, then
        # paste back.
        blend = getattr(ov, "blend_mode", "normal")
        if blend == "normal":
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.paste(wm, (x, y))
            return Image.alpha_composite(img, layer)
        from PIL import ImageChops
        base_region = img.crop((x, y, x + wm.width, y + wm.height)).convert("RGBA")
        rgb_base = base_region.convert("RGB")
        rgb_wm = wm.convert("RGB")
        if blend == "multiply":
            mixed = ImageChops.multiply(rgb_base, rgb_wm)
        elif blend == "screen":
            mixed = ImageChops.screen(rgb_base, rgb_wm)
        elif blend == "darken":
            mixed = ImageChops.darker(rgb_base, rgb_wm)
        elif blend == "lighten":
            mixed = ImageChops.lighter(rgb_base, rgb_wm)
        elif blend == "overlay":
            # Manual overlay: base<128 => 2*b*w/255, else => 255-2*(255-b)*(255-w)/255
            import numpy as _np
            ba = _np.asarray(rgb_base, dtype=_np.int32)
            wa = _np.asarray(rgb_wm, dtype=_np.int32)
            low = 2 * ba * wa // 255
            high = 255 - 2 * (255 - ba) * (255 - wa) // 255
            out = _np.where(ba < 128, low, high).astype(_np.uint8)
            mixed = Image.fromarray(out, "RGB")
        else:
            mixed = rgb_wm
        # Respect alpha from the watermark (for partial-alpha edges) and the
        # overall opacity baked in above
        mixed_rgba = mixed.convert("RGBA")
        mixed_rgba.putalpha(wm.split()[3])
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(mixed_rgba, (x, y))
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

        # Text outline/stroke (+ horizontal alignment for multiline)
        align = getattr(ov, "text_align", "left")
        if ov.stroke_color and ov.stroke_width > 0:
            or_, og, ob = _hex(ov.stroke_color)
            draw.text((x, y), render_text, font=font,
                       fill=(r, g, b, a), stroke_width=ov.stroke_width,
                       stroke_fill=(or_, og, ob, a), spacing=spacing,
                       align=align)
        else:
            draw.text((x, y), render_text, font=font, fill=(r, g, b, a),
                      spacing=spacing, align=align)

        # Underline / strikethrough — PIL doesn't expose these as text flags,
        # so render explicit lines under / through each text row.
        want_underline = bool(getattr(ov, "underline", False))
        want_strike = bool(getattr(ov, "strikethrough", False))
        if want_underline or want_strike:
            try:
                ascent, descent = font.getmetrics()
            except Exception:
                ascent, descent = int(ov.font_size * 0.8), int(ov.font_size * 0.2)
            line_w = max(1, ov.stroke_width if ov.stroke_width > 0 else max(1, ov.font_size // 12))
            lines = render_text.split("\n")
            line_step = ascent + descent + spacing
            for i, line in enumerate(lines):
                if not line:
                    continue
                row_top = y + i * line_step
                seg_bbox = draw.textbbox((x, row_top), line, font=font)
                x0, y0, x1, y1 = seg_bbox
                if want_underline:
                    uy = y0 + ascent + 2
                    draw.line([(x0, uy), (x1, uy)], fill=(r, g, b, a),
                              width=line_w)
                if want_strike:
                    sy = y0 + int(ascent * 0.6)
                    draw.line([(x0, sy), (x1, sy)], fill=(r, g, b, a),
                              width=line_w)

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
