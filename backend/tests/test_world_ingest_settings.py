import asyncio
from types import SimpleNamespace

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


def test_get_reembed_eligibility_allows_pending_new_sources(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "ingest_settings": {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 150,
            "embedding_model": "embed-model",
            "locked_at": "2026-03-20T00:00:00+00:00",
            "last_ingest_settings_at": "2026-03-20T00:00:00+00:00",
        },
        "sources": [
            {
                "source_id": "source-a",
                "display_name": "Book 1",
                "status": "complete",
                "chunk_count": 12,
                "ingested_at": "2026-03-20T00:00:00+00:00",
                "ingest_snapshot": {
                    "vault_filename": "book_1.txt",
                    "file_size": 123,
                    "file_sha256": "abc",
                    "chunk_size_chars": 4000,
                    "chunk_overlap_chars": 150,
                    "embedding_model": "embed-model",
                },
            },
            {
                "source_id": "source-b",
                "display_name": "Book 2",
                "status": "pending",
                "chunk_count": 0,
                "ingested_at": None,
            },
        ],
    }
    audit_summary = {
        "sources": [
            {"source_id": "source-a", "failed_records": 0},
        ]
    }

    monkeypatch.setattr(
        ingestion_engine,
        "_build_source_ingest_snapshot",
        lambda world_id, source, ingest_settings: dict(source["ingest_snapshot"]) if source.get("source_id") == "source-a" else None,
    )

    eligibility = ingestion_engine.get_reembed_eligibility("world-1", meta=meta, audit_summary=audit_summary)

    assert eligibility["can_reembed_all"] is True
    assert eligibility["ignored_pending_sources_count"] == 1
    assert eligibility["eligible_source_ids"] == ["source-a"]


def test_get_reembed_eligibility_blocks_legacy_world_without_source_snapshots():
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "ingest_settings": {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 150,
            "embedding_model": "embed-model",
            "locked_at": "2026-03-20T00:00:00+00:00",
            "last_ingest_settings_at": "2026-03-20T00:00:00+00:00",
        },
        "sources": [
            {
                "source_id": "source-a",
                "display_name": "Book 1",
                "status": "complete",
                "chunk_count": 12,
                "ingested_at": "2026-03-20T00:00:00+00:00",
            }
        ],
    }
    audit_summary = {
        "sources": [
            {"source_id": "source-a", "failed_records": 0},
        ]
    }

    eligibility = ingestion_engine.get_reembed_eligibility("world-1", meta=meta, audit_summary=audit_summary)

    assert eligibility["can_reembed_all"] is False
    assert eligibility["reason_code"] == "legacy_snapshot_missing"
    assert eligibility["requires_full_rebuild"] is True


def test_get_reembed_eligibility_blocks_when_ingested_source_file_changed(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "ingest_settings": {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 150,
            "embedding_model": "embed-model",
            "locked_at": "2026-03-20T00:00:00+00:00",
            "last_ingest_settings_at": "2026-03-20T00:00:00+00:00",
        },
        "sources": [
            {
                "source_id": "source-a",
                "display_name": "Book 1",
                "status": "complete",
                "chunk_count": 12,
                "ingested_at": "2026-03-20T00:00:00+00:00",
                "ingest_snapshot": {
                    "vault_filename": "book_1.txt",
                    "file_size": 123,
                    "file_sha256": "old-hash",
                    "chunk_size_chars": 4000,
                    "chunk_overlap_chars": 150,
                    "embedding_model": "embed-model",
                },
            }
        ],
    }
    audit_summary = {
        "sources": [
            {"source_id": "source-a", "failed_records": 0},
        ]
    }

    monkeypatch.setattr(
        ingestion_engine,
        "_build_source_ingest_snapshot",
        lambda world_id, source, ingest_settings: {
            "vault_filename": "book_1.txt",
            "file_size": 124,
            "file_sha256": "new-hash",
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 150,
            "embedding_model": "embed-model",
        },
    )

    eligibility = ingestion_engine.get_reembed_eligibility("world-1", meta=meta, audit_summary=audit_summary)

    assert eligibility["can_reembed_all"] is False
    assert eligibility["reason_code"] == "source_changed"
    assert eligibility["requires_full_rebuild"] is True


def test_get_reembed_eligibility_blocks_partially_ingested_source():
    meta = {
        "world_id": "world-1",
        "ingestion_status": "partial_failure",
        "ingest_settings": {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 150,
            "embedding_model": "embed-model",
            "locked_at": "2026-03-20T00:00:00+00:00",
            "last_ingest_settings_at": "2026-03-20T00:00:00+00:00",
        },
        "sources": [
            {
                "source_id": "source-a",
                "display_name": "Book 1",
                "status": "partial_failure",
                "chunk_count": 12,
                "ingested_at": None,
                "failed_chunks": [3],
                "stage_failures": [{"stage": "embedding", "chunk_index": 3}],
                "ingest_snapshot": {
                    "vault_filename": "book_1.txt",
                    "file_size": 123,
                    "file_sha256": "abc",
                    "chunk_size_chars": 4000,
                    "chunk_overlap_chars": 150,
                    "embedding_model": "embed-model",
                },
            }
        ],
    }
    audit_summary = {
        "sources": [
            {"source_id": "source-a", "failed_records": 1},
        ]
    }

    eligibility = ingestion_engine.get_reembed_eligibility("world-1", meta=meta, audit_summary=audit_summary)

    assert eligibility["can_reembed_all"] is False
    assert eligibility["reason_code"] == "source_not_complete"
    assert eligibility["requires_full_rebuild"] is False


def test_reembed_endpoint_rejects_when_chunk_settings_differ_from_locked_settings(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "ingest_settings": {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 150,
            "embedding_model": "embed-model",
            "locked_at": "2026-03-20T00:00:00+00:00",
            "last_ingest_settings_at": "2026-03-20T00:00:00+00:00",
        },
        "sources": [{"source_id": "source-a"}],
    }

    monkeypatch.setattr(ingestion_router, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "recover_stale_ingestion", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "has_active_ingestion_run", lambda world_id: False)
    monkeypatch.setattr(
        ingestion_router,
        "audit_ingestion_integrity",
        lambda world_id, synthesize_failures=True, persist=True: {"sources": [{"source_id": "source-a", "failed_records": 0}], "world": {"failed_records": 0}},
    )
    monkeypatch.setattr(
        ingestion_router,
        "get_reembed_eligibility",
        lambda world_id, meta=None, audit_summary=None: {
            "can_reembed_all": True,
            "reason_code": "ready",
            "message": "Ready",
            "ignored_pending_sources_count": 0,
            "requires_full_rebuild": False,
            "eligible_source_ids": ["source-a"],
            "eligible_sources_count": 1,
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingestion_router.ingest_start(
                "world-1",
                ingestion_router.IngestStartRequest(
                    resume=False,
                    operation="reembed_all",
                    ingest_settings={
                        "chunk_size_chars": 5000,
                        "chunk_overlap_chars": 150,
                        "embedding_model": "new-embed",
                    },
                ),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 400
    assert "locked chunk settings" in exc.value.detail


def test_persist_chunk_graph_artifacts_binds_edges_to_chunk_created_node_ids():
    class RecordingGraphStore:
        def __init__(self):
            self.created_nodes: list[str] = []
            self.edge_calls: list[dict] = []

        def upsert_node(self, node_id: str, display_name: str, description: str, source_chunk_id: str | None = None) -> str:
            created_id = f"uuid-{len(self.created_nodes) + 1}"
            self.created_nodes.append(created_id)
            return created_id

        def upsert_edge(self, **kwargs):
            self.edge_calls.append(kwargs)
            return "edge-1"

        def save(self):
            return None

        def get_node(self, node_id: str):
            return {"id": node_id, "display_name": node_id, "description": ""}

    graph_store = RecordingGraphStore()
    nodes = [
        SimpleNamespace(node_id="2B", display_name="2B", description="YoRHa combat android"),
        SimpleNamespace(node_id="9S", display_name="9S", description="YoRHa scanner android"),
    ]
    edges = [
        SimpleNamespace(source_node_id="2B", target_node_id="9S", description="Partners with", strength=8),
    ]

    node_records = ingestion_engine._persist_chunk_graph_artifacts(
        graph_store,  # type: ignore[arg-type]
        nodes=nodes,
        edges=edges,
        chunk_id="chunk_world-1_source-a_0",
        book_number=1,
        chunk_index=0,
    )

    assert [record["id"] for record in node_records] == ["uuid-1", "uuid-2"]
    assert graph_store.edge_calls == [
        {
            "source_node_id": "uuid-1",
            "target_node_id": "uuid-2",
            "description": "Partners with",
            "strength": 8,
            "source_book": 1,
            "source_chunk": 0,
        }
    ]


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
