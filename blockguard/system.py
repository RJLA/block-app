"""Elevation and the run-at-logon scheduled task."""

import ctypes
import os
import subprocess
import sys

from . import TASK_NAME
from .paths import data_dir, log
from .processes import NO_WINDOW

# Well-known SIDs, so this works regardless of the system's language.
ADMINISTRATORS_SID = "*S-1-5-32-544"
LOCAL_SYSTEM_SID = "*S-1-5-18"


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


def restrict_data_dir() -> bool:
    """Lock the config, PIN digest and log to administrators only.

    Without this the PIN is decoration: a standard user could simply delete
    blocklist.json and security.json to clear both the blocks and the PIN.
    Needs elevation, and is best-effort -- the app still works if it fails.
    """
    target = data_dir()
    cmd = ["icacls", target,
           "/inheritance:r",
           "/grant:r", f"{ADMINISTRATORS_SID}:(OI)(CI)F",
           "/grant:r", f"{LOCAL_SYSTEM_SID}:(OI)(CI)F",
           "/T", "/C", "/Q"]
    try:
        ok = subprocess.run(cmd, capture_output=True,
                            creationflags=NO_WINDOW).returncode == 0
    except OSError as exc:
        log(f"could not restrict {target}: {exc}")
        return False
    log(f"data directory restricted to administrators: {ok}")
    return ok


def install_logon_task(mode: str = "--background") -> bool:
    """Run Block Guard at every logon.

    The task records an absolute path, so moving the executable afterwards
    silently breaks it -- install somewhere permanent first.
    """
    exe = os.path.abspath(sys.argv[0])
    cmd = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON",
           "/RL", "HIGHEST", "/TR", f'"{exe}" {mode}']
    return subprocess.run(cmd, capture_output=True,
                          creationflags=NO_WINDOW).returncode == 0


def logon_task_exists() -> bool:
    """Whether Block Guard is already registered to start at logon."""
    cmd = ["schtasks", "/Query", "/TN", TASK_NAME]
    try:
        return subprocess.run(cmd, capture_output=True,
                              creationflags=NO_WINDOW).returncode == 0
    except OSError:
        return False


def remove_logon_task() -> bool:
    cmd = ["schtasks", "/Delete", "/F", "/TN", TASK_NAME]
    return subprocess.run(cmd, capture_output=True,
                          creationflags=NO_WINDOW).returncode == 0
