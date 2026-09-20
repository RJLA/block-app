"""The list widgets: the editable blocklists and the installed-app picker."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from .inventory import inventory
from .naming import PROTECTED_APPS, normalize_app
from .paths import log

POLL_MS = 150


class ListPane(ttk.LabelFrame):
    """An editable list of blocked entries."""

    def __init__(self, master, title, placeholder, normalizer, on_change):
        super().__init__(master, text=title, padding=8)
        self.normalizer, self.on_change = normalizer, on_change
        self._placeholder = placeholder

        row = ttk.Frame(self)
        row.pack(fill="x")
        self.entry = ttk.Entry(row, foreground="grey")
        self.entry.insert(0, placeholder)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._restore_placeholder)
        self.entry.bind("<Return>", lambda e: self.add())
        ttk.Button(row, text="Add", width=6, command=self.add).pack(side="left", padx=(6, 0))

        self.listbox = tk.Listbox(self, height=11, activestyle="none",
                                  exportselection=False, selectmode="extended")
        self.listbox.pack(fill="both", expand=True, pady=(8, 6))
        self.listbox.bind("<Delete>", lambda e: self.remove())
        ttk.Button(self, text="Remove selected", command=self.remove).pack(fill="x")

    def _clear_placeholder(self, _event=None):
        if self.entry.get() == self._placeholder:
            self.entry.delete(0, "end")
            self.entry.configure(foreground="")

    def _restore_placeholder(self, _event=None):
        if not self.entry.get().strip():
            self.entry.delete(0, "end")
            self.entry.insert(0, self._placeholder)
            self.entry.configure(foreground="grey")

    def items(self) -> list:
        return list(self.listbox.get(0, "end"))

    def set_items(self, items) -> None:
        self.listbox.delete(0, "end")
        for item in items:
            self.listbox.insert("end", item)

    def add_value(self, raw: str) -> bool:
        """Normalize and insert. False if empty or already present."""
        value = self.normalizer(raw)
        if not value or value in self.items():
            return False
        self.set_items(sorted(self.items() + [value]))
        self.on_change()
        return True

    def add(self) -> None:
        raw = self.entry.get()
        if raw == self._placeholder:
            return
        if self.add_value(raw):
            self.entry.delete(0, "end")

    def remove(self) -> None:
        for index in reversed(list(self.listbox.curselection())):
            self.listbox.delete(index)
        self.on_change()


class InstalledPane(ttk.Frame):
    """Lists what is installed on this PC so apps can be picked, not typed.

    The scan touches the registry and the disk, so it runs on a worker thread
    and hands results back through a queue that the UI thread polls -- Tk
    widgets are only ever touched from the UI thread.
    """

    def __init__(self, master, on_block):
        super().__init__(master, padding=8)
        self.on_block = on_block
        self._all = []
        self._queue = queue.Queue()

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Label(bar, text="Search").pack(side="left")
        self.search = ttk.Entry(bar, width=24)
        self.search.pack(side="left", padx=(6, 10))
        self.search.bind("<KeyRelease>", lambda e: self._render())
        self.running_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Running now only", variable=self.running_only,
                        command=self._render).pack(side="left")
        self.refresh_btn = ttk.Button(bar, text="Refresh", command=self.refresh)
        self.refresh_btn.pack(side="right")

        columns = ("name", "exe", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings",
                                 selectmode="extended", height=13)
        for key, label, width in (("name", "Application", 250),
                                  ("exe", "Executable", 150),
                                  ("status", "Status", 90)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(8, 6), side="left")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scroll.pack(fill="y", side="left", pady=(8, 6))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda e: self.block_selected())

        footer = ttk.Frame(self)
        footer.pack(fill="x", side="bottom")
        self.status = ttk.Label(footer, text="", foreground="grey")
        self.status.pack(side="left")
        ttk.Button(footer, text="Block selected",
                   command=self.block_selected).pack(side="right")

    # -- loading ------------------------------------------------------------
    def refresh(self) -> None:
        self.refresh_btn.configure(state="disabled")
        self.status.configure(text="Scanning this PC ...")
        threading.Thread(target=self._scan, daemon=True).start()
        self.after(POLL_MS, self._drain)

    def _scan(self) -> None:
        """Worker thread: never touches a widget."""
        try:
            self._queue.put(inventory())
        except Exception as exc:                  # a broken registry entry, say
            log(f"inventory failed: {exc}")
            self._queue.put([])

    def _drain(self) -> None:
        try:
            self._all = self._queue.get_nowait()
        except queue.Empty:
            self.after(POLL_MS, self._drain)
            return
        self.refresh_btn.configure(state="normal")
        self._render()

    # -- rendering ----------------------------------------------------------
    def _visible(self) -> list:
        term = self.search.get().strip().lower()
        rows = self._all
        if self.running_only.get():
            rows = [r for r in rows if r["running"]]
        if term:
            rows = [r for r in rows
                    if term in r["name"].lower() or term in r["exe"].lower()]
        # Running apps first -- those are the ones the watchdog can act on now.
        return sorted(rows, key=lambda r: (not r["running"], r["name"].lower()))

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = self._visible()
        for row in rows:
            self.tree.insert("", "end", values=(
                row["name"], row["exe"], "running" if row["running"] else ""))
        self.status.configure(
            text=f"{len(rows)} shown of {len(self._all)} found"
            if self._all else "No applications found.")

    # -- actions ------------------------------------------------------------
    def block_selected(self) -> None:
        chosen = [self.tree.item(i)["values"][1] for i in self.tree.selection()]
        usable = [str(e) for e in chosen
                  if e and normalize_app(str(e)) not in PROTECTED_APPS]
        if usable:
            self.on_block(usable)
