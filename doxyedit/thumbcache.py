"""Background thumbnail generator with disk cache for instant reloads."""
import hashlib
import json
import os
from collections import deque
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from PySide6.QtGui import QPixmap, QImage

from doxyedit.imaging import open_for_thumb, pil_to_qpixmap

THUMB_SIZE = 160
CACHE_DIR_NAME = ".doxyedit_cache"


def _cache_key(path: str, size: int) -> str:
    """Generate a cache filename from file path + mtime + size."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    raw = f"{path}|{mtime}|{size}"
    return hashlib.md5(raw.encode()).hexdigest()


class DiskCache:
    """Simple disk-based thumbnail cache. Stores PNGs keyed by path+mtime+size."""

    def __init__(self, cache_dir: str = None):
        if cache_dir:
            self._dir = Path(cache_dir)
        else:
            self._dir = Path.home() / ".doxyedit" / "thumbcache"
        self._dir.mkdir(parents=True, exist_ok=True)
        # Load dims index
        self._index_path = self._dir / "index.json"
        self._index: dict = {}
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text())
            except Exception:
                self._index = {}

    def get(self, path: str, size: int) -> tuple[QPixmap, int, int] | None:
        """Try to load a cached thumbnail. Returns (pixmap, orig_w, orig_h) or None."""
        key = _cache_key(path, size)
        cached_file = self._dir / f"{key}.png"
        if not cached_file.exists():
            return None
        pm = QPixmap(str(cached_file))
        if pm.isNull():
            return None
        dims = self._index.get(key, {})
        return pm, dims.get("w", 0), dims.get("h", 0)

    def put(self, path: str, size: int, pixmap: QPixmap, orig_w: int, orig_h: int):
        """Save a thumbnail to disk cache."""
        key = _cache_key(path, size)
        cached_file = self._dir / f"{key}.png"
        pixmap.save(str(cached_file), "PNG")
        self._index[key] = {"w": orig_w, "h": orig_h}

    def save_index(self):
        """Flush the dims index to disk."""
        try:
            self._index_path.write_text(json.dumps(self._index))
        except Exception:
            pass


class ThumbWorker(QThread):
    """Generates thumbnails in a background thread."""
    thumb_ready = Signal(str, QPixmap, int, int, int)
    visual_tags_ready = Signal(str, list)

    def __init__(self, disk_cache: DiskCache, parent=None):
        super().__init__(parent)
        self._disk_cache = disk_cache
        self._queue: deque[tuple[str, str, int]] = deque()
        self._mutex = QMutex()
        self._stop = False
        self._save_counter = 0

    def enqueue(self, asset_id: str, path: str, size: int = THUMB_SIZE):
        with QMutexLocker(self._mutex):
            self._queue = deque((a, p, s) for a, p, s in self._queue if a != asset_id)
            self._queue.append((asset_id, path, size))

    def enqueue_batch(self, items: list[tuple[str, str, int]]):
        with QMutexLocker(self._mutex):
            existing = {}
            for aid, path, size in self._queue:
                existing[aid] = (path, size)
            for aid, path, size in items:
                existing[aid] = (path, size)
            self._queue = deque((aid, p, s) for aid, (p, s) in existing.items())

    def clear_queue(self):
        with QMutexLocker(self._mutex):
            self._queue.clear()

    def stop(self):
        self._stop = True

    def run(self):
        while not self._stop:
            item = None
            with QMutexLocker(self._mutex):
                if self._queue:
                    item = self._queue.popleft()

            if item is None:
                self.msleep(50)
                continue

            asset_id, path, target_size = item

            # Try disk cache first
            cached = self._disk_cache.get(path, target_size)
            if cached:
                pm, w, h = cached
                self.thumb_ready.emit(asset_id, pm, w, h, target_size)
                continue

            # Generate from source
            try:
                from PIL import Image as PILImage
                img, orig_w, orig_h = open_for_thumb(path, target_size)

                # Compute visual tags before thumbnailing
                try:
                    from doxyedit.autotag import compute_visual_tags
                    vtags = compute_visual_tags(img)
                    if vtags:
                        self.visual_tags_ready.emit(asset_id, vtags)
                except Exception:
                    pass

                img.thumbnail((target_size, target_size), PILImage.LANCZOS)
                pm = pil_to_qpixmap(img)
                img.close()

                # Save to disk cache
                if not pm.isNull():
                    self._disk_cache.put(path, target_size, pm, orig_w, orig_h)
                    self._save_counter += 1
                    if self._save_counter % 20 == 0:
                        self._disk_cache.save_index()

                self.thumb_ready.emit(asset_id, pm, orig_w, orig_h, target_size)
            except Exception:
                self.thumb_ready.emit(asset_id, QPixmap(), 0, 0, target_size)

        # Save index on shutdown
        self._disk_cache.save_index()


class ThumbCache:
    """Manages memory + disk cache of thumbnails and a background worker."""

    def __init__(self):
        self._pixmaps: dict[str, QPixmap] = {}
        self._gen_sizes: dict[str, int] = {}
        self._dims: dict[str, tuple[int, int]] = {}
        from PySide6.QtCore import QSettings
        cache_dir = QSettings("DoxyEdit", "DoxyEdit").value("cache_dir", None)
        self._disk_cache = DiskCache(cache_dir=cache_dir)
        self._worker = ThumbWorker(self._disk_cache)
        self._worker.start()

    def get(self, asset_id: str) -> QPixmap | None:
        return self._pixmaps.get(asset_id)

    def get_dims(self, asset_id: str) -> tuple[int, int] | None:
        return self._dims.get(asset_id)

    def request(self, asset_id: str, path: str, size: int = THUMB_SIZE):
        if self._gen_sizes.get(asset_id, 0) >= size:
            return
        self._worker.enqueue(asset_id, path, size)

    def request_batch(self, items: list[tuple[str, str]], size: int = THUMB_SIZE):
        needed = [(aid, path, size) for aid, path in items
                  if self._gen_sizes.get(aid, 0) < size]
        if needed:
            # Prioritize: never-cached first, then upgrades (already have smaller version)
            fresh = [(a, p, s) for a, p, s in needed if a not in self._gen_sizes]
            upgrades = [(a, p, s) for a, p, s in needed if a in self._gen_sizes]
            self._worker.enqueue_batch(fresh + upgrades)

    def on_ready(self, asset_id: str, pixmap: QPixmap, w: int, h: int, gen_size: int):
        self._pixmaps[asset_id] = pixmap
        self._gen_sizes[asset_id] = gen_size
        if w and h:
            self._dims[asset_id] = (w, h)

    def clear(self):
        self._worker.clear_queue()
        self._pixmaps.clear()
        self._gen_sizes.clear()
        self._dims.clear()

    def connect_ready(self, callback):
        self._worker.thumb_ready.connect(callback)

    def connect_visual_tags(self, callback):
        self._worker.visual_tags_ready.connect(callback)

    def shutdown(self):
        self._worker.stop()
        self._worker.wait(3000)
        self._disk_cache.save_index()
