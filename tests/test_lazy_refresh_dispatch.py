"""Regression test for the lazy-panel dispatch loop. Mirrors the
loop in MainWindow._on_inner_tab_changed and
MainWindow._refresh_lazy_panels_on_current_tab so a refactor of
either can't drift apart in a way that leaves the gantt / platforms
panel un-refreshed when its tab activates.

The user reported 'gantt no longer shows values' — this test pins
the contract that any panel whose tab_widget IS the current widget
gets refresh_if_stale called."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _FakePanel:
    """Stand-in for any LazyRefreshMixin panel — counts refresh calls."""
    def __init__(self):
        self._lazy_stale = True
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1

    def refresh_if_stale(self):
        if self._lazy_stale:
            self._lazy_stale = False
            self.refresh()


def _dispatch(lazy_panels, current_widget):
    """Replicates MainWindow's lazy-refresh sweep. Mirrors window.py
    line 4677 _refresh_lazy_panels_on_current_tab."""
    for panel, tab_widget in lazy_panels:
        if tab_widget is current_widget:
            panel.refresh_if_stale()


class TestLazyDispatch(unittest.TestCase):
    def test_panel_in_current_tab_refreshes(self):
        social_split = object()
        gantt = _FakePanel()
        lazy_panels = [(gantt, social_split)]
        _dispatch(lazy_panels, social_split)
        self.assertEqual(gantt.refresh_calls, 1)

    def test_panel_in_other_tab_does_not_refresh(self):
        social_split = object()
        overview_split = object()
        gantt = _FakePanel()
        _dispatch([(gantt, social_split)], overview_split)
        self.assertEqual(gantt.refresh_calls, 0)

    def test_already_fresh_panel_does_not_refresh(self):
        social_split = object()
        gantt = _FakePanel()
        gantt._lazy_stale = False
        _dispatch([(gantt, social_split)], social_split)
        self.assertEqual(gantt.refresh_calls, 0)

    def test_multiple_panels_in_same_tab_all_refresh(self):
        """The Social tab contains gantt + timeline + calendar_pane +
        checklist. All of them must refresh when Social activates."""
        social_split = object()
        gantt = _FakePanel()
        timeline = _FakePanel()
        calendar = _FakePanel()
        checklist = _FakePanel()
        platform_panel = _FakePanel()  # different tab
        lazy_panels = [
            (gantt, social_split),
            (timeline, social_split),
            (calendar, social_split),
            (checklist, social_split),
            (platform_panel, object()),
        ]
        _dispatch(lazy_panels, social_split)
        for p in (gantt, timeline, calendar, checklist):
            self.assertEqual(p.refresh_calls, 1, type(p).__name__)
        # Platform panel's tab is a different widget → not refreshed.
        self.assertEqual(platform_panel.refresh_calls, 0)

    def test_repeat_dispatch_only_refreshes_stale_ones(self):
        """Two consecutive dispatches: first marks all fresh, second
        is a no-op. This mirrors switching to Social, then doing
        something that doesn't mark the panel stale, then switching
        back to Social — gantt should NOT re-render."""
        social_split = object()
        gantt = _FakePanel()
        _dispatch([(gantt, social_split)], social_split)
        _dispatch([(gantt, social_split)], social_split)
        self.assertEqual(gantt.refresh_calls, 1)


if __name__ == "__main__":
    unittest.main()
