"""LazyRefreshMixin — defers panel rebuilds until the parent tab is
visible. The whole "Social tab is fast despite 1k posts" trick lives
here. A regression where mark_stale doesn't stick or refresh_if_stale
fires twice in a row breaks the perf contract MainWindow's
currentChanged handler relies on."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_panel():
    """Build a tiny non-Qt LazyRefreshMixin user that just counts
    refresh() calls."""
    from doxyedit.panel_mixin import LazyRefreshMixin

    class FakePanel(LazyRefreshMixin):
        def __init__(self):
            self.refresh_calls = 0
            self.project = None

        def refresh(self):
            self.refresh_calls += 1

    return FakePanel()


class TestLazyRefreshMixin(unittest.TestCase):
    def test_starts_stale(self):
        p = _make_panel()
        # Default class attribute: stale = True so the first
        # refresh_if_stale always fires.
        self.assertTrue(p._lazy_stale)

    def test_refresh_if_stale_calls_refresh_once(self):
        p = _make_panel()
        p.refresh_if_stale()
        self.assertEqual(p.refresh_calls, 1)

    def test_second_call_skips_refresh(self):
        p = _make_panel()
        p.refresh_if_stale()
        p.refresh_if_stale()
        self.assertEqual(p.refresh_calls, 1)

    def test_mark_stale_re_arms(self):
        p = _make_panel()
        p.refresh_if_stale()
        p.mark_stale()
        p.refresh_if_stale()
        self.assertEqual(p.refresh_calls, 2)

    def test_set_project_stores_and_marks_stale(self):
        p = _make_panel()
        p.refresh_if_stale()  # consumes initial stale
        sentinel = object()
        p.set_project(sentinel)
        self.assertIs(p.project, sentinel)
        self.assertTrue(p._lazy_stale)
        p.refresh_if_stale()
        self.assertEqual(p.refresh_calls, 2)

    def test_no_refresh_method_noop(self):
        """refresh_if_stale must not crash when the subclass forgot to
        define refresh() — the mixin clears the flag and exits silently
        rather than blocking the parent tab transition."""
        from doxyedit.panel_mixin import LazyRefreshMixin

        class NoRefresh(LazyRefreshMixin):
            pass

        p = NoRefresh()
        p.refresh_if_stale()  # must not raise
        self.assertFalse(p._lazy_stale)


if __name__ == "__main__":
    unittest.main()
