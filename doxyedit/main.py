"""DoxyEdit main entry point."""
import sys
from PySide6.QtWidgets import QApplication
from doxyedit.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DoxyEdit")
    app.setOrganizationName("DoxyEdit")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
