"""The main window."""

import queue
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import APP_NAME, VERSION
from .browser_watch import BrowserWatch
from .config import load_data, save_data
from .mascot import load_mascot, set_window_icon
from .naming import app_blocked, normalize_app, normalize_site, site_blocked
from .paths import CONFIG_PATH, LOG_PATH, log
from .pin import has_pin
from .processes import Watchdog
from .sites import apply_site_policy, clear_site_policy, site_policy_active
from .single_instance import acquire, consume_show_request, request_show
from .sound import play_blocked, shutdown as shutdown_sound
from .system import (
    install_logon_task, is_admin, logon_task_exists, relaunch_as_admin,
    remove_logon_task, restrict_data_dir,
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
# How often a background session checks whether it has been summoned.
SHOW_POLL_MS = 600

ENFORCEMENT_HELP = (
    "Good to know:  after turning protection on, close and reopen Chrome or "
    "Edge — websites stay reachable until the browser restarts.  Other "
    "browsers such as Firefox ignore website blocking, so block those as apps "
    "instead.  Only the things on your lists are affected; everything else is "
    "left alone, and important Windows programs can never be blocked."
)

TURN_ON_WARNING = (
    "Protection will start now.\n\n"
    "These apps will close whenever they are opened:\n{apps}\n\n"
    "These websites will stop loading:\n{sites}\n\n"
    "Turn protection on?"
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
        self.browser_watch = None
        self.background = False
        self._messages = queue.Queue()
        self._blocked_events = queue.Queue()
        self._last_toast = {}
        data = load_data()

        # Plain-Python mirrors of the UI state. The watchdog thread reads these
        # instead of Tk widgets, which are not safe to touch off the UI thread.
        self._blocked_apps = list(data["apps"])
        self._blocked_sites = list(data["websites"])
        self._dry_run = bool(data["dry_run"])
        self._protection = bool(data["protection"])

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

        self.autostart.set(logon_task_exists())
        self.refresh_state()
        self.after(POLL_MS, self._drain_messages)

        # Protection resumes by itself if it was left on, before the PIN is
        # entered, so a student cannot dodge the blocks by dismissing the lock
        # screen or by closing the window.
        if self._protection and self.admin:
            self.resume_protection()

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
        """One switch, plain words, and the current state always visible."""
        card = ttk.LabelFrame(parent, text="Protection", padding=14)
        card.pack(fill="x")

        top = ttk.Frame(card)
        top.pack(fill="x")
        self.status_big = tk.Label(top, font=("TkDefaultFont", 15, "bold"),
                                   anchor="w")
        self.status_big.pack(side="left")
        self.protect_btn = ttk.Button(top, width=22,
                                      command=self.toggle_protection)
        self.protect_btn.pack(side="right")

        self.status_detail = tk.Label(card, anchor="w", justify="left",
                                      foreground="#374151")
        self.status_detail.pack(fill="x", pady=(8, 0))

        self.status_hint = tk.Label(card, anchor="w", justify="left",
                                    wraplength=620, foreground="#6b7280")
        self.status_hint.pack(fill="x", pady=(6, 0))

        options = ttk.LabelFrame(parent, text="Options", padding=14)
        options.pack(fill="x", pady=(12, 0))

        self.dry_run = tk.BooleanVar(value=self._dry_run)
        ttk.Checkbutton(
            options, variable=self.dry_run, command=self.on_test_mode_changed,
            text="Practice mode — show what would be blocked, but don't close anything"
        ).pack(anchor="w")

        self.autostart = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, variable=self.autostart, command=self.toggle_autostart,
            text="Turn on automatically whenever this PC starts"
        ).pack(anchor="w", pady=(6, 0))

        extras = ttk.Frame(parent)
        extras.pack(fill="x", pady=(14, 0))
        ttk.Button(extras, text="Change PIN",
                   command=self.change_pin).pack(side="left")
        ttk.Label(extras, foreground="grey",
                  text="Needed to open Block Guard.").pack(side="left", padx=10)

        tk.Label(parent, anchor="w", justify="left", wraplength=620,
                 foreground="#6b7280", text=ENFORCEMENT_HELP
                 ).pack(fill="x", pady=(14, 0))

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
        """Start the watchdog without touching widgets or asking for a PIN.

        No empty-list guard here: the watchdog skips its scan while the list
        is empty and picks up additions live, so a background session started
        with nothing blocked still works once entries are added.
        """
        if self.watchdog:
            return
        self.watchdog = Watchdog(lambda: self._blocked_apps,
                                 lambda: self._dry_run, self.say,
                                 on_blocked=self.note_blocked)
        self.watchdog.start()
        self.start_browser_watch()
        self.refresh_state()

    def start_browser_watch(self) -> None:
        """Notice blocked sites the browser is refusing to load."""
        if self.browser_watch:
            return
        self.browser_watch = BrowserWatch(lambda: self._blocked_sites,
                                          self.note_site_blocked)
        self.browser_watch.start()

    def stop_browser_watch(self) -> None:
        if self.browser_watch:
            self.browser_watch.stop()
            self.browser_watch = None

    # -- background mode ----------------------------------------------------
    def go_background(self) -> None:
        """Hide, keep running, and listen for a request to come back."""
        if not self.background:
            self.background = True
            self._poll_show_requests()
        self.hide()

    def enter_background(self) -> None:
        """Launched with --background: no window, protection resumed."""
        if self._protection and self.admin:
            self.resume_protection()
        self.go_background()
        self.say("Running in the background.")

    def _poll_show_requests(self) -> None:
        if consume_show_request():
            self.reveal()
        self.after(SHOW_POLL_MS, self._poll_show_requests)

    def reveal(self) -> None:
        """Bring the window back, always locked."""
        self.show_lock()
        top = self.winfo_toplevel()
        top.deiconify()
        top.lift()
        top.focus_force()

    def hide(self) -> None:
        """Re-lock and disappear, leaving enforcement running."""
        self.show_lock()
        self.winfo_toplevel().withdraw()

    def on_close(self) -> None:
        """Closing must never silently switch protection off.

        While protection is on the window hides and keeps working; only with
        protection off does closing actually quit.
        """
        if self.background or self.protection_on():
            self.go_background()
            return
        self.stop_browser_watch()
        shutdown_sound()
        self.winfo_toplevel().destroy()

    # -- state --------------------------------------------------------------
    def persist(self) -> None:
        """Save, and refresh the snapshots the watchdog thread reads."""
        self._blocked_apps = self.apps.items()
        self._blocked_sites = self.sites.items()
        self._dry_run = self.dry_run.get() if hasattr(self, "dry_run") else True
        try:
            save_data({"websites": self._blocked_sites,
                       "apps": self._blocked_apps,
                       "dry_run": self._dry_run,
                       "protection": self._protection})
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n{exc}")

    def say(self, line: str) -> None:
        """Safe to call from any thread; the UI drains the queue."""
        self._messages.put(line)

    def note_blocked(self, name: str) -> None:
        """Called from a worker thread; the UI thread does the popup."""
        self._blocked_events.put(name)

    def note_site_blocked(self, host: str) -> None:
        """A blocked site is on screen. Logged as well, so the match is
        visible in the Activity tab when tuning what the browser titles are."""
        if time.time() - self._last_toast.get(host, 0) >= TOAST_COOLDOWN_SECONDS:
            self.say(f"blocked site on screen: {host}")
        self._blocked_events.put(host)

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
        play_blocked()                     # shares the cooldown with the toast
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
        """Keep the Protection card honest about what is actually happening."""
        if not hasattr(self, "status_big"):
            return
        on = self.protection_on()
        practising = bool(self._dry_run)

        if on and practising:
            headline, colour = "Practice mode", "#b45309"
        elif on:
            headline, colour = "Protection is ON", "#1a7f37"
        else:
            headline, colour = "Protection is OFF", "#b42318"
        self.status_big.configure(text=headline, fg=colour)
        self.protect_btn.configure(
            text="Turn protection off" if on else "Turn protection on")

        sites_on = bool(winreg) and site_policy_active()
        self.status_detail.configure(text=(
            f"Websites:  {len(self._blocked_sites)} on the list"
            f"  —  {'being blocked' if sites_on else 'not blocked yet'}\n"
            f"Apps:  {len(self._blocked_apps)} on the list"
            f"  —  {'being watched' if on else 'not watched yet'}"))

        if self._protection and not on:
            # Wanted on, but cannot run -- say so rather than looking broken.
            hint = ("Protection is set to on, but Block Guard is not running "
                    "as administrator, so nothing is being blocked. Reopen it "
                    "with “Run as administrator”.")
        elif not on:
            hint = ("Nothing is being blocked right now. "
                    "Press “Turn protection on” when your lists are ready.")
        elif practising:
            hint = ("Nothing is really being closed. Open one of the blocked "
                    "apps and watch the Activity tab to check your list, then "
                    "untick practice mode when you are happy.")
        else:
            hint = ("Blocked apps will close on their own, and blocked "
                    "websites will not load. Closing this window keeps "
                    "protection running in the background.")
        self.status_hint.configure(text=hint)

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

    # -- protection, as one switch -----------------------------------------
    def protection_on(self) -> bool:
        return self.watchdog is not None

    def toggle_protection(self) -> None:
        if self.protection_on():
            self.turn_protection_off()
        else:
            self.turn_protection_on()

    def turn_protection_on(self) -> None:
        if self.need_admin():
            return
        self.persist()
        if not self._blocked_apps and not self._blocked_sites:
            messagebox.showinfo(
                APP_NAME,
                "Nothing is on your lists yet.\n\n"
                "Go to the Installed apps tab to pick apps to block, or add "
                "websites on the Blocklists tab.")
            return
        # Practice mode changes nothing on the PC, so it needs no warning.
        if not self._dry_run and not messagebox.askyesno(APP_NAME, TURN_ON_WARNING.format(
                apps=self._bullets(self._blocked_apps),
                sites=self._bullets(self._blocked_sites))):
            return

        self._protection = True
        self.persist()
        self.resume_protection()
        self.say("Protection is on, and will stay on.")

        # "On" has to mean on after a reboot too, or it quietly lapses the
        # first time the PC restarts.
        if not logon_task_exists() and install_logon_task():
            self.say("Block Guard will now start automatically with this PC.")
        self.autostart.set(logon_task_exists())
        self.refresh_state()

    def resume_protection(self) -> None:
        """Apply everything without prompting -- consent was given already."""
        if self._blocked_sites:
            touched = apply_site_policy(self._blocked_sites)
            self.say(f"Blocking {len(self._blocked_sites)} websites "
                     f"in {', '.join(touched) or 'no browser'}.")
        self.start_enforcement()
        self.refresh_state()

    def turn_protection_off(self) -> None:
        if self.need_admin():
            return
        self._protection = False
        self.persist()
        if self.watchdog:
            self.watchdog.stop()
            self.watchdog = None
        self.stop_browser_watch()
        clear_site_policy()
        self.say("Protection is off.")
        self.refresh_state()

    @staticmethod
    def _bullets(items) -> str:
        if not items:
            return "   (none)"
        shown = ["   • " + item for item in items[:8]]
        if len(items) > 8:
            shown.append(f"   • …and {len(items) - 8} more")
        return "\n".join(shown)

    def on_test_mode_changed(self) -> None:
        self.persist()
        self.say("Practice mode on — nothing will be closed."
                 if self._dry_run else "Practice mode off — blocking for real.")
        self.refresh_state()

    def toggle_autostart(self) -> None:
        if self.need_admin():
            self.autostart.set(logon_task_exists())
            return
        if self.autostart.get():
            ok = install_logon_task()
            self.say("Will start automatically with this PC."
                     if ok else "Could not set up automatic start.")
        else:
            ok = remove_logon_task()
            self.say("Will no longer start automatically."
                     if ok else "Could not remove automatic start.")
        self.autostart.set(logon_task_exists())



def main() -> None:
    background = "--background" in sys.argv

    # A second launch does not start a second copy; it asks the running one
    # to show its lock screen, which is the only way back in from background
    # mode since there is no window and no tray icon.
    if not acquire():
        request_show()
        return

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
    if background:
        app.enter_background()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
