"""ThumbCache / DiskCache GUI-thread commit contract (Batch 3).

set_project runs inside _rebind_project on the GUI thread. It must not
pay sqlite costs there: DiskCache connects lazily (first worker-side
get/put), save_index is a no-op when nothing was written, and the
shared-cache rebind path delegates the flush to the worker thread.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from PIL import Image


def test_diskcache_connects_lazily(tmp_path):
    from doxyedit.thumbcache import DiskCache

    dc = DiskCache(cache_dir=str(tmp_path / "cache"))
    assert not (tmp_path / "cache" / "cache.db").exists(), (
        "constructing DiskCache must not open sqlite")

    dc.save_index()  # no connection, no writes -> must stay lazy
    assert not (tmp_path / "cache" / "cache.db").exists()

    img = Image.new("RGB", (4, 4), (10, 20, 30))
    dc.put(str(tmp_path / "src.png"), 160, img, 4, 4)
    img.close()
    assert (tmp_path / "cache" / "cache.db").exists()


def test_diskcache_save_index_skips_when_clean(tmp_path):
    from doxyedit.thumbcache import DiskCache

    dc = DiskCache(cache_dir=str(tmp_path / "cache"))
    img = Image.new("RGB", (4, 4), (10, 20, 30))
    dc.put(str(tmp_path / "src.png"), 160, img, 4, 4)
    img.close()

    assert dc._pending_writes == 1
    dc.save_index()
    assert dc._pending_writes == 0

    # Round-trip proves the commit landed.
    got = dc.get(str(tmp_path / "src.png"), 160)
    assert got is not None
    _qimg, w, h = got
    assert (w, h) == (4, 4)


@pytest.fixture
def thumb_cache(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    QSettings("DoxyEdit", "DoxyEdit").setValue(
        "cache_dir", str(tmp_path / "thumbcache"))
    from doxyedit.thumbcache import ThumbCache

    tc = ThumbCache()
    yield tc
    tc._worker.stop()
    tc._worker.wait(3000)
    QSettings("DoxyEdit", "DoxyEdit").remove("cache_dir")


def test_set_project_same_folder_flushes_on_worker(thumb_cache):
    from PySide6.QtGui import QPixmap

    tc = thumb_cache
    tc.set_project("projA")
    disk = tc._disk_cache
    tc._pixmaps["asset_1"] = QPixmap()

    flushes = []
    tc._worker.request_flush = lambda: flushes.append(True)
    gui_saves = []
    disk.save_index = lambda: gui_saves.append(True)

    tc.set_project("projA")  # same folder: the common rebind path

    assert tc._disk_cache is disk, "no swap on same-folder rebind"
    assert "asset_1" in tc._pixmaps, "memory cache must survive"
    assert flushes, "flush must be delegated to the worker"
    assert not gui_saves, "no GUI-thread save_index on same-folder rebind"


def test_set_project_new_folder_swaps_and_clears(thumb_cache):
    from PySide6.QtGui import QPixmap

    tc = thumb_cache
    tc.set_project("projA")
    tc._pixmaps["asset_1"] = QPixmap()
    tc._gen_sizes["asset_1"] = 160

    tc.set_project("projB")

    assert tc._disk_cache._dir.name == "projB"
    assert tc._worker._disk_cache is tc._disk_cache
    assert not tc._pixmaps and not tc._gen_sizes
