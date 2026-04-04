"""Shared image loading utilities — PIL↔Qt conversion, PSD support."""
from pathlib import Path
from PySide6.QtGui import QPixmap, QImage
from PIL import Image as PILImage

PSD_EXTS = {".psd", ".psb"}
SHELL_THUMB_EXTS = {".sai", ".sai2", ".clip", ".csp", ".kra", ".xcf", ".ora"}


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
    """Load any supported image as QPixmap, including PSD and shell-supported formats."""
    ext = Path(path).suffix.lower()
    if ext in PSD_EXTS:
        try:
            img, w, h = load_psd(path)
            return pil_to_qpixmap(img), w, h
        except Exception:
            return QPixmap(), 0, 0

    if ext in SHELL_THUMB_EXTS:
        shell_img = _get_shell_thumbnail(path, 512)
        if shell_img:
            return pil_to_qpixmap(shell_img), shell_img.width, shell_img.height
        return QPixmap(), 0, 0

    pm = QPixmap(path)
    return pm, pm.width(), pm.height()


def _get_shell_thumbnail(path: str, size: int = 256) -> PILImage.Image | None:
    """Extract thumbnail via Windows Shell (works with SaiThumbs, etc.)."""
    try:
        import ctypes
        from ctypes import byref, POINTER, c_void_p, c_int, HRESULT

        ctypes.windll.ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                        ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

        class SIZE(ctypes.Structure):
            _fields_ = [('cx', c_int), ('cy', c_int)]

        IID = GUID(0xbcc18b79, 0xba16, 0x442f,
            (ctypes.c_ubyte * 8)(0x80, 0xc4, 0x8a, 0x59, 0xc3, 0x0c, 0x46, 0x3b))

        shell_item = c_void_p()
        hr = ctypes.windll.shell32.SHCreateItemFromParsingName(
            str(Path(path).resolve()), None, byref(IID), byref(shell_item))
        if hr != 0:
            return None

        vtable = ctypes.cast(
            ctypes.cast(shell_item, POINTER(c_void_p))[0],
            POINTER(c_void_p * 5))[0]

        GetImage = ctypes.CFUNCTYPE(HRESULT, c_void_p, SIZE, c_int, POINTER(c_void_p))(vtable[3])
        hbitmap = c_void_p()
        hr2 = GetImage(shell_item, SIZE(size, size), 0, byref(hbitmap))

        # Release shell item
        Release = ctypes.CFUNCTYPE(ctypes.c_ulong, c_void_p)(vtable[2])
        Release(shell_item)

        if hr2 != 0 or not hbitmap.value:
            return None

        import win32gui, win32ui
        info = win32gui.GetObject(int(hbitmap.value))
        w, h = info.bmWidth, info.bmHeight
        bmp = win32ui.CreateBitmapFromHandle(int(hbitmap.value))
        bits = bmp.GetBitmapBits(True)
        img = PILImage.frombuffer('RGBA', (w, h), bits, 'raw', 'BGRA', 0, 1)
        ctypes.windll.gdi32.DeleteObject(hbitmap)
        return img
    except Exception:
        return None


def _make_placeholder(path: str) -> tuple[PILImage.Image, int, int]:
    """Create a placeholder image for unsupported formats."""
    size = 256
    img = PILImage.new("RGBA", (size, size), (50, 50, 55, 255))
    try:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        ext = Path(path).suffix.upper()
        name = Path(path).stem
        # Big extension label
        draw.text((size // 2, size // 2 - 20), ext, fill=(200, 200, 200, 255), anchor="mm")
        # Filename below
        display_name = name[:20] + "..." if len(name) > 20 else name
        draw.text((size // 2, size // 2 + 15), display_name, fill=(130, 130, 130, 255), anchor="mm")
        # Border
        draw.rectangle([2, 2, size - 3, size - 3], outline=(80, 80, 90, 255), width=2)
    except Exception:
        pass
    return img, 0, 0


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

    # For SAI, CLIP, KRA etc — try Windows shell thumbnail (SaiThumbs etc.)
    if ext in SHELL_THUMB_EXTS:
        shell_img = _get_shell_thumbnail(path, target_size)
        if shell_img:
            return shell_img, shell_img.width, shell_img.height
        return _make_placeholder(path)

    # Standard PIL formats
    try:
        img = PILImage.open(path)
        return img, img.width, img.height
    except Exception:
        return _make_placeholder(path)
