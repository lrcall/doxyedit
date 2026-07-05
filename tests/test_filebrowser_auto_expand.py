"""FileBrowserPanel._auto_expand contract (Batch 3).

Expanding the tree walks the QFileSystemModel path chain with
GUI-thread directory scans (measured up to 8.4s on Dropbox). The
expand must therefore (a) be memoized on the resolved target so
repeat rebinds are free, (b) run deferred via QTimer so the rebind
paints first, and (c) the model must not install filesystem watchers.
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
def panel(qapp):
    from doxyedit.filebrowser import FileBrowserPanel

    p = FileBrowserPanel()
    yield p
    p.deleteLater()


def _count_expands(panel) -> dict:
    counter = {"n": 0, "targets": []}
    orig = panel._expand_to

    def counting(target):
        counter["n"] += 1
        counter["targets"].append(target)
        return orig(target)

    panel._expand_to = counting
    return counter


def test_no_filesystem_watchers(panel):
    from PySide6.QtWidgets import QFileSystemModel

    assert panel._model.testOption(
        QFileSystemModel.Option.DontWatchForChanges)


def test_auto_expand_deferred_and_memoized(panel, qapp, tmp_path):
    proj = make_project(tmp_path, n_assets=2, with_posts=False)
    expands = _count_expands(panel)

    panel.set_project(proj)
    assert expands["n"] == 0, "expand must be deferred, not synchronous"
    qapp.processEvents()
    assert expands["n"] == 1

    # Rebind with the same project: same target -> no second expand,
    # not even a scheduled one.
    panel.set_project(proj)
    qapp.processEvents()
    assert expands["n"] == 1


def test_auto_expand_reruns_when_target_changes(panel, qapp, tmp_path):
    proj_a = make_project(tmp_path / "a", n_assets=1, with_posts=False)
    proj_b = make_project(tmp_path / "b", n_assets=1, with_posts=False)
    expands = _count_expands(panel)

    panel.set_project(proj_a)
    qapp.processEvents()
    panel.set_project(proj_b)
    qapp.processEvents()

    assert expands["n"] == 2
    assert expands["targets"][0] != expands["targets"][1]
