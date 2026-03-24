from types import SimpleNamespace

import pytest

from core import vector_store


class DummyCollection:
    def __init__(self, *, query_error: Exception | None = None, name: str = "dummy", registry: dict[str, "DummyCollection"] | None = None):
        self.query_error = query_error
        self.name = name
        self._registry = registry
        self.upserts: list[dict] = []
        self.records: dict[str, dict] = {}

    def upsert(self, *, ids, embeddings, documents, metadatas):
        self.upserts.append(
            {
                "ids": ids,
                "embeddings": embeddings,
                "documents": documents,
                "metadatas": metadatas,
            }
        )
        for idx, record_id in enumerate(ids):
            self.records[str(record_id)] = {
                "document": documents[idx],
                "metadata": metadatas[idx],
            }

    def query(self, **kwargs):
        if self.query_error:
            raise self.query_error
        ids = list(self.records.keys())[: kwargs["n_results"]]
        return {
            "ids": [ids],
            "documents": [[self.records[record_id]["document"] for record_id in ids]],
            "metadatas": [[self.records[record_id]["metadata"] for record_id in ids]],
            "distances": [[0.0 for _ in ids]],
        }

    def count(self):
        return len(self.records)

    def get(self, ids=None, include=None):
        target_ids = ids or list(self.records.keys())
        return {
            "ids": list(target_ids),
            "documents": [self.records.get(str(record_id), {}).get("document", "") for record_id in target_ids],
            "metadatas": [self.records.get(str(record_id), {}).get("metadata", {}) for record_id in target_ids],
        }

    def modify(self, *, name=None, metadata=None, configuration=None):
        if name and self._registry is not None and name != self.name:
            self._registry[name] = self._registry.pop(self.name)
            self.name = name


class DummyClient:
    def __init__(self, path: str, collection: DummyCollection):
        self.path = path
        self._collections: dict[str, DummyCollection] = {}
        self._fallback_collection = collection
        self.deleted: list[str] = []

    def get_or_create_collection(self, name: str):
        if name in self._collections:
            return self._collections[name]
        if not self._collections:
            collection = self._fallback_collection
            collection.name = name
            collection._registry = self._collections
            self._collections[name] = collection
            return collection
        collection = DummyCollection(name=name, registry=self._collections)
        self._collections[name] = collection
        return collection

    def delete_collection(self, name: str):
        self.deleted.append(name)
        self._collections.pop(name, None)


def _patch_vector_dependencies(monkeypatch, *, collection: DummyCollection, embedding_model: str = "gemini-embedding-001", world_dir=None):
    client = DummyClient("dummy-path", collection)
    monkeypatch.setattr(
        vector_store.chromadb,
        "PersistentClient",
        lambda path: client,
    )
    monkeypatch.setattr(vector_store, "get_world_embedding_model", lambda world_id: embedding_model)
    monkeypatch.setattr(vector_store, "load_settings", lambda: {"embedding_model": embedding_model})
    monkeypatch.setattr(vector_store, "set_world_embedding_model", lambda world_id, model: None)
    if world_dir is not None:
        monkeypatch.setattr(vector_store, "world_chroma_dir", lambda world_id: world_dir)


def test_vector_store_prefers_world_embedding_model(monkeypatch):
    captured: dict[str, str] = {}
    collection = DummyCollection()

    class DummyModels:
        def embed_content(self, *, model: str, contents: str):
            captured["model"] = model
            captured["content"] = contents
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])])

    class DummyGenAIClient:
        def __init__(self, api_key: str):
            self.models = DummyModels()

    _patch_vector_dependencies(monkeypatch, collection=collection, embedding_model="models/text-embedding-004")
    monkeypatch.setattr(vector_store.genai, "Client", DummyGenAIClient)

    store = vector_store.VectorStore("world-123")
    embedding = store.embed_text("hello world", api_key="test-key")

    assert embedding == [0.1, 0.2, 0.3]
    assert captured["model"] == "models/text-embedding-004"
    assert captured["content"] == "hello world"


def test_vector_store_embed_texts_batches_multiple_contents(monkeypatch):
    captured: dict[str, object] = {}
    collection = DummyCollection()

    class DummyModels:
        def embed_content(self, *, model: str, contents):
            captured["model"] = model
            captured["contents"] = contents
            return SimpleNamespace(
                embeddings=[
                    SimpleNamespace(values=[0.1, 0.2]),
                    SimpleNamespace(values=[0.3, 0.4]),
                ]
            )

    class DummyGenAIClient:
        def __init__(self, api_key: str):
            self.models = DummyModels()

    _patch_vector_dependencies(monkeypatch, collection=collection, embedding_model="gemini-embedding-001")
    monkeypatch.setattr(vector_store.genai, "Client", DummyGenAIClient)

    store = vector_store.VectorStore("world-123")
    embeddings = store.embed_texts(["first", "second"], api_key="test-key")

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["model"] == "gemini-embedding-001"
    assert captured["contents"] == ["first", "second"]


def test_vector_store_embed_texts_retries_timeout_on_next_key(monkeypatch):
    collection = DummyCollection()
    calls: list[str] = []

    class DummyKM:
        api_keys = ["k1", "k2"]
        key_count = 2

        def __init__(self):
            self.reported: list[tuple[int, str]] = []

        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
            return ("k2", 1)

        def report_error(self, key_index: int, error_type: str) -> None:
            self.reported.append((key_index, error_type))

    class DummyModels:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def embed_content(self, *, model: str, contents):
            calls.append(self.api_key)
            if self.api_key == "k1":
                raise RuntimeError("request timed out")
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.7, 0.8, 0.9])])

    class DummyGenAIClient:
        def __init__(self, api_key: str):
            self.models = DummyModels(api_key)

    dummy_km = DummyKM()

    _patch_vector_dependencies(monkeypatch, collection=collection, embedding_model="gemini-embedding-001")
    monkeypatch.setattr(vector_store.genai, "Client", DummyGenAIClient)
    monkeypatch.setattr(vector_store, "get_key_manager", lambda: dummy_km)
    monkeypatch.setattr(vector_store.time, "sleep", lambda seconds: None)

    store = vector_store.VectorStore("world-123")
    embedding = store.embed_text("hello world", api_key="k1")

    assert embedding == [0.7, 0.8, 0.9]
    assert calls == ["k1", "k2"]
    assert dummy_km.reported == [(0, "timeout")]


def test_vector_store_query_blocks_when_manifest_model_is_stale(monkeypatch):
    collection = DummyCollection()
    manifest = {"collections": {}}

    class DummyModels:
        def embed_content(self, *, model: str, contents: str):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.4, 0.5, 0.6])])

    class DummyGenAIClient:
        def __init__(self, api_key: str):
            self.models = DummyModels()

    _patch_vector_dependencies(monkeypatch, collection=collection, embedding_model="new-model")
    monkeypatch.setattr(vector_store.genai, "Client", DummyGenAIClient)
    monkeypatch.setattr(vector_store.VectorStore, "_load_manifest", lambda self: manifest)
    monkeypatch.setattr(vector_store.VectorStore, "_save_manifest", lambda self, data: manifest.update(data))

    store = vector_store.VectorStore("world-123", collection_suffix="nodes")
    store.collection.records["node-1"] = {"document": "Node doc", "metadata": {}}
    store._set_recorded_embedding_model("old-model")

    with pytest.raises(RuntimeError) as exc:
        store.query_by_embedding([0.1, 0.2, 0.3], n_results=1)

    assert "different embedding model" in str(exc.value)


def test_vector_store_query_dimension_mismatch_requires_rebuild(monkeypatch):
    collection = DummyCollection(query_error=RuntimeError("dimension mismatch"))
    manifest = {"collections": {}}

    class DummyModels:
        def embed_content(self, *, model: str, contents: str):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.9, 0.8, 0.7])])

    class DummyGenAIClient:
        def __init__(self, api_key: str):
            self.models = DummyModels()

    _patch_vector_dependencies(monkeypatch, collection=collection, embedding_model="gemini-embedding-001")
    monkeypatch.setattr(vector_store.genai, "Client", DummyGenAIClient)
    monkeypatch.setattr(vector_store.VectorStore, "_load_manifest", lambda self: manifest)
    monkeypatch.setattr(vector_store.VectorStore, "_save_manifest", lambda self, data: manifest.update(data))

    store = vector_store.VectorStore("world-xyz", collection_suffix="nodes")
    store.collection.records["node-1"] = {"document": "Node doc", "metadata": {}}
    store._set_recorded_embedding_model("gemini-embedding-001")

    with pytest.raises(RuntimeError) as exc:
        store.query_by_embedding([0.9, 0.8, 0.7], n_results=1)

    assert "Re-embed All or Rechunk And Re-ingest" in str(exc.value)


def test_vector_store_swap_staged_collection_replaces_live_name(monkeypatch):
    collection = DummyCollection()
    _patch_vector_dependencies(monkeypatch, collection=collection, embedding_model="gemini-embedding-001")

    manifest = {"collections": {}}
    monkeypatch.setattr(vector_store.VectorStore, "_load_manifest", lambda self: manifest)
    monkeypatch.setattr(vector_store.VectorStore, "_save_manifest", lambda self, data: manifest.update(data))

    store = vector_store.VectorStore("world-123", collection_suffix="unique_nodes")
    store.collection.records["old-node"] = {"document": "old", "metadata": {}}

    staged = store.create_staging_store()
    staged.collection.records["new-node"] = {"document": "new", "metadata": {}}

    store.swap_staged_collection(staged)

    assert store.collection_name == "world_world_123_unique_nodes"
    assert store.collection.records == {"new-node": {"document": "new", "metadata": {}}}
    assert manifest["collections"]["unique_nodes"]["collection_name"] == "world_world_123_unique_nodes"
