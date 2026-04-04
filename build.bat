@echo off
echo === Building DoxyEdit with Nuitka ===
echo.
echo Installing Nuitka if needed...
pip install nuitka ordered-set zstandard

echo.
echo Building...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --output-filename=DoxyEdit.exe ^
    --output-dir=dist ^
    --include-package=doxyedit ^
    --include-module=PIL ^
    run.py

echo.
echo Done! Check dist\DoxyEdit.exe
pause
