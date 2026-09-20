"""The notice sound. MCI calls are captured rather than made audible."""

import os

import pytest

from blockguard import sound


@pytest.fixture
def mci(monkeypatch, tmp_path):
    """Record MCI commands; pretend the sound file exists."""
    sent = []
    monkeypatch.setattr(sound, "_send", lambda cmd: sent.append(cmd) or 0)
    path = tmp_path / "blocked.mp3"
    path.write_bytes(b"\xff\xfb")
    monkeypatch.setattr(sound, "sound_path", lambda: str(path))
    monkeypatch.setattr(sound, "enabled", True)
    return sent


class TestPlayBlocked:
    def test_opens_and_plays(self, mci):
        assert sound.play_blocked() is True
        assert any(c.startswith("open ") for c in mci)
        assert f"play {sound.ALIAS}" in mci

    def test_closes_previous_playback_first(self, mci):
        """MCI refuses to reopen a live alias, so a rapid second block
        would otherwise be silent."""
        sound.play_blocked()
        assert mci[0] == f"close {sound.ALIAS}"

    def test_plays_repeatedly(self, mci):
        for _ in range(3):
            assert sound.play_blocked() is True
        assert mci.count(f"play {sound.ALIAS}") == 3

    def test_declares_the_mp3_device_type(self, mci):
        sound.play_blocked()
        assert any("type mpegvideo" in c for c in mci)

    def test_silent_when_disabled(self, monkeypatch, mci):
        monkeypatch.setattr(sound, "enabled", False)
        assert sound.play_blocked() is False
        assert mci == []

    def test_missing_file_is_not_fatal(self, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setattr(sound, "_send", lambda cmd: sent.append(cmd) or 0)
        monkeypatch.setattr(sound, "sound_path",
                            lambda: str(tmp_path / "absent.mp3"))
        assert sound.play_blocked() is False
        assert sent == []

    def test_failure_to_open_is_reported(self, monkeypatch, tmp_path):
        path = tmp_path / "blocked.mp3"
        path.write_bytes(b"\xff\xfb")
        monkeypatch.setattr(sound, "sound_path", lambda: str(path))
        monkeypatch.setattr(sound, "_send",
                            lambda cmd: 0 if cmd.startswith("close") else 263)
        assert sound.play_blocked() is False

    def test_shutdown_releases_the_device(self, mci):
        sound.shutdown()
        assert mci == [f"close {sound.ALIAS}"]


def test_send_never_raises(monkeypatch):
    """No audio device, or a locked-down session, must not crash the app."""
    class Boom:
        def __getattr__(self, name):
            raise OSError("no winmm")
    monkeypatch.setattr(sound.ctypes, "windll", Boom())
    assert sound._send("play x") == -1


def test_the_real_sound_ships_with_the_app():
    assert os.path.exists(sound.sound_path()), "assets/blocked.mp3 is missing"
