"""Shared image loading utilities — PIL↔Qt conversion, PSD support."""
from pathlib import Path
from PySide6.QtGui import QPixmap, QImage
from PIL import Image as PILImage

PSD_EXTS = {".psd", ".psb"}


def pil_to_qpixmap(img: PILImage.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap."""
    if img.mode == "RGB":
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3,
                      QImage.Format.Format_RGB888).copy()
    else:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, img.width * 4,
                      QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def load_psd(path: str) -> tuple[PILImage.Image, int, int]:
    """Open a PSD/PSB and return (composited PIL image, doc_width, doc_height)."""
    from psd_tools import PSDImage
    psd = PSDImage.open(path)
    return psd.composite(), psd.width, psd.height


def load_psd_thumb(path: str, min_size: int = 0) -> tuple[PILImage.Image, int, int] | None:
    """Try to get the embedded PSD thumbnail. Returns None if too small or missing."""
    from psd_tools import PSDImage
    psd = PSDImage.open(path)
    thumb = psd.thumbnail()
    if thumb and max(thumb.size) >= min_size:
        return thumb, psd.width, psd.height
    return None


def load_pixmap(path: str) -> tuple[QPixmap, int, int]:
    """Load any supported image as QPixmap, including PSD. Returns (pixmap, w, h)."""
    ext = Path(path).suffix.lower()
    if ext in PSD_EXTS:
        try:
            img, w, h = load_psd(path)
            return pil_to_qpixmap(img), w, h
        except Exception:
            return QPixmap(), 0, 0

    pm = QPixmap(path)
    return pm, pm.width(), pm.height()


def open_for_thumb(path: str, target_size: int = 160) -> tuple[PILImage.Image, int, int]:
    """Open image for thumbnailing. Uses PSD embedded thumb if large enough."""
    ext = Path(path).suffix.lower()
    if ext in PSD_EXTS:
        try:
            result = load_psd_thumb(path, min_size=target_size)
            if result:
                return result
            return load_psd(path)
        except Exception:
            pass

    img = PILImage.open(path)
    return img, img.width, img.height
