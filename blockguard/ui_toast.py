"""The popup a student sees when a blocked app is closed.

Without this the app simply vanishes a few seconds after launch, which reads
as a broken PC rather than a deliberate block.

The toast is its own top-level window, so it still appears while Block Guard
itself is locked -- which is the only state a student will ever see it in.
"""

import tkinter as tk

from .mascot import load_mascot

DURATION_MS = 7000
MARGIN = 24
# Rough allowance for the taskbar, so the toast does not sit under it.
TASKBAR_ALLOWANCE = 64

BLOCKED_TEXT = "{name} is blocked"
HELP_TEXT = "Ask your Tito or Mommy Joy to unblock it."


class BlockedToast(tk.Toplevel):
    """A small, undecorated, always-on-top notice that dismisses itself."""

    def __init__(self, master, name: str, duration_ms: int = DURATION_MS):
        super().__init__(master)
        self.overrideredirect(True)
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

        outer = tk.Frame(self, background="#b42318", padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, background="#ffffff", padx=16, pady=14)
        inner.pack(fill="both", expand=True)

        self.mascot = load_mascot(self, 96)
        if self.mascot:
            tk.Label(inner, image=self.mascot, background="#ffffff"
                     ).pack(side="left", padx=(0, 14))

        text = tk.Frame(inner, background="#ffffff")
        text.pack(side="left", fill="both", expand=True)
        tk.Label(text, text=BLOCKED_TEXT.format(name=name), background="#ffffff",
                 foreground="#b42318", font=("TkDefaultFont", 14, "bold"),
                 anchor="w", justify="left").pack(fill="x")
        tk.Label(text, text=HELP_TEXT, background="#ffffff", foreground="#374151",
                 font=("TkDefaultFont", 11), anchor="w", justify="left",
                 wraplength=360).pack(fill="x", pady=(4, 0))

        self.bind("<Button-1>", lambda _e: self.close())
        for child in (outer, inner, text):
            child.bind("<Button-1>", lambda _e: self.close())

        self._place()
        self._job = self.after(duration_ms, self.close)

    def _place(self) -> None:
        """Bottom-right of the primary screen."""
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x = self.winfo_screenwidth() - width - MARGIN
        y = self.winfo_screenheight() - height - TASKBAR_ALLOWANCE
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def close(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        try:
            self.destroy()
        except tk.TclError:
            pass
