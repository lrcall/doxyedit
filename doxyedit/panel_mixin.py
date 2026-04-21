"""Mixin for panels that can defer refresh until they become visible.

Usage pattern:

    class MyPanel(LazyRefreshMixin, QWidget):
        def __init__(self, project, parent=None):
            super().__init__(parent)
            self.project = project
            # ... build UI ...

        def refresh(self):
            # heavy rebuild code
            ...

    panel = MyPanel(project)
    panel.set_project(new_project)       # cheap: stores ref, marks stale
    panel.refresh_if_stale()              # no-op if fresh, else calls refresh()

MainWindow wires `self.tabs.currentChanged` to a handler that calls
`refresh_if_stale()` on every registered lazy panel whose parent tab just
became visible. External mutations (tag change, star change, etc.) can call
`mark_stale()` on any panel; it'll re-refresh on the next tab activation.
"""
from __future__ import annotations


class LazyRefreshMixin:
    """Deferred-refresh contract.

    Panels that mix this in promise:
    - `set_project(project)` stores the project and marks self stale.
    - `refresh()` does the rebuild (implemented by the panel).
    - `mark_stale()` flips the stale flag without refreshing.
    - `refresh_if_stale()` is a no-op when fresh, calls refresh() otherwise.
    """

    _lazy_stale: bool = True

    def set_project(self, project) -> None:  # type: ignore[no-untyped-def]
        self.project = project
        self._lazy_stale = True

    def mark_stale(self) -> None:
        self._lazy_stale = True

    def refresh_if_stale(self) -> None:
        if self._lazy_stale:
            self._lazy_stale = False
            refresh = getattr(self, "refresh", None)
            if callable(refresh):
                refresh()
