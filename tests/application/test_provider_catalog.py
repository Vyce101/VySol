from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from vysol.creation_store import CreationStore
from vysol.credentials import FileCredentialVault
from vysol.provider_catalog import ProviderCatalog
from vysol.provider_profiles import preview_chat_models, profile_for
from vysol.server import create_app


def credential(store, vault, provider, *, base_url=None, secret="synthetic-provider-key"):
    key_id = str(uuid4())
    connection = next(item for item in store.connections() if item["provider"] == provider)
    with store.connect() as db:
        saved = store.save_key(db, key_id, f"{provider} key", provider, connection["id"], base_url)
    if secret:
        vault.write(key_id, secret)
    return saved


def test_provider_model_discovery_profiles_discovered_models_and_retains_stale_cache(tmp_path):
    store = CreationStore(tmp_path)
    vault = FileCredentialVault(tmp_path)
    saved = credential(store, vault, "openai")
    responses = [
        httpx.Response(200, json={"data": [
            {"id": "gpt-5.4"}, {"id": "vendor-new-chat-model"},
        ]}),
        httpx.Response(503, json={"error": "This response must not reach logs or users"}),
    ]
    requests = []

    def send(request):
        requests.append(request)
        return responses.pop(0)

    logger = _RecordingLogger()
    client = httpx.Client(transport=httpx.MockTransport(send))
    catalog = ProviderCatalog(store, vault, logger, client)

    first = catalog.refresh(saved["id"])
    assert [model["id"] for model in first["models"]] == ["gpt-5.4", "vendor-new-chat-model"]
    assert first["models"][0]["tested"] is True
    assert first["models"][0]["capabilities"]["reasoning_default"] == "none"
    assert first["models"][1]["tested"] is False
    assert requests[0].url.path == "/v1/models"
    assert requests[0].headers["authorization"] == "Bearer synthetic-provider-key"

    old_timestamp = first["models_updated_at"]
    failed = catalog.refresh(saved["id"])
    assert failed["models"] == first["models"]
    assert failed["models_updated_at"] == old_timestamp
    assert failed["models_error"] == "Model refresh failed (HTTP 503)."
    assert "response must not reach" not in json.dumps(failed)
    assert "synthetic-provider-key" not in json.dumps(logger.messages)

    client.close()


def test_compatible_catalog_uses_saved_base_url_without_a_key(tmp_path):
    store = CreationStore(tmp_path)
    vault = FileCredentialVault(tmp_path)
    saved = credential(store, vault, "openai_compatible", base_url="http://localhost:4321/v1", secret=None)
    seen = []

    def send(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "compatible-chat"}]})

    client = httpx.Client(transport=httpx.MockTransport(send))
    result = ProviderCatalog(store, vault, client=client).refresh(saved["id"])
    assert result["models"][0]["id"] == "compatible-chat"
    assert result["models"][0]["tested"] is False
    assert str(seen[0].url) == "http://localhost:4321/v1/models"
    assert "authorization" not in seen[0].headers
    client.close()


def test_compatible_catalog_explains_auth_failure_without_a_key(tmp_path):
    store = CreationStore(tmp_path)
    vault = FileCredentialVault(tmp_path)
    saved = credential(store, vault, "openai_compatible", base_url="http://localhost:4321/v1", secret=None)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(401, json={"error": "private server response"})))

    result = ProviderCatalog(store, vault, client=client).refresh(saved["id"])

    assert result["models_error"] == "This server requires a key or rejected the key."
    assert "private server response" not in json.dumps(result)
    client.close()


def test_stale_refresh_uses_last_success_age_and_keeps_failure_backoff(tmp_path):
    store = CreationStore(tmp_path)
    vault = FileCredentialVault(tmp_path)
    saved = credential(store, vault, "deepseek")
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{
            "id": "deepseek-flash", "context_window": 500000,
            "max_output_tokens": 64000, "input_modalities": ["text"],
            "output_modalities": ["text"],
            "effort": {"supported_levels": ["none", "low", "medium", "high"], "default_level": "medium"},
        }]})

    client = httpx.Client(transport=httpx.MockTransport(send))
    catalog = ProviderCatalog(store, vault, client=client)
    catalog.refresh(saved["id"])
    with store.connect() as db:
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        db.execute("UPDATE provider_model_catalog SET refreshed_at=? WHERE key_id=?", (old, saved["id"]))
    assert store.needs_catalog_refresh(saved["id"])
    catalog.refresh_stale_background()
    catalog._background_thread.join(timeout=3)
    assert len(calls) == 2
    entry = store.model_for(saved["id"], "deepseek-flash")
    assert entry["capabilities"]["input_limit"] == 500_000
    assert entry["capabilities"]["output_limit"] == 64_000
    assert entry["capabilities"]["reasoning_levels"] == ["low", "medium", "high"]
    assert entry["capabilities"]["reasoning_default"] == "medium"
    assert entry["capabilities"]["reasoning_off"] is True
    client.close()


def test_refresh_finishes_cleanly_when_credential_is_deleted_in_flight(tmp_path):
    store = CreationStore(tmp_path)
    vault = FileCredentialVault(tmp_path)
    saved = credential(store, vault, "openai")

    def send(_request):
        with store.connect() as db:
            db.execute("DELETE FROM provider_keys WHERE id=?", (saved["id"],))
        return httpx.Response(200, json={"data": [{"id": "gpt-5.4"}]})

    client = httpx.Client(transport=httpx.MockTransport(send))
    result = ProviderCatalog(store, vault, client=client).refresh(saved["id"])
    assert result == {"models": [], "models_updated_at": None, "models_error": None}
    client.close()


def test_provider_api_refreshes_added_compatible_credential_and_locks_base_url(tmp_path):
    app = create_app(tmp_path)
    service = app.state.creation.provider_catalog
    service.client.close()
    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})

    service.client = httpx.Client(transport=httpx.MockTransport(send))
    service._owns_client = True
    key_id = str(uuid4())
    with TestClient(app) as client:
        added = client.put(f"/api/providers/keys/{key_id}", json={
            "name": "Local server", "provider": "openai_compatible",
            "base_url": "http://LOCALHOST:9000/v1/", "secret": None,
        })
        assert added.status_code == 200
        assert added.json()["base_url"] == "http://localhost:9000/v1"
        assert added.json()["models"][0]["id"] == "local-model"
        assert str(requests[0].url) == "http://localhost:9000/v1/models"

        renamed = client.put(f"/api/providers/keys/{key_id}", json={"name": "Renamed"})
        assert renamed.status_code == 200
        assert renamed.json()["base_url"] == "http://localhost:9000/v1"
        changed = client.put(f"/api/providers/keys/{key_id}", json={
            "name": "Renamed", "provider": "openai_compatible",
            "base_url": "http://localhost:9001/v1",
        })
        assert changed.status_code == 422
        assert client.get(f"/api/providers/keys/{key_id}/models").json()["models"][0]["id"] == "local-model"
        assert len(client.get("/api/providers").json()["connections"]) == 5
        assert "Bearer" not in client.get("/api/providers").text
    service.client.close()


def test_referenced_credentials_cannot_be_deleted(tmp_path):
    store = CreationStore(tmp_path)
    vault = FileCredentialVault(tmp_path)
    saved = credential(store, vault, "openai")
    with store.connect() as db:
        db.execute("""
            CREATE TABLE embedding_profiles(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, key_id TEXT NOT NULL,
                model TEXT NOT NULL, dimensions INTEGER, max_input_tokens INTEGER,
                preflighted_at TEXT, input_format_version INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        stamp = datetime.now(timezone.utc).isoformat()
        profile_id = str(uuid4())
        db.execute(
            "INSERT INTO embedding_profiles(id,name,key_id,model,dimensions,max_input_tokens,preflighted_at,"
            "input_format_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (profile_id, "Profile", saved["id"], "text-embedding-3-large", 3072, 8192,
             None, 2, stamp, stamp),
        )
        db.execute("INSERT INTO attempts(id,data) VALUES(?,?)", (
            str(uuid4()), json.dumps({"state": "running", "embedding_profile_id": profile_id}),
        ))
    assert store.credential_used(saved["id"]) is True
    assert store.credential_busy(saved["id"]) is True


@pytest.mark.parametrize(("provider", "model", "expected_tested", "expected_api"), [
    ("google", "gemini-2.5-flash", True, "generate_content"),
    ("google", "gemini-3-pro-preview", True, "interactions"),
    ("google", "gemini-3.1-flash-lite", False, "interactions"),
    ("openai", "gpt-5.4", True, "responses"),
    ("anthropic", "claude-haiku-4-5-20251001", True, "messages"),
    ("deepseek", "deepseek-v4-pro", True, "chat_completions"),
    ("openai", "gpt-5.4-special-preview", False, "responses"),
])
def test_tested_profiles_are_exact_and_carry_api_contract(provider, model, expected_tested, expected_api):
    result = profile_for(provider, model)
    assert result["tested"] is expected_tested
    assert result["api"] == expected_api


def test_openai_catalog_separates_known_non_chat_models_from_unknown_chat_models():
    embedding = profile_for("openai", "text-embedding-future")
    image = profile_for("openai", "gpt-image-future")
    unknown_chat = profile_for("openai", "gpt-6-next")
    assert embedding["tested"] is False
    assert embedding["capabilities"]["chat"] is False
    assert embedding["capabilities"]["embeddings"] is True
    assert image["capabilities"]["chat"] is False
    assert image["capabilities"]["embeddings"] is False
    assert unknown_chat["tested"] is False
    assert unknown_chat["capabilities"]["chat"] is True
    assert unknown_chat["capabilities"]["embeddings"] is False


@pytest.mark.parametrize(("provider", "model_id"), [
    ("google", "gemini-2.5-flash-preview-tts"),
    ("google", "gemini-2.5-flash-image"),
    ("google", "gemini-3.1-pro-preview-customtools"),
    ("google", "gemini-3.5-flash-transcribe-preview"),
    ("google", "gemini-3.1-flash-tts-preview"),
    ("google", "lyria-3"),
    ("google", "gemini-robotics-er-2"),
    ("google", "antigravity-agent"),
    ("openai", "gpt-4o"),
    ("openai", "o3-deep-research"),
    ("openai", "computer-use-preview"),
])
def test_specialized_models_are_not_chat_models(provider, model_id):
    result = profile_for(provider, model_id, {"supportedGenerationMethods": ["generateContent"]})

    assert result["capabilities"]["chat"] is False


def test_non_chat_filter_preserves_embedding_discovery():
    embedding = profile_for("google", "gemini-embedding-2", {
        "supportedGenerationMethods": ["embedContent"],
    })

    assert embedding["capabilities"]["chat"] is False
    assert embedding["capabilities"]["embeddings"] is True


def test_preview_chat_models_contains_explicit_profiles_only():
    models = preview_chat_models()
    model_ids = {model["id"] for model in models}

    assert "gemini-3.8-flash" in model_ids
    assert "gpt-6-astra" in model_ids
    assert "claude-opus-5-5" in model_ids
    assert "deepseek-v4-pro" in model_ids
    assert "gemini-embedding-2" not in model_ids
    assert "gpt-4o" not in model_ids
    assert "gemini-3.1-pro-preview-customtools" not in model_ids
    assert "gemini-3.5-flash-transcribe-preview" not in model_ids
    assert "lyria-3" not in model_ids
    assert all(model["capabilities"]["chat"] is True for model in models)


def test_known_google_anthropic_and_deepseek_profiles_include_documented_limits():
    google_profile = profile_for("google", "gemini-2.5-pro")
    google = google_profile["capabilities"]
    assert google_profile["api"] == "generate_content"
    assert google["input_limit"] == 1_048_576
    assert google["output_limit"] == 65_536
    assert google["thinking_levels"] == []
    assert google["thinking_budget"] == {
        "minimum": 128, "maximum": 32_768, "default": "dynamic", "allow_zero": False,
    }

    flash = profile_for("google", "gemini-2.5-flash")
    assert flash["api"] == "generate_content"
    assert flash["capabilities"]["thinking_budget"] == {
        "minimum": 0, "maximum": 24_576, "default": "dynamic", "allow_zero": True,
    }

    flash_lite = profile_for("google", "gemini-2.5-flash-lite")
    assert flash_lite["api"] == "generate_content"
    assert flash_lite["capabilities"]["thinking_budget"] == {
        "minimum": 512, "maximum": 24_576, "default": "off", "allow_zero": True,
    }

    fable = profile_for("anthropic", "claude-fable-5-1")["capabilities"]
    assert fable["output_limit"] == 128_000
    assert fable["reasoning_default"] == "high"
    assert fable["thinking_mode"] == "adaptive"

    deepseek = profile_for("deepseek", "deepseek-v4-pro")
    assert deepseek["name"] == "DeepSeek V4 Pro"
    assert deepseek["series"] == "Pro"
    assert deepseek["capabilities"]["input_limit"] == 1_048_576
    assert deepseek["capabilities"]["output_limit"] == 393_216
    assert deepseek["capabilities"]["reasoning_levels"] == ["low", "high", "max"]
    assert deepseek["capabilities"]["reasoning_off"] is False

    deepseek_flash = profile_for("deepseek", "deepseek-flash")
    assert deepseek_flash["name"] == "DeepSeek V4.1 Flash"
    assert deepseek_flash["series"] == "Flash"

    gpt41 = profile_for("openai", "gpt-4.1")["capabilities"]
    assert gpt41["output_limit"] == 32_768
    assert gpt41["reasoning_levels"] == []


@pytest.mark.parametrize(("model", "input_limit", "output_limit"), [
    ("gpt-6-astra", 1_050_000, 128_000),
    ("gpt-5.4", 1_050_000, 128_000),
    ("gpt-5.4-pro", 1_050_000, 128_000),
    ("gpt-5-pro", 400_000, 272_000),
])
def test_openai_profile_uses_documented_decimal_limits(model, input_limit, output_limit):
    capabilities = profile_for("openai", model)["capabilities"]
    assert capabilities["input_limit"] == input_limit
    assert capabilities["output_limit"] == output_limit


def test_anthropic_manual_thinking_survives_provider_effort_metadata():
    result = profile_for("anthropic", "claude-haiku-4-5-20251001", {
        "max_input_tokens": 200000,
        "max_tokens": 64000,
        "capabilities": {"effort": {"supported": False},
                         "thinking": {"types": {"enabled": {"supported": True}}}},
    })
    capabilities = result["capabilities"]
    assert capabilities["thinking_mode"] == "manual"
    assert capabilities["reasoning_levels"] == ["low", "medium", "high"]
    assert capabilities["output_limit"] == 64000


class _RecordingLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(message % args)

    def warning(self, message, *args):
        self.messages.append(message % args)
