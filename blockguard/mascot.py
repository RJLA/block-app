"""The crying frog. Cosmetic throughout -- a missing asset never breaks the UI."""

import tkinter as tk

from .paths import log, resource_path

# Tk discards images that nothing on the Python side still references. Callers
# normally hold their own reference; this backs up the ones that cannot.
_KEEP_ALIVE = []


def load_mascot(master, size: int):
    """Return a PhotoImage at the requested size, or None if unavailable.

    `master` is required on purpose. Without it Tk binds the image to the
    default root, which breaks as soon as more than one root has existed --
    the second one raises TclError on a perfectly valid asset.
    """
    path = resource_path("assets", f"mascot_{size}.png")
    try:
        return tk.PhotoImage(master=master, file=path)
    except (tk.TclError, OSError):
        log(f"mascot {size}px unavailable at {path}")
        return None


def set_window_icon(root: tk.Tk) -> None:
    """Mascot in the title bar and taskbar."""
    try:
        root.iconbitmap(resource_path("assets", "mascot.ico"))
        return
    except tk.TclError:
        pass
    icon = load_mascot(root, 96)
    if icon:
        root.iconphoto(True, icon)
        _KEEP_ALIVE.append(icon)
