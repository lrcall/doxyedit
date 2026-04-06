@echo off
python -m nuitka ^
  --onefile ^
  --windows-icon-from-ico=doxyedit.ico ^
  --windows-console-mode=disable ^
  --output-filename=DOXYEDIT.exe ^
  launcher.py
echo Done. Pin DOXYEDIT.exe to your taskbar.
pause
