"""Shared image loading utilities — PIL↔Qt conversion, PSD support."""
from pathlib import Path
from PySide6.QtGui import QPixmap, QImage
from PIL import Image as PILImage

PSD_EXTS = {".psd", ".psb"}
SHELL_THUMB_EXTS = {".sai", ".sai2", ".clip", ".csp", ".kra", ".xcf", ".ora"}


def pil_to_qimage(img: PILImage.Image) -> QImage:
    """Convert a PIL Image to a QImage (thread-safe — no QPixmap involved)."""
    if img.mode == "RGB":
        data = img.tobytes("raw", "RGB")
        return QImage(data, img.width, img.height, img.width * 3,
                      QImage.Format.Format_RGB888).copy()
    else:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        return QImage(data, img.width, img.height, img.width * 4,
                      QImage.Format.Format_RGBA8888).copy()


def pil_to_qpixmap(img: PILImage.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap. Must be called from the GUI thread."""
    return QPixmap.fromImage(pil_to_qimage(img))


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


_PREVIEW_CACHE_DIR: Path | None = None
_PREVIEW_CACHE_MAX_AGE_DAYS = 30
_PREVIEW_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

def _get_preview_cache_dir() -> Path:
    global _PREVIEW_CACHE_DIR
    if _PREVIEW_CACHE_DIR is None:
        _PREVIEW_CACHE_DIR = Path.home() / ".doxyedit" / "preview_cache"
        _PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _prune_preview_cache(_PREVIEW_CACHE_DIR)
    return _PREVIEW_CACHE_DIR


def _prune_preview_cache(cache_dir: Path) -> None:
    """One-shot cleanup: delete files older than MAX_AGE_DAYS, then enforce size cap.

    Called once per process the first time the cache dir is touched. Silent on
    errors; the cache is best-effort. Not a hot path.
    """
    try:
        import os, time
        now = time.time()
        cutoff = now - _PREVIEW_CACHE_MAX_AGE_DAYS * 86400
        entries = []
        total = 0
        for entry in os.scandir(cache_dir):
            if not entry.is_file():
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                try:
                    os.remove(entry.path)
                except OSError:
                    pass
                continue
            entries.append((st.st_mtime, st.st_size, entry.path))
            total += st.st_size
        if total > _PREVIEW_CACHE_MAX_BYTES:
            entries.sort()  # oldest first
            for _, sz, p in entries:
                if total <= _PREVIEW_CACHE_MAX_BYTES:
                    break
                try:
                    os.remove(p)
                    total -= sz
                except OSError:
                    pass
    except Exception:
        pass

def _preview_cache_key(path: str) -> str:
    import hashlib
    mtime = int(Path(path).stat().st_mtime)
    return hashlib.md5(f"{path}|{mtime}".encode()).hexdigest()

def load_pixmap(path: str) -> tuple[QPixmap, int, int]:
    """Load any supported image as QPixmap, including PSD and shell-supported formats.
    PSD full composites are cached to disk for instant subsequent loads."""
    ext = Path(path).suffix.lower()
    if ext in PSD_EXTS:
        try:
            # Check preview cache first
            cache_dir = _get_preview_cache_dir()
            key = _preview_cache_key(path)
            cached = cache_dir / f"{key}.png"
            if cached.exists():
                pm = QPixmap(str(cached))
                if not pm.isNull():
                    return pm, pm.width(), pm.height()
            # Generate composite and cache it
            img, w, h = load_psd(path)
            pm = pil_to_qpixmap(img)
            # Save to cache in background-safe way
            try:
                img.save(str(cached), "PNG")
            except Exception:
                pass
            return pm, w, h
        except Exception:
            return QPixmap(), 0, 0

    if ext in SHELL_THUMB_EXTS:
        shell_img = get_shell_thumbnail(path, 512)
        if shell_img:
            return pil_to_qpixmap(shell_img), shell_img.width, shell_img.height
        return QPixmap(), 0, 0

    pm = QPixmap(path)
    return pm, pm.width(), pm.height()


def get_shell_thumbnail(path: str, size: int = 256) -> PILImage.Image | None:
    """Extract thumbnail via Windows Shell (works with SaiThumbs, etc.).
    Uses pure ctypes — no win32gui/win32ui required."""
    try:
        import ctypes
        from ctypes import byref, POINTER, c_void_p, c_int, c_uint32, c_int32, c_uint16, HRESULT

        ctypes.windll.ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                        ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

        class SIZE(ctypes.Structure):
            _fields_ = [('cx', c_int), ('cy', c_int)]

        class BITMAP(ctypes.Structure):
            _fields_ = [('bmType', c_int32), ('bmWidth', c_int32), ('bmHeight', c_int32),
                        ('bmWidthBytes', c_int32), ('bmPlanes', c_uint16),
                        ('bmBitsPixel', c_uint16), ('bmBits', c_void_p)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [('biSize', c_uint32), ('biWidth', c_int32), ('biHeight', c_int32),
                        ('biPlanes', c_uint16), ('biBitCount', c_uint16),
                        ('biCompression', c_uint32), ('biSizeImage', c_uint32),
                        ('biXPelsPerMeter', c_int32), ('biYPelsPerMeter', c_int32),
                        ('biClrUsed', c_uint32), ('biClrImportant', c_uint32)]

        # IShellItemImageFactory {BCC18B79-BA16-442F-80C4-8A59C30C463B}
        IID = GUID(0xbcc18b79, 0xba16, 0x442f,
            (ctypes.c_ubyte * 8)(0x80, 0xc4, 0x8a, 0x59, 0xc3, 0x0c, 0x46, 0x3b))

        # Create shell item — SHCreateItemFromParsingName needs a wide string
        path_resolved = str(Path(path).resolve())
        shell_item = c_void_p()
        SHCreate = ctypes.windll.shell32.SHCreateItemFromParsingName
        SHCreate.restype = HRESULT
        hr = SHCreate(path_resolved, None, byref(IID), byref(shell_item))
        if hr != 0 or not shell_item.value:
            return None

        # Get vtable and call GetImage (slot 3: QI=0, AddRef=1, Release=2, GetImage=3)
        vtable_ptr = ctypes.cast(shell_item, POINTER(c_void_p))[0]
        vtable = ctypes.cast(vtable_ptr, POINTER(c_void_p * 8))[0]
        GetImage = ctypes.CFUNCTYPE(HRESULT, c_void_p, SIZE, c_int, POINTER(c_void_p))(vtable[3])
        Release  = ctypes.CFUNCTYPE(ctypes.c_ulong, c_void_p)(vtable[2])

        hbitmap = c_void_p()
        hr2 = GetImage(shell_item, SIZE(size, size), 0, byref(hbitmap))
        Release(shell_item)

        if hr2 != 0 or not hbitmap.value:
            return None

        # hbitmap is owned from here on; ensure it's released on all paths.
        try:
            bm = BITMAP()
            ctypes.windll.gdi32.GetObjectW(hbitmap, ctypes.sizeof(BITMAP), byref(bm))
            w, h = bm.bmWidth, abs(bm.bmHeight)
            if w <= 0 or h <= 0:
                return None

            bi = BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bi.biWidth = w
            bi.biHeight = -h   # negative = top-down DIB
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = 0  # BI_RGB

            buf = (ctypes.c_byte * (w * h * 4))()
            hdc = ctypes.windll.user32.GetDC(None)
            try:
                ctypes.windll.gdi32.GetDIBits(hdc, hbitmap, 0, h, buf, byref(bi), 0)
            finally:
                ctypes.windll.user32.ReleaseDC(None, hdc)

            return PILImage.frombuffer('RGBA', (w, h), bytes(buf), 'raw', 'BGRA', 0, 1)
        finally:
            ctypes.windll.gdi32.DeleteObject(hbitmap)
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


def load_image_for_export(src_path: str) -> PILImage.Image:
    """Load any image format (PSD/PSB/PNG/JPG) as PIL RGBA Image for export."""
    ext = Path(src_path).suffix.lower()
    if ext in PSD_EXTS:
        img, _, _ = load_psd(src_path)
    else:
        img = PILImage.open(src_path).convert("RGBA")
    return img


def open_for_thumb(path: str, target_size: int = 160) -> tuple[PILImage.Image, int, int]:
    """Open image for thumbnailing. Prefers Windows Shell API for PSD/SAI
    (instant) over psd_tools composite (slow)."""
    ext = Path(path).suffix.lower()

    # PSD/PSB: use Shell thumbnail first (instant), fall back to embedded thumb
    if ext in PSD_EXTS:
        shell_img = get_shell_thumbnail(path, max(target_size, 256))
        if shell_img:
            return shell_img, shell_img.width, shell_img.height
        # Shell failed — try psd_tools embedded thumbnail
        try:
            result = load_psd_thumb(path, min_size=0)
            if result:
                return result
        except Exception:
            pass
        return _make_placeholder(path)

    # SAI, CLIP, KRA etc — Windows shell thumbnail
    if ext in SHELL_THUMB_EXTS:
        shell_img = get_shell_thumbnail(path, target_size)
        if shell_img:
            return shell_img, shell_img.width, shell_img.height
        return _make_placeholder(path)

    # Standard PIL formats
    try:
        img = PILImage.open(path)
        return img, img.width, img.height
    except Exception:
        return _make_placeholder(path)


def get_export_dir(project_path: str) -> Path:
    """Return a sidecar assets folder named after the project file.

    e.g. socials_jenni.doxyproj.json → socials_jenni_assets/
    Deduplicates with _001, _002 if a non-directory file with that name exists.
    """
    p = Path(project_path)
    # Strip all extensions (.doxyproj.json → stem)
    stem = p.stem
    if stem.endswith(".doxyproj"):
        stem = stem[: -len(".doxyproj")]
    base_name = f"{stem}_assets"
    d = p.parent / base_name
    if d.exists() and not d.is_dir():
        # Name collision with a file — add suffix
        for i in range(1, 1000):
            d = p.parent / f"{base_name}_{i:03d}"
            if not d.exists() or d.is_dir():
                break
    d.mkdir(exist_ok=True)
    return d
