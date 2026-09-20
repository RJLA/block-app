"""Enforcement side effects: browser policy, process kills, logon task.

Everything that touches the real registry, PowerShell or schtasks is faked,
so these run anywhere and never change the machine.
"""

import json

import pytest

from blockguard import processes, sites, system


# --------------------------------------------------------------------------
# A minimal in-memory stand-in for winreg
# --------------------------------------------------------------------------
class FakeKey:
    def __init__(self, registry, path):
        self.registry, self.path = registry, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def Close(self):
        pass


class FakeRegistry:
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.data = {}

    def CreateKey(self, _root, path):
        self.data.setdefault(path, {})
        return FakeKey(self, path)

    def OpenKey(self, _root, path):
        if path not in self.data:
            raise OSError(2, "not found")
        return FakeKey(self, path)

    def DeleteKey(self, _root, path):
        if path not in self.data:
            raise OSError(2, "not found")
        del self.data[path]

    def SetValueEx(self, key, name, _reserved, _type, value):
        self.data[key.path][name] = value

    def QueryValueEx(self, key, name):
        values = self.data.get(key.path, {})
        if name not in values:
            raise OSError(2, "no value")
        return values[name], self.REG_SZ

    def QueryInfoKey(self, key):
        return (0, len(self.data.get(key.path, {})), 0)


CHROME_BLOCK = r"SOFTWARE\Policies\Google\Chrome\URLBlocklist"
CHROME_ALLOW = r"SOFTWARE\Policies\Google\Chrome\URLAllowlist"
EDGE_BLOCK = r"SOFTWARE\Policies\Microsoft\Edge\URLBlocklist"


@pytest.fixture
def registry(monkeypatch):
    fake = FakeRegistry()
    monkeypatch.setattr(sites, "winreg", fake)
    return fake


class TestSitePolicy:
    def test_writes_blocked_domains_to_both_browsers(self, registry):
        touched = sites.apply_site_policy(["facebook.com", "tiktok.com"])
        assert touched == ["Chrome", "Edge"]
        assert registry.data[CHROME_BLOCK] == {"1": "facebook.com", "2": "tiktok.com"}
        assert registry.data[EDGE_BLOCK] == {"1": "facebook.com", "2": "tiktok.com"}

    def test_does_not_write_an_allowlist(self, registry):
        """The inverted model needs no allowlist -- and one would punch holes."""
        sites.apply_site_policy(["facebook.com"])
        assert CHROME_ALLOW not in registry.data

    def test_removes_a_stale_allowlist(self, registry):
        registry.data[CHROME_ALLOW] = {"1": "example.com"}
        sites.apply_site_policy(["facebook.com"])
        assert CHROME_ALLOW not in registry.data

    def test_applying_replaces_rather_than_appends(self, registry):
        sites.apply_site_policy(["a.com", "b.com"])
        sites.apply_site_policy(["c.com"])
        assert registry.data[CHROME_BLOCK] == {"1": "c.com"}

    def test_empty_list_writes_no_key(self, registry):
        sites.apply_site_policy([])
        assert CHROME_BLOCK not in registry.data

    def test_clear_removes_both_lists(self, registry):
        sites.apply_site_policy(["facebook.com"])
        sites.clear_site_policy()
        assert CHROME_BLOCK not in registry.data
        assert EDGE_BLOCK not in registry.data

    def test_policy_active_reflects_state(self, registry):
        assert sites.site_policy_active() is False
        sites.apply_site_policy(["facebook.com"])
        assert sites.site_policy_active() is True
        sites.clear_site_policy()
        assert sites.site_policy_active() is False

    def test_empty_key_does_not_count_as_active(self, registry):
        registry.data[CHROME_BLOCK] = {}
        assert sites.site_policy_active() is False


# --------------------------------------------------------------------------
# Process helpers
# --------------------------------------------------------------------------
class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode = stdout, returncode


class TestListProcesses:
    def test_parses_a_json_array(self, monkeypatch):
        rows = [{"ProcessId": 1, "Name": "a.exe"}, {"ProcessId": 2, "Name": "b.exe"}]
        monkeypatch.setattr(processes.subprocess, "run",
                            lambda *a, **k: FakeCompleted(json.dumps(rows)))
        assert processes.list_processes() == rows

    def test_wraps_a_single_object(self, monkeypatch):
        """PowerShell emits a bare object, not an array, for one result."""
        row = {"ProcessId": 1, "Name": "a.exe"}
        monkeypatch.setattr(processes.subprocess, "run",
                            lambda *a, **k: FakeCompleted(json.dumps(row)))
        assert processes.list_processes() == [row]

    def test_empty_output_is_empty_list(self, monkeypatch):
        monkeypatch.setattr(processes.subprocess, "run",
                            lambda *a, **k: FakeCompleted("   "))
        assert processes.list_processes() == []

    def test_failure_is_swallowed(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("powershell missing")
        monkeypatch.setattr(processes.subprocess, "run", boom)
        assert processes.list_processes() == []


class TestKill:
    def test_issues_a_forced_tree_kill(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return FakeCompleted()

        monkeypatch.setattr(processes.subprocess, "run", fake_run)
        assert processes.kill(4321) is True
        assert seen["cmd"] == ["taskkill", "/PID", "4321", "/F", "/T"]

    def test_failure_returns_false(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("denied")
        monkeypatch.setattr(processes.subprocess, "run", boom)
        assert processes.kill(1) is False


class TestLogonTask:
    def test_create_uses_highest_privileges_and_defaults_to_background(
            self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return FakeCompleted(returncode=0)

        monkeypatch.setattr(system.subprocess, "run", fake_run)
        assert system.install_logon_task() is True
        assert seen["cmd"][:8] == ["schtasks", "/Create", "/F", "/TN",
                                   "BlockGuard", "/SC", "ONLOGON", "/RL"]
        # Background is the default: blocks apply at logon with no window.
        assert "--background" in seen["cmd"][-1]

    def test_create_accepts_an_explicit_mode(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return FakeCompleted(returncode=0)

        monkeypatch.setattr(system.subprocess, "run", fake_run)
        assert system.install_logon_task("--enforce") is True
        assert "--enforce" in seen["cmd"][-1]

    def test_create_reports_failure(self, monkeypatch):
        monkeypatch.setattr(system.subprocess, "run",
                            lambda *a, **k: FakeCompleted(returncode=1))
        assert system.install_logon_task() is False

    def test_delete_targets_the_task(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return FakeCompleted(returncode=0)

        monkeypatch.setattr(system.subprocess, "run", fake_run)
        assert system.remove_logon_task() is True
        assert seen["cmd"] == ["schtasks", "/Delete", "/F", "/TN", "BlockGuard"]


def run_one_pass(dog):
    """Run exactly one scan, then let the loop exit.

    Stopping the dog before run() would skip the body entirely, since the
    while-condition is checked first -- so stop it at the end-of-cycle wait.
    """
    def stop_instead_of_waiting(_timeout=None):
        dog._stop.set()
        return True

    dog._stop.wait = stop_instead_of_waiting
    dog.run()


class TestWatchdog:
    def test_dry_run_reports_without_killing(self, monkeypatch):
        killed = []
        monkeypatch.setattr(processes, "kill", lambda pid: killed.append(pid))
        monkeypatch.setattr(processes, "list_processes",
                            lambda: [{"ProcessId": 50, "Name": "steam.exe",
                                      "SessionId": 1}])
        monkeypatch.setattr(processes, "current_session_id", lambda: 1)

        said = []
        dog = processes.Watchdog(lambda: ["steam"], lambda: True, said.append)
        run_one_pass(dog)

        assert killed == []
        assert any("[dry run] would terminate steam" in m for m in said)

    def test_live_mode_kills(self, monkeypatch):
        killed = []
        monkeypatch.setattr(processes, "kill", lambda pid: killed.append(pid) or True)
        monkeypatch.setattr(processes, "list_processes",
                            lambda: [{"ProcessId": 50, "Name": "steam.exe",
                                      "SessionId": 1}])
        monkeypatch.setattr(processes, "current_session_id", lambda: 1)

        said = []
        dog = processes.Watchdog(lambda: ["steam"], lambda: False, said.append)
        run_one_pass(dog)

        assert killed == [50]
        assert any("terminated steam" in m for m in said)

    def test_empty_blocklist_skips_the_process_scan(self, monkeypatch):
        scanned = []
        monkeypatch.setattr(processes, "list_processes",
                            lambda: scanned.append(1) or [])
        monkeypatch.setattr(processes, "current_session_id", lambda: 1)

        dog = processes.Watchdog(lambda: [], lambda: True, lambda _m: None)
        run_one_pass(dog)

        assert scanned == []
