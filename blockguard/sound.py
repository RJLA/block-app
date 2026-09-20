"""The sound that plays when a blocked app is closed.

Windows MCI via ctypes, because the app is stdlib-only and winsound cannot
play MP3 -- it handles WAV and system sounds only. MCI decodes MP3 natively
and `play` returns immediately, so the UI never blocks on it.

Entirely best-effort: a missing file, a machine with no audio device, or a
remote session simply means no sound.
"""

import ctypes
import os

from .paths import log, resource_path

ALIAS = "blockguard_blocked"
SOUND_NAME = "blocked.mp3"

enabled = True


def sound_path() -> str:
    return resource_path("assets", SOUND_NAME)


def _send(command: str) -> int:
    """Return 0 on success, or the MCI error code."""
    try:
        return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
    except Exception as exc:
        log(f"audio unavailable: {exc}")
        return -1


def play_blocked() -> bool:
    """Play the notice sound. False if it could not be played."""
    if not enabled:
        return False
    path = sound_path()
    if not os.path.exists(path):
        log(f"sound missing at {path}")
        return False

    # Close any previous playback first: MCI refuses to reopen a live alias,
    # and a rapid second block would otherwise fall silent.
    _send(f"close {ALIAS}")
    if _send(f'open "{path}" type mpegvideo alias {ALIAS}'):
        log("could not open the notice sound")
        return False
    if _send(f"play {ALIAS}"):
        _send(f"close {ALIAS}")
        return False
    return True


def shutdown() -> None:
    """Release the audio device on exit."""
    _send(f"close {ALIAS}")
