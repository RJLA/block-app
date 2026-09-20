#!/usr/bin/env python3
"""
Allowlist Guard  (Windows 10 / 11)
----------------------------------
Maintains an allowlist of websites and apps, and optionally ENFORCES it:

  Websites : writes Chrome + Edge enterprise policy under
             HKLM\\SOFTWARE\\Policies\\...\\URLBlocklist = *
             HKLM\\SOFTWARE\\Policies\\...\\URLAllowlist = <your domains>
  Apps     : a watchdog that terminates user-session processes whose
             executable is not on the allowlist (system processes and
             anything under C:\\Windows are never touched).

Stdlib only. Enforcement requires administrator rights; the app will
prompt for elevation via UAC.

Config: %ProgramData%\\AllowlistGuard\\allowlist.json
Log:    %ProgramData%\\AllowlistGuard\\guard.log
"""

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

try:
    import winreg
except ImportError:          # non-Windows, lets the logic be unit-tested
    winreg = None

APP_NAME = "Allowlist Guard"
TASK_NAME = "AllowlistGuard"
POLL_SECONDS = 5
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0

# Tk discards images that nothing on the Python side still references.
_KEEP_ALIVE = []

POLICY_KEYS = {
    "Chrome": r"SOFTWARE\Policies\Google\Chrome",
    "Edge": r"SOFTWARE\Policies\Microsoft\Edge",
}

# Never killed by the watchdog, regardless of the allowlist.
SAFE_APPS = {
    "explorer", "dwm", "csrss", "winlogon", "services", "lsass", "smss",
    "wininit", "svchost", "ctfmon", "sihost", "taskhostw", "runtimebroker",
    "searchapp", "searchhost", "startmenuexperiencehost", "shellexperiencehost",
    "applicationframehost", "lockapp", "userinit", "fontdrvhost", "audiodg",
    "textinputhost", "securityhealthsystray", "securityhealthservice",
    "msmpeng", "nissrv", "conhost", "taskmgr", "powershell", "cmd",
    "allowlist_guard", "allowlistguard", "python", "pythonw",
}


# --------------------------------------------------------------------------
# Paths / storage
# --------------------------------------------------------------------------
def data_dir() -> str:
    base = os.environ.get("ProgramData") or os.path.expanduser("~")
    path = os.path.join(base, "AllowlistGuard")
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AllowlistGuard")
        os.makedirs(fallback, exist_ok=True)
        return fallback


CONFIG_PATH = os.path.join(data_dir(), "allowlist.json")
LOG_PATH = os.path.join(data_dir(), "guard.log")


def resource_path(*parts: str) -> str:
    """Locate a bundled file, both when frozen by PyInstaller and from source."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, *parts)


def seed_path() -> str:
    return resource_path("default_allowlist.json")


def load_mascot(size: int):
    """The crying frog, or None if the asset is missing — never fatal."""
    path = resource_path("assets", f"mascot_{size}.png")
    try:
        return tk.PhotoImage(file=path)
    except (tk.TclError, OSError):
        log(f"mascot {size}px unavailable at {path}")
        return None


def normalize_site(value: str) -> str:
    """https://WWW.Example.com:8080/path?q=1 -> example.com"""
    s = value.strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    if s.count(":") == 1:
        s = s.split(":", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s.strip(".")


def normalize_app(value: str) -> str:
    """C:\\Program Files\\Slack\\Slack.exe -> slack"""
    s = value.strip().strip('"').lower().replace("\\", "/")
    s = s.rstrip("/").split("/")[-1]
    for ext in (".exe", ".app", ".lnk", ".appimage"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.strip()


def site_allowed(candidate: str, allowed) -> bool:
    host = normalize_site(candidate)
    return bool(host) and any(host == a or host.endswith("." + a) for a in allowed if a)


def app_allowed(candidate: str, allowed) -> bool:
    name = normalize_app(candidate)
    return bool(name) and name in allowed


def load_data() -> dict:
    for path in (CONFIG_PATH, seed_path()):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return {
                "websites": sorted({normalize_site(x) for x in raw.get("websites", []) if x}),
                "apps": sorted({normalize_app(x) for x in raw.get("apps", []) if x}),
                "dry_run": bool(raw.get("dry_run", True)),
            }
        except (OSError, ValueError):
            continue
    return {"websites": [], "apps": [], "dry_run": True}


def save_data(data: dict) -> None:
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, CONFIG_PATH)


def log(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {line}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# Elevation
# --------------------------------------------------------------------------
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)


# --------------------------------------------------------------------------
# Website enforcement — Chrome / Edge enterprise policy
# --------------------------------------------------------------------------
def _write_policy_list(root_path: str, sub: str, entries) -> None:
    full = root_path + "\\" + sub
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, full)
    except OSError:
        pass
    if not entries:
        return
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, full) as key:
        for i, value in enumerate(entries, start=1):
            winreg.SetValueEx(key, str(i), 0, winreg.REG_SZ, value)


def apply_site_policy(domains) -> list:
    """Block everything, then allow the listed domains. Returns browsers touched."""
    touched = []
    for browser, path in POLICY_KEYS.items():
        try:
            winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, path).Close()
            _write_policy_list(path, "URLBlocklist", ["*"])
            _write_policy_list(path, "URLAllowlist", list(domains))
            touched.append(browser)
        except OSError as exc:
            log(f"policy {browser} failed: {exc}")
    log(f"site policy applied to {touched} with {len(domains)} domains")
    return touched


def clear_site_policy() -> None:
    for browser, path in POLICY_KEYS.items():
        for sub in ("URLBlocklist", "URLAllowlist"):
            try:
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, path + "\\" + sub)
            except OSError:
                pass
        log(f"site policy cleared for {browser}")


def site_policy_active() -> bool:
    for path in POLICY_KEYS.values():
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path + "\\URLBlocklist") as key:
                if winreg.QueryValueEx(key, "1")[0] == "*":
                    return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------
# App enforcement — watchdog
# --------------------------------------------------------------------------
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
    try:
        pid = os.getpid()
        dll = ctypes.windll.kernel32
        sid = ctypes.c_ulong()
        dll.ProcessIdToSessionId(pid, ctypes.byref(sid))
        return int(sid.value)
    except Exception:
        return -1


def offenders(processes, allowed, session_id) -> list:
    """Processes that should be terminated. System paths are always spared."""
    windir = (os.environ.get("SystemRoot") or r"C:\Windows").lower()
    self_dir = os.path.dirname(os.path.abspath(sys.argv[0])).lower()
    hits = []
    for proc in processes:
        path = (proc.get("ExecutablePath") or "").lower()
        name = normalize_app(proc.get("Name") or "")
        pid = proc.get("ProcessId")
        if not path or not name or pid in (None, 0, os.getpid()):
            continue
        if session_id >= 0 and proc.get("SessionId") != session_id:
            continue                       # services / other users
        if path.startswith(windir) or path.startswith(self_dir):
            continue
        if name in SAFE_APPS or name in allowed:
            continue
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
    def __init__(self, get_allowed, get_dry_run, report):
        super().__init__(daemon=True)
        self.get_allowed = get_allowed
        self.get_dry_run = get_dry_run
        self.report = report
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        session = current_session_id()
        self.report(f"Watchdog started (session {session}).")
        while not self._stop.is_set():
            allowed = set(self.get_allowed())
            dry = self.get_dry_run()
            for pid, name in offenders(list_processes(), allowed, session):
                if dry:
                    msg = f"[dry run] would terminate {name} (pid {pid})"
                else:
                    msg = f"terminated {name} (pid {pid})" if kill(pid) else f"FAILED to terminate {name} (pid {pid})"
                log(msg)
                self.report(msg)
            self._stop.wait(POLL_SECONDS)
        self.report("Watchdog stopped.")


# --------------------------------------------------------------------------
# Run at logon (elevated) via Task Scheduler
# --------------------------------------------------------------------------
def install_logon_task() -> bool:
    exe = os.path.abspath(sys.argv[0])
    cmd = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON",
           "/RL", "HIGHEST", "/TR", f'"{exe}" --enforce']
    return subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).returncode == 0


def remove_logon_task() -> bool:
    cmd = ["schtasks", "/Delete", "/F", "/TN", TASK_NAME]
    return subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).returncode == 0


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
class ListPane(ttk.LabelFrame):
    def __init__(self, master, title, placeholder, normalizer, on_change):
        super().__init__(master, text=title, padding=8)
        self.normalizer, self.on_change = normalizer, on_change
        self._placeholder = placeholder

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.entry = ttk.Entry(row, foreground="grey")
        self.entry.insert(0, placeholder)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<FocusIn>", self._clear)
        self.entry.bind("<Return>", lambda e: self.add())
        ttk.Button(row, text="Add", width=6, command=self.add).pack(side="left", padx=(6, 0))

        self.listbox = tk.Listbox(self, height=12, activestyle="none", exportselection=False)
        self.listbox.pack(fill="both", expand=True, pady=(8, 6))
        self.listbox.bind("<Delete>", lambda e: self.remove())
        ttk.Button(self, text="Remove selected", command=self.remove).pack(fill="x")

    def _clear(self, _e):
        if self.entry.get() == self._placeholder:
            self.entry.delete(0, "end")
            self.entry.configure(foreground="")

    def items(self):
        return list(self.listbox.get(0, "end"))

    def set_items(self, items):
        self.listbox.delete(0, "end")
        for item in items:
            self.listbox.insert("end", item)

    def add(self):
        raw = self.entry.get()
        if raw == self._placeholder:
            return
        value = self.normalizer(raw)
        if not value or value in self.items():
            return
        self.set_items(sorted(self.items() + [value]))
        self.entry.delete(0, "end")
        self.on_change()

    def remove(self):
        for index in reversed(list(self.listbox.curselection())):
            self.listbox.delete(index)
        self.on_change()


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.pack(fill="both", expand=True)
        self.watchdog = None
        data = load_data()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        tab_lists = ttk.Frame(nb, padding=8)
        tab_enforce = ttk.Frame(nb, padding=8)
        tab_log = ttk.Frame(nb, padding=8)
        nb.add(tab_lists, text="Lists")
        nb.add(tab_enforce, text="Enforcement")
        nb.add(tab_log, text="Activity")

        # --- Lists ---------------------------------------------------------
        panes = ttk.Frame(tab_lists)
        panes.pack(fill="both", expand=True)
        self.sites = ListPane(panes, "Allowed websites", "example.com", normalize_site, self.persist)
        self.sites.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.apps = ListPane(panes, "Allowed apps", "slack.exe", normalize_app, self.persist)
        self.apps.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.sites.set_items(data["websites"])
        self.apps.set_items(data["apps"])

        check = ttk.LabelFrame(tab_lists, text="Check", padding=8)
        check.pack(fill="x", pady=(10, 0))
        self.query = ttk.Entry(check)
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<Return>", lambda e: self.check())
        self.kind = ttk.Combobox(check, values=["Website", "App"], width=9, state="readonly")
        self.kind.current(0)
        self.kind.pack(side="left", padx=6)
        ttk.Button(check, text="Check", command=self.check).pack(side="left")
        # The mascot turns up only for a miss — a blocked lookup gets a sad frog.
        self.mascot_small = load_mascot(48)
        self.result = tk.Label(tab_lists, text="", font=("TkDefaultFont", 11, "bold"),
                               pady=6, compound="left", padx=8)
        self.result.pack(fill="x")

        # --- Enforcement ---------------------------------------------------
        ttk.Label(tab_enforce, wraplength=560, justify="left", text=(
            "Websites: applies Chrome and Edge enterprise policy — everything blocked "
            "except the listed domains. Takes effect when the browser restarts; verify at "
            "chrome://policy. Firefox and other browsers are NOT covered — block them in "
            "the app watchdog if you need full coverage.\n\n"
            "Apps: terminates running programs that are not on the app allowlist. "
            "Windows system processes and anything under C:\\Windows are never touched."
        )).pack(fill="x", pady=(0, 10))

        srow = ttk.Frame(tab_enforce)
        srow.pack(fill="x", pady=3)
        ttk.Button(srow, text="Apply website policy", command=self.apply_sites).pack(side="left")
        ttk.Button(srow, text="Remove website policy", command=self.clear_sites).pack(side="left", padx=6)
        self.site_state = ttk.Label(srow, text="")
        self.site_state.pack(side="left", padx=10)

        arow = ttk.Frame(tab_enforce)
        arow.pack(fill="x", pady=(12, 3))
        self.dry_run = tk.BooleanVar(value=data["dry_run"])
        ttk.Checkbutton(arow, text="Dry run (log only, don't terminate)",
                        variable=self.dry_run, command=self.persist).pack(side="left")
        self.watch_btn = ttk.Button(arow, text="Start app watchdog", command=self.toggle_watchdog)
        self.watch_btn.pack(side="left", padx=10)

        trow = ttk.Frame(tab_enforce)
        trow.pack(fill="x", pady=(12, 3))
        ttk.Button(trow, text="Run at logon", command=self.add_task).pack(side="left")
        ttk.Button(trow, text="Stop running at logon", command=self.del_task).pack(side="left", padx=6)

        # --- Log -----------------------------------------------------------
        self.logbox = tk.Text(tab_log, height=16, wrap="word", state="disabled")
        self.logbox.pack(fill="both", expand=True)
        ttk.Label(tab_log, text=LOG_PATH, foreground="grey").pack(fill="x", pady=(4, 0))

        self.admin = is_admin()
        ttk.Label(self, foreground="grey", text=(
            f"{CONFIG_PATH}   |   {'administrator' if self.admin else 'NOT elevated — enforcement disabled'}"
        )).pack(fill="x", pady=(6, 0))
        self.refresh_state()

        if "--enforce" in sys.argv and self.admin:
            self.toggle_watchdog()

    # -- helpers ------------------------------------------------------------
    def persist(self):
        try:
            save_data({"websites": self.sites.items(),
                       "apps": self.apps.items(),
                       "dry_run": self.dry_run.get()})
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n{exc}")

    def say(self, line):
        def append():
            self.logbox.configure(state="normal")
            self.logbox.insert("end", f"{datetime.now():%H:%M:%S}  {line}\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        self.after(0, append)

    def refresh_state(self):
        if winreg:
            self.site_state.configure(text="active" if site_policy_active() else "not applied")

    def need_admin(self) -> bool:
        if self.admin:
            return False
        if messagebox.askyesno(APP_NAME, "Enforcement needs administrator rights.\nRestart elevated now?"):
            relaunch_as_admin()
        return True

    def check(self):
        value = self.query.get().strip()
        if not value:
            return
        if self.kind.get() == "Website":
            ok, shown = site_allowed(value, self.sites.items()), normalize_site(value)
        else:
            ok, shown = app_allowed(value, self.apps.items()), normalize_app(value)
        self.result.configure(text=f"{shown} — {'ALLOWED' if ok else 'NOT ON THE LIST'}",
                              fg="#1a7f37" if ok else "#b42318",
                              image="" if ok else (self.mascot_small or ""))

    # -- actions ------------------------------------------------------------
    def apply_sites(self):
        if self.need_admin():
            return
        domains = self.sites.items()
        if not domains and not messagebox.askyesno(
                APP_NAME, "The website list is empty — this will block ALL browsing. Continue?"):
            return
        touched = apply_site_policy(domains)
        self.say(f"Website policy applied to {', '.join(touched) or 'nothing'}.")
        self.refresh_state()

    def clear_sites(self):
        if self.need_admin():
            return
        clear_site_policy()
        self.say("Website policy removed.")
        self.refresh_state()

    def toggle_watchdog(self):
        if self.watchdog:
            self.watchdog.stop()
            self.watchdog = None
            self.watch_btn.configure(text="Start app watchdog")
            return
        if self.need_admin():
            return
        if not self.dry_run.get() and not messagebox.askyesno(
                APP_NAME, "Live mode will close every running program that is not on the "
                          "app allowlist. Do a dry run first if you haven't.\n\nContinue?"):
            return
        self.watchdog = Watchdog(self.apps.items, self.dry_run.get, self.say)
        self.watchdog.start()
        self.watch_btn.configure(text="Stop app watchdog")

    def add_task(self):
        if self.need_admin():
            return
        self.say("Logon task created." if install_logon_task() else "Could not create logon task.")

    def del_task(self):
        if self.need_admin():
            return
        self.say("Logon task removed." if remove_logon_task() else "Could not remove logon task.")


def set_window_icon(root: tk.Tk) -> None:
    """Mascot in the title bar and taskbar; cosmetic, so failures are ignored."""
    try:
        root.iconbitmap(resource_path("assets", "mascot.ico"))
        return
    except tk.TclError:
        pass
    icon = load_mascot(96)
    if icon:
        root.iconphoto(True, icon)
        _KEEP_ALIVE.append(icon)        # keep a reference or Tk drops the image


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("660x540")
    root.minsize(600, 480)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    set_window_icon(root)
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.watchdog and app.watchdog.stop(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
