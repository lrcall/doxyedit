import subprocess
import sys
import os

here = os.path.dirname(os.path.abspath(sys.executable))
bat = os.path.join(here, "doxyedit.bat")
subprocess.Popen(["cmd", "/c", bat], cwd=here)
