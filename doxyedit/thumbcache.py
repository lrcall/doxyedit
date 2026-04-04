"""Background thumbnail generator — loads and scales images off the main thread."""
from collections import deque
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from PySide6.QtGui import QPixmap, QImage
from PIL import Image as PILImage

THUMB_SIZE = 160


class ThumbWorker(QThread):
    """Generates thumbnails in a background thread."""
    thumb_ready = Signal(str, QPixmap, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: deque[tuple[str, str, int]] = deque()
        self._mutex = QMutex()
        self._stop = False

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
            self._queue = [(aid, p, s) for aid, (p, s) in existing.items()]

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
            try:
                with PILImage.open(path) as img:
                    orig_w, orig_h = img.size
                    img.thumbnail((target_size, target_size), PILImage.LANCZOS)
                    if img.mode != "RGBA":
                        img = img.convert("RGBA")
                    data = img.tobytes("raw", "RGBA")
                    qimg = QImage(data, img.width, img.height, img.width * 4,
                                  QImage.Format.Format_RGBA8888).copy()
                    pm = QPixmap.fromImage(qimg)
                    self.thumb_ready.emit(asset_id, pm, orig_w, orig_h, target_size)
            except Exception:
                self.thumb_ready.emit(asset_id, QPixmap(), 0, 0, target_size)


class ThumbCache:
    """Manages a cache of thumbnails and a background worker to generate them.

    Tracks the size at which each thumbnail was generated. If the requested
    display size exceeds the cached size, re-generates at higher resolution.
    """

    def __init__(self):
        self._pixmaps: dict[str, QPixmap] = {}
        self._gen_sizes: dict[str, int] = {}  # asset_id → size it was generated at
        self._dims: dict[str, tuple[int, int]] = {}
        self._worker = ThumbWorker()
        self._worker.start()

    def get(self, asset_id: str) -> QPixmap | None:
        return self._pixmaps.get(asset_id)

    def get_dims(self, asset_id: str) -> tuple[int, int] | None:
        return self._dims.get(asset_id)

    def request(self, asset_id: str, path: str, size: int = THUMB_SIZE):
        cached_size = self._gen_sizes.get(asset_id, 0)
        if cached_size >= size:
            return  # already have a good enough version
        self._worker.enqueue(asset_id, path, size)

    def request_batch(self, items: list[tuple[str, str]], size: int = THUMB_SIZE):
        needed = []
        for aid, path in items:
            cached_size = self._gen_sizes.get(aid, 0)
            if cached_size < size:
                needed.append((aid, path, size))
        if needed:
            self._worker.enqueue_batch(needed)

    def on_ready(self, asset_id: str, pixmap: QPixmap, w: int, h: int, gen_size: int):
        """Called when worker emits — stores in cache."""
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

    def shutdown(self):
        self._worker.stop()
        self._worker.wait(3000)
