"""DoxyEdit main entry point."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon
from doxyedit.window import MainWindow


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


def main():
    _apply_config()
    app = QApplication(sys.argv)
    app.setApplicationName("DoxyEdit")
    app.setOrganizationName("DoxyEdit")
    app.setFont(QFont("Segoe UI", 10))

    # Set app icon
    icon_path = Path(__file__).parent.parent / "doxyedit.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    skip_autoload = "--new" in sys.argv
    window = MainWindow(_skip_autoload=skip_autoload)
    window.show()
    window._update_title_bar_color()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
