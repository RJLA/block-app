"""UI construction and the behaviour wired into it.

Needs a display. Skipped automatically where Tk cannot open one.
"""

import time
import tkinter as tk

import pytest

from blockguard import ui_app, ui_lists

FAKE_INVENTORY = [
    {"name": "Google Chrome", "exe": "chrome", "running": True},
    {"name": "Steam", "exe": "steam", "running": False},
    {"name": "Discord", "exe": "discord", "running": True},
]


@pytest.fixture
def app(monkeypatch):
    """A real App, with disk writes and the PC scan stubbed out."""
    monkeypatch.setattr(ui_app, "save_data", lambda _data: None)
    monkeypatch.setattr(ui_app, "load_data", lambda: {
        "websites": ["facebook.com"], "apps": ["steam"], "dry_run": True})
    monkeypatch.setattr(ui_lists, "inventory", lambda: list(FAKE_INVENTORY))

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    instance = ui_app.App(root)
    root.update()
    yield instance
    if instance.watchdog:
        instance.watchdog.stop()
    root.destroy()


def drain_inventory(app):
    """Pump the event loop until the worker thread's results are rendered.

    The sleep matters: the pane polls its queue via after(), and Tk timers
    only fire once real time has passed.
    """
    for _ in range(100):
        app.update()
        if app.installed._all:
            return
        time.sleep(0.02)
    raise AssertionError("inventory never loaded")


class TestLists:
    def test_loads_saved_lists(self, app):
        assert app.sites.items() == ["facebook.com"]
        assert app.apps.items() == ["steam"]

    def test_adding_normalizes_the_value(self, app):
        app.apps.add_value(r"C:\Games\Discord\Discord.exe")
        assert "discord" in app.apps.items()

    def test_duplicates_are_rejected(self, app):
        assert app.apps.add_value("steam.exe") is False
        assert app.apps.items().count("steam") == 1

    def test_adding_updates_the_watchdog_snapshot(self, app):
        """The watchdog reads a plain list, never the Tk widget."""
        app.apps.add_value("discord")
        assert "discord" in app._blocked_apps


class TestCheck:
    def test_blocked_site_shows_the_mascot(self, app):
        app.query.insert(0, "https://www.facebook.com/feed")
        app.kind.current(0)
        app.check()
        assert "BLOCKED" in app.result.cget("text")
        assert bool(app.result.cget("image")) is (app.mascot_small is not None)

    def test_unlisted_site_has_no_mascot(self, app):
        app.query.insert(0, "github.com")
        app.kind.current(0)
        app.check()
        assert "not blocked" in app.result.cget("text")
        assert not app.result.cget("image")

    def test_protected_app_reports_not_blocked(self, app):
        app.apps.add_value("explorer")
        app.query.insert(0, "explorer.exe")
        app.kind.current(1)
        app.check()
        assert "not blocked" in app.result.cget("text")

    def test_empty_query_is_ignored(self, app):
        app.check()
        assert app.result.cget("text") == ""


class TestInstalledPane:
    def test_lists_discovered_apps(self, app):
        drain_inventory(app)
        assert len(app.installed.tree.get_children()) == len(FAKE_INVENTORY)

    def test_running_apps_sort_first(self, app):
        drain_inventory(app)
        first = app.installed._visible()[0]
        assert first["running"]

    def test_search_filters_rows(self, app):
        drain_inventory(app)
        app.installed.search.insert(0, "steam")
        app.installed._render()
        assert [r["exe"] for r in app.installed._visible()] == ["steam"]

    def test_running_only_filter(self, app):
        drain_inventory(app)
        app.installed.running_only.set(True)
        assert all(r["running"] for r in app.installed._visible())

    def test_blocking_from_inventory_adds_to_the_list(self, app):
        drain_inventory(app)
        app.block_from_inventory(["discord", "chrome"])
        assert "discord" in app.apps.items()
        assert "chrome" in app.apps.items()

    def test_blocking_a_protected_app_is_refused(self, app):
        app.block_from_inventory(["explorer"])
        # add_value still records it, but matching refuses to act on it.
        from blockguard.naming import app_blocked
        assert not app_blocked("explorer", app.apps.items())


class TestActivityLog:
    def test_messages_reach_the_log_box(self, app):
        app.say("hello from a thread")
        app._drain_messages()
        app.update()
        assert "hello from a thread" in app.logbox.get("1.0", "end")
