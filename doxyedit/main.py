"""DoxyEdit main entry point."""
import sys
import ctypes
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from doxyedit.window import MainWindow


def set_title_bar_color(window, r, g, b):
    """Set Windows title bar color to match the app theme (Windows 10/11)."""
    try:
        hwnd = int(window.winId())
        # DWMWA_CAPTION_COLOR = 35
        color = r | (g << 8) | (b << 16)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(ctypes.c_int(color)), ctypes.sizeof(ctypes.c_int)
        )
    except Exception:
        pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DoxyEdit")
    app.setOrganizationName("DoxyEdit")
    app.setFont(QFont("Segoe UI", 10))

    window = MainWindow()
    window.show()

    # Match title bar to theme background
    theme = window._theme
    bg = theme.bg_raised
    r = int(bg[1:3], 16)
    g = int(bg[3:5], 16)
    b = int(bg[5:7], 16)
    set_title_bar_color(window, r, g, b)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
