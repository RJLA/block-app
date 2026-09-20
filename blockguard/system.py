"""Elevation and the run-at-logon scheduled task."""

import ctypes
import os
import subprocess
import sys

from . import TASK_NAME
from .processes import NO_WINDOW


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """Restart the app under UAC and exit this instance."""
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)


def install_logon_task() -> bool:
    exe = os.path.abspath(sys.argv[0])
    cmd = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON",
           "/RL", "HIGHEST", "/TR", f'"{exe}" --enforce']
    return subprocess.run(cmd, capture_output=True,
                          creationflags=NO_WINDOW).returncode == 0


def remove_logon_task() -> bool:
    cmd = ["schtasks", "/Delete", "/F", "/TN", TASK_NAME]
    return subprocess.run(cmd, capture_output=True,
                          creationflags=NO_WINDOW).returncode == 0
