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
