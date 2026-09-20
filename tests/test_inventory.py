"""Deriving a usable executable name for installed applications."""

import pytest

from blockguard.inventory import (
    exe_from_display_icon, exe_from_folder, is_junk_exe, is_skippable_product,
)


@pytest.mark.parametrize("raw, expected", [
    (r"C:\Apps\Thing\thing.exe,0", "thing"),
    (r"C:\Apps\Thing\thing.exe", "thing"),
    (r'"C:\Apps\Thing\thing.exe",-1', "thing"),
    (r"C:\Apps\Thing\icon.ico", ""),          # icon file, not a launcher
    ("", ""),
])
def test_exe_from_display_icon(raw, expected):
    assert exe_from_display_icon(raw) == expected


@pytest.mark.parametrize("exe", ["unins000", "setup", "vcredist_install",
                                 "crashpad", "appupdate"])
def test_junk_executables_are_rejected(exe):
    assert is_junk_exe(exe)


@pytest.mark.parametrize("exe", ["steam", "chrome", "code", "discord"])
def test_real_executables_are_kept(exe):
    assert not is_junk_exe(exe)


@pytest.mark.parametrize("name", [
    "Microsoft Visual C++ 2015 Redistributable",
    "Microsoft Windows Desktop Runtime - 7.0.16",
    "Killer Ethernet Driver Suite",
])
def test_non_application_products_are_skipped(name):
    assert is_skippable_product(name)


@pytest.mark.parametrize("name", ["Google Chrome", "Steam", "GIMP 3.2.4"])
def test_real_products_are_kept(name):
    assert not is_skippable_product(name)


class TestExeFromFolder:
    def test_prefers_exe_matching_the_product_name(self, tmp_path):
        (tmp_path / "unins000.exe").touch()
        (tmp_path / "slack.exe").touch()
        assert exe_from_folder(str(tmp_path), "Slack") == "slack"

    def test_falls_back_to_first_non_junk_exe(self, tmp_path):
        (tmp_path / "setup.exe").touch()
        (tmp_path / "launcher.exe").touch()
        assert exe_from_folder(str(tmp_path), "Some Product") == "launcher"

    def test_returns_empty_when_only_uninstallers(self, tmp_path):
        (tmp_path / "unins000.exe").touch()
        assert exe_from_folder(str(tmp_path), "Some Product") == ""

    def test_returns_empty_for_missing_folder(self, tmp_path):
        assert exe_from_folder(str(tmp_path / "nope"), "Thing") == ""

    def test_ignores_non_executables(self, tmp_path):
        (tmp_path / "readme.txt").touch()
        assert exe_from_folder(str(tmp_path), "Thing") == ""
