"""Qt binding compatibility shim.

DoxyEdit imports PySide6 directly (hundreds of `from PySide6.Qt* import ...`
call sites) — that's the canonical, shipped binding. This module exists as
a seed / documentation for swapping to PyQt6 when evaluating differences
(e.g., signal marshaling, painting subtleties, Windows HiDPI behavior).

## Why both bindings exist

PySide6 is the official Qt for Python binding (LGPL). PyQt6 is Riverbank's
binding (GPL / commercial). Both wrap the same C++ Qt6. API surface is
~95% identical; notable deltas:

- Signal / Slot: PySide6 = `from PySide6.QtCore import Signal, Slot`
  PyQt6 = `from PyQt6.QtCore import pyqtSignal as Signal, pyqtSlot as Slot`
- Property system: `@Property(int)` (PySide6) vs `pyqtProperty` (PyQt6)
- QObject `__init_subclass__` hooks differ for introspection libraries
- Some enum values (e.g. `Qt.Key_Return` vs `Qt.Key.Key_Return`) — PyQt6
  is stricter about the scoped enum path; PySide6 accepts both
- `QIODevice` byte-array signatures: PySide6 accepts bytes where PyQt6
  often wants a QByteArray
- Signals with object-type parameters: PySide6 auto-converts more Python
  types; PyQt6 sometimes needs `pyqtSignal(object)`

## How to use this shim

Prefer direct `from PySide6.QtFoo import Bar` in application code — it
keeps imports explicit and IDE-friendly. This shim is for:

1. New utility modules that want to compile under either binding
2. Test harnesses that want to compare painting output across bindings
3. Future migration if we ever decide to switch primary binding

Example usage in a test module:

    from doxyedit.qt_compat import Qt, QApplication, Signal, QWidget
    class MyWidget(QWidget):
        changed = Signal(int)

That code works on PySide6 today and PyQt6 with PREFER_BINDING=PyQt6 set.

## Building a PyQt6 smoke test

The environment variable `DOXYEDIT_QT_BINDING=pyqt6` switches this shim;
run `py -m doxyedit.qt_compat` to print which binding is active.

Caveat: the rest of the codebase still hard-imports PySide6. Only modules
that use THIS shim will swap. For a full cross-binding build, either:

(a) Codemod every `from PySide6.QtX import Y` to `from doxyedit.qt_compat
    import Y` (mechanical, ~500 lines to touch).
(b) Install the `qtpy` package and codemod to `from qtpy.QtWidgets import
    QWidget` etc. qtpy handles the binding indirection at import time.

Option (b) is what Spyder, napari, and most scientific-Python apps use.

## Known-good PyQt6 swap invocation

    pip install PyQt6
    $env:DOXYEDIT_QT_BINDING="pyqt6"
    py run.py
"""
import os as _os

_BINDING = _os.environ.get("DOXYEDIT_QT_BINDING", "pyside6").lower()

if _BINDING == "pyqt6":
    from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
    from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, QTimer, QSettings
    from PyQt6.QtCore import pyqtSignal as Signal  # type: ignore
    from PyQt6.QtCore import pyqtSlot as Slot      # type: ignore
    from PyQt6.QtGui import (
        QColor, QPen, QBrush, QFont, QPainter, QPixmap, QImage,
        QKeySequence, QShortcut, QAction, QUndoStack, QUndoCommand,
    )
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QMainWindow, QDialog,
        QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
        QGraphicsScene, QGraphicsView, QGraphicsItem,
        QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsTextItem,
        QGraphicsLineItem, QComboBox, QSlider, QSpinBox, QFileDialog,
        QInputDialog, QListWidget, QListWidgetItem, QSplitter,
        QFontComboBox, QColorDialog, QMenu, QScrollArea, QGridLayout,
        QToolBar, QFormLayout,
    )
else:  # pyside6 (default)
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QTimer, QSettings
    from PySide6.QtCore import Signal, Slot
    from PySide6.QtGui import (
        QColor, QPen, QBrush, QFont, QPainter, QPixmap, QImage,
        QKeySequence, QShortcut, QAction, QUndoStack, QUndoCommand,
    )
    from PySide6.QtWidgets import (
        QApplication, QWidget, QMainWindow, QDialog,
        QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
        QGraphicsScene, QGraphicsView, QGraphicsItem,
        QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsTextItem,
        QGraphicsLineItem, QComboBox, QSlider, QSpinBox, QFileDialog,
        QInputDialog, QListWidget, QListWidgetItem, QSplitter,
        QFontComboBox, QColorDialog, QMenu, QScrollArea, QGridLayout,
        QToolBar, QFormLayout,
    )


def binding() -> str:
    """Return the active binding name ('pyside6' / 'pyqt6')."""
    return _BINDING


if __name__ == "__main__":
    print(f"Active Qt binding: {binding()}")
