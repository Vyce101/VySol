import asyncio
import json
from pathlib import Path

import pytest

from core import config
from routers import settings as settings_router


def _make_temp_paths(name: str) -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[2] / ".codex-test-key-manager"
    root.mkdir(parents=True, exist_ok=True)
    settings_path = root / f"{name}-settings.json"
    prompts_path = root / f"{name}-default-prompts.json"
    return settings_path, prompts_path


def _cleanup_temp_paths(*paths: Path) -> None:
    parents: set[Path] = set()
    for path in paths:
        if path.exists():
            path.unlink()
        parents.add(path.parent)
    for parent in parents:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


def test_load_settings_includes_provider_defaults_and_locked_default_preset(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-defaults")
    try:
        settings_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        loaded = config.load_settings()

        assert loaded["entity_resolution_top_k"] == 50
        assert loaded["default_model_flash"] == "gemini-3.1-flash-lite-preview"
        assert loaded["default_model_chat"] == "gemini-3-flash-preview"
        assert loaded["default_model_chat_provider"] == "gemini"
        assert loaded["embedding_provider"] == "gemini"
        assert loaded["gemini_chat_send_thinking"] is True
        assert loaded["groq_chat_include_reasoning"] is False
        assert loaded["entity_resolution_chooser_prompt"] is None
        assert loaded["entity_resolution_combiner_prompt"] is None
        assert loaded["graph_architect_prompt"] is None
        assert loaded["graph_architect_glean_prompt"] is None
        assert loaded["active_settings_preset_name"] == "Default"
        assert loaded["active_settings_preset_locked"] is True
        assert loaded["settings_presets"] == [
            {
                "id": loaded["active_settings_preset_id"],
                "name": "Default",
                "locked": True,
            }
        ]
        assert loaded["provider_registry"]["providers"]["groq"]["family"] == "openai_compatible"
        assert loaded["provider_status"]["embedding"]["provider"] == "gemini"
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_provider_capabilities_expose_exact_text_and_embedding_model_catalogs():
    capabilities = config.get_provider_capabilities()
    gemini_models = capabilities["providers"]["gemini"]["text_model_options"]
    groq_models = capabilities["providers"]["groq"]["text_model_options"]
    gemini_embedding_models = capabilities["providers"]["gemini"]["embedding_model_options"]

    assert [option["value"] for option in gemini_models] == [
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3-flash-preview",
    ]
    assert [option["value"] for option in groq_models] == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3-32b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "moonshotai/kimi-k2-instruct-0905",
    ]
    assert gemini_models[0]["gemini_thinking_levels"] == ["low", "medium", "high"]
    assert groq_models[0]["groq_reasoning_options"] == [
        {"value": "low", "label": "Low"},
        {"value": "medium", "label": "Medium"},
        {"value": "high", "label": "High"},
    ]
    assert groq_models[2]["groq_reasoning_options"] == [
        {"value": "none", "label": "None"},
        {"value": "default", "label": "Reasoning On (provider default)"},
    ]
    assert groq_models[3]["supports_groq_reasoning"] is False
    assert [option["value"] for option in gemini_embedding_models] == [
        "gemini-embedding-001",
        "gemini-embedding-2-preview",
    ]
    assert not any("text-embedding" in option["value"] for option in gemini_embedding_models)
    assert capabilities["providers"]["groq"]["embedding_model_options"] == []


def test_settings_payload_strips_secrets_and_internal_fields(monkeypatch):
    monkeypatch.setattr(
        settings_router,
        "load_settings",
        lambda: {
            "default_model_chat": "gemini-3-flash-preview",
            "provider_status": {"chat": {"ok": True}},
            "provider_registry": {"providers": {}},
            "settings_presets": [{"id": "default", "name": "Default", "locked": True}],
            "active_settings_preset_id": "default",
            "active_settings_preset_name": "Default",
            "api_keys": [
                {"value": "secret-1", "enabled": True},
                {"value": "secret-2", "enabled": False},
            ],
            "_provider_credentials": {
                "gemini": [{"api_key": "secret-1"}],
            },
            "_active_settings_preset_id": "default",
        },
    )

    payload = settings_router._settings_payload()

    assert payload["api_key_count"] == 2
    assert payload["api_key_active_count"] == 1
    assert payload["default_model_chat"] == "gemini-3-flash-preview"
    assert "api_keys" not in payload
    assert "_provider_credentials" not in payload
    assert "_active_settings_preset_id" not in payload


def test_prompt_keys_expose_graph_and_entity_resolution_prompts():
    expected = {
        "graph_architect_prompt",
        "graph_architect_glean_prompt",
        "entity_resolution_chooser_prompt",
        "entity_resolution_combiner_prompt",
        "chat_system_prompt",
    }

    assert expected.issubset(set(settings_router.PROMPT_KEYS))


def test_load_prompt_prefers_custom_settings_and_falls_back_to_default(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-prompts")
    try:
        settings_path.write_text(
            json.dumps(
                {
                    "entity_resolution_chooser_prompt": "custom chooser prompt",
                }
            ),
            encoding="utf-8",
        )
        prompts_path.write_text(
            json.dumps(
                {
                    "graph_architect_prompt": "default graph prompt",
                    "graph_architect_glean_prompt": "default glean prompt",
                    "entity_resolution_chooser_prompt": "default chooser prompt",
                    "entity_resolution_combiner_prompt": "default combiner prompt",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)
        monkeypatch.setattr(config, "DEFAULT_PROMPTS_FILE", prompts_path)

        assert config.load_prompt("entity_resolution_chooser_prompt") == "custom chooser prompt"
        assert config.load_prompt("graph_architect_prompt") == "default graph prompt"
        assert config.load_prompt("graph_architect_glean_prompt") == "default glean prompt"
        assert config.load_prompt("entity_resolution_combiner_prompt") == "default combiner prompt"
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_load_prompt_prefers_world_overrides_before_global_and_default(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: {
            "graph_architect_prompt": "global graph prompt",
            "graph_architect_glean_prompt": "global glean prompt",
            "entity_resolution_chooser_prompt": None,
            "entity_resolution_combiner_prompt": None,
        },
    )
    monkeypatch.setattr(
        config,
        "load_default_prompts",
        lambda: {
            "graph_architect_prompt": "default graph prompt",
            "graph_architect_glean_prompt": "default glean prompt",
            "entity_resolution_chooser_prompt": "default chooser prompt",
            "entity_resolution_combiner_prompt": "default combiner prompt",
        },
    )
    monkeypatch.setattr(
        config,
        "load_world_meta",
        lambda world_id: {
            "world_id": world_id,
            "ingest_prompt_overrides": {
                "graph_architect_prompt": "world graph prompt",
            },
        },
    )

    assert config.load_prompt("graph_architect_prompt", world_id="world-1") == "world graph prompt"
    assert config.load_prompt("graph_architect_glean_prompt", world_id="world-1") == "global glean prompt"
    assert config.load_prompt("entity_resolution_chooser_prompt", world_id="world-1") == "default chooser prompt"


def test_get_world_ingest_prompt_states_reports_world_global_and_default_sources(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: {
            "graph_architect_prompt": None,
            "graph_architect_glean_prompt": "global glean prompt",
            "entity_resolution_chooser_prompt": None,
            "entity_resolution_combiner_prompt": None,
        },
    )
    monkeypatch.setattr(
        config,
        "load_default_prompts",
        lambda: {
            "graph_architect_prompt": "default graph prompt",
            "graph_architect_glean_prompt": "default glean prompt",
            "entity_resolution_chooser_prompt": "default chooser prompt",
            "entity_resolution_combiner_prompt": "default combiner prompt",
        },
    )

    states = config.get_world_ingest_prompt_states(
        meta={
            "world_id": "world-1",
            "ingest_prompt_overrides": {
                "graph_architect_prompt": "world graph prompt",
            },
        }
    )

    assert states["graph_architect_prompt"] == {"value": "world graph prompt", "source": "world"}
    assert states["graph_architect_glean_prompt"] == {"value": "global glean prompt", "source": "global"}
    assert states["entity_resolution_combiner_prompt"] == {"value": "default combiner prompt", "source": "default"}


def test_load_settings_normalizes_stage_specific_concurrency_controls(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-concurrency")
    try:
        settings_path.write_text(
            json.dumps(
                {
                    "ingestion_concurrency": 3,
                    "graph_extraction_concurrency": 0,
                    "graph_extraction_cooldown_seconds": -5,
                    "embedding_concurrency": -2,
                    "embedding_cooldown_seconds": -1,
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        loaded = config.load_settings()

        assert loaded["graph_extraction_concurrency"] == 1
        assert loaded["graph_extraction_cooldown_seconds"] == 0.0
        assert loaded["embedding_concurrency"] == 1
        assert loaded["embedding_cooldown_seconds"] == 0.0
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_save_settings_persists_stage_specific_controls_into_active_preset(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-save-concurrency")
    try:
        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        config.save_settings(
            {
                "graph_extraction_concurrency": 6,
                "graph_extraction_cooldown_seconds": 2.5,
                "embedding_concurrency": 12,
                "embedding_cooldown_seconds": -4,
            }
        )

        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        preset_values = saved["settings_presets"][0]["values"]

        assert preset_values["graph_extraction_concurrency"] == 6
        assert preset_values["graph_extraction_cooldown_seconds"] == 2.5
        assert preset_values["embedding_concurrency"] == 12
        assert preset_values["embedding_cooldown_seconds"] == 0.0
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_load_settings_migrates_legacy_api_key_strings_to_provider_library(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-migrate-keys")
    try:
        settings_path.write_text(
            json.dumps(
                {
                    "api_keys": ["k1", "k2"],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        loaded = config.load_settings()
        saved = json.loads(settings_path.read_text(encoding="utf-8"))

        assert loaded["api_keys"] == [
            {"value": "k1", "enabled": True},
            {"value": "k2", "enabled": True},
        ]
        assert saved["settings_presets"][0]["name"] == "Default"
        assert saved["settings_presets"][0]["locked"] is True
        assert [entry["api_key"] for entry in saved["provider_credentials"]["gemini"]] == ["k1", "k2"]
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_sanitize_settings_coerces_gemini_thinking_toggle_from_string_values():
    enabled = config.sanitize_settings({"gemini_chat_send_thinking": "true"})
    disabled = config.sanitize_settings({"gemini_chat_send_thinking": "false"})

    assert enabled["gemini_chat_send_thinking"] is True
    assert disabled["gemini_chat_send_thinking"] is False


def test_resolve_gemini_thinking_settings_supports_level_and_manual_budget():
    supported = config.resolve_gemini_thinking_settings(
        {
            "default_model_chat_thinking_level": "medium",
            "default_model_chat_thinking_manual": "200",
        },
        slot_key="default_model_chat",
        model_name="gemini-3.1-pro-preview",
        include_thoughts=True,
    )
    manual = config.resolve_gemini_thinking_settings(
        {
            "default_model_chat_thinking_level": "",
            "default_model_chat_thinking_manual": "200",
        },
        slot_key="default_model_chat",
        model_name="gemini-2.5-pro",
    )

    assert supported == {
        "thinking_level": "MEDIUM",
        "include_thoughts": True,
    }
    assert manual == {
        "thinking_budget": 200,
    }


def test_resolve_groq_reasoning_effort_respects_supported_unsupported_and_custom_models():
    assert config.resolve_groq_reasoning_effort(
        {"default_model_chat_groq_reasoning_effort": "high"},
        slot_key="default_model_chat",
        model_name="openai/gpt-oss-20b",
    ) == "high"

    assert config.resolve_groq_reasoning_effort(
        {"default_model_chat_groq_reasoning_effort": "high"},
        slot_key="default_model_chat",
        model_name="llama-3.3-70b-versatile",
    ) == ""

    assert config.resolve_groq_reasoning_effort(
        {"default_model_chat_groq_reasoning_effort": "medium"},
        slot_key="default_model_chat",
        model_name="custom/groq-model",
    ) == "medium"


def test_save_settings_persists_legacy_api_key_enabled_state_into_gemini_library(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-save-keys")
    try:
        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        config.save_settings(
            {
                "api_keys": [
                    {"value": "k1", "enabled": True},
                    {"value": "k2", "enabled": False},
                ],
            }
        )

        saved = json.loads(settings_path.read_text(encoding="utf-8"))

        assert saved["provider_credentials"]["gemini"] == [
            {
                "id": saved["provider_credentials"]["gemini"][0]["id"],
                "label": "Google (Gemini) 1",
                "enabled": True,
                "api_key": "k1",
            },
            {
                "id": saved["provider_credentials"]["gemini"][1]["id"],
                "label": "Google (Gemini) 2",
                "enabled": False,
                "api_key": "k2",
            },
        ]
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_save_settings_preserves_existing_provider_labels_when_legacy_api_keys_are_reposted(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-preserve-provider-labels")
    try:
        settings_path.write_text(
            json.dumps(
                {
                    "schema_version": config.SETTINGS_SCHEMA_VERSION,
                    "settings_presets": [
                        {
                            "id": "default",
                            "name": "Default",
                            "locked": True,
                            "values": dict(config.PRESET_SETTINGS_DEFAULTS),
                        }
                    ],
                    "active_settings_preset_id": "default",
                    "provider_credentials": {
                        "gemini": [
                            {
                                "id": "gem-1",
                                "label": "Main Gemini Key",
                                "enabled": True,
                                "api_key": "k1",
                            },
                            {
                                "id": "gem-2",
                                "label": "Backup Gemini Key",
                                "enabled": False,
                                "api_key": "k2",
                            },
                        ],
                        "groq": [],
                        "intenserp": [],
                    },
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        config.save_settings(
            {
                "api_keys": [
                    {"value": "k1", "enabled": True},
                    {"value": "k2", "enabled": False},
                ],
            }
        )

        saved = json.loads(settings_path.read_text(encoding="utf-8"))

        assert saved["provider_credentials"]["gemini"] == [
            {
                "id": "gem-1",
                "label": "Main Gemini Key",
                "enabled": True,
                "api_key": "k1",
            },
            {
                "id": "gem-2",
                "label": "Backup Gemini Key",
                "enabled": False,
                "api_key": "k2",
            },
        ]
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_get_settings_reports_active_and_total_api_key_counts(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-key-counts")
    try:
        settings_path.write_text(
            json.dumps(
                {
                    "api_keys": [
                        {"value": "k1", "enabled": True},
                        {"value": "k2", "enabled": False},
                        {"value": "k3", "enabled": True},
                    ],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)
        monkeypatch.setattr(settings_router, "load_settings", config.load_settings)

        payload = asyncio.run(settings_router.get_settings())

        assert payload["api_key_count"] == 3
        assert payload["api_key_active_count"] == 2
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_create_settings_preset_clones_active_config_and_keeps_default_locked(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-create-preset")
    try:
        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        config.save_settings(
            {
                "ui_theme": "light",
                "default_model_chat_provider": "openai_compatible",
                "default_model_chat_openai_compatible_provider": "groq",
            }
        )

        created = config.create_settings_preset("Groq Preset")
        loaded = config.load_settings()
        saved = json.loads(settings_path.read_text(encoding="utf-8"))

        assert created["name"] == "Groq Preset"
        assert loaded["active_settings_preset_name"] == "Groq Preset"
        assert loaded["active_settings_preset_locked"] is False
        assert saved["settings_presets"][0]["name"] == "Default"
        assert saved["settings_presets"][0]["locked"] is True
        assert saved["settings_presets"][1]["name"] == "Groq Preset"
        assert saved["settings_presets"][1]["locked"] is False
        assert saved["settings_presets"][1]["values"]["ui_theme"] == "light"
        assert saved["settings_presets"][1]["values"]["default_model_chat_provider"] == "openai_compatible"
        assert saved["settings_presets"][1]["values"]["default_model_chat_openai_compatible_provider"] == "groq"
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_rename_settings_preset_rejects_locked_default_preset(monkeypatch):
    settings_path, prompts_path = _make_temp_paths("settings-rename-default")
    try:
        monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

        loaded = config.load_settings()

        with pytest.raises(ValueError, match="locked"):
            config.rename_settings_preset(loaded["active_settings_preset_id"], "Renamed")
    finally:
        _cleanup_temp_paths(settings_path, prompts_path)


def test_compute_provider_statuses_marks_missing_credentials_and_unsupported_embedding(monkeypatch):
    monkeypatch.setattr(
        config,
        "get_provider_pool",
        lambda provider: [{"api_key": "gem-key"}] if provider == "gemini" else [],
    )

    settings = config.sanitize_settings(
        {
            "default_model_chat_provider": "openai_compatible",
            "default_model_chat_openai_compatible_provider": "groq",
            "embedding_provider": "openai_compatible",
            "embedding_openai_compatible_provider": "groq",
        }
    )

    statuses = config.compute_provider_statuses(settings)

    assert statuses["chat"]["provider"] == "groq"
    assert statuses["chat"]["ok"] is False
    assert "Key Library" in statuses["chat"]["message"]
    assert statuses["embedding"]["provider"] == "groq"
    assert statuses["embedding"]["ok"] is False
    assert "not available for embeddings yet" in statuses["embedding"]["message"]
