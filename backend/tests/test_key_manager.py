import json

from core import config, key_manager


def test_key_manager_uses_only_enabled_saved_keys(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "api_keys": [
                    {"value": "k1", "enabled": True},
                    {"value": "k2", "enabled": False},
                    {"value": "k3", "enabled": True},
                ],
                "key_rotation_mode": "ROUND_ROBIN",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)
    monkeypatch.setattr(key_manager, "_key_manager", None)

    manager = key_manager.get_key_manager(force_reload=True)

    assert manager.api_keys == ["k1", "k3"]
    assert manager.get_active_key() == ("k1", 0)
    assert manager.get_active_key() == ("k3", 1)


def test_key_manager_falls_back_to_env_when_all_saved_keys_are_disabled(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "api_keys": [
                    {"value": "k1", "enabled": False},
                    {"value": "k2", "enabled": False},
                ],
                "key_rotation_mode": "FAIL_OVER",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)
    monkeypatch.setattr(key_manager, "_key_manager", None)
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    manager = key_manager.get_key_manager(force_reload=True)

    assert manager.api_keys == ["env-key"]
    assert manager.get_active_key() == ("env-key", 0)
