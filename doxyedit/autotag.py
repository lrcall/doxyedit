"""Auto-generate visual property tags from image pixel data.

These tags are computed from the image itself — no AI, just math.
Runs in the background thumb worker thread so it doesn't block the UI.
"""
from PIL import Image as PILImage
import numpy as np


def compute_visual_tags(img: PILImage.Image) -> list[str]:
    """Analyze an image and return auto-generated visual property tags."""
    tags = []

    # Work on a small version for speed
    thumb = img.copy()
    thumb.thumbnail((200, 200), PILImage.NEAREST)
    if thumb.mode not in ("RGB", "RGBA"):
        thumb = thumb.convert("RGB")
    arr = np.array(thumb)
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[:, :, :3]  # drop alpha

    if arr.size == 0:
        return tags

    # --- Color temperature ---
    r_avg = arr[:, :, 0].mean()
    b_avg = arr[:, :, 2].mean()
    if r_avg > b_avg + 15:
        tags.append("warm")
    elif b_avg > r_avg + 15:
        tags.append("cool")

    # --- Luminance ---
    luminance = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    avg_lum = luminance.mean()
    if avg_lum < 80:
        tags.append("dark")
    elif avg_lum > 190:
        tags.append("bright")

    # --- Edge density (detail level) ---
    try:
        from PIL import ImageFilter
        gray = thumb.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_arr = np.array(edges)
        edge_density = (edge_arr > 30).mean() * 100
        if edge_density > 20:
            tags.append("detailed")
        elif edge_density < 8:
            tags.append("flat")
    except Exception:
        pass

    # --- Aspect ratio ---
    w, h = img.size
    if h > 0:
        ratio = w / h
        if ratio > 2.5:
            tags.append("panoramic")
        elif ratio > 1.2:
            tags.append("landscape")
        elif ratio > 0.8:
            tags.append("square")
        elif ratio > 0.4:
            tags.append("portrait")
        else:
            tags.append("tall")

    return tags


def compute_dominant_colors(img: PILImage.Image, n: int = 3) -> list[str]:
    """Get top N dominant colors as hex strings."""
    thumb = img.copy()
    thumb.thumbnail((50, 50), PILImage.NEAREST)
    if thumb.mode != "RGB":
        thumb = thumb.convert("RGB")
    colors = thumb.getcolors(maxcolors=2500)
    if not colors:
        return []
    colors.sort(key=lambda c: c[0], reverse=True)
    result = []
    for count, (r, g, b) in colors[:n]:
        result.append(f"#{r:02x}{g:02x}{b:02x}")
    return result
