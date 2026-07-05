"""GlobalCacheIndex eviction (Batch 3) - the last unbounded cache.

The cross-project thumb index grew forever (one row per
path+mtime+size forever, including rows for files that no longer
exist). It now stamps registration order and evicts oldest rows once
past a row budget, checked periodically from the worker thread.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest


@pytest.fixture
def fake_clock(monkeypatch):
    """Monotonic fake time so same-second registers stay ordered."""
    import doxyedit.thumbcache as tc

    state = {"t": 1_000_000}

    def tick():
        state["t"] += 1
        return state["t"]

    monkeypatch.setattr(tc.time, "time", tick)
    return state


def _rows(idx) -> list[str]:
    return [r[0] for r in
            idx._con.execute("SELECT key FROM cache ORDER BY ts").fetchall()]


def test_evicts_oldest_past_budget(tmp_path, fake_clock):
    from doxyedit.thumbcache import GlobalCacheIndex

    idx = GlobalCacheIndex(tmp_path, max_rows=10, keep_rows=5)
    for i in range(12):
        idx.register(f"key{i:02d}", tmp_path / f"{i}.png")
    idx._con.commit()

    idx.evict_if_needed()

    assert _rows(idx) == [f"key{i:02d}" for i in range(7, 12)], (
        "newest keep_rows entries must survive, oldest go")


def test_no_eviction_under_budget(tmp_path, fake_clock):
    from doxyedit.thumbcache import GlobalCacheIndex

    idx = GlobalCacheIndex(tmp_path, max_rows=10, keep_rows=5)
    for i in range(8):
        idx.register(f"key{i}", tmp_path / f"{i}.png")
    idx._con.commit()

    idx.evict_if_needed()

    assert len(_rows(idx)) == 8


def test_legacy_schema_without_ts_migrates(tmp_path, fake_clock):
    """A pre-eviction content_index.db (no ts column) must open cleanly;
    legacy rows count as oldest and are evicted first."""
    db = tmp_path / "content_index.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE cache (key TEXT PRIMARY KEY, path TEXT) WITHOUT ROWID")
    con.executemany(
        "INSERT INTO cache (key, path) VALUES (?,?)",
        [(f"legacy{i}", f"/old/{i}.png") for i in range(6)])
    con.commit()
    con.close()

    from doxyedit.thumbcache import GlobalCacheIndex

    idx = GlobalCacheIndex(tmp_path, max_rows=8, keep_rows=4)
    for i in range(4):
        idx.register(f"new{i}", tmp_path / f"{i}.png")
    idx._con.commit()

    idx.evict_if_needed()

    survivors = _rows(idx)
    assert len(survivors) == 4
    assert all(k.startswith("new") for k in survivors)
