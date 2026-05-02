# DoxyEdit Performance Optimization Roadmap

## Current Architecture (v0.5)

- **Thumbnail grid**: `QGridLayout` with `ThumbnailWidget` (QFrame + 5 child widgets each)
- **Paging**: 100 per page, destroys/recreates all widgets on page change
- **Thumb generation**: background `QThread` with PIL, results cached to disk
- **Filtering/sorting**: recomputes on every filter change

## Done

- [x] Background thread thumbnail generation (thumbcache.py)
- [x] Disk cache with MD5 keys (persistent across sessions)
- [x] Paged display (configurable 50-500 per page)
- [x] `setUpdatesEnabled(False/True)` during grid rebuild
- [x] `setParent(None)` for immediate widget cleanup
- [x] Removed grid rebuild on tag changes
- [x] Single-pass tag discovery
- [x] Set-based selected IDs for O(1) lookup
- [x] Lazy dict index for `Project.get_asset()`
- [x] Deque for thumb worker queue
- [x] "Cache All" checkbox to pre-generate all thumbnails

## High Impact — Future

### 1. QListView + QStyledItemDelegate (v1.0)
**Impact: 10x+ speedup for grid display**

Replace `QGridLayout` of 100 `ThumbnailWidget` frames with a single `QListView` in `IconMode` + custom delegate.

- Qt's model-view only paints visible items (virtual scrolling)
- No widget creation/destruction — just paint calls
- Handles 1000+ items with no paging needed
- Selection, keyboard nav, drag-drop built in

**Effort**: Large refactor. Need `QAbstractListModel`, custom `QStyledItemDelegate` for painting thumbnails + dots + stars + names, and role-based data access.

### 2. OpenGL Viewport
**Impact: 2-3x rendering speedup**

```python
from PySide6.QtOpenGLWidgets import QOpenGLWidget
view.setViewport(QOpenGLWidget())
```

GPU-accelerated rendering for the grid. Simple one-liner but requires OpenGL support.

### 3. Thumbnail Atlas / Sprite Sheet
**Impact: Reduced memory, faster blitting**

Instead of 100 separate QPixmaps, pack thumbnails into a single large texture/pixmap and blit regions. Reduces draw calls and memory fragmentation.

### 4. Incremental Filtering
**Impact: Faster filter/sort**

Cache sorted lists and filter incrementally instead of re-sorting on every keystroke. Use a debounce timer on search input (already partially done with resize debounce).

### 5. Lazy Dimension Loading
**Impact: Faster initial import**

Don't read image dimensions on import. Read them in the thumb worker alongside thumbnail generation. Already partially done (thumbcache reports dims).

### 6. Connection Pooling for Signals
**Impact: Reduced overhead**

Each thumbnail connects 4 signals. With 100 thumbnails that's 400 signal connections created and destroyed per page. A single signal mapper or event filter would reduce this.

## Low Priority

- QWaitCondition instead of busy-poll in thumb worker (saves CPU when idle)
- LRU eviction for in-memory pixmap cache (saves RAM with huge projects)
- Stat syscall caching for sort-by-date/size (avoid repeated OS calls)
- Pre-scaled pixmap cache keyed by (asset_id, display_size)
- Batch QSettings writes instead of per-change
