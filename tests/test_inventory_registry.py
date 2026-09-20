"""Walking the uninstall registry and merging it with running processes."""

import pytest

from blockguard import inventory

UNINSTALL = inventory.UNINSTALL_PATH


class FakeKey:
    def __init__(self, registry, path):
        self.registry, self.path = registry, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeRegistry:
    """Holds {path: {"subkeys": [...], "values": {...}}} for one hive."""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, tree):
        self.tree = tree

    def OpenKey(self, root, path):
        if root != self.HKEY_LOCAL_MACHINE or path not in self.tree:
            raise OSError(2, "not found")
        return FakeKey(self, path)

    def QueryInfoKey(self, key):
        node = self.tree[key.path]
        return (len(node.get("subkeys", [])), len(node.get("values", {})), 0)

    def EnumKey(self, key, index):
        try:
            return self.tree[key.path]["subkeys"][index]
        except IndexError:
            raise OSError(259, "no more data")

    def QueryValueEx(self, key, name):
        values = self.tree[key.path].get("values", {})
        if name not in values:
            raise OSError(2, "no value")
        return values[name], 1


def build(entries):
    """entries: {subkey_name: {value_name: value}} under the uninstall path."""
    tree = {UNINSTALL: {"subkeys": list(entries), "values": {}}}
    for name, values in entries.items():
        tree[f"{UNINSTALL}\\{name}"] = {"subkeys": [], "values": values}
    return FakeRegistry(tree)


@pytest.fixture
def no_processes(monkeypatch):
    monkeypatch.setattr(inventory, "list_processes", lambda: [])
    monkeypatch.setattr(inventory, "current_session_id", lambda: 1)


class TestInstalledFromRegistry:
    def test_reads_name_and_executable(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", build({
            "Steam": {"DisplayName": "Steam", "DisplayIcon": r"C:\S\steam.exe,0"},
        }))
        found = inventory.installed_from_registry()
        assert found == [{"name": "Steam", "exe": "steam", "running": False}]

    def test_skips_entries_without_a_display_name(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", build({
            "Ghost": {"DisplayIcon": r"C:\G\ghost.exe"},
        }))
        assert inventory.installed_from_registry() == []

    def test_skips_system_components(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", build({
            "Hidden": {"DisplayName": "Hidden Thing", "SystemComponent": 1,
                       "DisplayIcon": r"C:\H\h.exe"},
        }))
        assert inventory.installed_from_registry() == []

    def test_skips_updates(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", build({
            "KB1": {"DisplayName": "Security Patch", "ReleaseType": "Update",
                    "DisplayIcon": r"C:\K\k.exe"},
        }))
        assert inventory.installed_from_registry() == []

    def test_skips_redistributables(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", build({
            "VC": {"DisplayName": "Microsoft Visual C++ 2015 Redistributable",
                   "DisplayIcon": r"C:\V\vc.exe"},
        }))
        assert inventory.installed_from_registry() == []

    def test_falls_back_to_scanning_install_location(self, monkeypatch, tmp_path):
        (tmp_path / "unins000.exe").touch()
        (tmp_path / "gimp.exe").touch()
        monkeypatch.setattr(inventory, "winreg", build({
            "GIMP": {"DisplayName": "GIMP 3.2.4", "InstallLocation": str(tmp_path)},
        }))
        found = inventory.installed_from_registry()
        assert found == [{"name": "GIMP 3.2.4", "exe": "gimp", "running": False}]

    def test_uninstaller_icon_is_rejected(self, monkeypatch):
        """A DisplayIcon pointing at the uninstaller must not become the exe."""
        monkeypatch.setattr(inventory, "winreg", build({
            "CapCut": {"DisplayName": "CapCut", "DisplayIcon": r"C:\C\uninst.exe"},
        }))
        assert inventory.installed_from_registry() == [
            {"name": "CapCut", "exe": "", "running": False}]

    def test_missing_hive_is_not_fatal(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", FakeRegistry({}))
        assert inventory.installed_from_registry() == []

    def test_returns_empty_without_winreg(self, monkeypatch):
        monkeypatch.setattr(inventory, "winreg", None)
        assert inventory.installed_from_registry() == []


class TestRunningApps:
    def test_lists_distinct_session_processes(self, monkeypatch):
        monkeypatch.setattr(inventory, "current_session_id", lambda: 1)
        monkeypatch.setattr(inventory, "list_processes", lambda: [
            {"Name": "chrome.exe", "SessionId": 1},
            {"Name": "chrome.exe", "SessionId": 1},      # duplicate tab process
            {"Name": "steam.exe", "SessionId": 1},
        ])
        assert {a["exe"] for a in inventory.running_apps()} == {"chrome", "steam"}

    def test_excludes_other_sessions(self, monkeypatch):
        monkeypatch.setattr(inventory, "current_session_id", lambda: 1)
        monkeypatch.setattr(inventory, "list_processes", lambda: [
            {"Name": "service.exe", "SessionId": 0},
        ])
        assert inventory.running_apps() == []

    def test_excludes_protected_processes(self, monkeypatch):
        monkeypatch.setattr(inventory, "current_session_id", lambda: 1)
        monkeypatch.setattr(inventory, "list_processes", lambda: [
            {"Name": "explorer.exe", "SessionId": 1},
        ])
        assert inventory.running_apps() == []


class TestInventoryMerge:
    def test_drops_entries_with_no_executable(self, monkeypatch, no_processes):
        monkeypatch.setattr(inventory, "winreg", build({
            "Thing": {"DisplayName": "Thing With No Exe"},
        }))
        assert inventory.inventory() == []

    def test_prefers_the_friendly_registry_name(self, monkeypatch):
        monkeypatch.setattr(inventory, "current_session_id", lambda: 1)
        monkeypatch.setattr(inventory, "list_processes", lambda: [
            {"Name": "chrome.exe", "SessionId": 1}])
        monkeypatch.setattr(inventory, "winreg", build({
            "Chrome": {"DisplayName": "Google Chrome",
                       "DisplayIcon": r"C:\C\chrome.exe,0"},
        }))
        result = inventory.inventory()
        assert result == [{"name": "Google Chrome", "exe": "chrome", "running": True}]

    def test_sorts_by_display_name(self, monkeypatch, no_processes):
        monkeypatch.setattr(inventory, "winreg", build({
            "Z": {"DisplayName": "Zoom", "DisplayIcon": r"C:\Z\zoom.exe"},
            "A": {"DisplayName": "Audacity", "DisplayIcon": r"C:\A\audacity.exe"},
        }))
        assert [e["name"] for e in inventory.inventory()] == ["Audacity", "Zoom"]

    def test_protected_apps_never_appear(self, monkeypatch, no_processes):
        monkeypatch.setattr(inventory, "winreg", build({
            "E": {"DisplayName": "Explorer", "DisplayIcon": r"C:\W\explorer.exe"},
        }))
        assert inventory.inventory() == []
