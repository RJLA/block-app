"""One running copy at a time, plus a way to summon its window.

In background mode there is no window and no tray icon, so launching Block
Guard again has to reach the copy that is already running. It does that by
dropping a small sentinel file that the running copy polls for and deletes --
no sockets, which would otherwise trigger a Windows Firewall prompt on a
machine the teacher may not be able to approve.
"""

import ctypes
import os

from .paths import data_dir, log

# Session-local: the logon task and any manual launch share a session, and a
# Local name needs no special privilege the way Global does.
MUTEX_NAME = "Local\\BlockGuardSingleInstance"
SHOW_REQUEST_PATH = os.path.join(data_dir(), "show.request")
ERROR_ALREADY_EXISTS = 183

_handle = None


def acquire() -> bool:
    """True if this is the only copy. False means one is already running."""
    global _handle
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True                    # cannot tell -- do not block startup
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _handle = handle
        return True
    except Exception as exc:
        log(f"single-instance check unavailable: {exc}")
        return True


def request_show() -> bool:
    """Ask the running copy to bring up its lock screen."""
    try:
        with open(SHOW_REQUEST_PATH, "w", encoding="utf-8") as fh:
            fh.write("show")
        return True
    except OSError as exc:
        log(f"could not signal the running copy: {exc}")
        return False


def consume_show_request() -> bool:
    """True once per request; removes the sentinel so it fires only once."""
    try:
        if not os.path.exists(SHOW_REQUEST_PATH):
            return False
        os.remove(SHOW_REQUEST_PATH)
        return True
    except OSError:
        return False
