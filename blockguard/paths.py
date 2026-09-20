"""Where the config, log and bundled resources live."""

import os
import sys
from datetime import datetime

from . import CONFIG_NAME, FOLDER_NAME, LOG_NAME


def data_dir() -> str:
    """%ProgramData%\\BlockGuard, falling back to %APPDATA% if it is unwritable."""
    base = os.environ.get("ProgramData") or os.path.expanduser("~")
    path = os.path.join(base, FOLDER_NAME)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), FOLDER_NAME
        )
        os.makedirs(fallback, exist_ok=True)
        return fallback


CONFIG_PATH = os.path.join(data_dir(), CONFIG_NAME)
LOG_PATH = os.path.join(data_dir(), LOG_NAME)


def resource_path(*parts: str) -> str:
    """Locate a bundled file, both when frozen by PyInstaller and from source."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(base, *parts)


def seed_path() -> str:
    return resource_path("default_blocklist.json")


def log(line: str) -> None:
    """Append to the on-disk log; never raises, logging must not break the app."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {line}\n")
    except OSError:
        pass
