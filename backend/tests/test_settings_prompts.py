import json
import asyncio

from core import config
from routers import settings as settings_router


def test_load_settings_includes_entity_resolution_defaults(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

    loaded = config.load_settings()

    assert loaded["entity_resolution_top_k"] == 50
    assert loaded["default_model_entity_chooser"] == "gemini-flash-latest"
    assert loaded["default_model_entity_combiner"] == "gemini-flash-lite-latest"
    assert loaded["entity_resolution_chooser_prompt"] is None
    assert loaded["entity_resolution_combiner_prompt"] is None
    assert loaded["graph_architect_prompt"] is None
    assert loaded["graph_architect_glean_prompt"] is None


def test_prompt_keys_expose_graph_and_entity_resolution_prompts():
    expected = {
        "graph_architect_prompt",
        "graph_architect_glean_prompt",
        "entity_resolution_chooser_prompt",
        "entity_resolution_combiner_prompt",
        "chat_system_prompt",
    }

    assert expected.issubset(set(settings_router.PROMPT_KEYS))


def test_load_prompt_prefers_custom_settings_and_falls_back_to_default(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    prompts_path = tmp_path / "default_prompts.json"

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


def test_load_settings_normalizes_stage_specific_concurrency_controls(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
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


def test_save_settings_persists_stage_specific_controls_with_validation(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
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

    assert saved["graph_extraction_concurrency"] == 6
    assert saved["graph_extraction_cooldown_seconds"] == 2.5
    assert saved["embedding_concurrency"] == 12
    assert saved["embedding_cooldown_seconds"] == 0.0


def test_load_settings_migrates_legacy_api_key_strings_to_enabled_entries(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
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

    assert loaded["api_keys"] == [
        {"value": "k1", "enabled": True},
        {"value": "k2", "enabled": True},
    ]


def test_save_settings_persists_api_key_enabled_state(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
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

    assert saved["api_keys"] == [
        {"value": "k1", "enabled": True},
        {"value": "k2", "enabled": False},
    ]


def test_get_settings_reports_active_and_total_api_key_counts(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
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
