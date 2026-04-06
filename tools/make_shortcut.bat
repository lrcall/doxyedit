@echo off
powershell -ExecutionPolicy Bypass -Command ^
  "$s=New-Object -Com WScript.Shell; $l=$s.CreateShortcut('%USERPROFILE%\Desktop\DOXYEDIT.lnk'); $l.TargetPath='%~dp0doxyedit.bat'; $l.WorkingDirectory='%~dp0'; $l.IconLocation='%~dp0doxyedit.ico'; $l.Description='DoxyEdit'; $l.Save()"
echo Shortcut created on Desktop.
pause
