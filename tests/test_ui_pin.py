"""The lock screen and change-PIN dialog, exercised directly."""

import pytest

from blockguard import ui_pin


@pytest.fixture
def enrolled(monkeypatch):
    """No PIN on file yet, with set_pin captured instead of written."""
    saved = {}
    monkeypatch.setattr(ui_pin, "has_pin", lambda: False)
    monkeypatch.setattr(ui_pin, "lockout_remaining", lambda: 0)
    monkeypatch.setattr(ui_pin, "set_pin",
                        lambda value: saved.setdefault("pin", value) is not None)
    return saved


class TestEnrollment:
    def test_opens_in_enrollment_mode_without_a_pin(self, window, enrolled):
        screen = ui_pin.LockScreen(window, lambda: None)
        assert screen.enrolling is True
        assert screen.confirm is not None

    def test_rejects_a_short_pin(self, window, enrolled):
        done = []
        screen = ui_pin.LockScreen(window, lambda: done.append(True))
        screen.entry.var.set("123")
        screen.confirm.var.set("123")
        screen.submit()
        assert done == []
        assert "6 digits" in screen.message.cget("text")

    def test_rejects_mismatched_confirmation(self, window, enrolled):
        done = []
        screen = ui_pin.LockScreen(window, lambda: done.append(True))
        screen.entry.var.set("123456")
        screen.confirm.var.set("654321")
        screen.submit()
        assert done == []
        assert "do not match" in screen.message.cget("text")

    def test_successful_enrollment_saves_and_unlocks(self, window, enrolled):
        done = []
        screen = ui_pin.LockScreen(window, lambda: done.append(True))
        screen.entry.var.set("246810")
        screen.confirm.var.set("246810")
        screen.submit()
        assert enrolled["pin"] == "246810"
        assert done == [True]


class TestUnlockMode:
    @pytest.fixture(autouse=True)
    def _existing_pin(self, monkeypatch):
        monkeypatch.setattr(ui_pin, "has_pin", lambda: True)
        monkeypatch.setattr(ui_pin, "lockout_remaining", lambda: 0)
        monkeypatch.setattr(ui_pin, "verify_pin", lambda v: v == "123456")

    def test_opens_in_unlock_mode(self, window):
        screen = ui_pin.LockScreen(window, lambda: None)
        assert screen.enrolling is False
        assert screen.confirm is None

    def test_wrong_pin_clears_the_field(self, window):
        screen = ui_pin.LockScreen(window, lambda: None)
        screen.entry.var.set("999999")
        screen.submit()
        assert screen.entry.value() == ""

    def test_correct_pin_calls_back(self, window):
        done = []
        screen = ui_pin.LockScreen(window, lambda: done.append(True))
        screen.entry.var.set("123456")
        screen.submit()
        assert done == [True]


class TestLockoutDisplay:
    def test_controls_disable_during_lockout(self, window, monkeypatch):
        monkeypatch.setattr(ui_pin, "has_pin", lambda: True)
        monkeypatch.setattr(ui_pin, "lockout_remaining", lambda: 42)
        screen = ui_pin.LockScreen(window, lambda: None)
        assert str(screen.button.cget("state")) == "disabled"
        assert "42s" in screen.message.cget("text")


class TestChangePinDialog:
    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch):
        self.changed = []
        monkeypatch.setattr(ui_pin, "lockout_remaining", lambda: 0)
        monkeypatch.setattr(
            ui_pin, "change_pin",
            lambda current, new: (current == "111111"
                                  and bool(self.changed.append(new)) is False))

    def fill(self, dialog, current, new, again):
        dialog.fields["current"].var.set(current)
        dialog.fields["new"].var.set(new)
        dialog.fields["again"].var.set(again)

    def test_rejects_an_invalid_new_pin(self, window):
        dialog = ui_pin.ChangePinDialog(window)
        self.fill(dialog, "111111", "12", "12")
        dialog.submit()
        assert self.changed == []
        assert "6 digits" in dialog.message.cget("text")

    def test_rejects_mismatched_confirmation(self, window):
        dialog = ui_pin.ChangePinDialog(window)
        self.fill(dialog, "111111", "222222", "333333")
        dialog.submit()
        assert self.changed == []
        assert "do not match" in dialog.message.cget("text")

    def test_rejects_a_wrong_current_pin(self, window):
        dialog = ui_pin.ChangePinDialog(window)
        self.fill(dialog, "999999", "222222", "222222")
        dialog.submit()
        assert self.changed == []
        assert "current PIN is wrong" in dialog.message.cget("text")

    def test_successful_change_reports_and_closes(self, window):
        done = []
        dialog = ui_pin.ChangePinDialog(window, on_done=lambda: done.append(True))
        self.fill(dialog, "111111", "222222", "222222")
        dialog.submit()
        assert self.changed == ["222222"]
        assert done == [True]
