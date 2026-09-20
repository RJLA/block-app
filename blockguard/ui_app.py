"""The main window."""

import queue
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import APP_NAME, VERSION
from .config import load_data, save_data
from .mascot import load_mascot, set_window_icon
from .naming import app_blocked, normalize_app, normalize_site, site_blocked
from .paths import CONFIG_PATH, LOG_PATH, log
from .pin import has_pin
from .processes import Watchdog
from .sites import apply_site_policy, clear_site_policy, site_policy_active
from .system import (
    install_logon_task, is_admin, relaunch_as_admin, remove_logon_task,
    restrict_data_dir,
)
from .ui_lists import InstalledPane, ListPane
from .ui_pin import ChangePinDialog, LockScreen
from .ui_toast import BlockedToast

try:
    import winreg
except ImportError:
    winreg = None

POLL_MS = 150
# One toast per app at most this often. A browser or game can spawn a dozen
# processes that all die in the same sweep; the student needs one notice.
TOAST_COOLDOWN_SECONDS = 30

ENFORCEMENT_HELP = (
    "Websites: applies Chrome and Edge enterprise policy so the listed domains "
    "are blocked. Everything else stays reachable. Takes effect when the "
    "browser restarts; verify at chrome://policy. Firefox and other browsers "
    "are NOT covered — block them as apps instead.\n\n"
    "Apps: terminates running programs that ARE on the blocked list. Anything "
    "you have not listed is left alone, and critical Windows processes are "
    "refused even if you list them."
)


class Header(ttk.Frame):
    """Mascot, name and tagline — the app's face, always on screen."""

    def __init__(self, master):
        super().__init__(master, padding=(10, 8))
        self.mascot = load_mascot(self, 96)
        if self.mascot:
            tk.Label(self, image=self.mascot).pack(side="left", padx=(0, 12))
        text = ttk.Frame(self)
        text.pack(side="left", anchor="w")
        tk.Label(text, text=APP_NAME, font=("TkDefaultFont", 16, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(text, anchor="w", foreground="#6b7280", justify="left",
                 text="Lists what to block. Everything else is left alone.").pack(fill="x")


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.pack(fill="both", expand=True)
        self.watchdog = None
        self._messages = queue.Queue()
        self._blocked_events = queue.Queue()
        self._last_toast = {}
        data = load_data()

        # Plain-Python mirrors of the UI state. The watchdog thread reads these
        # instead of Tk widgets, which are not safe to touch off the UI thread.
        self._blocked_apps = list(data["apps"])
        self._dry_run = bool(data["dry_run"])

        Header(self).pack(fill="x", pady=(0, 6))

        # Everything below the header lives in `body`, which stays hidden
        # behind the lock screen until the PIN is entered.
        self.body = ttk.Frame(self)
        self.was_enrolling = not has_pin()

        nb = ttk.Notebook(self.body)
        nb.pack(fill="both", expand=True)
        tab_lists = ttk.Frame(nb, padding=8)
        tab_installed = ttk.Frame(nb)
        tab_enforce = ttk.Frame(nb, padding=8)
        tab_log = ttk.Frame(nb, padding=8)
        nb.add(tab_lists, text="Blocklists")
        nb.add(tab_installed, text="Installed apps")
        nb.add(tab_enforce, text="Enforcement")
        nb.add(tab_log, text="Activity")
        self.notebook, self.tab_lists = nb, tab_lists

        self._build_lists(tab_lists, data)
        self._build_installed(tab_installed)
        self._build_enforcement(tab_enforce)
        self._build_log(tab_log)

        self.admin = is_admin()
        status = ttk.Frame(self.body)
        status.pack(fill="x", pady=(6, 0))
        ttk.Label(status, foreground="grey", text=(
            f"v{VERSION}   |   {CONFIG_PATH}   |   "
            f"{'administrator' if self.admin else 'NOT elevated — enforcement disabled'}"
        )).pack(side="left")
        ttk.Button(status, text="Lock", width=6,
                   command=self.lock_now).pack(side="right")

        self.refresh_state()
        self.after(POLL_MS, self._drain_messages)

        # Enforcement starts before the PIN is entered, so a student cannot
        # dodge the blocks simply by dismissing the lock screen at logon.
        if "--enforce" in sys.argv and self.admin:
            self.start_enforcement()

        self.lock = None
        self.show_lock()

    # -- construction -------------------------------------------------------
    def _build_lists(self, parent, data) -> None:
        panes = ttk.Frame(parent)
        panes.pack(fill="both", expand=True)
        self.sites = ListPane(panes, "Blocked websites", "facebook.com",
                              normalize_site, self.persist)
        self.sites.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.apps = ListPane(panes, "Blocked apps", "steam.exe",
                             normalize_app, self.persist)
        self.apps.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.sites.set_items(data["websites"])
        self.apps.set_items(data["apps"])

        check = ttk.LabelFrame(parent, text="Check", padding=8)
        check.pack(fill="x", pady=(10, 0))
        self.query = ttk.Entry(check)
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<Return>", lambda e: self.check())
        self.kind = ttk.Combobox(check, values=["Website", "App"], width=9,
                                 state="readonly")
        self.kind.current(0)
        self.kind.pack(side="left", padx=6)
        ttk.Button(check, text="Check", command=self.check).pack(side="left")

        self.mascot_small = load_mascot(self, 48)
        self.result = tk.Label(parent, text="", font=("TkDefaultFont", 11, "bold"),
                               pady=6, padx=8, compound="left")
        self.result.pack(fill="x")

    def _build_installed(self, parent) -> None:
        # The scan is deferred until unlock -- no point scanning the PC for a
        # list nobody can see yet.
        self.installed = InstalledPane(parent, self.block_from_inventory)
        self.installed.pack(fill="both", expand=True)

    def _build_enforcement(self, parent) -> None:
        ttk.Label(parent, wraplength=600, justify="left",
                  text=ENFORCEMENT_HELP).pack(fill="x", pady=(0, 10))

        srow = ttk.Frame(parent)
        srow.pack(fill="x", pady=3)
        ttk.Button(srow, text="Apply website blocks",
                   command=self.apply_sites).pack(side="left")
        ttk.Button(srow, text="Remove website blocks",
                   command=self.clear_sites).pack(side="left", padx=6)
        self.site_state = ttk.Label(srow, text="")
        self.site_state.pack(side="left", padx=10)

        arow = ttk.Frame(parent)
        arow.pack(fill="x", pady=(12, 3))
        self.dry_run = tk.BooleanVar(value=self._dry_run)
        ttk.Checkbutton(arow, text="Dry run (log only, don't terminate)",
                        variable=self.dry_run, command=self.persist).pack(side="left")
        self.watch_btn = ttk.Button(arow, text="Start app watchdog",
                                    command=self.toggle_watchdog)
        self.watch_btn.pack(side="left", padx=10)

        trow = ttk.Frame(parent)
        trow.pack(fill="x", pady=(12, 3))
        ttk.Button(trow, text="Run at logon", command=self.add_task).pack(side="left")
        ttk.Button(trow, text="Stop running at logon",
                   command=self.del_task).pack(side="left", padx=6)

        prow = ttk.Frame(parent)
        prow.pack(fill="x", pady=(12, 3))
        ttk.Button(prow, text="Change PIN", command=self.change_pin).pack(side="left")
        ttk.Label(prow, foreground="grey",
                  text="Required to open Block Guard.").pack(side="left", padx=10)

    def _build_log(self, parent) -> None:
        self.logbox = tk.Text(parent, height=16, wrap="word", state="disabled")
        self.logbox.pack(fill="both", expand=True)
        ttk.Label(parent, text=LOG_PATH, foreground="grey").pack(fill="x", pady=(4, 0))

    # -- locking ------------------------------------------------------------
    def show_lock(self) -> None:
        """Hide everything behind the lock screen. Enforcement keeps running."""
        if self.lock:
            return
        self.body.pack_forget()
        self.lock = LockScreen(self, self.on_unlocked)
        self.lock.pack(fill="both", expand=True)

    def lock_now(self) -> None:
        self.was_enrolling = False
        self.show_lock()

    def on_unlocked(self) -> None:
        if self.was_enrolling:
            # Fresh enrollment: stop standard users from simply deleting the
            # PIN and blocklist files to undo all of this.
            if self.admin and restrict_data_dir():
                self.say("Configuration locked to administrators.")
            self.was_enrolling = False
        if self.lock:
            self.lock.destroy()
            self.lock = None
        self.body.pack(fill="both", expand=True)
        self.say("Unlocked.")
        if not self.installed._all:
            self.installed.refresh()

    def change_pin(self) -> None:
        ChangePinDialog(self, on_done=lambda: self.say("PIN changed."))

    def start_enforcement(self) -> None:
        """Start the watchdog without touching widgets or asking for a PIN."""
        if self.watchdog or not self._blocked_apps:
            return
        self.watchdog = Watchdog(lambda: self._blocked_apps,
                                 lambda: self._dry_run, self.say,
                                 on_blocked=self.note_blocked)
        self.watchdog.start()
        self.watch_btn.configure(text="Stop app watchdog")

    # -- state --------------------------------------------------------------
    def persist(self) -> None:
        """Save, and refresh the snapshots the watchdog thread reads."""
        self._blocked_apps = self.apps.items()
        self._dry_run = self.dry_run.get() if hasattr(self, "dry_run") else True
        try:
            save_data({"websites": self.sites.items(),
                       "apps": self._blocked_apps,
                       "dry_run": self._dry_run})
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n{exc}")

    def say(self, line: str) -> None:
        """Safe to call from any thread; the UI drains the queue."""
        self._messages.put(line)

    def note_blocked(self, name: str) -> None:
        """Called from the watchdog thread; the UI thread does the popup."""
        self._blocked_events.put(name)

    def display_name(self, exe: str) -> str:
        """Prefer the friendly product name the inventory found."""
        for entry in self.installed._all:
            if entry["exe"] == exe:
                return entry["name"]
        return exe.title()

    def _show_toast(self, exe: str) -> None:
        now = time.time()
        if now - self._last_toast.get(exe, 0) < TOAST_COOLDOWN_SECONDS:
            return
        self._last_toast[exe] = now
        try:
            BlockedToast(self.winfo_toplevel(), self.display_name(exe))
        except tk.TclError as exc:
            log(f"could not show the blocked notice: {exc}")

    def _drain_messages(self) -> None:
        while True:
            try:
                line = self._messages.get_nowait()
            except queue.Empty:
                break
            self.logbox.configure(state="normal")
            self.logbox.insert("end", f"{datetime.now():%H:%M:%S}  {line}\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        while True:
            try:
                self._show_toast(self._blocked_events.get_nowait())
            except queue.Empty:
                break
        self.after(POLL_MS, self._drain_messages)

    def refresh_state(self) -> None:
        if winreg:
            self.site_state.configure(
                text="active" if site_policy_active() else "not applied")

    def need_admin(self) -> bool:
        if self.admin:
            return False
        if messagebox.askyesno(
                APP_NAME, "Enforcement needs administrator rights.\nRestart elevated now?"):
            relaunch_as_admin()
        return True

    # -- actions ------------------------------------------------------------
    def check(self) -> None:
        value = self.query.get().strip()
        if not value:
            return
        if self.kind.get() == "Website":
            hit, shown = site_blocked(value, self.sites.items()), normalize_site(value)
        else:
            hit, shown = app_blocked(value, self.apps.items()), normalize_app(value)
        self.result.configure(
            text=f"{shown} — {'BLOCKED' if hit else 'not blocked'}",
            fg="#b42318" if hit else "#1a7f37",
            image=(self.mascot_small or "") if hit else "")

    def block_from_inventory(self, executables) -> None:
        added = [exe for exe in executables if self.apps.add_value(exe)]
        if added:
            self.say(f"Blocked: {', '.join(sorted(added))}")
            self.notebook.select(self.tab_lists)
        else:
            self.say("Those apps are already blocked.")

    def apply_sites(self) -> None:
        if self.need_admin():
            return
        domains = self.sites.items()
        if not domains:
            messagebox.showinfo(APP_NAME, "The blocked website list is empty — "
                                          "there is nothing to block.")
            return
        touched = apply_site_policy(domains)
        self.say(f"Blocked {len(domains)} domains in {', '.join(touched) or 'nothing'}.")
        self.refresh_state()

    def clear_sites(self) -> None:
        if self.need_admin():
            return
        clear_site_policy()
        self.say("Website blocks removed.")
        self.refresh_state()

    def toggle_watchdog(self) -> None:
        if self.watchdog:
            self.watchdog.stop()
            self.watchdog = None
            self.watch_btn.configure(text="Start app watchdog")
            return
        if self.need_admin():
            return
        self.persist()
        if not self._blocked_apps:
            messagebox.showinfo(APP_NAME, "The blocked app list is empty — "
                                          "the watchdog would have nothing to do.")
            return
        if not self._dry_run and not messagebox.askyesno(
                APP_NAME, "Live mode will close these programs whenever they "
                          f"run:\n\n{', '.join(self._blocked_apps)}\n\nContinue?"):
            return
        self.watchdog = Watchdog(lambda: self._blocked_apps,
                                 lambda: self._dry_run, self.say,
                                 on_blocked=self.note_blocked)
        self.watchdog.start()
        self.watch_btn.configure(text="Stop app watchdog")

    def add_task(self) -> None:
        if self.need_admin():
            return
        self.say("Logon task created." if install_logon_task()
                 else "Could not create logon task.")

    def del_task(self) -> None:
        if self.need_admin():
            return
        self.say("Logon task removed." if remove_logon_task()
                 else "Could not remove logon task.")


def main() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("760x640")
    root.minsize(680, 560)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    set_window_icon(root)
    app = App(root)
    root.protocol("WM_DELETE_WINDOW",
                  lambda: (app.watchdog and app.watchdog.stop(), root.destroy()))
    root.mainloop()
