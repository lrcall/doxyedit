import subprocess
import os

bat = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doxyedit.bat")
subprocess.Popen(["cmd", "/c", bat], cwd=os.path.dirname(bat))
