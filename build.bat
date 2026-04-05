@echo off
title DoxyEdit Build
echo === Building DoxyEdit with Nuitka ===
echo.

echo Installing/updating dependencies...
pip install nuitka ordered-set zstandard

echo.
echo Clearing Nuitka cache to ensure fresh build...
if exist "run.build" rmdir /s /q "run.build"
if exist "run.dist" rmdir /s /q "run.dist"
if exist "run.onefile-build" rmdir /s /q "run.onefile-build"

echo.
echo Building...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=doxyedit.ico ^
    --output-filename=DoxyEdit.exe ^
    --output-dir=dist ^
    --include-package=doxyedit ^
    --include-module=PIL ^
    --include-module=psd_tools ^
    --include-module=numpy ^
    --nofollow-import-to=matplotlib ^
    --nofollow-import-to=scipy ^
    --nofollow-import-to=skimage ^
    --nofollow-import-to=sklearn ^
    --nofollow-import-to=pandas ^
    --nofollow-import-to=tkinter ^
    --nofollow-import-to=unittest ^
    --nofollow-import-to=test ^
    --nofollow-import-to=setuptools ^
    --nofollow-import-to=pip ^
    --nofollow-import-to=distutils ^
    run.py

if errorlevel 1 (
    echo.
    echo [!] Build FAILED.
    pause
    exit /b 1
)

echo.
echo === Build complete! ===
echo Output: dist\DoxyEdit.exe
pause
