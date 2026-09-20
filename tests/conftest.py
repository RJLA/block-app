"""Shared Tk fixtures.

Creating a Tk() per test spins up a fresh Tcl interpreter each time, and on
Windows that intermittently fails to read Tcl's own library files (antivirus
and file-handle contention), producing random spurious skips. One interpreter
for the whole session, with a throwaway Toplevel per test, avoids that and is
considerably faster.
"""

import tkinter as tk

import pytest


@pytest.fixture(autouse=True)
def silence_sound(monkeypatch):
    """Tests must not make noise. test_sound.py re-enables it deliberately."""
    monkeypatch.setattr("blockguard.sound.enabled", False)


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal dialog in a test hangs the whole run with nothing on screen.

    Individual tests override these when the answer is what they assert on.
    """
    for name, answer in (("askyesno", False), ("askokcancel", False),
                         ("showinfo", None), ("showerror", None),
                         ("showwarning", None)):
        monkeypatch.setattr(f"tkinter.messagebox.{name}",
                            lambda *a, _answer=answer, **k: _answer)


@pytest.fixture(scope="session")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:                 # genuinely headless
        pytest.skip(f"Tk unavailable: {exc}")
        return
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def window(tk_root):
    """A fresh Toplevel per test, so widgets never leak between tests."""
    top = tk.Toplevel(tk_root)
    top.withdraw()
    yield top
    try:
        top.destroy()
    except tk.TclError:
        pass
