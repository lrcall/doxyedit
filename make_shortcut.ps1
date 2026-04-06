$WshShell = New-Object -ComObject WScript.Shell
$Desktop  = [System.Environment]::GetFolderPath("Desktop")
$RepoDir  = Split-Path -Parent $MyInvocation.MyCommand.Path

$Lnk = $WshShell.CreateShortcut("$Desktop\DOXYEDIT.lnk")
$Lnk.TargetPath       = "$RepoDir\doxyedit.bat"
$Lnk.WorkingDirectory = $RepoDir
$Lnk.IconLocation     = "$RepoDir\doxyedit.ico"
$Lnk.Description      = "DoxyEdit"
$Lnk.Save()

Write-Host "Shortcut created on Desktop with DoxyEdit icon."
