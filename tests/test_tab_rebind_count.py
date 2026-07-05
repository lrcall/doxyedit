"""Rebind-count contracts for tab management + collection restore.

_rebind_project is the expensive launch path (apply_theme + thumbcache
swap + full browser refresh; 0.4-1.2s on real projects per perf.log).
Before Batch 3, every _add_project_tab ran TWO full rebinds (the
unblocked setCurrentIndex fired _on_proj_tab_changed -> _switch_to_slot,
then _add_project_tab called _switch_to_slot again explicitly), and
collection restore ran 2N+1 rebinds for N projects. These tests pin
the allowed rebind count per operation so the N+1 can't come back.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from PySide6.QtCore import QObject, Signal

from tests.factory import make_project, make_saved_project


@pytest.fixture
def win(qapp):
    from doxyedit.window import MainWindow

    w = MainWindow(_skip_autoload=True)
    yield w
    w.close()


def _count_calls(obj, name: str) -> dict:
    """Wrap obj.<name> with a counting shim. Returns the counter dict."""
    counter = {"n": 0}
    orig = getattr(obj, name)

    def counting(*args, **kwargs):
        counter["n"] += 1
        return orig(*args, **kwargs)

    setattr(obj, name, counting)
    return counter


class _SyncLoader(QObject):
    """ProjectLoader stand-in: loads synchronously inside start() so the
    collection chain completes without an event loop or worker thread."""

    loaded = Signal(object, str)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path

    def start(self):
        from doxyedit.models import Project

        try:
            proj = Project.load(self._path)
        except Exception as e:  # corrupt / unreadable file
            self.failed.emit(self._path, str(e))
            return
        self.loaded.emit(proj, self._path)


def test_add_tab_switch_runs_exactly_one_rebind(win, tmp_path):
    rebinds = _count_calls(win, "_rebind_project")
    proj = make_project(tmp_path, n_assets=1, with_posts=False)

    win._add_project_tab(proj, None, "P2")

    assert rebinds["n"] == 1
    assert win._current_slot == 1
    assert win.project is proj
    assert win._proj_tab_bar.count() == 2
    assert win._proj_tab_bar.currentIndex() == 1


def test_add_tab_no_switch_runs_zero_rebinds(win, tmp_path):
    rebinds = _count_calls(win, "_rebind_project")
    before = win.project
    proj = make_project(tmp_path, n_assets=1, with_posts=False)

    win._add_project_tab(proj, None, "P2", switch=False)

    assert rebinds["n"] == 0
    assert win._current_slot == 0
    assert win.project is before
    assert win._proj_tab_bar.count() == 2
    assert win._proj_tab_bar.currentIndex() == 0
    assert win._project_slots[1]["project"] is proj
    assert win._project_slots[1]["label"] == "P2"


def test_close_tab_runs_exactly_one_rebind(win, tmp_path):
    proj = make_project(tmp_path, n_assets=1, with_posts=False)
    win._add_project_tab(proj, None, "P2")
    rebinds = _count_calls(win, "_rebind_project")

    win._close_proj_tab(1)

    assert rebinds["n"] == 1
    assert win._current_slot == 0
    assert win._proj_tab_bar.count() == 1


def test_collection_restore_runs_exactly_one_rebind(win, tmp_path, monkeypatch):
    """N projects restored => ONE full rebind (the slot-0 seed), no
    redundant second _apply_theme, all N tabs present, slot 0 active."""
    import doxyedit.window as window_mod

    monkeypatch.setattr(window_mod, "ProjectLoader", _SyncLoader)

    paths = []
    for i in range(3):
        d = tmp_path / f"proj{i}"
        d.mkdir()
        _, p = make_saved_project(
            d, n_assets=1, with_posts=False,
            name=f"Coll {i}", filename=f"coll{i}.doxy")
        paths.append(str(p))
    coll = tmp_path / "restore.doxycol"
    coll.write_text(json.dumps({"projects": paths}), encoding="utf-8")

    rebinds = _count_calls(win, "_rebind_project")
    themes = _count_calls(win, "_apply_theme")

    assert win._restore_collection_async(str(coll)) is True

    assert rebinds["n"] == 1
    # _rebind_project applies the theme internally; the restore path
    # must not apply it a second time on top.
    assert themes["n"] == 1
    assert win._proj_tab_bar.count() == 3
    assert win._current_slot == 0
    assert win.project.name == "Coll 0"
    assert [s["label"] for s in win._project_slots] == [
        "coll0", "coll1", "coll2"]


def test_collection_restore_first_path_corrupt_still_seeds_slot0(
        win, tmp_path, monkeypatch):
    """If path 0 fails to load, the first SUCCESSFUL project must seed
    slot 0 (pre-Batch-3 the seed was keyed on index==0, leaving the
    blank startup project visible in slot 0)."""
    import doxyedit.window as window_mod

    monkeypatch.setattr(window_mod, "ProjectLoader", _SyncLoader)
    # _finalize pops a modal "some projects failed" warning - would hang
    # the offscreen run.
    monkeypatch.setattr(window_mod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))

    bad = tmp_path / "corrupt.doxy"
    bad.write_text("{not valid json", encoding="utf-8")
    d = tmp_path / "good"
    d.mkdir()
    _, good = make_saved_project(
        d, n_assets=1, with_posts=False, name="Good", filename="good.doxy")
    coll = tmp_path / "restore.doxycol"
    coll.write_text(
        json.dumps({"projects": [str(bad), str(good)]}), encoding="utf-8")

    assert win._restore_collection_async(str(coll)) is True

    assert win._current_slot == 0
    assert win.project.name == "Good"
    assert win._proj_tab_bar.count() == 1
