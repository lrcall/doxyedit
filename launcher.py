import subprocess
import sys
import os

here = os.path.dirname(os.path.abspath(sys.argv[0]))
bat = os.path.join(here, "doxyedit.bat")
# CREATE_NO_WINDOW (0x08000000) so the cmd shell doesn't flash a
# console window on Windows.
flags = 0x08000000 if sys.platform == "win32" else 0
subprocess.Popen(["cmd", "/c", bat], cwd=here, creationflags=flags)
