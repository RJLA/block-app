"""Website blocking via Chrome / Edge enterprise policy.

Writes HKLM\\SOFTWARE\\Policies\\...\\URLBlocklist with the blocked domains.
Anything not listed stays reachable, so no URLAllowlist is needed -- and any
stale one is removed, since it would punch holes in the blocklist.
"""

from .paths import log

try:
    import winreg
except ImportError:          # non-Windows, lets the logic be imported for tests
    winreg = None

POLICY_KEYS = {
    "Chrome": r"SOFTWARE\Policies\Google\Chrome",
    "Edge": r"SOFTWARE\Policies\Microsoft\Edge",
}
BLOCK_SUB = "URLBlocklist"
ALLOW_SUB = "URLAllowlist"


def _delete_list(root_path: str, sub: str) -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, root_path + "\\" + sub)
    except OSError:
        pass


def _write_list(root_path: str, sub: str, entries) -> None:
    """Chrome policy lists are numbered string values starting at "1"."""
    _delete_list(root_path, sub)
    if not entries:
        return
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, root_path + "\\" + sub) as key:
        for i, value in enumerate(entries, start=1):
            winreg.SetValueEx(key, str(i), 0, winreg.REG_SZ, value)


def apply_site_policy(domains) -> list:
    """Block the listed domains. Returns the browsers actually touched."""
    touched = []
    for browser, path in POLICY_KEYS.items():
        try:
            winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, path).Close()
            _write_list(path, BLOCK_SUB, list(domains))
            _delete_list(path, ALLOW_SUB)     # an allowlist would override the block
            touched.append(browser)
        except OSError as exc:
            log(f"policy {browser} failed: {exc}")
    log(f"site policy applied to {touched} blocking {len(domains)} domains")
    return touched


def clear_site_policy() -> None:
    for browser, path in POLICY_KEYS.items():
        _delete_list(path, BLOCK_SUB)
        _delete_list(path, ALLOW_SUB)
        log(f"site policy cleared for {browser}")


def site_policy_active() -> bool:
    """True if any browser currently has at least one blocked domain."""
    for path in POLICY_KEYS.values():
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, path + "\\" + BLOCK_SUB
            ) as key:
                if winreg.QueryInfoKey(key)[1] > 0:
                    return True
        except OSError:
            continue
    return False
