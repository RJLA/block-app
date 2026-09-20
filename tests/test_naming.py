"""Normalization and blocklist matching."""

import pytest

from blockguard.naming import (
    PROTECTED_APPS, app_blocked, is_protected, normalize_app, normalize_site,
    site_blocked,
)


@pytest.mark.parametrize("raw, expected", [
    ("https://WWW.Example.com:8080/path?q=1", "example.com"),
    ("http://example.com/", "example.com"),
    ("  Example.COM  ", "example.com"),
    ("user:pw@example.com", "example.com"),
    ("www.sub.example.com", "sub.example.com"),
    ("example.com.", "example.com"),
    ("", ""),
])
def test_normalize_site(raw, expected):
    assert normalize_site(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("C:\\Program Files\\Slack\\Slack.exe", "slack"),
    ('"C:/Apps/Thing.EXE"', "thing"),
    ("steam.exe", "steam"),
    ("steam", "steam"),
    ("  Discord.lnk ", "discord"),
    ("", ""),
])
def test_normalize_app(raw, expected):
    assert normalize_app(raw) == expected


class TestSiteBlocked:
    BLOCKED = ["facebook.com", "tiktok.com"]

    def test_exact_match_is_blocked(self):
        assert site_blocked("facebook.com", self.BLOCKED)

    def test_subdomain_is_blocked(self):
        assert site_blocked("m.facebook.com", self.BLOCKED)

    def test_url_form_is_blocked(self):
        assert site_blocked("https://www.facebook.com/feed", self.BLOCKED)

    def test_unlisted_is_allowed(self):
        """The inverted model: anything not listed stays reachable."""
        assert not site_blocked("github.com", self.BLOCKED)

    def test_suffix_lookalike_is_not_blocked(self):
        assert not site_blocked("notfacebook.com", self.BLOCKED)

    def test_empty_list_blocks_nothing(self):
        assert not site_blocked("facebook.com", [])


class TestAppBlocked:
    BLOCKED = ["steam", "discord.exe"]

    def test_listed_app_is_blocked(self):
        assert app_blocked("steam.exe", self.BLOCKED)

    def test_listed_with_extension_is_blocked(self):
        assert app_blocked("discord", self.BLOCKED)

    def test_full_path_is_blocked(self):
        assert app_blocked("C:\\Games\\Steam\\steam.exe", self.BLOCKED)

    def test_unlisted_app_is_left_alone(self):
        assert not app_blocked("notepad.exe", self.BLOCKED)

    def test_empty_list_blocks_nothing(self):
        assert not app_blocked("steam", [])

    @pytest.mark.parametrize("critical", ["explorer.exe", "lsass", "winlogon"])
    def test_protected_apps_are_never_blocked(self, critical):
        """Protection wins even when the user explicitly lists the process."""
        assert not app_blocked(critical, [critical])


def test_is_protected():
    assert is_protected("explorer.exe")
    assert not is_protected("steam.exe")


def test_block_guard_cannot_block_itself():
    assert "blockguard" in PROTECTED_APPS
    assert not app_blocked("BlockGuard.exe", ["blockguard"])
