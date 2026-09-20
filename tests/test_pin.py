"""PIN enrollment, verification and lockout."""

import json

import pytest

from blockguard import pin


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Isolated PIN file, with cheap hashing so tests stay fast."""
    path = tmp_path / "security.json"
    monkeypatch.setattr(pin, "SECURITY_PATH", str(path))
    monkeypatch.setattr(pin, "ITERATIONS", 1000)
    return path


@pytest.mark.parametrize("value", ["123456", "000000", "999999"])
def test_valid_pins(value):
    assert pin.is_valid_pin(value)


@pytest.mark.parametrize("value", ["12345", "1234567", "12345a", "", "  1234",
                                   "12 456", None, 123456])
def test_invalid_pins(value):
    assert not pin.is_valid_pin(value)


class TestEnrollment:
    def test_no_pin_initially(self, store):
        assert pin.has_pin() is False

    def test_set_then_has(self, store):
        assert pin.set_pin("123456") is True
        assert pin.has_pin() is True

    def test_rejects_invalid_pin(self, store):
        assert pin.set_pin("12345") is False
        assert pin.has_pin() is False

    def test_pin_is_never_stored_in_plaintext(self, store):
        pin.set_pin("135790")
        raw = store.read_text(encoding="utf-8")
        assert "135790" not in raw
        record = json.loads(raw)
        assert set(record) >= {"salt", "hash", "iterations"}

    def test_each_enrollment_uses_a_fresh_salt(self, store):
        pin.set_pin("123456")
        first = json.loads(store.read_text(encoding="utf-8"))
        pin.set_pin("123456")
        second = json.loads(store.read_text(encoding="utf-8"))
        assert first["salt"] != second["salt"]
        assert first["hash"] != second["hash"]


class TestVerification:
    def test_correct_pin_verifies(self, store):
        pin.set_pin("123456")
        assert pin.verify_pin("123456") is True

    def test_wrong_pin_rejected(self, store):
        pin.set_pin("123456")
        assert pin.verify_pin("654321") is False

    def test_verification_without_enrollment_fails(self, store):
        assert pin.verify_pin("123456") is False

    def test_success_resets_the_failure_count(self, store):
        pin.set_pin("123456")
        pin.verify_pin("000000")
        assert json.loads(store.read_text(encoding="utf-8"))["failures"] == 1
        pin.verify_pin("123456")
        assert json.loads(store.read_text(encoding="utf-8"))["failures"] == 0

    def test_corrupt_store_is_not_fatal(self, store):
        store.write_text("{ not json", encoding="utf-8")
        assert pin.has_pin() is False
        assert pin.verify_pin("123456") is False


class TestLockout:
    def test_free_attempts_do_not_lock(self, store):
        pin.set_pin("123456")
        for _ in range(pin.FREE_ATTEMPTS):
            pin.verify_pin("000000")
        assert pin.lockout_remaining() == 0

    def test_lockout_after_too_many_failures(self, store):
        pin.set_pin("123456")
        for _ in range(pin.FREE_ATTEMPTS + 1):
            pin.verify_pin("000000")
        assert pin.lockout_remaining() > 0

    def test_correct_pin_is_refused_while_locked_out(self, store):
        """Otherwise the lockout would not slow a guessing attack at all."""
        pin.set_pin("123456")
        for _ in range(pin.FREE_ATTEMPTS + 1):
            pin.verify_pin("000000")
        assert pin.verify_pin("123456") is False

    def test_lockout_grows_with_further_failures(self, store):
        pin.set_pin("123456")
        for _ in range(pin.FREE_ATTEMPTS + 1):
            pin.verify_pin("000000")
        first = pin.lockout_remaining()

        record = json.loads(store.read_text(encoding="utf-8"))
        record["locked_until"] = 0          # serve the first lockout
        store.write_text(json.dumps(record), encoding="utf-8")

        pin.verify_pin("000000")
        assert pin.lockout_remaining() > first

    def test_lockout_survives_a_restart(self, store):
        """State is on disk, so closing the app does not clear it."""
        pin.set_pin("123456")
        for _ in range(pin.FREE_ATTEMPTS + 1):
            pin.verify_pin("000000")
        assert json.loads(store.read_text(encoding="utf-8"))["locked_until"] > 0

    def test_enrolling_clears_the_lockout(self, store):
        pin.set_pin("123456")
        for _ in range(pin.FREE_ATTEMPTS + 2):
            pin.verify_pin("000000")
        pin.set_pin("654321")
        assert pin.lockout_remaining() == 0


class TestChangePin:
    def test_changes_with_the_correct_current_pin(self, store):
        pin.set_pin("111111")
        assert pin.change_pin("111111", "222222") is True
        assert pin.verify_pin("222222") is True

    def test_refuses_without_the_current_pin(self, store):
        pin.set_pin("111111")
        assert pin.change_pin("999999", "222222") is False
        assert pin.verify_pin("111111") is True

    def test_refuses_an_invalid_new_pin(self, store):
        pin.set_pin("111111")
        assert pin.change_pin("111111", "22") is False
        assert pin.verify_pin("111111") is True
