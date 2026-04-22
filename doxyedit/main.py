"""DoxyEdit main entry point."""
import sys
import traceback
import logging
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
)
from PySide6.QtGui import QFont, QIcon, QColor
from PySide6.QtCore import Qt, QTimer, QEventLoop
from doxyedit.window import MainWindow

_LOG_PATH = Path.home() / ".doxyedit" / "doxyedit.log"

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
        self.setFixedSize(520, 280)
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
        self._quit_btn = QPushButton("Quit", card)
        self._quit_btn.clicked.connect(self._on_quit)
        btn_row.addWidget(self._quit_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _on_cancel(self):
        self._cancelled = True
        self._cancel_btn.setEnabled(False)
        self._status.setText("Cancelling...")
        # Forward immediately to the active loader so it stops on its
        # next chokepoint instead of waiting for the main-thread poll.
        if self._cancel_binding is not None:
            try:
                self._cancel_binding()
            except Exception:
                pass

    def _on_quit(self):
        self._quit = True
        QApplication.quit()

    def bind_cancel(self, fn):
        """Install a callable invoked when Cancel is pressed."""
        self._cancel_binding = fn

    def set_status(self, text: str):
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
    from doxyedit.themes import THEMES, DEFAULT_THEME
    # Use the user's saved theme (same QSettings MainWindow reads) so the
    # splash matches the main window, not the soot default.
    from PySide6.QtCore import QSettings
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

    skip_autoload = "--new" in sys.argv

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
