"""The crying frog. Cosmetic throughout -- a missing asset never breaks the UI."""

import tkinter as tk

from .paths import log, resource_path

# Tk discards images that nothing on the Python side still references.
_KEEP_ALIVE = []


def load_mascot(size: int):
    """Return a PhotoImage at the requested size, or None if unavailable."""
    path = resource_path("assets", f"mascot_{size}.png")
    try:
        image = tk.PhotoImage(file=path)
    except (tk.TclError, OSError):
        log(f"mascot {size}px unavailable at {path}")
        return None
    _KEEP_ALIVE.append(image)
    return image


def set_window_icon(root: tk.Tk) -> None:
    """Mascot in the title bar and taskbar."""
    try:
        root.iconbitmap(resource_path("assets", "mascot.ico"))
        return
    except tk.TclError:
        pass
    icon = load_mascot(96)
    if icon:
        root.iconphoto(True, icon)
