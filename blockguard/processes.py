"""Enumerating and terminating running processes."""

import ctypes
import json
import os
import subprocess
import sys
import threading

from . import POLL_SECONDS
from .naming import PROTECTED_APPS, normalize_app
from .paths import log

NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0

PS_QUERY = (
    "Get-CimInstance Win32_Process | "
    "Select-Object ProcessId,Name,ExecutablePath,SessionId | ConvertTo-Json -Compress"
)


def list_processes() -> list:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_QUERY],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
        ).stdout
        parsed = json.loads(out) if out.strip() else []
        return parsed if isinstance(parsed, list) else [parsed]
    except Exception as exc:
        log(f"process query failed: {exc}")
        return []


def current_session_id() -> int:
    """-1 means "unknown", which disables the same-session filter."""
    try:
        sid = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
        return int(sid.value)
    except Exception:
        return -1


def offenders(processes, blocked, session_id) -> list:
    """Running processes that are on the blocklist and safe to terminate.

    Unlike an allowlist, only explicitly listed names are candidates -- so a
    forgotten app is simply left alone rather than killed.
    """
    wanted = {normalize_app(b) for b in blocked if b} - PROTECTED_APPS
    hits = []
    for proc in processes:
        name = normalize_app(proc.get("Name") or "")
        pid = proc.get("ProcessId")
        if not name or pid in (None, 0, os.getpid()):
            continue
        if session_id >= 0 and proc.get("SessionId") != session_id:
            continue                       # services / other users
        if name in wanted:
            hits.append((pid, name))
    return hits


def kill(pid: int) -> bool:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       capture_output=True, timeout=10, creationflags=NO_WINDOW)
        return True
    except Exception:
        return False


class Watchdog(threading.Thread):
    """Polls for blocked processes and terminates them.

    `get_blocked` and `get_dry_run` must be cheap, thread-safe callables --
    they are invoked from this thread, so they must not touch Tk widgets.
    """

    def __init__(self, get_blocked, get_dry_run, report, on_blocked=None):
        super().__init__(daemon=True)
        self.get_blocked = get_blocked
        self.get_dry_run = get_dry_run
        self.report = report
        # Called with the app name after a real termination, so the UI can
        # tell the user what happened. Never called during a dry run.
        self.on_blocked = on_blocked
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        session = current_session_id()
        self.report(f"Watchdog started (session {session}).")
        while not self._stop.is_set():
            blocked = set(self.get_blocked())
            if blocked:
                dry = self.get_dry_run()
                for pid, name in offenders(list_processes(), blocked, session):
                    if dry:
                        msg = f"[dry run] would terminate {name} (pid {pid})"
                    else:
                        ok = kill(pid)
                        msg = (f"terminated {name} (pid {pid})" if ok
                               else f"FAILED to terminate {name} (pid {pid})")
                        if ok and self.on_blocked:
                            self.on_blocked(name)
                    log(msg)
                    self.report(msg)
            self._stop.wait(POLL_SECONDS)
        self.report("Watchdog stopped.")
