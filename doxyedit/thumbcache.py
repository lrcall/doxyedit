"""Background thumbnail generator with disk cache for instant reloads."""
import hashlib
import json
import os
import re
import sqlite3
from collections import deque, OrderedDict
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker, QSettings
from PySide6.QtGui import QPixmap, QImage

from doxyedit.imaging import (
    open_for_thumb, pil_to_qimage, get_shell_thumbnail,
    PSD_EXTS, SHELL_THUMB_EXTS, _make_placeholder, load_psd_thumb,
)

THUMB_SIZE = 160
CACHE_DIR_NAME = ".doxyedit_cache"

# Fast cache mode: store uncompressed BMP instead of PNG.
# Reads/writes ~3-5x faster but uses ~10x more disk space per thumbnail.
# Toggled via QSettings key "fast_cache" (0 or 1).
_FAST_FMT = "BMP"
_FAST_EXT = ".bmp"
_STD_FMT  = "PNG"
_STD_EXT  = ".png"


def _cache_fmt() -> tuple[str, str]:
    """Return (format, ext) based on fast_cache setting."""
    fast = QSettings("DoxyEdit", "DoxyEdit").value("fast_cache", 0, type=int)
    return (_FAST_FMT, _FAST_EXT) if fast else (_STD_FMT, _STD_EXT)


def _cache_key(path: str, size: int) -> str:
    """Generate a cache filename from file path + mtime + size."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    raw = f"{path}|{mtime}|{size}"
    return hashlib.md5(raw.encode()).hexdigest()


class GlobalCacheIndex:
    """Cross-project index: maps cache_key → absolute path of cached PNG.

    Stored as an SQLite DB at <base_cache_dir>/content_index.db for O(1)
    keyed lookups without loading the whole file into memory.
    """

    def __init__(self, base_dir: Path):
        db_path = base_dir / "content_index.db"
        self._con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, path TEXT) WITHOUT ROWID")
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.execute("PRAGMA busy_timeout=3000")
        self._con.commit()

    def lookup(self, key: str) -> Path | None:
        """Return path to cached PNG if another project has it, else None."""
        try:
            row = self._con.execute("SELECT path FROM cache WHERE key=?", (key,)).fetchone()
        except sqlite3.OperationalError:
            return None
        if row:
            p = Path(row[0])
            if p.exists():
                return p
            try:
                self._con.execute("DELETE FROM cache WHERE key=?", (key,))
                self._con.commit()
            except sqlite3.OperationalError:
                pass
        return None

    def register(self, key: str, png_path: Path):
        """Record that this key was cached at png_path."""
        try:
            self._con.execute(
                "INSERT OR REPLACE INTO cache (key, path) VALUES (?,?)", (key, str(png_path)))
        except sqlite3.OperationalError:
            pass

    def save(self):
        try:
            self._con.commit()
        except Exception:
            pass


# Module-level singleton; set by ThumbCache after base_dir is known
_global_index: GlobalCacheIndex | None = None


class DiskCache:
    """Simple disk-based thumbnail cache. Stores images keyed by path+mtime+size.

    Dims (original w/h) are stored in a per-project SQLite DB (cache.db) instead
    of index.json. Existing index.json files are migrated on first open.
    """

    def __init__(self, cache_dir: str = None):
        if cache_dir:
            self._dir = Path(cache_dir)
        else:
            self._dir = Path.home() / ".doxyedit" / "thumbcache"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fmt, self._ext = _cache_fmt()  # read once in main thread; update via set_fast_cache()
        self._con = sqlite3.connect(str(self._dir / "cache.db"), check_same_thread=False,
                                     timeout=5)
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS dims (key TEXT PRIMARY KEY, w INTEGER, h INTEGER)"
            " WITHOUT ROWID")
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.execute("PRAGMA busy_timeout=3000")
        self._con.commit()
        self._migrate_json_index()

    def _migrate_json_index(self):
        """One-time migration: import any existing index.json into cache.db."""
        old = self._dir / "index.json"
        if not old.exists():
            return
        try:
            data = json.loads(old.read_text())
            self._con.executemany(
                "INSERT OR IGNORE INTO dims (key, w, h) VALUES (?,?,?)",
                ((k, v.get("w", 0), v.get("h", 0)) for k, v in data.items()))
            self._con.commit()
            old.rename(self._dir / "index.json.bak")
        except Exception:
            pass

    def _get_dims(self, key: str) -> tuple[int, int]:
        try:
            row = self._con.execute("SELECT w, h FROM dims WHERE key=?", (key,)).fetchone()
            return (row[0], row[1]) if row else (0, 0)
        except sqlite3.OperationalError:
            return (0, 0)

    def get(self, path: str, size: int) -> tuple[QImage, int, int] | None:
        """Try to load a cached thumbnail. Returns (qimage, orig_w, orig_h) or None.
        Uses QImage (thread-safe) — caller converts to QPixmap in the GUI thread."""
        key = _cache_key(path, size)
        # Try both extensions so switching modes doesn't break existing caches
        for ext in (_FAST_EXT, _STD_EXT):
            cached_file = self._dir / f"{key}{ext}"
            if cached_file.exists():
                qimg = QImage(str(cached_file))
                if not qimg.isNull():
                    w, h = self._get_dims(key)
                    return qimg, w, h
        # Check cross-project global index
        if _global_index:
            other = _global_index.lookup(key)
            if other:
                qimg = QImage(str(other))
                if not qimg.isNull():
                    w, h = self._get_dims(key)
                    return qimg, w, h
        return None

    def set_fast_cache(self, on: bool):
        """Call from main thread when fast cache setting changes."""
        self._fmt, self._ext = (_FAST_FMT, _FAST_EXT) if on else (_STD_FMT, _STD_EXT)

    def put(self, path: str, size: int, pil_img, orig_w: int, orig_h: int):
        """Save a thumbnail to disk cache using PIL (thread-safe; QPixmap.save is not)."""
        fmt, ext = self._fmt, self._ext
        key = _cache_key(path, size)
        cached_file = self._dir / f"{key}{ext}"
        try:
            save_img = pil_img
            if ext == _FAST_EXT and pil_img.mode == "RGBA":
                save_img = pil_img.convert("RGB")
            save_kwargs = {"compress_level": 1} if fmt == _STD_FMT else {}
            save_img.save(str(cached_file), fmt, **save_kwargs)
        except Exception:
            return
        try:
            self._con.execute(
                "INSERT OR REPLACE INTO dims (key, w, h) VALUES (?,?,?)", (key, orig_w, orig_h))
        except sqlite3.OperationalError:
            pass
        if _global_index:
            _global_index.register(key, cached_file)

    def save_index(self):
        """Flush pending writes."""
        try:
            self._con.commit()
            if _global_index:
                _global_index.save()
        except Exception:
            pass


class ThumbWorker(QThread):
    """Generates thumbnails in a background thread."""
    thumb_ready = Signal(str, QImage, int, int, int)  # QImage is thread-safe; GUI converts to QPixmap
    visual_tags_ready = Signal(str, list)
    palette_ready = Signal(str, list)  # asset_id, list of hex color strings
    phash_ready = Signal(str, str)  # asset_id, hex hash string (64-bit overflows Qt int)

    def __init__(self, disk_cache: DiskCache, parent=None):
        super().__init__(parent)
        self._disk_cache = disk_cache
        self._queue: deque[tuple[str, str, int]] = deque()
        self._mutex = QMutex()
        self._stop = False
        self._save_counter = 0
        self._force_regen: set[str] = set()  # asset IDs that must bypass disk cache
        self._autotag = False  # set True to compute visual tags during generation
        self._upgrade_queue: deque = deque()  # (asset_id, path, size, pil_img, w, h)
        self._slow_queue: deque = deque()     # (asset_id, path, size) — PSD/SAI deferred hi-res

    def enqueue(self, asset_id: str, path: str, size: int = THUMB_SIZE):
        with QMutexLocker(self._mutex):
            self._queue = deque((a, p, s) for a, p, s in self._queue if a != asset_id)
            self._queue.append((asset_id, path, size))

    def enqueue_batch(self, items: list[tuple[str, str, int]], force: bool = False):
        with QMutexLocker(self._mutex):
            existing = {}
            for aid, path, size in self._queue:
                existing[aid] = (path, size)
            for aid, path, size in items:
                existing[aid] = (path, size)
                if force:
                    self._force_regen.add(aid)
            self._queue = deque((aid, p, s) for aid, (p, s) in existing.items())

    def reprioritize(self, priority_ids: set):
        """Move items whose asset_id is in priority_ids to the front of the queue."""
        with QMutexLocker(self._mutex):
            front = deque(item for item in self._queue if item[0] in priority_ids)
            rest  = deque(item for item in self._queue if item[0] not in priority_ids)
            self._queue = front + rest

    def clear_queue(self):
        with QMutexLocker(self._mutex):
            self._queue.clear()
            for item in self._upgrade_queue:
                try:
                    item[3].close()
                except Exception:
                    pass
            self._upgrade_queue.clear()
            self._slow_queue.clear()

    def stop(self):
        self._stop = True

    def run(self):
        while not self._stop:
            # Priority 1: fast previews from main queue
            item = None
            with QMutexLocker(self._mutex):
                if self._queue:
                    item = self._queue.popleft()

            if item is not None:
                try:
                    self._process_item(item)
                except Exception:
                    try:
                        self.thumb_ready.emit(item[0], QImage(), 0, 0, item[2])
                    except Exception:
                        pass
                continue

            # Priority 2: quality upgrades (only when no fast work pending)
            upgrade = None
            with QMutexLocker(self._mutex):
                if self._upgrade_queue:
                    upgrade = self._upgrade_queue.popleft()

            if upgrade is not None:
                try:
                    self._process_upgrade(*upgrade)
                except Exception:
                    try:
                        upgrade[3].close()
                    except Exception:
                        pass
                continue

            # Priority 3: slow formats (PSD/SAI2 via psd_tools) — only when idle
            slow = None
            with QMutexLocker(self._mutex):
                if self._slow_queue:
                    slow = self._slow_queue.popleft()

            if slow is not None:
                try:
                    self._process_slow(*slow)
                except Exception:
                    pass
                continue

            self.msleep(50)

        # Save index on shutdown
        self._disk_cache.save_index()

    def _process_item(self, item: tuple[str, str, int]):
        asset_id, path, target_size = item

        # Try disk cache (skip if force-regen requested for this asset)
        force = asset_id in self._force_regen
        if force:
            self._force_regen.discard(asset_id)
        cached = None if force else self._disk_cache.get(path, target_size)
        if cached:
            qimg, w, h = cached
            self.thumb_ready.emit(asset_id, qimg, w, h, target_size)
            return

        ext = Path(path).suffix.lower()
        is_slow_format = ext in PSD_EXTS or ext in SHELL_THUMB_EXTS

        # For PSD/SAI2: emit shell thumb now, defer psd_tools to after everything else
        if is_slow_format:
            shell_img = get_shell_thumbnail(path, max(target_size, 256))
            if shell_img:
                from PIL import Image as PILImage
                orig_w, orig_h = shell_img.width, shell_img.height
                shell_img.thumbnail((target_size, target_size), PILImage.LANCZOS)
                qimg = pil_to_qimage(shell_img)
                self.thumb_ready.emit(asset_id, qimg, orig_w, orig_h, target_size)
                self._disk_cache.put(path, target_size, shell_img, orig_w, orig_h)
                shell_img.close()
                return
            # Shell failed — emit placeholder now, queue psd_tools for later
            ph_img, _, _ = _make_placeholder(path)
            qimg_ph = pil_to_qimage(ph_img)
            ph_img.close()
            self.thumb_ready.emit(asset_id, qimg_ph, 0, 0, 32)
            with QMutexLocker(self._mutex):
                self._slow_queue.append((asset_id, path, target_size))
            return

        from PIL import Image as PILImage

        img, orig_w, orig_h = open_for_thumb(path, target_size)

        # Fast pass: emit a quick preview at 1/4 target size using NEAREST
        fast_size = max(64, min(160, target_size // 4))
        if target_size > fast_size:
            fast = img.copy()
            fast.thumbnail((fast_size, fast_size), PILImage.NEAREST)
            qimg_fast = pil_to_qimage(fast)
            fast.close()
            self.thumb_ready.emit(asset_id, qimg_fast, orig_w, orig_h, fast_size)

        # Queue quality upgrade — deferred so other fast previews get processed first
        with QMutexLocker(self._mutex):
            self._upgrade_queue.append((asset_id, path, target_size, img, orig_w, orig_h))

    def _process_slow(self, asset_id: str, path: str, target_size: int):
        """Third pass: PSD/SAI2 via psd_tools — only runs when everything else is done."""
        from PIL import Image as PILImage

        ext = Path(path).suffix.lower()
        img, orig_w, orig_h = None, 0, 0

        if ext in PSD_EXTS:
            try:
                result = load_psd_thumb(path, min_size=0)
                if result:
                    img, orig_w, orig_h = result
            except Exception:
                pass

        if img is None:
            return  # nothing we can do — shell already failed, psd_tools failed too

        img.thumbnail((target_size, target_size), PILImage.LANCZOS)
        qimg = pil_to_qimage(img)
        self.thumb_ready.emit(asset_id, qimg, orig_w, orig_h, target_size)
        self._disk_cache.put(path, target_size, img, orig_w, orig_h)
        img.close()

    def _process_upgrade(self, asset_id, path, target_size, img, orig_w, orig_h):
        """Second pass: high-quality resize + disk save."""
        from PIL import Image as PILImage

        img.thumbnail((target_size, target_size), PILImage.LANCZOS)

        if self._autotag:
            try:
                from doxyedit.autotag import compute_visual_tags
                vtags = compute_visual_tags(img)
                if vtags:
                    self.visual_tags_ready.emit(asset_id, vtags)
            except Exception:
                pass

        # Extract dominant colors for palette display
        try:
            from doxyedit.autotag import compute_dominant_colors
            palette = compute_dominant_colors(img, n=5)
            if palette:
                self.palette_ready.emit(asset_id, palette)
        except Exception:
            pass

        # Compute perceptual hash for similarity detection
        try:
            from doxyedit.autotag import compute_phash
            ph = compute_phash(img)
            if ph is not None:
                self.phash_ready.emit(asset_id, hex(ph))
        except Exception:
            pass

        qimg = pil_to_qimage(img)
        self.thumb_ready.emit(asset_id, qimg, orig_w, orig_h, target_size)

        self._disk_cache.put(path, target_size, img, orig_w, orig_h)
        img.close()
        self._save_counter += 1
        if self._save_counter % 20 == 0:
            self._disk_cache.save_index()
            if _global_index:
                _global_index.save()


_LRU_MAX = 2000  # max pixmaps kept in memory — prioritize speed over footprint


def _safe_name(project_name: str) -> str:
    """Sanitize a project name for use as a directory name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project_name).strip('. ')
    return name or "default"


def _migrate_flat_cache(base_dir: Path):
    """Move any loose .png / index.json files in base_dir into a 'default' subfolder."""
    loose_pngs = list(base_dir.glob("*.png"))
    loose_idx = base_dir / "index.json"
    if not loose_pngs and not loose_idx.exists():
        return
    dest = base_dir / "default"
    dest.mkdir(exist_ok=True)
    for f in loose_pngs:
        f.rename(dest / f.name)
    if loose_idx.exists():
        loose_idx.rename(dest / "index.json")


class ThumbCache:
    """Manages memory + disk cache of thumbnails and a background worker."""

    def __init__(self):
        self._lru_max = _LRU_MAX
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._gen_sizes: dict[str, int] = {}
        self._dims: dict[str, tuple[int, int]] = {}
        self._base_cache_dir: Path | None = (
            Path(QSettings("DoxyEdit", "DoxyEdit").value("cache_dir"))
            if QSettings("DoxyEdit", "DoxyEdit").value("cache_dir") else None
        )
        if self._base_cache_dir is None:
            self._base_cache_dir = Path.home() / ".doxyedit" / "thumbcache"
        self._base_cache_dir.mkdir(parents=True, exist_ok=True)
        _migrate_flat_cache(self._base_cache_dir)
        global _global_index
        _global_index = GlobalCacheIndex(self._base_cache_dir)
        self._disk_cache = DiskCache(cache_dir=str(self._base_cache_dir / "default"))
        self._worker = ThumbWorker(self._disk_cache)
        self._worker.start()

    def set_lru_max(self, n: int):
        """Set the max number of pixmaps kept in memory."""
        self._lru_max = max(100, n)

    def set_project(self, project_name: str):
        """Switch disk cache to a per-project subfolder.
        Keeps in-memory cache when the disk folder doesn't change (shared cache)."""
        subfolder = self._base_cache_dir / _safe_name(project_name)
        subfolder.mkdir(parents=True, exist_ok=True)
        same_folder = (subfolder == self._disk_cache._dir)
        # Drain the worker queue before swapping disk cache
        self._worker.clear_queue()
        self._disk_cache.save_index()
        if not same_folder:
            new_disk = DiskCache(cache_dir=str(subfolder))
            self._worker._disk_cache = new_disk
            self._disk_cache = new_disk
            # Different folder — clear in-memory cache to avoid stale thumbnails
            self._pixmaps.clear()
            self._gen_sizes.clear()
            self._dims.clear()

    def get(self, asset_id: str) -> QPixmap | None:
        return self._pixmaps.get(asset_id)

    def get_dims(self, asset_id: str) -> tuple[int, int] | None:
        return self._dims.get(asset_id)

    def invalidate(self, asset_id: str):
        """Remove cached pixmap so the next request regenerates it."""
        self._pixmaps.pop(asset_id, None)
        self._gen_sizes.pop(asset_id, None)
        self._dims.pop(asset_id, None)

    def request(self, asset_id: str, path: str, size: int = THUMB_SIZE):
        if self._gen_sizes.get(asset_id, 0) >= size:
            return
        self._worker.enqueue(asset_id, path, size)

    def request_batch(self, items: list[tuple[str, str]], size: int = THUMB_SIZE,
                      force: bool = False):
        needed = [(aid, path, size) for aid, path in items
                  if force or self._gen_sizes.get(aid, 0) < size]
        if needed:
            if force:
                # Force-regen: invalidate memory cache entries too
                for aid, _, _ in needed:
                    self._pixmaps.pop(aid, None)
                    self._gen_sizes.pop(aid, None)
                self._worker.enqueue_batch(needed, force=True)
            else:
                fresh    = [(a, p, s) for a, p, s in needed if a not in self._gen_sizes]
                upgrades = [(a, p, s) for a, p, s in needed if a in self._gen_sizes]
                self._worker.enqueue_batch(fresh + upgrades)

    def on_ready(self, asset_id: str, img_or_pm, w: int, h: int, gen_size: int) -> bool:
        """Store pixmap. Returns True if this was an upgrade (caller should repaint).
        Accepts QImage (from worker thread) or QPixmap; converts QImage here in the GUI thread."""
        current = self._gen_sizes.get(asset_id, 0)
        if gen_size < current:
            return False  # don't overwrite a higher-res image with a placeholder
        if isinstance(img_or_pm, QImage):
            if img_or_pm.isNull():
                return False  # failed generation — don't mark as done, allow retry
            pixmap = QPixmap.fromImage(img_or_pm)
        else:
            pixmap = img_or_pm
            if pixmap.isNull():
                return False
        self._pixmaps[asset_id] = pixmap
        self._pixmaps.move_to_end(asset_id)
        self._gen_sizes[asset_id] = gen_size
        if w and h:
            self._dims[asset_id] = (w, h)
        # Evict oldest entries if over limit
        while len(self._pixmaps) > self._lru_max:
            evicted = next(iter(self._pixmaps))
            del self._pixmaps[evicted]
            self._gen_sizes.pop(evicted, None)
            self._dims.pop(evicted, None)
        return True

    def clear_queue(self):
        """Stop all pending thumbnail generation without clearing the memory cache."""
        self._worker.clear_queue()

    def reprioritize(self, priority_ids: set):
        """Move the given asset IDs to the front of the generation queue."""
        self._worker.reprioritize(priority_ids)

    def clear(self):
        self._worker.clear_queue()
        self._pixmaps.clear()
        self._gen_sizes.clear()
        self._dims.clear()

    def set_autotag(self, on: bool):
        self._worker._autotag = on

    def connect_ready(self, callback):
        self._worker.thumb_ready.connect(callback)

    def connect_visual_tags(self, callback):
        self._worker.visual_tags_ready.connect(callback)

    def connect_palette(self, callback):
        """Connect to palette_ready signal."""
        self._worker.palette_ready.connect(callback)

    def connect_phash(self, callback):
        """Connect to phash_ready signal."""
        self._worker.phash_ready.connect(callback)

    def shutdown(self):
        self._worker.stop()
        self._worker.wait(3000)
        self._disk_cache.save_index()
        if _global_index:
            _global_index.save()
