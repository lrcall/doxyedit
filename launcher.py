import subprocess
import sys
import os

desktop = os.path.join(os.path.expanduser("~"), "Desktop")
log = os.path.join(desktop, "launcher.log")

here = os.path.dirname(os.path.abspath(sys.argv[0]))
bat = os.path.join(here, "doxyedit.bat")

with open(log, "w") as f:
    f.write(f"sys.argv[0]: {sys.argv[0]}\n")
    f.write(f"sys.executable: {sys.executable}\n")
    f.write(f"here: {here}\n")
    f.write(f"bat: {bat}\n")
    f.write(f"bat exists: {os.path.exists(bat)}\n")
    try:
        proc = subprocess.Popen(["cmd", "/c", bat], cwd=here)
        f.write(f"launched ok, pid={proc.pid}\n")
    except Exception as e:
        f.write(f"error: {e}\n")
