import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vysol.books.chunking import split_text
from vysol.creation_store import CreationConflict
from vysol.server import create_app
from vysol.worlds import atomic_json


class MemoryVault:
    def __init__(self):
        self.values = {}

    def read(self, key):
        return self.values.get(key)

    def write(self, key, secret):
        self.values[key] = secret

    def delete(self, key):
        self.values.pop(key, None)


class RecordingEmbeddings:
    def __init__(self):
        self.calls = []

    def embed_profile(self, text, credential, secret, model, dimensions, purpose, stop, logger):
        self.calls.append({"text": text, "credential": credential, "secret": secret,
                           "model": model, "dimensions": dimensions, "purpose": purpose})
        return [1.0] + [0.0] * ((dimensions or 4) - 1)


def add_credential(creation, vault, provider, *, secret="secret", base_url=None, models=None):
    connection = creation.store.add_connection(provider)
    key_id = str(uuid4())
    with creation.store.connect() as db:
        creation.store.save_key(db, key_id, f"{provider} key", provider, connection["id"])
        if base_url:
            db.execute("UPDATE provider_keys SET base_url=? WHERE id=?", (base_url, key_id))
    if secret:
        vault.write(key_id, secret)
    creation.store.save_catalog(key_id, models or [])
    return key_id


def compatible_model(model_id="provider-embedding"):
    return {"id": model_id, "name": "Provider Embedding", "provider": "openai_compatible",
            "capabilities": {"embeddings": None, "embedding": None}}


def test_unknown_compatible_profile_preflight_and_safe_world_rebind(tmp_path):
    vault, embedder = MemoryVault(), RecordingEmbeddings()
    app = create_app(tmp_path, vault=vault, embedder=embedder)
    creation = app.state.creation
    first_key = add_credential(creation, vault, "openai_compatible", secret="", base_url="https://embed.example/v1",
                               models=[compatible_model()])
    second_key = add_credential(creation, vault, "openai_compatible", secret="", base_url="https://embed.example/v1",
                                models=[compatible_model()])

    first = creation.embedding_profiles.save(None, "Primary", first_key, "provider-embedding")
    assert first["dimensions"] is None and not first["usable"]
    first = creation.embedding_profiles.preflight(first["id"])
    assert first["dimensions"] == 4 and first["usable"]
    second = creation.embedding_profiles.save(None, "Replacement", second_key, "provider-embedding")
    second = creation.embedding_profiles.preflight(second["id"])

    world_id = str(uuid4())
    world = creation.worlds.create(world_id, "Bound World")
    profile = creation.embedding_profiles._profile(first["id"])
    credential = creation.embedding_profiles._credential(first_key)
    world["embedding_profile_id"] = first["id"]
    world["embedding_spec"] = creation.embedding_profiles._profile_spec(profile, credential)
    atomic_json(creation.worlds.directory(world_id) / "world.json", world)

    with pytest.raises(CreationConflict, match="used by a World"):
        creation.embedding_profiles.delete(first["id"])
    changed_base = add_credential(creation, vault, "openai_compatible", secret="", base_url="https://other.example/v1",
                                  models=[compatible_model()])
    different = creation.embedding_profiles.save(None, "Different endpoint", changed_base, "provider-embedding")
    different = creation.embedding_profiles.preflight(different["id"])
    with pytest.raises(CreationConflict, match="same provider, model, dimensions, and Base URL"):
        creation.embedding_profiles.rebind_world(world_id, different["id"])

    assert creation.embedding_profiles.rebind_world(world_id, second["id"])["id"] == second["id"]
    rebound_world = creation.worlds.get(world_id)
    assert creation.embedding_profiles.world_profile(rebound_world)["name"] == "Replacement"
    assert creation.embedding_profiles.delete(first["id"]) == {"deleted": True}
    vector = creation.embed_world_query(world_id, "Who is here?", threading.Event())
    assert vector == [1.0, 0.0, 0.0, 0.0]
    assert embedder.calls[-1]["purpose"] == "query"
    assert embedder.calls[-1]["credential"]["base_url"] == "https://embed.example/v1"
    assert embedder.calls[-1]["secret"] == ""


def test_pending_world_details_show_its_selected_embedding_profile(tmp_path):
    vault = MemoryVault()
    app = create_app(tmp_path, vault=vault)
    creation = app.state.creation
    key_id = add_credential(creation, vault, "google", models=[{
        "id": "gemini-embedding-2", "name": "Gemini Embedding 2", "provider": "google",
        "capabilities": {"embeddings": True, "embedding": {
            "dimensions": [3072], "max_dimensions": 3072, "input_limit": 8192,
        }},
    }])
    profile = creation.embedding_profiles.save(None, "Real", key_id, "gemini-embedding-2")
    _, spec = creation.embedding_profiles.snapshot(profile["id"])
    world_id = str(uuid4())
    with creation.store.connect() as db:
        creation.store.put(db, {
            "id": world_id, "name": "Pending World", "state": "paused", "revision": 1,
            "books": [], "config": {"size": 8000, "search": 1000}, "key_id": key_id,
            "embedding_profile_id": profile["id"], "embedding_spec": spec,
        })

    with TestClient(app) as client:
        details = client.get(f"/api/worlds/{world_id}").json()
    assert details["embedding_profile"]["id"] == profile["id"]
    assert details["embedding_profile"]["name"] == "Real"
    assert details["embedding_profile"]["worlds"] == [{"id": world_id, "name": "Pending World"}]
    assert details["embedding_profile"]["in_use"] is True
    assert details["embedding_profile"]["pending_count"] == 1
    renamed = creation.embedding_profiles.save(profile["id"], "Renamed", key_id, "gemini-embedding-2")
    assert renamed["name"] == "Renamed"
    with pytest.raises(CreationConflict, match="Only the name can change"):
        creation.embedding_profiles.save(profile["id"], "Renamed", key_id, "gemini-embedding-2", 768)


def test_openai_profile_uses_discovered_model_and_max_dimensions(tmp_path):
    vault, embedder = MemoryVault(), RecordingEmbeddings()
    app = create_app(tmp_path, vault=vault, embedder=embedder)
    creation = app.state.creation
    key_id = add_credential(
        creation, vault, "openai", models=[{
            "id": "text-embedding-3-large", "name": "Text Embedding 3 Large", "provider": "openai",
            "capabilities": {"embeddings": True, "embedding": {
                "dimensions": [3072], "max_dimensions": 3072, "input_limit": 8192,
            }},
        }],
    )
    profile = creation.embedding_profiles.save(None, "OpenAI Default", key_id, "text-embedding-3-large")
    assert profile["dimensions"] == 3072
    assert profile["max_input_tokens"] == 8192
    assert profile["usable"]
    smaller = creation.embedding_profiles.save(None, "OpenAI Smaller", key_id,
                                               "text-embedding-3-large", 1024)
    assert smaller["dimensions"] == 1024
    assert creation.embedding_profiles._profile(smaller["id"])["dimensions"] == 1024
    with pytest.raises(ValueError, match="cannot exceed"):
        creation.embedding_profiles.save(None, "Too Large", key_id, "text-embedding-3-large", 4096)
    with pytest.raises(ValueError, match="discovered model"):
        creation.embedding_profiles.save(None, "Typed Model", key_id, "not-in-the-catalog")


def test_unknown_compatible_custom_dimensions_require_preflight(tmp_path):
    vault, embedder = MemoryVault(), RecordingEmbeddings()
    app = create_app(tmp_path, vault=vault, embedder=embedder)
    creation = app.state.creation
    key_id = add_credential(creation, vault, "openai_compatible", secret="",
                            base_url="https://embed.example/v1", models=[compatible_model()])
    profile = creation.embedding_profiles.save(None, "Custom", key_id, "provider-embedding", 6)
    assert profile["dimensions"] == 6
    assert not profile["usable"]
    checked = creation.embedding_profiles.preflight(profile["id"])
    assert checked["usable"]
    assert embedder.calls[-1]["dimensions"] == 6


def test_existing_768_dimension_world_migrates_and_keeps_query_binding(tmp_path):
    vault, embedder = MemoryVault(), RecordingEmbeddings()
    app = create_app(tmp_path, vault=vault, embedder=embedder)
    creation = app.state.creation
    key_id = add_credential(creation, vault, "google", models=[])
    world_id, book_id = str(uuid4()), str(uuid4())
    modern_profile_id = str(uuid4())
    stamp = "2026-09-26T00:00:00+00:00"
    with creation.store.connect() as db:
        db.execute(
            "INSERT INTO embedding_profiles(id,name,key_id,model,dimensions,max_input_tokens,input_format_version,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,2,?,?)",
            (modern_profile_id, "New format", key_id, "gemini-embedding-2", 768, 8192, stamp, stamp),
        )
    world = creation.worlds.create(world_id, "Old World")
    atomic_json(creation.worlds.directory(world_id) / "world.json", {
        **world, "processing": {"model": "gemini-embedding-2", "size": 8000, "search": 1000},
    })
    with creation.store.connect() as db:
        creation.store.put(db, {
            "id": world_id, "name": "Old World", "state": "complete", "revision": 1,
            "key_id": key_id, "config": {"model": "gemini-embedding-2"}, "books": [],
        })
    chunks = split_text("Old searchable passage")
    creation.store.add_chunks(world_id, book_id, chunks, {}, dimensions=768, model="gemini-embedding-2")
    with creation.store.connect() as db:
        chunk_id = db.execute("SELECT id FROM chunks WHERE world_id=?", (world_id,)).fetchone()["id"]
    creation.store.save_vector(chunk_id, [1.0] + [0.0] * 767, dimensions=768, model="gemini-embedding-2")

    creation.embedding_profiles._migrate_worlds()
    migrated = creation.worlds.get(world_id)
    assert migrated["embedding_spec"]["dimensions"] == 768
    assert migrated["embedding_spec"]["model"] == "gemini-embedding-2"
    assert migrated["embedding_profile_id"] != modern_profile_id
    assert migrated["embedding_spec"]["input_format_version"] == 1
    with pytest.raises(CreationConflict, match="same provider, model, dimensions, and Base URL"):
        creation.embedding_profiles.rebind_world(world_id, modern_profile_id)
    assert creation.embed_world_query(world_id, "Old query", threading.Event()) == [1.0] + [0.0] * 767
    assert embedder.calls[-1]["dimensions"] == 768
    assert embedder.calls[-1]["credential"]["provider"] == "google"
    assert embedder.calls[-1]["text"] == "task: search result | query: Old query"
    assert embedder.calls[-1]["purpose"] == "legacy_query"
