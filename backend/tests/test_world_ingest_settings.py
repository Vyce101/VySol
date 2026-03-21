import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

from core import config, entity_text, ingestion_engine
from routers import ingestion as ingestion_router


def test_unlocked_pending_world_uses_current_global_defaults(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: {
            "chunk_size_chars": 20000,
            "chunk_overlap_chars": 150,
            "embedding_model": "global-embed",
        },
    )

    meta = {
        "world_id": "world-1",
        "ingestion_status": "pending",
        "total_chunks": 0,
        "embedding_model": "old-top-level",
        "ingest_settings": {
            "locked_at": None,
            "last_ingest_settings_at": None,
        },
    }

    resolved = config.get_world_ingest_settings(meta=meta)

    assert resolved["chunk_size_chars"] == 20000
    assert resolved["chunk_overlap_chars"] == 150
    assert resolved["embedding_model"] == "global-embed"
    assert resolved["locked_at"] is None


def test_locked_world_prefers_saved_ingest_settings(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: {
            "chunk_size_chars": 20000,
            "chunk_overlap_chars": 150,
            "embedding_model": "global-embed",
        },
    )

    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "total_chunks": 88,
        "embedding_model": "legacy-top-level",
        "ingest_settings": {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 200,
            "embedding_model": "world-embed",
            "locked_at": "2026-03-20T01:00:00+00:00",
            "last_ingest_settings_at": "2026-03-20T01:00:00+00:00",
        },
    }

    resolved = config.get_world_ingest_settings(meta=meta)

    assert resolved["chunk_size_chars"] == 4000
    assert resolved["chunk_overlap_chars"] == 200
    assert resolved["embedding_model"] == "world-embed"
    assert resolved["locked_at"] == "2026-03-20T01:00:00+00:00"


def test_prepare_source_for_reembed_keeps_extraction_and_clears_embedding_state():
    source = {
        "status": "partial_failure",
        "chunk_count": 3,
        "failed_chunks": [2],
        "stage_failures": [
            {"stage": "embedding", "chunk_index": 2},
            {"stage": "extraction", "chunk_index": 1},
        ],
        "extracted_chunks": [0, 1, 2],
        "embedded_chunks": [0],
    }

    ingestion_engine._prepare_source_for_reembed(source)

    assert source["status"] == "ingesting"
    assert source["extracted_chunks"] == [0, 1, 2]
    assert source["embedded_chunks"] == []
    assert source["stage_failures"] == [{"stage": "extraction", "chunk_index": 1}]
    assert source["failed_chunks"] == [1]


def test_reembed_endpoint_rejects_when_extraction_is_incomplete(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "sources": [{"source_id": "source-a"}],
    }

    monkeypatch.setattr(ingestion_router, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "recover_stale_ingestion", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "has_active_ingestion_run", lambda world_id: False)
    monkeypatch.setattr(
        ingestion_router,
        "audit_ingestion_integrity",
        lambda world_id, synthesize_failures=True, persist=True: {
            "sources": [{"missing_extraction_chunks": [1]}],
            "world": {"failed_records": 1},
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingestion_router.ingest_start(
                "world-1",
                ingestion_router.IngestStartRequest(
                    resume=False,
                    operation="reembed_all",
                    ingest_settings={"embedding_model": "new-embed"},
                ),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 400
    assert "Cannot re-embed while extraction coverage is incomplete" in exc.value.detail


def test_unique_node_document_uses_display_name_and_description_only():
    text = entity_text.build_unique_node_document(
        {
            "id": "node-1",
            "display_name": "2B",
            "description": "YoRHa combat android",
            "claims": [
                {"text": "Carries a sword."},
                {"text": "Carries a sword."},
                {"text": "Travels with 9S."},
            ],
        }
    )

    assert text == "2B\n\nYoRHa combat android"


def test_upsert_unique_node_vectors_batches_node_embeddings():
    class DummyNodeVectorStore:
        def __init__(self):
            self.embed_calls: list[dict] = []
            self.upsert_calls: list[dict] = []

        def embed_texts(self, texts: list[str], api_key: str):
            self.embed_calls.append({"texts": texts, "api_key": api_key})
            return [[float(index)] for index, _ in enumerate(texts, start=1)]

        def upsert_documents_embeddings(self, *, document_ids: list[str], texts: list[str], metadatas: list[dict], embeddings: list[list[float]]):
            self.upsert_calls.append(
                {
                    "document_ids": document_ids,
                    "texts": texts,
                    "metadatas": metadatas,
                    "embeddings": embeddings,
                }
            )

    node_store = DummyNodeVectorStore()
    records = [
        {
            "id": "node-a",
            "display_name": "2B",
            "normalized_id": "2b",
            "description": "YoRHa combat android",
            "claims": [{"text": "Protects 9S."}],
        },
        {
            "id": "node-b",
            "display_name": "9S",
            "normalized_id": "9s",
            "description": "YoRHa scanner android",
            "claims": [{"text": "Studies machine lifeforms."}],
        },
    ]

    embedded_count = asyncio.run(
        ingestion_engine._upsert_unique_node_vectors(
            unique_node_vector_store=node_store,  # type: ignore[arg-type]
            node_records=records,
            api_key="test-key",
        )
    )

    assert embedded_count == 2
    assert len(node_store.embed_calls) == 1
    assert len(node_store.upsert_calls) == 1
    assert node_store.upsert_calls[0]["document_ids"] == [
        "node-a",
        "node-b",
    ]
    assert node_store.upsert_calls[0]["texts"][0] == "2B\n\nYoRHa combat android"
    assert node_store.upsert_calls[0]["texts"][1] == "9S\n\nYoRHa scanner android"
