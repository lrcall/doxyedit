"""_rebind_project must NOT clear browser._stat_cache.

The stat cache maps source_path -> (mtime, size) and is keyed on the
FILE, not the project - it is valid across rebinds and tab switches.
Clearing it on every rebind forced a full re-stat storm (67k
GUI-thread os.stat calls on Dropbox paths, several seconds) the next
time a Newest/Oldest/Largest/Smallest sort ran.
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

from tests.factory import make_project


@pytest.fixture
def win(qapp):
    from doxyedit.window import MainWindow

    w = MainWindow(_skip_autoload=True)
    yield w
    w.close()


def test_rebind_preserves_stat_cache(win, tmp_path):
    win.browser._stat_cache["G:/some/file.png"] = (1234.5, 999)

    win.project = make_project(tmp_path, n_assets=1, with_posts=False)
    win._rebind_project(clear_folder_state=True)

    assert win.browser._stat_cache.get("G:/some/file.png") == (1234.5, 999)


def test_stat_sort_reuses_cached_stats(win, tmp_path):
    """A stat-sorted refresh must consult the cache instead of re-statting
    paths it has already seen (the cache entry wins over the real file)."""
    win.project = make_project(tmp_path, n_assets=2, with_posts=False)
    win._rebind_project(clear_folder_state=True)

    paths = [a.source_path for a in win.project.assets]
    # Poison the cache with fake stats; if _compute_filtered re-stats,
    # sorting would use real (different) mtimes and this stays unused.
    win.browser._stat_cache[paths[0]] = (100.0, 10)
    win.browser._stat_cache[paths[1]] = (200.0, 20)

    real_stat = os.stat
    stat_calls = []

    def spy_stat(p, *a, **k):
        stat_calls.append(str(p))
        return real_stat(p, *a, **k)

    import doxyedit.browser as browser_mod

    orig = browser_mod.os.stat
    browser_mod.os.stat = spy_stat
    try:
        idx = win.browser.sort_combo.findText("Newest")
        assert idx >= 0
        win.browser.sort_combo.setCurrentIndex(idx)
        win.browser._refresh_grid()
    finally:
        browser_mod.os.stat = orig

    assert not [p for p in stat_calls if p in paths], (
        "cached paths were re-statted")
