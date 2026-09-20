"""Reading and writing the blocklist on disk."""

import json
import os

from .naming import normalize_app, normalize_site
from .paths import CONFIG_PATH, seed_path

DEFAULTS = {"websites": [], "apps": [], "dry_run": True, "protection": False}


def _clean(raw: dict) -> dict:
    """Normalize and de-duplicate whatever was on disk."""
    return {
        "websites": sorted({normalize_site(x) for x in raw.get("websites", []) if x}),
        "apps": sorted({normalize_app(x) for x in raw.get("apps", []) if x}),
        # Dry run defaults to ON -- never start terminating without being told.
        "dry_run": bool(raw.get("dry_run", True)),
        # Whether protection was left switched on, so it resumes by itself
        # rather than quietly lapsing when the app is closed or the PC reboots.
        "protection": bool(raw.get("protection", False)),
    }


def load_data() -> dict:
    """Live config first, then the bundled seed, then empty."""
    for path in (CONFIG_PATH, seed_path()):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return _clean(json.load(fh))
        except (OSError, ValueError):
            continue
    return dict(DEFAULTS)


def save_data(data: dict) -> None:
    """Write atomically so a crash mid-write cannot corrupt the blocklist."""
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_clean(data), fh, indent=2)
    os.replace(tmp, CONFIG_PATH)
