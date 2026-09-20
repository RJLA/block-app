"""Discovering what is installed on this PC, so apps can be picked from a
list instead of typed from memory.

Two sources, merged:
  * the Windows uninstall registry -- what is installed
  * running processes             -- ground truth for what the watchdog sees

Slow enough (registry walk plus a shallow disk scan) that callers should run
it off the UI thread.
"""

import os

from .naming import PROTECTED_APPS, normalize_app
from .paths import log
from .processes import current_session_id, list_processes

try:
    import winreg
except ImportError:          # non-Windows, lets the logic be imported for tests
    winreg = None

UNINSTALL_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
WOW_UNINSTALL_PATH = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"

# Entries of these release types are patches, not applications.
SKIP_RELEASE_TYPES = {"update", "hotfix", "security update", "servicepack"}
# Upper bound on InstallLocation folders scanned for an .exe, to keep the
# refresh responsive on machines with hundreds of installed programs.
MAX_DISK_SCANS = 120
# An uninstaller is not the thing the user wants to block.
JUNK_EXE_HINTS = ("unins", "setup", "install", "update", "crash", "repair",
                  "helper", "report")
# Products that are never a thing a person "uses", so never worth blocking.
SKIP_NAME_HINTS = ("redistributable", "runtime", "driver", " sdk", "language pack")


def is_junk_exe(exe: str) -> bool:
    return any(hint in exe for hint in JUNK_EXE_HINTS)


def is_skippable_product(display_name: str) -> bool:
    lowered = display_name.lower()
    return any(hint in lowered for hint in SKIP_NAME_HINTS)


def _value(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def exe_from_display_icon(display_icon: str) -> str:
    """"C:\\Apps\\thing.exe,0" -> "thing"; returns "" if it is not an exe."""
    if not display_icon:
        return ""
    path = display_icon.strip()
    head, sep, tail = path.rpartition(",")
    if sep and tail.strip().lstrip("-").isdigit():
        path = head                       # drop the ",0" icon index
    path = path.strip().strip('"')        # quotes come off last -- "x.exe",0
    return normalize_app(path) if path.lower().endswith(".exe") else ""


def exe_from_folder(folder: str, display_name: str) -> str:
    """Pick the most plausible top-level .exe inside an install folder."""
    try:
        names = [e.name for e in os.scandir(folder)
                 if e.is_file() and e.name.lower().endswith(".exe")]
    except OSError:
        return ""
    if not names:
        return ""
    wanted = normalize_app(display_name)
    candidates = [normalize_app(n) for n in names]
    # Prefer an exe whose name relates to the product name, e.g. Slack -> slack.exe
    for cand in candidates:
        if cand and not is_junk_exe(cand) and (cand in wanted or wanted.startswith(cand)):
            return cand
    for cand in candidates:
        if cand and not is_junk_exe(cand):
            return cand
    return ""                              # only uninstallers here -- not useful


def _read_entry(root, subpath: str, name: str, scans: list) -> dict:
    try:
        with winreg.OpenKey(root, f"{subpath}\\{name}") as key:
            display = (_value(key, "DisplayName") or "").strip()
            if not display or _value(key, "SystemComponent") == 1:
                return {}
            if is_skippable_product(display):
                return {}
            release = str(_value(key, "ReleaseType") or "").strip().lower()
            if release in SKIP_RELEASE_TYPES:
                return {}
            exe = exe_from_display_icon(str(_value(key, "DisplayIcon") or ""))
            if is_junk_exe(exe):
                exe = ""                   # DisplayIcon pointed at the uninstaller
            location = str(_value(key, "InstallLocation") or "").strip().strip('"')
            if not exe and location and len(scans) < MAX_DISK_SCANS:
                scans.append(location)
                exe = exe_from_folder(location, display)
            return {"name": display, "exe": exe, "running": False}
    except OSError:
        return {}


def installed_from_registry() -> list:
    """Walk the uninstall registry across both bitnesses and the current user."""
    if not winreg:
        return []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_PATH),
        (winreg.HKEY_LOCAL_MACHINE, WOW_UNINSTALL_PATH),
        (winreg.HKEY_CURRENT_USER, UNINSTALL_PATH),
    ]
    found, scans = [], []
    for root, subpath in roots:
        try:
            parent = winreg.OpenKey(root, subpath)
        except OSError:
            continue                       # key absent on this machine
        with parent:
            try:
                count = winreg.QueryInfoKey(parent)[0]
            except OSError:
                continue
            for index in range(count):
                try:
                    name = winreg.EnumKey(parent, index)
                except OSError:
                    break
                entry = _read_entry(root, subpath, name, scans)
                if entry:
                    found.append(entry)
    return found


def running_apps() -> list:
    """Distinct user-facing processes in the current desktop session.

    Filtering by session drops Windows services (session 0), which are noise
    here -- the watchdog would not touch them anyway.
    """
    session = current_session_id()
    seen = {}
    for proc in list_processes():
        exe = normalize_app(proc.get("Name") or "")
        if not exe or exe in PROTECTED_APPS:
            continue
        if session >= 0 and proc.get("SessionId") != session:
            continue
        seen.setdefault(exe, {"name": exe, "exe": exe, "running": True})
    return list(seen.values())


def inventory() -> list:
    """Merged, de-duplicated, sorted by display name.

    Entries with no resolvable executable are dropped -- the watchdog matches
    on process name, so an entry it could never act on would be misleading.
    """
    merged = {}
    for entry in installed_from_registry() + running_apps():
        exe = entry["exe"]
        if not exe or exe in PROTECTED_APPS:
            continue
        existing = merged.get(exe)
        if existing:
            # Keep the friendlier registry name, but remember it is running.
            existing["running"] = existing["running"] or entry["running"]
            if entry["name"] != exe and existing["name"] == exe:
                existing["name"] = entry["name"]
        else:
            merged[exe] = dict(entry)
    result = sorted(merged.values(), key=lambda e: e["name"].lower())
    log(f"inventory: {len(result)} apps discovered")
    return result
