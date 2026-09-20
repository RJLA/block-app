"""The notice a student sees when a blocked app is closed."""

import pytest

from blockguard import processes, ui_toast


def all_text(widget):
    """Every text= string in the widget tree, at any depth."""
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:
            pass
        found.extend(all_text(child))
    return found


class TestBlockedToast:
    def test_names_the_app_and_tells_them_who_to_ask(self, window):
        toast = ui_toast.BlockedToast(window, "Steam")
        labels = all_text(toast)
        assert "Steam is blocked" in labels
        assert "Ask your Tito or Mommy Joy to unblock it." in labels
        toast.close()

    def test_is_always_on_top(self, window):
        toast = ui_toast.BlockedToast(window, "Steam")
        assert toast.attributes("-topmost") in (1, True)
        toast.close()

    def test_has_no_title_bar(self, window):
        """Undecorated, so it reads as a notice rather than a window."""
        toast = ui_toast.BlockedToast(window, "Steam")
        assert toast.overrideredirect() in (1, True)
        toast.close()

    def test_closing_twice_is_safe(self, window):
        toast = ui_toast.BlockedToast(window, "Steam")
        toast.close()
        toast.close()

    def test_sits_on_screen(self, window):
        toast = ui_toast.BlockedToast(window, "Steam")
        toast.update_idletasks()
        assert toast.winfo_x() >= 0 and toast.winfo_y() >= 0
        toast.close()


class TestWatchdogNotification:
    def _spin(self, dog):
        def stop(_timeout=None):
            dog._stop.set()
            return True
        dog._stop.wait = stop
        dog.run()

    @pytest.fixture(autouse=True)
    def _one_blocked_process(self, monkeypatch):
        monkeypatch.setattr(processes, "list_processes",
                            lambda: [{"ProcessId": 50, "Name": "steam.exe",
                                      "SessionId": 1}])
        monkeypatch.setattr(processes, "current_session_id", lambda: 1)

    def test_notifies_after_a_real_kill(self, monkeypatch):
        monkeypatch.setattr(processes, "kill", lambda pid: True)
        seen = []
        self._spin(processes.Watchdog(lambda: ["steam"], lambda: False,
                                      lambda m: None, on_blocked=seen.append))
        assert seen == ["steam"]

    def test_silent_during_a_dry_run(self, monkeypatch):
        """Dry run means take no action -- including not alarming the user."""
        monkeypatch.setattr(processes, "kill", lambda pid: True)
        seen = []
        self._spin(processes.Watchdog(lambda: ["steam"], lambda: True,
                                      lambda m: None, on_blocked=seen.append))
        assert seen == []

    def test_silent_when_the_kill_fails(self, monkeypatch):
        monkeypatch.setattr(processes, "kill", lambda pid: False)
        seen = []
        self._spin(processes.Watchdog(lambda: ["steam"], lambda: False,
                                      lambda m: None, on_blocked=seen.append))
        assert seen == []

    def test_works_without_a_notifier(self, monkeypatch):
        monkeypatch.setattr(processes, "kill", lambda pid: True)
        self._spin(processes.Watchdog(lambda: ["steam"], lambda: False,
                                      lambda m: None))
