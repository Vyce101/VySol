import asyncio
import threading
import time

import pytest
from fastapi import BackgroundTasks, HTTPException

from core import ingestion_engine
from routers import ingestion as ingestion_router


class DummyGraph:
    def __init__(self, chunk_ids: list[str]):
        self._chunk_ids = chunk_ids

    def nodes(self, data=False):
        rows = [
            (
                f"n{i}",
                {
                    "source_chunks": [chunk_id],
                    "display_name": f"Node {i}",
                    "normalized_id": f"node-{i}",
                },
            )
            for i, chunk_id in enumerate(self._chunk_ids)
        ]
        if data:
            return rows
        return [row[0] for row in rows]


class DummyGraphStore:
    def __init__(self, world_id: str, chunk_ids: list[str]):
        self.world_id = world_id
        self.graph = DummyGraph(chunk_ids)

    def get_node_count(self) -> int:
        return len(self.graph.nodes())

    def get_edge_count(self) -> int:
        return max(0, len(self.graph.nodes()) - 1)


class DummyVectorStore:
    def __init__(self, world_id: str, records: list[dict], *, collection_suffix: str = ""):
        self.world_id = world_id
        self._records = records
        self.collection_suffix = collection_suffix

    def get_all_chunk_records(self):
        return list(self._records)

    def count(self) -> int:
        return len(self._records)


class RecordingNodeVectorStore:
    def __init__(self):
        self.upsert_batch_sizes: list[int] = []
        self.upsert_document_ids: list[str] = []

    def upsert_documents_embeddings(self, *, document_ids, texts, metadatas, embeddings):
        self.upsert_batch_sizes.append(len(document_ids))
        self.upsert_document_ids.extend(document_ids)


def _build_node_vector_records(graph_chunk_ids: list[str], vector_records: list[dict]) -> list[dict]:
    chunk_to_node = {chunk_id: f"n{index}" for index, chunk_id in enumerate(graph_chunk_ids)}
    node_records: list[dict] = []
    for record in vector_records:
        chunk_id = str(record.get("id", ""))
        node_id = chunk_to_node.get(chunk_id)
        if not node_id:
            continue
        node_records.append(
            {
                "id": node_id,
                "metadata": {
                    "node_id": node_id,
                },
            }
        )
    return node_records


def _patch_audit_dependencies(monkeypatch, meta, *, graph_chunk_ids: list[str], vector_records: list[dict], saved=None):
    if saved is None:
        saved = {}
    node_vector_records = _build_node_vector_records(graph_chunk_ids, vector_records)
    monkeypatch.setattr(ingestion_engine, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_engine, "_save_meta", lambda world_id, payload: saved.setdefault("meta", payload))
    monkeypatch.setattr(ingestion_engine, "GraphStore", lambda world_id: DummyGraphStore(world_id, graph_chunk_ids))
    monkeypatch.setattr(
        ingestion_engine,
        "VectorStore",
        lambda world_id, collection_suffix="", **kwargs: DummyVectorStore(
            world_id,
            node_vector_records if collection_suffix == "unique_nodes" else vector_records,
            collection_suffix=collection_suffix,
        ),
    )
    return saved


def _patch_meta_store(monkeypatch, meta: dict):
    holder = {"meta": meta}

    def load_meta(world_id: str):
        return holder["meta"]

    def save_meta(world_id: str, payload: dict):
        holder["meta"] = payload

    monkeypatch.setattr(ingestion_engine, "_load_meta", load_meta)
    monkeypatch.setattr(ingestion_engine, "_save_meta", save_meta)
    monkeypatch.setattr(ingestion_engine, "_active_runs", {})
    monkeypatch.setattr(ingestion_engine, "_abort_events", {})
    monkeypatch.setattr(ingestion_engine, "_sse_queues", {})
    monkeypatch.setattr(ingestion_engine, "_sse_locks", {})
    return holder


def test_audit_synthesizes_stage_failures_from_coverage_gaps(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "complete",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [],
                "embedded_chunks": [],
            }
        ],
    }
    saved = {}

    _patch_audit_dependencies(
        monkeypatch,
        meta,
        saved=saved,
        graph_chunk_ids=[
            "chunk_world-1_source-a_0",
            "chunk_world-1_source-a_1",
        ],
        vector_records=[
            {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
        ],
    )

    summary = ingestion_engine.audit_ingestion_integrity("world-1", synthesize_failures=True, persist=True)

    assert summary["world"]["expected_chunks"] == 3
    assert summary["world"]["extracted_chunks"] == 2
    assert summary["world"]["embedded_chunks"] == 1
    assert summary["world"]["current_unique_nodes"] == 2
    assert summary["world"]["embedded_unique_nodes"] == 1
    assert summary["world"]["failed_records"] == 4
    assert summary["world"]["synthesized_failures"] == 4

    source = saved["meta"]["sources"][0]
    assert source["status"] == "partial_failure"
    assert source["failed_chunks"] == [1, 2]
    stages = {
        (row["stage"], row["chunk_index"], row.get("scope", "chunk"))
        for row in source["stage_failures"]
    }
    assert ("extraction", 2, "chunk") in stages
    assert ("embedding", 1, "chunk") in stages
    assert ("embedding", 1, "node") in stages
    assert ("embedding", 2, "chunk") in stages


def test_audit_clears_out_of_range_failures_when_current_coverage_is_complete(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "partial_failure",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "partial_failure",
                "failed_chunks": [79],
                "stage_failures": [
                    {"stage": "embedding", "chunk_index": 79, "chunk_id": "chunk_world-1_source-a_79"},
                ],
                "extracted_chunks": [0, 1, 2],
                "embedded_chunks": [0, 1, 2],
            }
        ],
    }
    saved = _patch_audit_dependencies(
        monkeypatch,
        meta,
        graph_chunk_ids=[
            "chunk_world-1_source-a_0",
            "chunk_world-1_source-a_1",
            "chunk_world-1_source-a_2",
        ],
        vector_records=[
            {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
            {"id": "chunk_world-1_source-a_1", "metadata": {"source_id": "source-a", "chunk_index": 1}},
            {"id": "chunk_world-1_source-a_2", "metadata": {"source_id": "source-a", "chunk_index": 2}},
        ],
    )

    summary = ingestion_engine.audit_ingestion_integrity("world-1", synthesize_failures=True, persist=True)

    assert summary["world"]["failed_records"] == 0
    assert summary["world"]["embedded_chunks"] == 3

    source = saved["meta"]["sources"][0]
    assert source["status"] == "complete"
    assert source["failed_chunks"] == []
    assert source["stage_failures"] == []


def test_audit_reports_orphan_graph_nodes_without_blocking_full_coverage(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "complete",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 1,
                "status": "complete",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0],
                "embedded_chunks": [0],
            }
        ],
    }
    saved = {}

    class AuditGraph:
        def nodes(self, data=False):
            rows = [
                (
                    "n0",
                    {
                        "source_chunks": ["chunk_world-1_source-a_0"],
                        "display_name": "Tracked Node",
                        "normalized_id": "tracked-node",
                    },
                ),
                (
                    "orphan",
                    {
                        "source_chunks": [],
                        "display_name": "Orphan Node",
                        "normalized_id": "orphan-node",
                    },
                ),
            ]
            if data:
                return rows
            return [row[0] for row in rows]

        def edges(self, data=False):
            return []

    class AuditGraphStore:
        def __init__(self, world_id: str):
            self.world_id = world_id
            self.graph = AuditGraph()

        def get_node_count(self) -> int:
            return 2

        def get_edge_count(self) -> int:
            return 0

    class AuditVectorStore:
        def __init__(self, world_id: str, records: list[dict]):
            self.world_id = world_id
            self._records = records

        def get_all_chunk_records(self):
            return list(self._records)

    chunk_records = [
        {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
    ]
    node_records = [
        {
            "id": "n0",
            "metadata": {"node_id": "n0"},
        },
        {
            "id": "orphan",
            "metadata": {"node_id": "orphan"},
        },
    ]

    monkeypatch.setattr(ingestion_engine, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_engine, "_save_meta", lambda world_id, payload: saved.setdefault("meta", payload))
    monkeypatch.setattr(ingestion_engine, "GraphStore", lambda world_id: AuditGraphStore(world_id))
    monkeypatch.setattr(
        ingestion_engine,
        "VectorStore",
        lambda world_id, collection_suffix="", **kwargs: AuditVectorStore(
            world_id,
            node_records if collection_suffix == "unique_nodes" else chunk_records,
        ),
    )

    summary = ingestion_engine.audit_ingestion_integrity("world-1", synthesize_failures=True, persist=True)

    assert summary["world"]["orphan_graph_nodes"] == 1
    assert summary["world"]["failed_records"] == 0
    assert summary["blocking_issues"] == []
    assert saved["meta"]["ingestion_status"] == "complete"


def test_build_chunk_plan_respects_stage_retry_modes():
    source = {
        "source_id": "source-a",
        "failed_chunks": [],
        "stage_failures": [
            {"stage": "embedding", "chunk_index": 2},
            {"stage": "extraction", "chunk_index": 1},
        ],
    }

    embedding_only = ingestion_engine._build_chunk_plan(
        "world-1",
        source,
        chunks_total=5,
        resume=True,
        retry_only=True,
        retry_stage="embedding",
        checkpoint=None,
    )
    assert embedding_only == {2: "embedding_only"}

    all_modes = ingestion_engine._build_chunk_plan(
        "world-1",
        source,
        chunks_total=5,
        resume=True,
        retry_only=False,
        retry_stage="all",
        checkpoint={"source_id": "source-a", "last_completed_chunk_index": 3},
    )
    assert all_modes[1] == "full_cleanup"
    assert all_modes[2] == "embedding_only"
    assert all_modes[4] == "full"


def test_checkpoint_ignores_stale_failures_after_audit(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "partial_failure",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "partial_failure",
                "failed_chunks": [79],
                "stage_failures": [
                    {"stage": "embedding", "chunk_index": 79, "chunk_id": "chunk_world-1_source-a_79"},
                ],
                "extracted_chunks": [0, 1, 2],
                "embedded_chunks": [0, 1, 2],
            }
        ],
    }
    _patch_audit_dependencies(
        monkeypatch,
        meta,
        graph_chunk_ids=[
            "chunk_world-1_source-a_0",
            "chunk_world-1_source-a_1",
            "chunk_world-1_source-a_2",
        ],
        vector_records=[
            {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
            {"id": "chunk_world-1_source-a_1", "metadata": {"source_id": "source-a", "chunk_index": 1}},
            {"id": "chunk_world-1_source-a_2", "metadata": {"source_id": "source-a", "chunk_index": 2}},
        ],
    )
    monkeypatch.setattr(ingestion_engine, "_load_checkpoint", lambda world_id: {
        "source_id": "source-a",
        "last_completed_chunk_index": 79,
        "chunks_total": 80,
    })

    checkpoint = ingestion_engine.get_checkpoint_info("world-1")

    assert checkpoint["can_resume"] is False
    assert checkpoint["chunk_index"] == 0
    assert checkpoint["chunks_total"] == 0
    assert checkpoint["failures"] == []
    assert checkpoint["stage_counters"]["failed_records"] == 0


def test_retry_endpoint_rejects_when_only_stale_failures_exist(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "partial_failure",
        "sources": [
            {
                "source_id": "source-a",
                "status": "partial_failure",
                "failed_chunks": [79],
                "stage_failures": [
                    {"stage": "embedding", "chunk_index": 79, "chunk_id": "chunk_world-1_source-a_79"},
                ],
            }
        ],
    }

    def fake_audit(world_id: str, synthesize_failures: bool = True, persist: bool = True):
        meta["sources"][0]["status"] = "complete"
        meta["sources"][0]["failed_chunks"] = []
        meta["sources"][0]["stage_failures"] = []
        return {"world": {"failed_records": 0}, "failures": []}

    monkeypatch.setattr(ingestion_router, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "recover_stale_ingestion", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "has_active_ingestion_run", lambda world_id: False)
    monkeypatch.setattr(ingestion_router, "audit_ingestion_integrity", fake_audit)
    monkeypatch.setattr(ingestion_router, "list_safety_reviews", lambda world_id: [])

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingestion_router.ingest_retry(
                "world-1",
                ingestion_router.IngestRetryRequest(stage="all"),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "No retryable failures for the requested stage."


def test_recover_stale_ingestion_marks_partial_failure_when_embeddings_are_missing(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_updated_at": "2026-03-20T00:00:00+00:00",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [],
                "embedded_chunks": [],
            }
        ],
    }
    holder = _patch_meta_store(monkeypatch, meta)
    graph_chunk_ids = [
        "chunk_world-1_source-a_0",
        "chunk_world-1_source-a_1",
        "chunk_world-1_source-a_2",
    ]
    chunk_records = [
        {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
    ]
    node_records = _build_node_vector_records(graph_chunk_ids, chunk_records)
    monkeypatch.setattr(ingestion_engine, "GraphStore", lambda world_id: DummyGraphStore(world_id, graph_chunk_ids))
    monkeypatch.setattr(
        ingestion_engine,
        "VectorStore",
        lambda world_id, collection_suffix="", **kwargs: DummyVectorStore(
            world_id,
            node_records if collection_suffix == "unique_nodes" else chunk_records,
            collection_suffix=collection_suffix,
        ),
    )

    recovered = ingestion_engine.recover_stale_ingestion("world-1")

    assert recovered["ingestion_status"] == "partial_failure"
    assert recovered.get("ingestion_recovered_at")
    source = holder["meta"]["sources"][0]
    assert source["status"] == "partial_failure"
    stages = {(row["stage"], row["chunk_index"]) for row in source["stage_failures"]}
    assert ("embedding", 1) in stages
    assert ("embedding", 2) in stages


def test_recover_stale_ingestion_marks_complete_when_coverage_is_full(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_updated_at": "2026-03-20T00:00:00+00:00",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 2,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [],
                "embedded_chunks": [],
            }
        ],
    }
    _patch_meta_store(monkeypatch, meta)
    graph_chunk_ids = [
        "chunk_world-1_source-a_0",
        "chunk_world-1_source-a_1",
    ]
    chunk_records = [
        {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
        {"id": "chunk_world-1_source-a_1", "metadata": {"source_id": "source-a", "chunk_index": 1}},
    ]
    node_records = _build_node_vector_records(graph_chunk_ids, chunk_records)
    monkeypatch.setattr(ingestion_engine, "GraphStore", lambda world_id: DummyGraphStore(world_id, graph_chunk_ids))
    monkeypatch.setattr(
        ingestion_engine,
        "VectorStore",
        lambda world_id, collection_suffix="", **kwargs: DummyVectorStore(
            world_id,
            node_records if collection_suffix == "unique_nodes" else chunk_records,
            collection_suffix=collection_suffix,
        ),
    )

    recovered = ingestion_engine.recover_stale_ingestion("world-1")

    assert recovered["ingestion_status"] == "complete"


def test_checkpoint_recovers_stale_in_progress_world_into_resumable_state(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_updated_at": "2026-03-20T00:00:00+00:00",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [],
                "embedded_chunks": [],
            }
        ],
    }
    _patch_meta_store(monkeypatch, meta)
    graph_chunk_ids = [
        "chunk_world-1_source-a_0",
        "chunk_world-1_source-a_1",
        "chunk_world-1_source-a_2",
    ]
    chunk_records = [
        {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
    ]
    node_records = _build_node_vector_records(graph_chunk_ids, chunk_records)
    monkeypatch.setattr(ingestion_engine, "GraphStore", lambda world_id: DummyGraphStore(world_id, graph_chunk_ids))
    monkeypatch.setattr(
        ingestion_engine,
        "VectorStore",
        lambda world_id, collection_suffix="", **kwargs: DummyVectorStore(
            world_id,
            node_records if collection_suffix == "unique_nodes" else chunk_records,
            collection_suffix=collection_suffix,
        ),
    )
    monkeypatch.setattr(ingestion_engine, "_load_checkpoint", lambda world_id: {
        "source_id": "source-a",
        "last_completed_chunk_index": 0,
        "chunks_total": 3,
    })

    checkpoint = ingestion_engine.get_checkpoint_info("world-1")

    assert checkpoint["can_resume"] is True
    assert checkpoint["chunk_index"] == 1
    assert checkpoint["chunks_total"] == 3
    assert checkpoint["active_ingestion_run"] is False
    assert checkpoint["stage_counters"]["failed_records"] == 4


def test_start_endpoint_allows_stale_in_progress_world_once_recovered(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_updated_at": "2026-03-20T00:00:00+00:00",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 2,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [],
                "embedded_chunks": [],
            }
        ],
    }
    _patch_meta_store(monkeypatch, meta)
    monkeypatch.setattr(ingestion_router, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "recover_stale_ingestion", lambda world_id: {
        **meta,
        "ingestion_status": "partial_failure",
    })
    monkeypatch.setattr(ingestion_router, "has_active_ingestion_run", lambda world_id: False)

    result = asyncio.run(
        ingestion_router.ingest_start(
            "world-1",
            ingestion_router.IngestStartRequest(resume=False),
            BackgroundTasks(),
        )
    )

    assert result["status"] == "accepted"


def test_start_endpoint_still_rejects_true_live_run(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "sources": [],
    }
    monkeypatch.setattr(ingestion_router, "recover_stale_ingestion", lambda world_id: meta)
    monkeypatch.setattr(ingestion_router, "has_active_ingestion_run", lambda world_id: True)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            ingestion_router.ingest_start(
                "world-1",
                ingestion_router.IngestStartRequest(resume=False),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Ingestion already in progress."


def test_abort_ingestion_persists_terminal_state_for_stale_run(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_updated_at": "2026-03-20T00:00:00+00:00",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [],
                "embedded_chunks": [],
            }
        ],
    }
    holder = _patch_meta_store(monkeypatch, meta)
    graph_chunk_ids = [
        "chunk_world-1_source-a_0",
        "chunk_world-1_source-a_1",
        "chunk_world-1_source-a_2",
    ]
    chunk_records = [
        {"id": "chunk_world-1_source-a_0", "metadata": {"source_id": "source-a", "chunk_index": 0}},
    ]
    node_records = _build_node_vector_records(graph_chunk_ids, chunk_records)
    monkeypatch.setattr(ingestion_engine, "GraphStore", lambda world_id: DummyGraphStore(world_id, graph_chunk_ids))
    monkeypatch.setattr(
        ingestion_engine,
        "VectorStore",
        lambda world_id, collection_suffix="", **kwargs: DummyVectorStore(
            world_id,
            node_records if collection_suffix == "unique_nodes" else chunk_records,
            collection_suffix=collection_suffix,
        ),
    )

    ingestion_engine.abort_ingestion("world-1")

    assert holder["meta"]["ingestion_status"] == "aborted"
    events = ingestion_engine.drain_sse_events("world-1")
    assert events[-1]["event"] == "aborted"


def test_active_checkpoint_reports_embedding_phase_progress_for_reembed_all(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_operation": "reembed_all",
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0, 1, 2],
                "embedded_chunks": [],
            }
        ],
    }
    holder = _patch_meta_store(monkeypatch, meta)
    monkeypatch.setattr(ingestion_engine, "_active_runs", {"world-1": object()})
    monkeypatch.setattr(
        ingestion_engine,
        "audit_ingestion_integrity",
        lambda world_id, synthesize_failures=False, persist=True: {"world": {"embedded_chunks": 0}, "failures": []},
    )
    monkeypatch.setattr(ingestion_engine, "_load_checkpoint", lambda world_id: None)

    checkpoint = ingestion_engine.get_checkpoint_info("world-1")

    assert holder["meta"]["ingestion_status"] == "in_progress"
    assert checkpoint["active_ingestion_run"] is True
    assert checkpoint["progress_phase"] == "embedding"
    assert checkpoint["completed_chunks_current_phase"] == 0
    assert checkpoint["total_chunks_current_phase"] == 3
    assert checkpoint["chunk_index"] == 0
    assert checkpoint["chunks_total"] == 3


def test_build_progress_event_includes_live_stage_counters_and_progress_source(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_operation": "default",
        "total_nodes": 8,
        "embedded_unique_nodes": 5,
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 3,
                "status": "complete",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0, 1, 2],
                "embedded_chunks": [0, 1, 2],
            },
            {
                "source_id": "source-b",
                "book_number": 2,
                "display_name": "Book 2",
                "chunk_count": 4,
                "status": "ingesting",
                "failed_chunks": [2],
                "stage_failures": [
                    {
                        "stage": "embedding",
                        "chunk_index": 2,
                        "chunk_id": "chunk_world-1_source-b_2",
                        "error_type": "provider_error",
                    }
                ],
                "extracted_chunks": [0, 1, 3],
                "embedded_chunks": [0, 1],
            },
        ],
    }
    monkeypatch.setattr(ingestion_engine, "_active_runs", {"world-1": object()})

    event = ingestion_engine._build_progress_event("world-1", meta)

    assert event["stage_counters"]["expected_chunks"] == 7
    assert event["stage_counters"]["extracted_chunks"] == 6
    assert event["stage_counters"]["embedded_chunks"] == 5
    assert event["stage_counters"]["current_unique_nodes"] == 8
    assert event["stage_counters"]["embedded_unique_nodes"] == 5
    assert event["stage_counters"]["failed_records"] == 1
    assert event["stage_counters"]["sources_total"] == 2
    assert event["stage_counters"]["sources_complete"] == 1
    assert event["stage_counters"]["sources_partial_failure"] == 0
    assert event["progress_source_id"] == "source-b"
    assert event["progress_source_display_name"] == "Book 2"
    assert event["progress_source_book_number"] == 2


def test_get_checkpoint_info_includes_live_wait_snapshot(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_operation": "default",
        "total_nodes": 6,
        "embedded_unique_nodes": 4,
        "ingestion_wait": {
            "wait_state": "waiting_for_api_key",
            "wait_stage": "embedding",
            "wait_label": "Waiting for API key cooldown",
            "wait_retry_after_seconds": 12.5,
        },
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 4,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0, 1],
                "embedded_chunks": [0],
            }
        ],
    }
    _patch_meta_store(monkeypatch, meta)
    monkeypatch.setattr(ingestion_engine, "_active_runs", {"world-1": object()})
    monkeypatch.setattr(
        ingestion_engine,
        "audit_ingestion_integrity",
        lambda world_id, synthesize_failures=False, persist=True: {
            "world": {
                "expected_chunks": 4,
                "extracted_chunks": 2,
                "embedded_chunks": 1,
                "current_unique_nodes": 6,
                "embedded_unique_nodes": 4,
                "failed_records": 0,
                "sources_total": 1,
                "sources_complete": 0,
                "sources_partial_failure": 0,
            },
            "failures": [],
        },
    )
    monkeypatch.setattr(ingestion_engine, "_load_checkpoint", lambda world_id: None)

    checkpoint = ingestion_engine.get_checkpoint_info("world-1")

    assert checkpoint["stage_counters"]["expected_chunks"] == 4
    assert checkpoint["stage_counters"]["extracted_chunks"] == 2
    assert checkpoint["stage_counters"]["embedded_chunks"] == 1
    assert checkpoint["stage_counters"]["current_unique_nodes"] == 6
    assert checkpoint["stage_counters"]["embedded_unique_nodes"] == 4
    assert checkpoint["wait_state"] == "waiting_for_api_key"
    assert checkpoint["wait_stage"] == "embedding"
    assert checkpoint["wait_label"] == "Waiting for API key cooldown"
    assert checkpoint["wait_retry_after_seconds"] == 12.5
    assert checkpoint["progress_source_id"] == "source-a"
    assert checkpoint["progress_source_display_name"] == "Book 1"
    assert checkpoint["progress_source_book_number"] == 1


def test_abort_ingestion_emits_aborting_for_live_run(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_operation": "reembed_all",
        "ingestion_wait": {
            "wait_state": "waiting_for_api_key",
            "wait_stage": "embedding",
            "wait_label": "Waiting for API key cooldown",
            "wait_retry_after_seconds": 9.0,
        },
        "sources": [
            {
                "source_id": "source-a",
                "book_number": 1,
                "display_name": "Book 1",
                "chunk_count": 2,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0, 1],
                "embedded_chunks": [],
            }
        ],
    }
    holder = _patch_meta_store(monkeypatch, meta)
    live_event = threading.Event()
    monkeypatch.setattr(ingestion_engine, "_abort_events", {"world-1": live_event})
    monkeypatch.setattr(ingestion_engine, "_active_runs", {"world-1": live_event})
    monkeypatch.setattr(ingestion_engine, "_wake_stage_schedulers", lambda: None)

    ingestion_engine.abort_ingestion("world-1")

    assert live_event.is_set() is True
    assert holder["meta"]["ingestion_abort_requested_at"]
    assert "ingestion_wait" not in holder["meta"]
    events = ingestion_engine.drain_sse_events("world-1")
    assert events[-1]["event"] == "aborting"
    assert events[-1]["progress_phase"] == "aborting"
    assert events[-1]["wait_state"] is None


def test_finish_wait_emits_waiting_event_for_long_wait(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "ingestion_operation": "default",
        "ingestion_wait": {
            "wait_state": "waiting_for_api_key",
            "wait_stage": "embedding",
            "wait_label": "Waiting for API key cooldown",
            "wait_retry_after_seconds": 7.0,
        },
        "sources": [],
    }
    holder = _patch_meta_store(monkeypatch, meta)
    monkeypatch.setattr(
        ingestion_engine,
        "_active_waits",
        {
            "world-1": {
                "wait-1": {
                    "wait_state": "waiting_for_api_key",
                    "wait_stage": "embedding",
                    "wait_label": "Waiting for API key cooldown",
                    "wait_retry_after_seconds": 7.0,
                    "source_id": "source-a",
                    "book_number": 2,
                    "chunk_index": 11,
                    "active_agent": "node_embedding",
                    "started_monotonic": time.monotonic() - 3.5,
                }
            }
        },
    )

    asyncio.run(
        ingestion_engine._finish_wait(
            "world-1",
            holder["meta"],
            asyncio.Lock(),
            wait_key="wait-1",
            emit_log=True,
        )
    )

    assert "ingestion_wait" not in holder["meta"]
    events = ingestion_engine.drain_sse_events("world-1")
    assert events[-1]["event"] == "waiting"
    assert events[-1]["wait_state"] == "waiting_for_api_key"
    assert events[-1]["chunk_index"] == 11
    assert events[-1]["wait_duration_seconds"] >= 2.0


def test_stage_scheduler_abort_wakes_waiter_during_cooldown():
    async def scenario():
        scheduler = ingestion_engine._StageScheduler("test")
        owner_event = threading.Event()
        waiter_event = threading.Event()

        await scheduler.configure(concurrency=1, cooldown_seconds=30)
        slot_index = await scheduler.acquire(owner_event)
        await scheduler.release(slot_index)

        waiter_task = asyncio.create_task(scheduler.acquire(waiter_event))
        await asyncio.sleep(0)
        waiter_event.set()
        await scheduler.wake_all()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter_task, timeout=0.5)

    asyncio.run(scenario())


def test_unique_node_vector_upsert_stops_between_batches_when_aborted():
    async def scenario():
        store = RecordingNodeVectorStore()
        node_records = [
            {
                "id": f"node-{index}",
                "display_name": f"Node {index}",
                "normalized_id": f"node-{index}",
            }
            for index in range(10)
        ]
        embeddings = [[float(index)] for index in range(len(node_records))]
        abort_requested = {"value": False}

        def abort_check():
            if abort_requested["value"]:
                raise asyncio.CancelledError()

        def mark_abort_after_first_batch(*, document_ids, texts, metadatas, embeddings):
            store.upsert_batch_sizes.append(len(document_ids))
            abort_requested["value"] = True

        store.upsert_documents_embeddings = mark_abort_after_first_batch  # type: ignore[method-assign]

        with pytest.raises(asyncio.CancelledError):
            await ingestion_engine._upsert_unique_node_vectors(
                unique_node_vector_store=store,  # type: ignore[arg-type]
                node_records=node_records,
                api_key="test-key",
                embeddings=embeddings,
                batch_size=3,
                abort_check=abort_check,
            )

        assert store.upsert_batch_sizes == [3]

    asyncio.run(scenario())


def test_unique_node_vector_upsert_uses_graph_node_document_ids():
    async def scenario():
        store = RecordingNodeVectorStore()
        await ingestion_engine._upsert_unique_node_vectors(
            unique_node_vector_store=store,  # type: ignore[arg-type]
            node_records=[
                {"id": "node-a", "display_name": "Node A", "normalized_id": "node-a"},
                {"id": "node-b", "display_name": "Node B", "normalized_id": "node-b"},
            ],
            api_key="test-key",
            embeddings=[[0.1], [0.2]],
        )

        assert store.upsert_document_ids == [
            "node-a",
            "node-b",
        ]

    asyncio.run(scenario())
