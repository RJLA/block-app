"""The 6-digit PIN that gates the blocklist UI.

The PIN is never stored. Only a PBKDF2-HMAC-SHA256 digest and its random salt
are written to disk, and comparisons are constant-time.

A 6-digit PIN is only a million combinations, so the stretching alone is not
enough -- repeated wrong entries trigger an escalating lockout that is
persisted, so closing and reopening the app does not reset it.
"""

import hashlib
import hmac
import json
import os
import secrets
import time

from .paths import data_dir, log

SECURITY_PATH = os.path.join(data_dir(), "security.json")

PIN_LENGTH = 6
ITERATIONS = 600_000
SALT_BYTES = 16
# Wrong entries allowed before the first lockout.
FREE_ATTEMPTS = 3
# Lockout grows with each failure past the free ones, to this ceiling.
LOCKOUT_STEP_SECONDS = 30
MAX_LOCKOUT_SECONDS = 15 * 60


def is_valid_pin(pin: str) -> bool:
    """Exactly six digits. No spaces, no letters, no shorter codes."""
    return isinstance(pin, str) and len(pin) == PIN_LENGTH and pin.isdigit()


def _digest(pin: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), bytes.fromhex(salt), iterations
    ).hex()


def _read() -> dict:
    try:
        with open(SECURITY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    tmp = SECURITY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, SECURITY_PATH)


def has_pin() -> bool:
    record = _read()
    return bool(record.get("hash") and record.get("salt"))


def set_pin(pin: str) -> bool:
    """Enroll or replace the PIN. Clears any lockout."""
    if not is_valid_pin(pin):
        return False
    salt = secrets.token_hex(SALT_BYTES)
    _write({
        "salt": salt,
        "hash": _digest(pin, salt, ITERATIONS),
        "iterations": ITERATIONS,
        "failures": 0,
        "locked_until": 0,
    })
    log("PIN enrolled")
    return True


def lockout_remaining() -> int:
    """Seconds left before another attempt is allowed; 0 when unlocked."""
    locked_until = _read().get("locked_until", 0)
    try:
        return max(0, int(float(locked_until) - time.time()))
    except (TypeError, ValueError):
        return 0


def _register_failure(record: dict) -> None:
    failures = int(record.get("failures", 0)) + 1
    record["failures"] = failures
    if failures > FREE_ATTEMPTS:
        penalty = min((failures - FREE_ATTEMPTS) * LOCKOUT_STEP_SECONDS,
                      MAX_LOCKOUT_SECONDS)
        record["locked_until"] = time.time() + penalty
        log(f"PIN failure {failures}; locked out for {penalty}s")
    else:
        log(f"PIN failure {failures}")
    try:
        _write(record)
    except OSError:
        pass


def verify_pin(pin: str) -> bool:
    """Check a PIN, recording failures. False while locked out."""
    if lockout_remaining() > 0:
        return False
    record = _read()
    if not record.get("hash") or not record.get("salt"):
        return False
    candidate = _digest(pin, record["salt"], int(record.get("iterations", ITERATIONS)))
    if hmac.compare_digest(candidate, record["hash"]):
        record["failures"] = 0
        record["locked_until"] = 0
        try:
            _write(record)
        except OSError:
            pass
        return True
    _register_failure(record)
    return False


def change_pin(current: str, new: str) -> bool:
    """Replace the PIN, but only for someone who knows the current one."""
    if not is_valid_pin(new) or not verify_pin(current):
        return False
    return set_pin(new)
