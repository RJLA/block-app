"""Loading, cleaning and saving the blocklist."""

import json

from blockguard import config


def test_clean_normalizes_and_sorts():
    result = config._clean({
        "websites": ["https://WWW.Facebook.com/feed", "tiktok.com"],
        "apps": [r"C:\Games\Steam\Steam.exe", "discord.exe"],
        "dry_run": True,
    })
    assert result["websites"] == ["facebook.com", "tiktok.com"]
    assert result["apps"] == ["discord", "steam"]


def test_clean_deduplicates():
    result = config._clean({"websites": ["facebook.com", "www.facebook.com",
                                         "https://facebook.com/x"], "apps": []})
    assert result["websites"] == ["facebook.com"]


def test_clean_drops_empty_entries():
    result = config._clean({"websites": ["", None, "ok.com"], "apps": ["", "steam"]})
    assert result["websites"] == ["ok.com"]
    assert result["apps"] == ["steam"]


def test_dry_run_defaults_to_true_when_absent():
    """Never start terminating processes unless explicitly told to."""
    assert config._clean({})["dry_run"] is True


def test_dry_run_is_preserved_when_false():
    assert config._clean({"dry_run": False})["dry_run"] is False


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "blocklist.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    config.save_data({"websites": ["Facebook.com"], "apps": ["Steam.exe"],
                      "dry_run": False})

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written == {"websites": ["facebook.com"], "apps": ["steam"],
                       "dry_run": False}


def test_load_falls_back_when_config_is_corrupt(tmp_path, monkeypatch):
    path = tmp_path / "blocklist.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    monkeypatch.setattr(config, "seed_path", lambda: str(tmp_path / "missing.json"))

    assert config.load_data() == config.DEFAULTS


def test_save_is_atomic_leaving_no_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "blocklist.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(path))
    config.save_data({"websites": [], "apps": [], "dry_run": True})
    assert not (tmp_path / "blocklist.json.tmp").exists()
