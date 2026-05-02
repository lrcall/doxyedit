"""DoxyEdit main entry point."""
import sys
import traceback
import logging
import faulthandler
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
)
from PySide6.QtGui import QFont, QIcon
from PySide6.QtCore import Qt, QTimer, QEventLoop, QSettings, QObject, QEvent
from doxyedit.themes import THEMES, DEFAULT_THEME
from doxyedit.window import MainWindow

_LOG_PATH = Path.home() / ".doxyedit" / "doxyedit.log"
_FAULT_PATH = Path.home() / ".doxyedit" / "faulthandler.log"
_RUNNING_LOCK = Path.home() / ".doxyedit" / "running.lock"
_AUTOLOAD_HARD_TIMEOUT_S = 60.0


class _WindowMemoryFilter(QObject):
    """App-wide geometry persistence for every top-level window.

    Hooks QShowEvent / QResizeEvent / QMoveEvent on QWidgets that are
    their own window (QDialog, popup tools, the main window itself).
    Saves geometry under a key derived from the widget's objectName,
    or its class name as a fallback. Subsequent shows of the same
    window class restore the saved geometry without each dialog
    needing to wire up its own _GEOM_KEY plumbing.

    Key per widget: "win_geom/<objectName-or-className>"
    """

    _SAVE_DEBOUNCE_MS = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qs = QSettings("DoxyEdit", "DoxyEdit")
        # Per-widget pending-save timer to avoid registry spam during drag.
        self._pending: dict[int, QTimer] = {}
        # Track widgets we've already restored once this session so we
        # don't fight a widget that programmatically resizes itself
        # mid-show.
        self._restored: set[int] = set()
        # One-time cleanup: an earlier version of this filter persisted
        # geometry for QMenu / tooltip popups, which then made every
        # right-click menu open at the same restored size + position.
        # Wipe those stray keys so the new filter (which skips popups)
        # has a clean slate.
        for stale in ("win_geom/QMenu", "win_geom/QToolTip",
                      "win_geom/QFrame",
                      "win_geom/QComboBoxPrivateContainer"):
            try:
                self._qs.remove(stale)
            except Exception:
                pass

    @staticmethod
    def _key_for(widget) -> str:
        from PySide6.QtWidgets import QWidget
        if not isinstance(widget, QWidget):
            return ""
        # Prefer objectName so renames don't lose user state. Fall back
        # to the class name when objectName isn't set.
        name = widget.objectName() or widget.__class__.__name__
        if not name or name == "QWidget":
            return ""
        return f"win_geom/{name}"

    def _schedule_save(self, widget):
        from PySide6.QtCore import QTimer
        wid = id(widget)
        timer = self._pending.get(wid)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(self._SAVE_DEBOUNCE_MS)
            timer.timeout.connect(lambda w=widget: self._save_now(w))
            self._pending[wid] = timer
        timer.start()

    def _save_now(self, widget):
        try:
            key = self._key_for(widget)
            if not key:
                return
            # Don't save degenerate sizes (minimized / not laid out yet).
            if widget.width() < 50 or widget.height() < 50:
                return
            self._qs.setValue(key, widget.saveGeometry())
        except Exception:
            pass

    def _maybe_restore(self, widget):
        wid = id(widget)
        if wid in self._restored:
            return
        try:
            key = self._key_for(widget)
            if not key:
                return
            blob = self._qs.value(key, None)
            if blob:
                widget.restoreGeometry(blob)
            self._restored.add(wid)
        except Exception:
            pass

    @staticmethod
    def _is_persistable_window(widget) -> bool:
        """Only QDialog / QMainWindow style windows should remember
        geometry. Skip popups (QMenu, tooltips, combobox dropdowns) -
        they're transient and should be positioned by Qt at the
        cursor or anchor, never restored from disk."""
        from PySide6.QtWidgets import QWidget, QDialog, QMainWindow
        if not isinstance(widget, QWidget):
            return False
        # Class-name skip-list catches Qt's transient widget classes.
        cls = widget.__class__.__name__
        if cls in {"QMenu", "QToolTip", "QComboBoxPrivateContainer",
                   "QCompleterPrivate", "QFrame"}:
            return False
        # Window-type flag screen: anything tagged Popup/ToolTip/SplashScreen
        # is transient by design.
        try:
            wt = widget.windowType()
        except Exception:
            return False
        if wt in (Qt.WindowType.Popup, Qt.WindowType.ToolTip,
                  Qt.WindowType.SplashScreen, Qt.WindowType.Drawer,
                  Qt.WindowType.Sheet):
            return False
        # Only persist genuine user-facing windows.
        return isinstance(widget, (QDialog, QMainWindow)) or wt == Qt.WindowType.Window

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            # Only act on top-level widgets - the things with their own
            # frame that the user perceives as "windows".
            if (t in (QEvent.Type.Show, QEvent.Type.Move, QEvent.Type.Resize)
                    and obj.isWidgetType()
                    and obj.isWindow()
                    and self._is_persistable_window(obj)):
                if t == QEvent.Type.Show:
                    self._maybe_restore(obj)
                else:
                    self._schedule_save(obj)
        except Exception:
            pass
        return False


def _previous_launch_crashed() -> bool:
    """True if the running-lock sentinel from the previous launch is still
    on disk - i.e. the prior process didn't reach its closeEvent (kill,
    OOM, segfault). Used to default the splash to skip-autoload so a bad
    project file or a stuck filesystem can't trap us in a hang loop."""
    try:
        return _RUNNING_LOCK.exists()
    except Exception:
        return False


def _arm_running_lock():
    try:
        _RUNNING_LOCK.parent.mkdir(parents=True, exist_ok=True)
        _RUNNING_LOCK.write_text(str(int(__import__('time').time())), encoding="utf-8")
    except Exception:
        pass


def _release_running_lock():
    try:
        _RUNNING_LOCK.unlink(missing_ok=True)
    except Exception:
        pass

def _setup_logging():
    """File logger for all warnings/errors — survives windowless mode."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(_LOG_PATH),
            level=logging.WARNING,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Catch native segfaults that bypass sys.excepthook. File is kept open
        # for the lifetime of the process so the kernel can flush on crash.
        _fh = open(str(_FAULT_PATH), "a", buffering=1, encoding="utf-8")
        _fh.write(f"\n=== faulthandler armed {Path(__file__).name} ===\n")
        faulthandler.enable(file=_fh, all_threads=True)
        # Defensive: deep recursion has bitten us (browser._mark_dirty self-call).
        # Lift the cap modestly so the next case still raises but doesn't exhaust
        # the stack mid-paint.
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 3000))
    except Exception as e:
        print(f"Logging setup failed: {e}", file=sys.stderr)

def _install_exception_hook():
    """Catch unhandled exceptions: log to file + show in status bar."""
    _orig = sys.excepthook
    def _hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Unhandled exception:\n%s", msg)
        # Show short message in status bar if window exists
        try:
            for w in QApplication.topLevelWidgets():
                if hasattr(w, 'status'):
                    short = f"Error: {exc_type.__name__}: {exc_value}"
                    w.status.showMessage(short, 10000)
                    break
        except Exception:
            pass
        _orig(exc_type, exc_value, exc_tb)
    sys.excepthook = _hook


def _apply_config():
    """Apply doxyedit.config.json overrides to model defaults (if the file exists)."""
    try:
        from doxyedit.config import get_config
        from doxyedit import models
        cfg = get_config()
        if cfg._tag_presets is not None:
            models.TAG_PRESETS.update(cfg.get_tag_presets())
        if cfg._tag_sized is not None:
            models.TAG_SIZED.update(cfg.get_tag_sized())
        if cfg._tag_presets is not None or cfg._tag_sized is not None:
            models.TAG_ALL.clear()
            models.TAG_ALL.update({**models.TAG_PRESETS, **models.TAG_SIZED})
        if cfg._tag_shortcuts is not None:
            models.TAG_SHORTCUTS_DEFAULT.update(cfg.get_tag_shortcuts())
            models.TAG_SHORTCUTS.update(models.TAG_SHORTCUTS_DEFAULT)
    except Exception:
        pass


class _Splash(QWidget):
    """Themed startup splash with a status line and Cancel / Quit buttons."""

    def __init__(self, theme):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self._theme = theme
        self._cancelled = False
        self._quit = False
        self._cancel_binding = None
        from doxyedit.themes import themed_dialog_size
        self.setFixedSize(*themed_dialog_size(43.33, 23.33, theme.font_size))
        self.setStyleSheet(
            f"QWidget {{ background: {theme.bg_main}; color: {theme.text_primary};"
            f" font-family: '{theme.font_family}'; font-size: {theme.font_size}px; }}"
            f"#splash_card {{ border: 1px solid {theme.accent}; }}"
            f"#splash_title {{ font-size: {theme.font_size * 3}px; font-weight: bold;"
            f" color: {theme.text_primary}; }}"
            f"#splash_tag {{ color: {theme.text_secondary}; }}"
            f"#splash_status {{ color: {theme.text_secondary}; }}"
            f"QPushButton {{ background: {theme.bg_raised}; color: {theme.text_primary};"
            f" border: 1px solid {theme.border}; padding: 6px 16px; border-radius: 3px; }}"
            f"QPushButton:hover {{ background: {theme.bg_hover}; border-color: {theme.accent}; }}"
            f"QPushButton:pressed {{ background: {theme.accent}; color: {theme.text_on_accent}; }}"
        )
        card = QWidget(self)
        card.setObjectName("splash_card")
        card.setGeometry(0, 0, self.width(), self.height())
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 36, 32, 20)
        layout.setSpacing(8)

        title = QLabel("DoxyEdit", card)
        title.setObjectName("splash_title")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        tag = QLabel("art asset management", card)
        tag.setObjectName("splash_tag")
        tag.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(tag)

        layout.addStretch(1)

        self._status = QLabel("", card)
        self._status.setObjectName("splash_status")
        self._status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel Load", card)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)
        self._empty_btn = QPushButton("Open Empty Project", card)
        self._empty_btn.clicked.connect(self._on_open_empty)
        btn_row.addWidget(self._empty_btn)
        self._quit_btn = QPushButton("Quit", card)
        self._quit_btn.clicked.connect(self._on_quit)
        btn_row.addWidget(self._quit_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Heartbeat: even when the loader is silent (e.g. mid JSON parse),
        # show elapsed seconds so the user can tell hang from progress.
        # Stops as soon as status text is set by the worker.
        import time as _t
        self._t0 = _t.monotonic()
        self._last_real_status = ""
        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._tick)
        self._heartbeat.start(500)

    def _tick(self):
        import time as _t
        elapsed = _t.monotonic() - self._t0
        # Append elapsed only when the worker hasn't pushed a fresh status
        # in a while. Avoids stomping on its messages.
        cur = self._status.text()
        base = self._last_real_status or cur
        if elapsed >= 2:
            self._status.setText(f"{base}   ({elapsed:.0f}s)")

    def _on_cancel(self):
        self._cancelled = True
        self._cancel_btn.setEnabled(False)
        self._empty_btn.setEnabled(False)
        self._status.setText("Cancelling...")
        # Forward immediately to the active loader so it stops on its
        # next chokepoint instead of waiting for the main-thread poll.
        if self._cancel_binding is not None:
            try:
                self._cancel_binding()
            except Exception:
                pass

    def _on_open_empty(self):
        """Same end state as Cancel - blank project - but the button label
        tells the user what they'll get instead of just "what they're
        leaving". Reaches the same code path."""
        self._on_cancel()

    def _on_quit(self):
        self._quit = True
        QApplication.quit()

    def bind_cancel(self, fn):
        """Install a callable invoked when Cancel is pressed."""
        self._cancel_binding = fn

    def set_status(self, text: str):
        self._last_real_status = text
        self._status.setText(text)
        QApplication.processEvents()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def quitting(self) -> bool:
        return self._quit


def main():
    _setup_logging()
    _install_exception_hook()
    _apply_config()
    app = QApplication(sys.argv)
    app.setApplicationName("DoxyEdit")
    app.setOrganizationName("DoxyEdit")
    # Global window-geometry memory: every top-level window/dialog
    # remembers position + size automatically without each one wiring
    # up its own _GEOM_KEY plumbing. Keyed by objectName / className.
    _win_mem = _WindowMemoryFilter(app)
    app.installEventFilter(_win_mem)
    app._doxy_win_mem = _win_mem  # keep alive
    # Use the user's saved theme (same QSettings MainWindow reads) so the
    # splash matches the main window, not the soot default.
    _saved_tid = QSettings("DoxyEdit", "DoxyEdit").value("theme", DEFAULT_THEME)
    if _saved_tid not in THEMES:
        _saved_tid = DEFAULT_THEME
    _dt = THEMES[_saved_tid]
    app.setFont(QFont(_dt.font_family, _dt.font_size))

    # Set app icon
    icon_path = Path(__file__).parent.parent / "doxyedit.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    splash = _Splash(_dt)
    # Center on primary screen
    scr = app.primaryScreen().availableGeometry()
    splash.move(scr.center().x() - splash.width() // 2,
                scr.center().y() - splash.height() // 2)
    splash.show()
    splash.set_status("Starting DoxyEdit…")

    # Crash-detection: if a sentinel from a previous launch is still on
    # disk, that launch never reached closeEvent (killed, OOM, segfault).
    # Default to skip-autoload so we don't loop into the same hang. The
    # user can still hit any of the splash buttons to load manually.
    crashed_last_time = _previous_launch_crashed()
    _arm_running_lock()
    # Always clear the sentinel on Python exit, even on crashes that
    # bypass closeEvent. atexit fires before interpreter teardown.
    import atexit as _atexit
    _atexit.register(_release_running_lock)

    skip_autoload = ("--new" in sys.argv) or crashed_last_time
    if crashed_last_time:
        splash.set_status("Previous session ended uncleanly - skipping autoload")

    # Build window with autoload deferred so the UI paints before disk I/O
    splash.set_status("Building interface…")
    window = MainWindow(_skip_autoload=True)
    window.show()
    window._update_title_bar_color()
    QApplication.processEvents()

    def _finish_startup():
        if splash.quitting:
            return
        # MainWindow(_skip_autoload=True) already registered a "New Project" slot.
        # If the user didn't pass --new and didn't cancel, replace it by restoring the last session.
        if skip_autoload or splash.cancelled:
            splash.close()
            return

        splash.set_status("Loading last project...")
        # Brief head-start so the splash buttons become responsive before
        # we spin up a worker thread. The splash event loop is running
        # throughout, so this is never "frozen" from the user's POV.
        deadline_loop = QEventLoop()
        QTimer.singleShot(200, deadline_loop.quit)
        deadline_loop.exec()
        if splash.quitting:
            return
        if splash.cancelled:
            window.status.showMessage("Startup load cancelled - blank project", 5000)
            splash.close()
            return

        # Kick off the background load. The worker runs on a QThread;
        # the UI thread stays free to process splash button clicks.
        done = {"flag": False, "kind": None}
        wait_loop = QEventLoop()

        def _on_status(text: str):
            splash.set_status(text)

        def _on_complete(kind: str):
            done["flag"] = True
            done["kind"] = kind
            wait_loop.quit()

        try:
            handle = window._restore_last_session_async(
                on_status=_on_status, on_complete=_on_complete)
        except Exception:
            logging.exception("Autoload failed to start")
            splash.close()
            return

        # Wire the splash's Cancel button to the in-flight loader.
        splash.bind_cancel(handle.cancel)

        # Hard timeout: if the autoload doesn't complete in N seconds, we
        # auto-cancel. Slow filesystems (Dropbox sync, network share, dead
        # process residue) can stretch a normal load into minutes - users
        # see "frozen" and force-kill, which leaves the running.lock and
        # we can't tell if it was actually a crash. The hard cap turns
        # "indefinite hang" into "graceful blank project" every time.
        def _timeout_cancel():
            if not done["flag"]:
                splash.set_status(
                    f"Autoload timed out ({_AUTOLOAD_HARD_TIMEOUT_S:.0f}s) - cancelling")
                try:
                    handle.cancel()
                except Exception:
                    pass
        QTimer.singleShot(int(_AUTOLOAD_HARD_TIMEOUT_S * 1000), _timeout_cancel)

        # Block the startup flow while the worker runs, but keep the Qt
        # event loop spinning so splash button clicks are handled. If the
        # async path already completed synchronously (e.g. blank-slate),
        # done["flag"] is already True and we skip the wait entirely.
        if not done["flag"]:
            wait_loop.exec()
        if splash.quitting:
            return

        if done["kind"] == "cancelled":
            window.status.showMessage("Startup load cancelled - blank project", 5000)
            # Ensure there's at least a blank slot registered. If the async
            # single-project path bailed before _register_initial_slot ran
            # (unlikely but safe), bring it back here.
            if not getattr(window, "_project_slots", None):
                window._register_initial_slot(None, "New Project")
        splash.close()

    QTimer.singleShot(50, _finish_startup)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
