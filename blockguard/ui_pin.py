"""The lock screen: PIN enrollment on first run, PIN entry afterwards."""

import tkinter as tk
from tkinter import ttk

from . import APP_NAME
from .mascot import load_mascot
from .pin import (
    PIN_LENGTH, change_pin, has_pin, is_valid_pin, lockout_remaining, set_pin,
    verify_pin,
)

TICK_MS = 500

ENROLL_BLURB = (
    "Choose a 6-digit PIN. It will be required every time Block Guard is "
    "opened, so the blocklist cannot be changed by anyone who does not know it."
)
UNLOCK_BLURB = (
    "Enter the PIN to view and change the blocklist. Blocking stays active "
    "either way."
)


class PinEntry(ttk.Entry):
    """An entry that accepts at most six digits and shows dots."""

    def __init__(self, master, on_submit):
        self.var = tk.StringVar()
        super().__init__(master, textvariable=self.var, show="•",
                         justify="center", width=12,
                         font=("TkDefaultFont", 20, "bold"))
        self.var.trace_add("write", self._sanitize)
        self.bind("<Return>", lambda e: on_submit())

    def _sanitize(self, *_args):
        digits = "".join(c for c in self.var.get() if c.isdigit())[:PIN_LENGTH]
        if digits != self.var.get():
            self.var.set(digits)

    def value(self) -> str:
        return self.var.get()

    def clear(self) -> None:
        self.var.set("")


class LockScreen(ttk.Frame):
    """Covers the app until the correct PIN is entered.

    Enrollment mode is chosen automatically when no PIN exists yet.
    """

    def __init__(self, master, on_unlocked):
        super().__init__(master, padding=24)
        self.on_unlocked = on_unlocked
        self.enrolling = not has_pin()
        self._countdown_job = None

        self.mascot = load_mascot(self, 96)
        if self.mascot:
            tk.Label(self, image=self.mascot).pack(pady=(10, 4))

        tk.Label(self, font=("TkDefaultFont", 15, "bold"),
                 text=("Create a PIN" if self.enrolling else f"{APP_NAME} is locked")
                 ).pack(pady=(4, 2))
        tk.Label(self, wraplength=420, justify="center", foreground="#6b7280",
                 text=ENROLL_BLURB if self.enrolling else UNLOCK_BLURB
                 ).pack(pady=(0, 14))

        self.entry = PinEntry(self, self.submit)
        self.entry.pack()

        self.confirm = None
        if self.enrolling:
            tk.Label(self, text="Confirm", foreground="#6b7280").pack(pady=(10, 2))
            self.confirm = PinEntry(self, self.submit)
            self.confirm.pack()

        self.message = tk.Label(self, text="", foreground="#b42318",
                                font=("TkDefaultFont", 10, "bold"))
        self.message.pack(pady=(12, 6))

        self.button = ttk.Button(
            self, text="Set PIN" if self.enrolling else "Unlock",
            command=self.submit)
        self.button.pack()

        self.entry.focus_set()
        if not self.enrolling:
            self._tick_lockout()

    # -- lockout ------------------------------------------------------------
    def _tick_lockout(self) -> None:
        remaining = lockout_remaining()
        if remaining > 0:
            self.button.configure(state="disabled")
            self.entry.configure(state="disabled")
            self.message.configure(
                text=f"Too many wrong attempts. Try again in {remaining}s.")
        else:
            self.button.configure(state="normal")
            self.entry.configure(state="normal")
            if self.message.cget("text").startswith("Too many"):
                self.message.configure(text="")
        self._countdown_job = self.after(TICK_MS, self._tick_lockout)

    def destroy(self) -> None:
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
        super().destroy()

    # -- actions ------------------------------------------------------------
    def submit(self) -> None:
        if self.enrolling:
            self._enroll()
        else:
            self._unlock()

    def _enroll(self) -> None:
        if self.confirm is None:
            return
        pin, again = self.entry.value(), self.confirm.value()
        if not is_valid_pin(pin):
            self._fail(f"The PIN must be exactly {PIN_LENGTH} digits.")
            return
        if pin != again:
            self._fail("The two entries do not match.")
            self.confirm.clear()
            self.confirm.focus_set()
            return
        if not set_pin(pin):
            self._fail("Could not save the PIN.")
            return
        self.on_unlocked()

    def _unlock(self) -> None:
        pin = self.entry.value()
        if verify_pin(pin):
            self.on_unlocked()
            return
        self.entry.clear()
        self.entry.focus_set()
        remaining = lockout_remaining()
        self._fail("Too many wrong attempts." if remaining
                   else "Wrong PIN.")

    def _fail(self, text: str) -> None:
        self.message.configure(text=text)


class ChangePinDialog(tk.Toplevel):
    """Replace the PIN. Requires the current one, so an unlocked but
    unattended window still cannot be used to lock the owner out."""

    def __init__(self, master, on_done=None):
        super().__init__(master)
        self.title(f"{APP_NAME} — Change PIN")
        self.resizable(False, False)
        self.transient(master)
        self.on_done = on_done

        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)

        self.fields = {}
        for key, label in (("current", "Current PIN"),
                           ("new", "New PIN"),
                           ("again", "Confirm new PIN")):
            ttk.Label(body, text=label).pack(anchor="w", pady=(6, 2))
            field = PinEntry(body, self.submit)
            field.pack()
            self.fields[key] = field

        self.message = tk.Label(body, text="", foreground="#b42318")
        self.message.pack(pady=(10, 6))

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(row, text="Change PIN",
                   command=self.submit).pack(side="right", padx=(0, 6))

        self.fields["current"].focus_set()
        try:
            self.grab_set()                # modal; fails if not yet viewable
        except tk.TclError:
            pass

    def submit(self) -> None:
        new, again = self.fields["new"].value(), self.fields["again"].value()
        if not is_valid_pin(new):
            self.message.configure(text=f"The new PIN must be {PIN_LENGTH} digits.")
            return
        if new != again:
            self.message.configure(text="The new entries do not match.")
            return
        if not change_pin(self.fields["current"].value(), new):
            remaining = lockout_remaining()
            self.message.configure(
                text=f"Locked out for {remaining}s." if remaining
                else "The current PIN is wrong.")
            self.fields["current"].clear()
            self.fields["current"].focus_set()
            return
        if self.on_done:
            self.on_done()
        self.destroy()
