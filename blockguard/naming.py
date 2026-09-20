"""Normalizing user input, and deciding whether something is blocked.

Kept free of Windows APIs so the matching rules can be unit-tested anywhere.
"""

# Refused even when the user puts them on the blocklist -- terminating these
# breaks the desktop, locks the user out, or kills Block Guard itself.
PROTECTED_APPS = {
    "explorer", "dwm", "csrss", "winlogon", "services", "lsass", "smss",
    "wininit", "svchost", "ctfmon", "sihost", "taskhostw", "runtimebroker",
    "searchapp", "searchhost", "startmenuexperiencehost", "shellexperiencehost",
    "applicationframehost", "lockapp", "userinit", "fontdrvhost", "audiodg",
    "textinputhost", "securityhealthsystray", "securityhealthservice",
    "msmpeng", "nissrv", "conhost", "taskmgr",
    "blockguard", "block_guard", "python", "pythonw",
}


def normalize_site(value: str) -> str:
    """https://WWW.Example.com:8080/path?q=1 -> example.com"""
    s = value.strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    if s.count(":") == 1:
        s = s.split(":", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s.strip(".")


def normalize_app(value: str) -> str:
    """C:\\Program Files\\Slack\\Slack.exe -> slack"""
    s = value.strip().strip('"').lower().replace("\\", "/")
    s = s.rstrip("/").split("/")[-1]
    for ext in (".exe", ".app", ".lnk", ".appimage"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.strip()


def site_blocked(candidate: str, blocked) -> bool:
    """A blocked domain also covers its subdomains."""
    host = normalize_site(candidate)
    return bool(host) and any(host == b or host.endswith("." + b) for b in blocked if b)


def app_blocked(candidate: str, blocked) -> bool:
    """Blocked only if listed AND not protected -- protection always wins."""
    name = normalize_app(candidate)
    if not name or name in PROTECTED_APPS:
        return False
    return name in {normalize_app(b) for b in blocked if b}


def is_protected(candidate: str) -> bool:
    return normalize_app(candidate) in PROTECTED_APPS
