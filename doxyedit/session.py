"""Session / project-load threading infrastructure.

Contains the QThread worker that loads a project off the UI thread, plus the
opaque async-load handle used by the splash screen and other callers to
cancel an in-flight load without knowing whether it's a single-project or
collection load.

MainWindow in window.py consumes these classes; the restore methods
themselves remain on MainWindow to keep their access to per-window state
simple. Moving the methods is a follow-up stage.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from doxyedit.models import Project


class AsyncLoadHandle:
    """Opaque handle returned from async restore methods.

    Gives the caller (splash) a way to signal cancel without knowing
    whether a single-project or multi-project load is in flight.
    """

    def __init__(self, loader):
        self._current_loader = loader
        self._cancelled = False
        self._state = None  # optional collection state dict

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        """Request cancel. Safe to call from UI thread at any time."""
        self._cancelled = True
        if self._current_loader is not None:
            try:
                self._current_loader.cancel()
            except Exception:
                pass


class ProjectLoader(QThread):
    """Background loader for Project.load().

    Reads + hydrates JSON off the UI thread. Safe because models.py has no
    Qt imports - Project.from_dict / Project.load is pure data.

    Emit order: either `loaded(project, path)` OR `failed(path, error)` OR
    `cancelled(path)`. The worker self-polls the `_cancel` flag at the two
    coarsest chokepoints: after JSON parse, and just before returning the
    hydrated project. Once emitted, the owner is responsible for discarding
    the result if it arrived after a cancel.
    """

    loaded = Signal(object, str)     # (Project, path)
    failed = Signal(str, str)        # (path, error_message)
    cancelled = Signal(str)          # (path)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @property
    def path(self) -> str:
        return self._path

    def run(self):
        try:
            if self._cancel:
                self.cancelled.emit(self._path)
                return
            # Project.load reads + hydrates in one call. We can't cheaply
            # split it without duplicating the method, so we check cancel
            # once before and once after. The JSON read itself can't be
            # aborted mid-flight, but a 1MB-ish file is ~50ms anyway.
            project = Project.load(self._path)
            if self._cancel:
                self.cancelled.emit(self._path)
                return
            self.loaded.emit(project, self._path)
        except Exception as e:
            self.failed.emit(self._path, str(e))
