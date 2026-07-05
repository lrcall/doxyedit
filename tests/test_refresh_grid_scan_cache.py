"""_refresh_grid full-asset scan cache + mark_mutated coverage (Batch 3).

The starred/tagged counts and the duplicate-group / variant-set /
used-tag indexes are O(all assets) scans that used to run on EVERY
refresh. They are now cached by (id(project), project.version), which
makes every asset/tag/star/specs mutation path responsible for calling
project.mark_mutated(). These tests pin both halves: the cache serves
stale data only until the version bumps, and every user-facing
mutation helper bumps it.
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
def win(qapp, tmp_path):
    from doxyedit.window import MainWindow

    w = MainWindow(_skip_autoload=True)
    w.project = make_project(tmp_path, n_assets=4, with_posts=False)
    for a in w.project.assets:
        a.starred = 0
        a.tags = []
    w.project.mark_mutated()
    w._rebind_project(clear_folder_state=True)
    yield w
    w.close()


def _starred_in_label(win) -> str:
    return win.browser.count_label.text()


def test_scan_cache_keyed_on_version(win):
    win.browser._refresh_grid()
    assert "0★" in _starred_in_label(win)

    # Direct mutation WITHOUT mark_mutated: the cache may serve stale
    # values - this pins the cache key so a future "recompute every
    # refresh" regression (or an over-eager key) shows up here.
    win.project.assets[0].starred = 3
    win.browser._refresh_grid()
    assert "0★" in _starred_in_label(win)

    win.project.mark_mutated()
    win.browser._refresh_grid()
    assert "1★" in _starred_in_label(win)


def test_toggle_star_bumps_version_and_counts(win):
    win.browser._refresh_grid()
    v0 = win.project.version

    win.browser._toggle_star(win.project.assets[0])

    assert win.project.version > v0
    assert "1★" in _starred_in_label(win)

    win.browser._unstar(win.project.assets[0])
    assert "0★" in _starred_in_label(win)


def test_toggle_tag_updates_used_tags(win):
    win.browser._refresh_grid()
    assert "factory" not in win.browser._used_tag_ids

    win.browser._toggle_tag(win.project.assets[0], "factory")

    assert "factory" in win.browser._used_tag_ids
    assert "1 tagged" in _starred_in_label(win)


def test_dissolve_duplicate_group_updates_index(win):
    a0, a1 = win.project.assets[0], win.project.assets[1]
    a0.specs["duplicate_group"] = "dg1"
    a1.specs["duplicate_group"] = "dg1"
    win.project.mark_mutated()
    win.browser._refresh_grid()
    assert win.browser._duplicate_groups.get("dg1") == [a0.id, a1.id]

    win.browser._dissolve_duplicate_group("dg1")

    assert "dg1" not in win.browser._duplicate_groups
    assert not a0.specs.get("duplicate_group")


def test_variant_link_updates_index(win):
    ids = [a.id for a in win.project.assets[:2]]
    win.browser._selected_ids.update(ids)
    win.browser._refresh_grid()

    win.browser._link_selected_as_variants()

    sets = list(win.browser._variant_sets.values())
    assert any(sorted(s) == sorted(ids) for s in sets)


def test_tagpanel_set_tag_bumps_version(qapp, tmp_path):
    from doxyedit.tagpanel import TagPanel

    proj = make_project(tmp_path, n_assets=2, with_posts=False)
    panel = TagPanel()
    panel._project = proj
    panel._assets = list(proj.assets)
    v0 = proj.version

    panel._set_tag("brand_new_tag", True)

    assert proj.version > v0
    assert all("brand_new_tag" in a.tags for a in proj.assets)
    panel.deleteLater()
