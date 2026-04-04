"""DoxyEdit main entry point."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon
from doxyedit.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DoxyEdit")
    app.setOrganizationName("DoxyEdit")
    app.setFont(QFont("Segoe UI", 10))

    # Set app icon
    icon_path = Path(__file__).parent.parent / "doxyedit.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    window._update_title_bar_color()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
