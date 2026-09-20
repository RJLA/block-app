"""Spotting a blocked site from the browser's window title."""

import pytest

from blockguard import browser_watch
from blockguard.browser_watch import blocked_hits, strip_browser_suffix

BLOCKED = ["reddit.com", "facebook.com"]


@pytest.mark.parametrize("title, expected", [
    ("reddit.com - Google Chrome", "reddit.com"),
    ("reddit.com - Microsoft Edge", "reddit.com"),
    ("reddit.com - Mozilla Firefox", "reddit.com"),
    ("Some Page - Brave", "Some Page"),
])
def test_strip_browser_suffix(title, expected):
    assert strip_browser_suffix(title) == expected


def test_non_browser_title_is_unchanged():
    assert strip_browser_suffix("Untitled - Notepad") == "Untitled - Notepad"


class TestBlockedHits:
    def test_detects_a_blocked_host(self):
        assert blocked_hits(["reddit.com - Google Chrome"], BLOCKED) == ["reddit.com"]

    def test_detects_a_www_host(self):
        assert blocked_hits(["www.reddit.com - Google Chrome"], BLOCKED) == \
            ["reddit.com"]

    def test_detects_a_full_url(self):
        assert blocked_hits(["reddit.com/r/all - Google Chrome"], BLOCKED) == \
            ["reddit.com"]

    def test_detects_a_subdomain(self):
        assert blocked_hits(["old.reddit.com - Google Chrome"], BLOCKED) == \
            ["old.reddit.com"]

    def test_searching_for_the_domain_is_not_a_hit(self):
        """The important false positive: this must stay silent."""
        assert blocked_hits(["reddit.com - Google Search - Google Chrome"],
                            BLOCKED) == []

    def test_an_article_mentioning_the_domain_is_not_a_hit(self):
        assert blocked_hits(["Why reddit.com went down - Google Chrome"],
                            BLOCKED) == []

    def test_unblocked_site_is_not_a_hit(self):
        assert blocked_hits(["github.com - Google Chrome"], BLOCKED) == []

    def test_non_browser_windows_are_ignored(self):
        """Editing a file named reddit.com must not trigger a notice."""
        assert blocked_hits(["reddit.com - Notepad"], BLOCKED) == []

    def test_empty_blocklist_never_hits(self):
        assert blocked_hits(["reddit.com - Google Chrome"], []) == []

    def test_empty_titles_are_safe(self):
        assert blocked_hits(["", None], BLOCKED) == []

    def test_several_windows(self):
        hits = blocked_hits(["reddit.com - Google Chrome",
                             "github.com - Google Chrome",
                             "facebook.com - Microsoft Edge"], BLOCKED)
        assert sorted(hits) == ["facebook.com", "reddit.com"]


class TestBrowserWatch:
    def _one_pass(self, watch):
        def stop(_timeout=None):
            watch._stop.set()
            return True
        watch._stop.wait = stop
        watch.run()

    def test_reports_a_hit(self, monkeypatch):
        monkeypatch.setattr(browser_watch, "list_window_titles",
                            lambda: ["reddit.com - Google Chrome"])
        seen = []
        self._one_pass(browser_watch.BrowserWatch(lambda: BLOCKED, seen.append))
        assert seen == ["reddit.com"]

    def test_skips_the_scan_with_no_blocked_sites(self, monkeypatch):
        scanned = []
        monkeypatch.setattr(browser_watch, "list_window_titles",
                            lambda: scanned.append(1) or [])
        self._one_pass(browser_watch.BrowserWatch(lambda: [], lambda h: None))
        assert scanned == []

    def test_duplicate_windows_report_once(self, monkeypatch):
        monkeypatch.setattr(browser_watch, "list_window_titles",
                            lambda: ["reddit.com - Google Chrome"] * 4)
        seen = []
        self._one_pass(browser_watch.BrowserWatch(lambda: BLOCKED, seen.append))
        assert seen == ["reddit.com"]


def test_enumeration_never_raises(monkeypatch):
    class Boom:
        def __getattr__(self, name):
            raise OSError("no user32")
    monkeypatch.setattr(browser_watch.ctypes, "windll", Boom())
    assert browser_watch.list_window_titles() == []
