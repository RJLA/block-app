"""Which running processes the watchdog will act on."""

import os

from blockguard.processes import offenders


def proc(pid, name, session=1, path=r"C:\Apps\x.exe"):
    return {"ProcessId": pid, "Name": name, "ExecutablePath": path,
            "SessionId": session}


SESSION = 1


def test_blocked_process_is_an_offender():
    found = offenders([proc(100, "steam.exe")], ["steam"], SESSION)
    assert found == [(100, "steam")]


def test_unlisted_process_is_left_alone():
    """The core of the inverted model -- no blocklist entry, no action."""
    assert offenders([proc(100, "notepad.exe")], ["steam"], SESSION) == []


def test_empty_blocklist_touches_nothing():
    processes = [proc(i, f"app{i}.exe") for i in range(10)]
    assert offenders(processes, [], SESSION) == []


def test_protected_process_is_spared_even_if_listed():
    assert offenders([proc(100, "explorer.exe")], ["explorer"], SESSION) == []


def test_other_session_is_ignored():
    """Services run in session 0 and are not the user's problem."""
    assert offenders([proc(100, "steam.exe", session=0)], ["steam"], SESSION) == []


def test_unknown_session_disables_the_filter():
    found = offenders([proc(100, "steam.exe", session=0)], ["steam"], -1)
    assert found == [(100, "steam")]


def test_own_process_is_never_an_offender():
    mine = proc(os.getpid(), "python.exe")
    assert offenders([mine], ["python"], SESSION) == []


def test_missing_fields_are_skipped():
    rows = [{}, {"ProcessId": None, "Name": "steam.exe", "SessionId": SESSION},
            {"ProcessId": 0, "Name": "steam.exe", "SessionId": SESSION}]
    assert offenders(rows, ["steam"], SESSION) == []


def test_blocklist_entries_are_normalized():
    found = offenders([proc(7, "Steam.exe")], [r"C:\Games\Steam\STEAM.EXE"], SESSION)
    assert found == [(7, "steam")]


def test_process_outside_windows_dir_is_still_matched():
    """A blocklist is explicit intent, so location does not exempt a process."""
    found = offenders([proc(9, "notepad.exe", path=r"C:\Windows\notepad.exe")],
                      ["notepad"], SESSION)
    assert found == [(9, "notepad")]
