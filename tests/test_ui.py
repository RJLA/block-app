"""UI construction and the behaviour wired into it.

Needs a display. Skipped automatically where Tk cannot open one.
"""

import time

import pytest

from blockguard import ui_app, ui_lists, ui_pin

FAKE_INVENTORY = [
    {"name": "Google Chrome", "exe": "chrome", "running": True},
    {"name": "Steam", "exe": "steam", "running": False},
    {"name": "Discord", "exe": "discord", "running": True},
]


@pytest.fixture
def locked_app(monkeypatch, window):
    """A real App sitting on its lock screen, with disk and PC access stubbed."""
    monkeypatch.setattr(ui_app, "save_data", lambda _data: None)
    monkeypatch.setattr(ui_app, "load_data", lambda: {
        "websites": ["facebook.com"], "apps": ["steam"],
        "dry_run": True, "protection": False})
    monkeypatch.setattr(ui_lists, "inventory", lambda: list(FAKE_INVENTORY))
    monkeypatch.setattr(ui_app, "restrict_data_dir", lambda: True)
    # A PIN already exists, so the lock screen opens in unlock mode.
    monkeypatch.setattr(ui_app, "has_pin", lambda: True)
    monkeypatch.setattr(ui_pin, "has_pin", lambda: True)
    monkeypatch.setattr(ui_pin, "lockout_remaining", lambda: 0)
    monkeypatch.setattr(ui_pin, "verify_pin", lambda value: value == "123456")

    instance = ui_app.App(window)
    instance.admin = True          # otherwise every action prompts for UAC
    window.update()
    yield instance
    if instance.watchdog:
        instance.watchdog.stop()


@pytest.fixture
def app(locked_app):
    """The same App, already unlocked."""
    locked_app.on_unlocked()
    locked_app.update()
    return locked_app


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


def is_shown(widget):
    """Packed or not. winfo_ismapped() is useless here -- the test root is
    withdrawn, so nothing is ever mapped."""
    return widget.winfo_manager() != ""


class TestLockScreen:
    def test_starts_locked(self, locked_app):
        assert locked_app.lock is not None
        assert is_shown(locked_app.lock)

    def test_lists_are_not_visible_while_locked(self, locked_app):
        """A student must not be able to read or edit the blocklist."""
        assert not is_shown(locked_app.body)

    def test_wrong_pin_keeps_it_locked(self, locked_app):
        locked_app.lock.entry.var.set("000000")
        locked_app.lock.submit()
        locked_app.update()
        assert locked_app.lock is not None
        assert "Wrong PIN" in locked_app.lock.message.cget("text")

    def test_correct_pin_reveals_the_app(self, locked_app):
        locked_app.lock.entry.var.set("123456")
        locked_app.lock.submit()
        locked_app.update()
        assert locked_app.lock is None
        assert is_shown(locked_app.body)

    def test_lock_again_hides_the_app(self, app):
        app.lock_now()
        app.update()
        assert app.lock is not None
        assert not is_shown(app.body)

    def test_pin_entry_accepts_only_six_digits(self, locked_app):
        locked_app.lock.entry.var.set("12ab34xyz56789")
        assert locked_app.lock.entry.value() == "123456"

    def test_enforcement_runs_before_the_pin_is_entered(self, locked_app):
        """The logon case: blocks must apply without anyone unlocking."""
        locked_app.start_enforcement()
        assert locked_app.watchdog is not None
        assert locked_app.watchdog.is_alive()
        assert locked_app.lock is not None      # still locked


class TestBlockedNotice:
    def test_a_kill_also_plays_the_sound(self, app, monkeypatch):
        played = []
        monkeypatch.setattr(ui_app, "BlockedToast", lambda master, name: None)
        monkeypatch.setattr(ui_app, "play_blocked", lambda: played.append(True))
        app.note_blocked("steam")
        app._drain_messages()
        assert played == [True]

    def test_the_sound_shares_the_toast_cooldown(self, app, monkeypatch):
        """Twelve dying browser processes are one notice and one sound."""
        played = []
        monkeypatch.setattr(ui_app, "BlockedToast", lambda master, name: None)
        monkeypatch.setattr(ui_app, "play_blocked", lambda: played.append(True))
        for _ in range(12):
            app.note_blocked("chrome")
        app._drain_messages()
        assert len(played) == 1

    def test_a_kill_raises_one_toast(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr(ui_app, "BlockedToast",
                            lambda master, name: shown.append(name))
        app.note_blocked("steam")
        app._drain_messages()
        assert shown == ["Steam"]

    def test_repeat_kills_are_collapsed(self, app, monkeypatch):
        """A browser dies as a dozen processes -- that is still one notice."""
        shown = []
        monkeypatch.setattr(ui_app, "BlockedToast",
                            lambda master, name: shown.append(name))
        for _ in range(12):
            app.note_blocked("chrome")
        app._drain_messages()
        assert len(shown) == 1

    def test_different_apps_each_get_a_notice(self, app, monkeypatch):
        shown = []
        monkeypatch.setattr(ui_app, "BlockedToast",
                            lambda master, name: shown.append(name))
        app.note_blocked("steam")
        app.note_blocked("discord")
        app._drain_messages()
        assert sorted(shown) == ["Discord", "Steam"]

    def test_uses_the_friendly_name_when_known(self, app, monkeypatch):
        drain_inventory(app)
        shown = []
        monkeypatch.setattr(ui_app, "BlockedToast",
                            lambda master, name: shown.append(name))
        app.note_blocked("chrome")
        app._drain_messages()
        assert shown == ["Google Chrome"]

    def test_notice_appears_even_while_locked(self, locked_app, monkeypatch):
        """The only state a student ever sees the app in."""
        shown = []
        monkeypatch.setattr(ui_app, "BlockedToast",
                            lambda master, name: shown.append(name))
        locked_app.note_blocked("steam")
        locked_app._drain_messages()
        assert shown == ["Steam"]


class TestProtectionPersists:
    """The reported bug: closing the app silently switched blocking off."""

    @pytest.fixture(autouse=True)
    def _no_real_policy(self, monkeypatch):
        self.saved = []
        monkeypatch.setattr(ui_app, "apply_site_policy", lambda d: ["Chrome"])
        monkeypatch.setattr(ui_app, "clear_site_policy", lambda: None)
        monkeypatch.setattr(ui_app, "site_policy_active", lambda: True)
        monkeypatch.setattr(ui_app, "logon_task_exists", lambda: True)
        monkeypatch.setattr(ui_app, "install_logon_task", lambda: True)

    def record_saves(self, app, monkeypatch):
        """Patch after the app fixture, which stubs save_data to a no-op."""
        monkeypatch.setattr(ui_app, "save_data", self.saved.append)

    def test_turning_on_is_written_to_disk(self, app, monkeypatch):
        self.record_saves(app, monkeypatch)
        app.turn_protection_on()
        assert self.saved[-1]["protection"] is True

    def test_turning_off_is_written_to_disk(self, app, monkeypatch):
        self.record_saves(app, monkeypatch)
        app.turn_protection_on()
        app.turn_protection_off()
        assert self.saved[-1]["protection"] is False

    def test_closing_keeps_protection_running(self, app):
        app.turn_protection_on()
        dog = app.watchdog
        app.on_close()
        assert app.protection_on() is True
        assert not dog._stop.is_set()
        assert app.winfo_toplevel().state() == "withdrawn"

    def test_closing_with_protection_off_really_exits(self, locked_app, monkeypatch):
        destroyed = []
        monkeypatch.setattr(locked_app.winfo_toplevel(), "destroy",
                            lambda: destroyed.append(True))
        locked_app.on_close()
        assert destroyed == [True]

    def test_relaunch_resumes_protection(self, monkeypatch, window):
        """A fresh App with protection saved on must start blocking itself."""
        monkeypatch.setattr(ui_app, "load_data", lambda: {
            "websites": ["facebook.com"], "apps": ["steam"],
            "dry_run": False, "protection": True})
        monkeypatch.setattr(ui_app, "has_pin", lambda: True)
        monkeypatch.setattr(ui_pin, "has_pin", lambda: True)
        monkeypatch.setattr(ui_pin, "lockout_remaining", lambda: 0)
        monkeypatch.setattr(ui_lists, "inventory", list)
        monkeypatch.setattr(ui_app, "is_admin", lambda: True)

        fresh = ui_app.App(window)
        try:
            assert fresh.protection_on() is True
            assert "ON" in fresh.status_big.cget("text")
        finally:
            if fresh.watchdog:
                fresh.watchdog.stop()

    def test_relaunch_stays_off_when_it_was_off(self, app):
        assert app.protection_on() is False

    def test_turning_on_also_enables_autostart(self, app, monkeypatch):
        """Otherwise protection quietly lapses at the next reboot."""
        installed = []
        monkeypatch.setattr(ui_app, "logon_task_exists",
                            lambda: bool(installed))
        monkeypatch.setattr(ui_app, "install_logon_task",
                            lambda: installed.append(True) or True)
        app.turn_protection_on()
        assert installed == [True]

    def test_wanted_on_but_not_admin_is_explained(self, app):
        app._protection = True
        app.refresh_state()
        assert "administrator" in app.status_hint.cget("text")


class TestBackgroundMode:
    def test_enter_background_hides_and_enforces(self, locked_app):
        locked_app._protection = True
        locked_app.enter_background()
        assert locked_app.background is True
        assert locked_app.winfo_toplevel().state() == "withdrawn"
        assert locked_app.watchdog is not None

    def test_enforces_even_with_an_empty_blocklist(self, locked_app):
        """Entries added later must still be picked up by the running scan."""
        locked_app._blocked_apps = []
        locked_app._protection = True
        locked_app.enter_background()
        assert locked_app.watchdog is not None

    def test_being_summoned_shows_a_locked_window(self, locked_app, monkeypatch):
        locked_app._protection = True
        locked_app.enter_background()
        locked_app.on_unlocked()                    # pretend someone unlocked
        monkeypatch.setattr(ui_app, "consume_show_request", lambda: True)
        locked_app._poll_show_requests()
        locked_app.update()
        assert locked_app.winfo_toplevel().state() == "normal"
        assert locked_app.lock is not None          # re-locked on reveal

    def test_closing_hides_instead_of_exiting(self, locked_app):
        locked_app._protection = True
        locked_app.enter_background()
        locked_app.reveal()
        locked_app.on_close()
        assert locked_app.winfo_toplevel().state() == "withdrawn"
        assert locked_app.watchdog is not None      # still enforcing

    def test_closing_never_stops_a_running_watchdog(self, app):
        """Closing the window must not be a way to switch blocking off."""
        app.start_enforcement()
        dog = app.watchdog
        app.on_close()
        assert not dog._stop.is_set()
        assert app.winfo_toplevel().state() == "withdrawn"


class TestProtectionSwitch:
    @pytest.fixture(autouse=True)
    def _no_real_policy(self, monkeypatch):
        self.applied, self.cleared = [], []
        monkeypatch.setattr(ui_app, "apply_site_policy",
                            lambda domains: self.applied.append(list(domains)) or ["Chrome"])
        monkeypatch.setattr(ui_app, "clear_site_policy",
                            lambda: self.cleared.append(True))
        monkeypatch.setattr(ui_app, "site_policy_active", lambda: bool(self.applied))
        monkeypatch.setattr(ui_app, "logon_task_exists", lambda: False)

    def test_starts_off(self, app):
        assert app.protection_on() is False
        assert "OFF" in app.status_big.cget("text")

    def test_turning_on_covers_apps_and_websites(self, app):
        """One button has to do both, or new users only ever do half."""
        app.turn_protection_on()
        assert app.protection_on() is True
        assert self.applied == [["facebook.com"]]

    def test_practice_mode_is_labelled_not_on(self, app):
        app.dry_run.set(True)
        app.turn_protection_on()
        assert "Practice" in app.status_big.cget("text")

    def test_live_mode_says_on(self, app, monkeypatch):
        monkeypatch.setattr(ui_app.messagebox, "askyesno", lambda *a, **k: True)
        app.dry_run.set(False)
        app.turn_protection_on()
        assert "ON" in app.status_big.cget("text")

    def test_going_live_asks_first(self, app, monkeypatch):
        asked = []
        monkeypatch.setattr(ui_app.messagebox, "askyesno",
                            lambda *a, **k: asked.append(a) or False)
        app.dry_run.set(False)
        app.turn_protection_on()
        assert asked, "must confirm before closing real programs"
        assert app.protection_on() is False

    def test_practice_mode_needs_no_confirmation(self, app, monkeypatch):
        monkeypatch.setattr(ui_app.messagebox, "askyesno",
                            lambda *a, **k: pytest.fail("should not ask"))
        app.dry_run.set(True)
        app.turn_protection_on()
        assert app.protection_on() is True

    def test_empty_lists_explain_rather_than_start(self, app, monkeypatch):
        told = []
        monkeypatch.setattr(ui_app.messagebox, "showinfo",
                            lambda title, msg: told.append(msg))
        app.sites.set_items([])
        app.apps.set_items([])
        app.persist()
        app.turn_protection_on()
        assert app.protection_on() is False
        assert told and "Installed apps" in told[0]

    def test_turning_off_stops_everything(self, app):
        app.turn_protection_on()
        dog = app.watchdog
        app.turn_protection_off()
        assert app.protection_on() is False
        assert dog._stop.is_set()
        assert self.cleared == [True]

    def test_button_text_follows_state(self, app):
        assert "Turn protection on" in app.protect_btn.cget("text")
        app.turn_protection_on()
        assert "Turn protection off" in app.protect_btn.cget("text")

    def test_detail_reports_both_lists(self, app):
        app.refresh_state()
        detail = app.status_detail.cget("text")
        assert "Websites:" in detail and "Apps:" in detail


class TestActivityLog:
    def test_messages_reach_the_log_box(self, app):
        app.say("hello from a thread")
        app._drain_messages()
        app.update()
        assert "hello from a thread" in app.logbox.get("1.0", "end")
