"""The single-instance guard and the show-me sentinel."""

import os

import pytest

from blockguard import single_instance


@pytest.fixture
def sentinel(tmp_path, monkeypatch):
    path = tmp_path / "show.request"
    monkeypatch.setattr(single_instance, "SHOW_REQUEST_PATH", str(path))
    return path


class TestShowRequest:
    def test_no_request_initially(self, sentinel):
        assert single_instance.consume_show_request() is False

    def test_request_then_consume(self, sentinel):
        assert single_instance.request_show() is True
        assert sentinel.exists()
        assert single_instance.consume_show_request() is True

    def test_consuming_removes_the_sentinel(self, sentinel):
        """Otherwise the window would be summoned over and over."""
        single_instance.request_show()
        single_instance.consume_show_request()
        assert not sentinel.exists()
        assert single_instance.consume_show_request() is False

    def test_repeated_requests_collapse_to_one(self, sentinel):
        for _ in range(5):
            single_instance.request_show()
        assert single_instance.consume_show_request() is True
        assert single_instance.consume_show_request() is False

    def test_unwritable_location_is_not_fatal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(single_instance, "SHOW_REQUEST_PATH",
                            str(tmp_path / "missing" / "show.request"))
        assert single_instance.request_show() is False


class TestAcquire:
    def test_first_acquire_succeeds(self, monkeypatch):
        monkeypatch.setattr(single_instance, "_handle", None)
        monkeypatch.setattr(single_instance, "MUTEX_NAME",
                            f"Local\\BlockGuardTest{os.getpid()}")
        assert single_instance.acquire() is True

    def test_second_acquire_is_refused(self, monkeypatch):
        """A second launch must not start a second watchdog."""
        monkeypatch.setattr(single_instance, "_handle", None)
        monkeypatch.setattr(single_instance, "MUTEX_NAME",
                            f"Local\\BlockGuardTestDup{os.getpid()}")
        assert single_instance.acquire() is True
        assert single_instance.acquire() is False
