import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import config, key_manager


def _temp_settings_path(name: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    temp_dir = root / ".codex-test-key-manager"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / name


def test_key_manager_uses_only_enabled_saved_keys(monkeypatch):
    settings_path = _temp_settings_path("settings-enabled.json")
    try:
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
    finally:
        if settings_path.exists():
            settings_path.unlink()
        if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
            settings_path.parent.rmdir()


def test_key_manager_falls_back_to_env_when_all_saved_keys_are_disabled(monkeypatch):
    settings_path = _temp_settings_path("settings-disabled.json")
    try:
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
    finally:
        if settings_path.exists():
            settings_path.unlink()
        if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
            settings_path.parent.rmdir()


def test_key_manager_raises_structured_cooldown_error(monkeypatch):
    manager = key_manager.KeyManager(api_keys=["k1", "k2"], mode="ROUND_ROBIN")
    now = 100.0

    monkeypatch.setattr(key_manager.time, "time", lambda: now)

    manager.report_error(0, "429")
    manager.report_error(1, "429")

    with pytest.raises(key_manager.AllKeysInCooldownError) as exc:
        manager.get_active_key()

    assert exc.value.retry_after_seconds == 65.0
    assert "Retry in 65 seconds" in str(exc.value)


def test_round_robin_does_not_skip_next_key_after_transient_cooldown():
    manager = key_manager.KeyManager(api_keys=["k1", "k2", "k3"], mode="ROUND_ROBIN")

    assert manager.get_active_key() == ("k1", 0)
    manager.report_error(0, "timeout")

    assert manager.get_active_key() == ("k2", 1)


def test_wait_for_request_key_exhausts_currently_available_keys_before_failing(monkeypatch):
    manager = key_manager.KeyManager(api_keys=["k1", "k2", "k3"], mode="FAIL_OVER")
    now = 100.0

    monkeypatch.setattr(key_manager.time, "time", lambda: now)
    manager.report_error(2, "429")

    tried: set[int] = set()
    assert manager.wait_for_request_key(tried) == ("k1", 0)
    tried.add(0)
    assert manager.wait_for_request_key(tried) == ("k2", 1)
    tried.add(1)

    with pytest.raises(key_manager.AllKeysInCooldownError) as exc:
        manager.wait_for_request_key(tried)

    assert exc.value.retry_after_seconds == 65.0


def test_get_request_key_raises_when_every_key_was_already_tried():
    manager = key_manager.KeyManager(api_keys=["k1", "k2"], mode="ROUND_ROBIN")

    with pytest.raises(key_manager.RequestKeyPoolExhaustedError):
        manager.get_request_key({0, 1})


def test_wait_for_request_key_raises_when_remaining_untried_keys_are_cooling_down(monkeypatch):
    manager = key_manager.KeyManager(api_keys=["k1", "k2"], mode="FAIL_OVER")
    now = {"value": 100.0}

    monkeypatch.setattr(key_manager.time, "time", lambda: now["value"])

    manager.report_error(1, "429")

    with pytest.raises(key_manager.AllKeysInCooldownError):
        manager.wait_for_request_key({0})


class _DummyGeminiRateLimitError(RuntimeError):
    def __init__(self, *, message: str, headers: dict[str, str] | None = None):
        self.code = 429
        self.status = "RESOURCE_EXHAUSTED"
        self.message = message
        self.details = {"error": {"message": message}}
        self.response = SimpleNamespace(headers=headers or {})
        super().__init__(message)


def test_generic_gemini_429_is_request_backoff_not_cooldown():
    assessment = key_manager.assess_transient_provider_error(
        _DummyGeminiRateLimitError(message="Too Many Requests"),
        provider="gemini",
    )

    assert assessment is not None
    assert assessment.kind == "429"
    assert assessment.action == "request_backoff"


def test_explicit_gemini_api_key_quota_429_triggers_cooldown():
    assessment = key_manager.assess_transient_provider_error(
        _DummyGeminiRateLimitError(message="API key quota exceeded for this request."),
        provider="gemini",
    )

    assert assessment is not None
    assert assessment.kind == "429"
    assert assessment.action == "cooldown_key"


def test_gemini_429_retry_after_header_is_parsed():
    assessment = key_manager.assess_transient_provider_error(
        _DummyGeminiRateLimitError(
            message="Too Many Requests",
            headers={"Retry-After": "12"},
        ),
        provider="gemini",
    )

    assert assessment is not None
    assert assessment.retry_after_seconds == 12.0
