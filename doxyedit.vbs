' Silent launcher for DoxyEdit. Runs the python entrypoint via pythonw
' (no console window). Falls back to the .bat launcher if pythonw is
' not found on PATH. Use this shortcut to avoid the brief cmd flash
' that the .bat-based launcher produces.
Option Explicit

Dim sh, fso, here
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

' Try pythonw first, then pyw, then fall back to the .bat (which itself
' picks the best available interpreter). All invocations are run hidden
' (intWindowStyle = 0) so no console window flashes on screen.
On Error Resume Next
sh.Run "pythonw """ & here & "\run.py""", 0, False
If Err.Number = 0 Then WScript.Quit
Err.Clear

sh.Run "pyw """ & here & "\run.py""", 0, False
If Err.Number = 0 Then WScript.Quit
Err.Clear

sh.Run """" & here & "\doxyedit.bat""", 0, False
