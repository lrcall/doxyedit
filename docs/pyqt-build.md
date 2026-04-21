# Building a PyQt6 exe for side-by-side comparison

## Why

DoxyEdit ships PySide6 (LGPL). You can build a PyQt6 variant to compare
rendering, event timing, and Qt bug differences.

## How

```powershell
py tools/build_pyqt.py
```

The script:

1. Installs PyQt6 via pip if missing.
2. Copies the source tree to `build_pyqt_tmp/`.
3. Regex-codemods `from PySide6.Qt*` → `from PyQt6.Qt*` and renames
   `Signal` / `Slot` → `pyqtSignal as Signal` / `pyqtSlot as Slot` so
   call sites keep working.
4. Runs a smoke import of `doxyedit.window` to catch obvious breakage.
5. Invokes Nuitka with `--enable-plugin=pyqt6` into
   `dist/DoxyEdit-pyqt.exe`.

Run both exes side-by-side: the original `dist/DoxyEdit.exe` is PySide6;
`dist/DoxyEdit-pyqt.exe` is PyQt6.

## Known diffs to patch by hand

The regex catches the bulk, but you may need to touch these:

- **Enum access**: PyQt6 is strict about scoped enums. `Qt.Key_Return`
  needs to be `Qt.Key.Key_Return`. doxyedit already uses scoped forms.
- **QBoxLayout replacements**: `layout.replaceWidget()` return type
  differs; PyQt6 returns `QLayoutItem`, PySide6 returns bool-ish.
- **QColor constructor**: PySide6 accepts `QColor("#rrggbbaa")` on older
  versions; PyQt6 is strict — use named constructor explicitly.
- **`exec_` method name**: both modern bindings accept `exec()`, but if
  you hit a legacy `.exec_()` call site, PyQt6 may warn.
- **Signal binding in lambdas**: capture-by-value semantics are the
  same, but `Signal` decorator variants differ in PyQt6 (`@pyqtSlot`
  form required for some marshaling cases).
- **QWidget.findChild returning wrong type**: PySide6 is smarter about
  C++ → Python casting for some widget types.

## When to use which

- **PySide6**: shipping binding. LGPL — no license fees for commercial use.
- **PyQt6**: GPL (or paid commercial license). Useful if an ecosystem
  library you want only supports PyQt6.

## Reverting

`build_pyqt_tmp/` is a scratch dir; delete it freely. The regex never
touches the actual source tree.
