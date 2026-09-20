"""Spotting when a blocked website was opened.

Block Guard writes browser policy and the browser does the blocking itself, so
there is no callback to hang a notice on. The nearest honest signal is the
browser's window title: a blocked tab shows the host it refused to load.

Matching is deliberately strict -- the whole title, minus a known browser
suffix, must resolve to a blocked host. A Google search for "reddit.com" is
titled "reddit.com - Google Search", which does not match, and that matters
more than catching every possible title format.
"""

import ctypes
import threading

from .naming import normalize_site, site_blocked
from .paths import log

POLL_SECONDS = 2

# Trailing text browsers append to the page title.
BROWSER_SUFFIXES = (
    " - Google Chrome",
    " - Microsoft Edge",
    " - Mozilla Firefox",
    " - Brave",
    " - Opera",
    " - Vivaldi",
    " and 1 more page - Personal - Microsoft​ Edge",
)


def list_window_titles() -> list:
    """Titles of every visible top-level window."""
    titles = []
    try:
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                           ctypes.c_void_p)

        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append(buffer.value)
            return True

        user32.EnumWindows(callback_type(visit), 0)
    except Exception as exc:
        log(f"window enumeration failed: {exc}")
    return titles


def strip_browser_suffix(title: str) -> str:
    """"reddit.com - Google Chrome" -> "reddit.com"."""
    cleaned = (title or "").strip()
    for suffix in BROWSER_SUFFIXES:
        # Edge inserts a zero-width space before its name on some builds.
        for variant in (suffix, suffix.replace("​", "")):
            if variant and cleaned.endswith(variant):
                return cleaned[: -len(variant)].strip(" -​")
    return cleaned


def blocked_hits(titles, blocked_sites) -> list:
    """Which blocked domains are currently showing in a browser window."""
    if not blocked_sites:
        return []
    found = []
    for title in titles:
        candidate = strip_browser_suffix(title)
        if not candidate or candidate == title:
            continue                       # not a browser window we recognise
        host = normalize_site(candidate)
        if host and " " not in host and site_blocked(host, blocked_sites):
            found.append(host)
    return found


class BrowserWatch(threading.Thread):
    """Polls window titles and reports blocked sites that are on screen.

    `get_blocked_sites` must be thread-safe -- it is called from this thread,
    so it must not touch Tk widgets.
    """

    def __init__(self, get_blocked_sites, on_hit):
        super().__init__(daemon=True)
        self.get_blocked_sites = get_blocked_sites
        self.on_hit = on_hit
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            sites = self.get_blocked_sites()
            if sites:
                for host in set(blocked_hits(list_window_titles(), sites)):
                    self.on_hit(host)
            self._stop.wait(POLL_SECONDS)
