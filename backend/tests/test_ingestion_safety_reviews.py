import asyncio
from pathlib import Path
import shutil

import pytest

from core import agents, graph_store, ingestion_engine, vector_store
from core.agents import AgentCallError, EdgeOut, GraphArchitectOutput, NodeOut
from core.temporal_indexer import TemporalChunk


TEST_EMBEDDING_MODEL = "test-embed"


def _prepare_world(monkeypatch, world_id: str) -> dict:
    scratch_root = Path(__file__).resolve().parent / "_ingestion_safety_review_tmp"
    world_root = scratch_root / world_id
    if world_root.exists():
        shutil.rmtree(world_root, ignore_errors=True)
    world_root.mkdir(parents=True, exist_ok=True)

    meta_path = world_root / "meta.json"
    checkpoint_path = world_root / "checkpoint.json"
    log_path = world_root / "ingest.log"
    safety_reviews_path = world_root / "safety_reviews.json"
    graph_path = world_root / "world_graph.gexf"
    chroma_path = world_root / "chroma"

    monkeypatch.setattr(ingestion_engine, "world_meta_path", lambda _: meta_path)
    monkeypatch.setattr(ingestion_engine, "world_checkpoint_path", lambda _: checkpoint_path)
    monkeypatch.setattr(ingestion_engine, "world_log_path", lambda _: log_path)
    monkeypatch.setattr(ingestion_engine, "world_safety_reviews_path", lambda _: safety_reviews_path)
    monkeypatch.setattr(graph_store, "world_graph_path", lambda _: graph_path)
    monkeypatch.setattr(vector_store, "world_chroma_dir", lambda _: chroma_path)
    monkeypatch.setattr(
        ingestion_engine,
        "load_settings",
        lambda: {
            "graph_extraction_concurrency": 1,
            "embedding_concurrency": 1,
            "graph_extraction_cooldown_seconds": 0,
            "embedding_cooldown_seconds": 0,
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 0,
            "glean_amount": 0,
        },
    )
    monkeypatch.setattr(
        ingestion_engine,
        "get_world_ingest_settings",
        lambda meta=None: {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 0,
            "embedding_model": TEST_EMBEDDING_MODEL,
            "glean_amount": 0,
        },
    )
    monkeypatch.setattr(ingestion_engine, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(ingestion_engine, "get_checkpoint_info", lambda _world_id: {"world_id": _world_id})
    monkeypatch.setattr(ingestion_engine, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(ingestion_engine, "_build_source_ingest_snapshot", lambda *args, **kwargs: {"saved": True})

    ingestion_engine._abort_events.clear()
    ingestion_engine._active_runs.clear()
    ingestion_engine._sse_queues.clear()
    ingestion_engine._sse_locks.clear()
    ingestion_engine._graph_locks.clear()
    ingestion_engine._vector_locks.clear()
    ingestion_engine._meta_locks.clear()
    ingestion_engine._active_waits.clear()

    return {
        "world_id": world_id,
        "meta_path": meta_path,
        "safety_reviews_path": safety_reviews_path,
        "graph_path": graph_path,
        "chroma_path": chroma_path,
    }


def _make_temporal_chunk(world_id: str, source_id: str, body: str, *, overlap_text: str = "") -> TemporalChunk:
    return TemporalChunk(
        prefixed_text=f"[B1:C0] {body}",
        raw_text=body,
        primary_text=body,
        overlap_text=overlap_text,
        book_number=1,
        chunk_index=0,
        source_id=source_id,
        world_id=world_id,
        char_start=0,
        char_end=len(body),
        display_label="Book 1 > Chunk 0",
    )


def _seed_review_state(
    world_id: str,
    *,
    active_override_raw_text: str,
    draft_raw_text: str,
    has_active_override: bool | None = None,
    overlap_raw_text: str = "",
) -> str:
    source_id = "source-a"
    chunk_id = f"chunk_{world_id}_{source_id}_0"
    meta = {
        "world_id": world_id,
        "ingestion_status": "complete",
        "sources": [
            {
                "source_id": source_id,
                "display_name": "Book 1",
                "status": "complete",
                "book_number": 1,
                "chunk_count": 1,
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0],
                "embedded_chunks": [0],
            }
        ],
    }
    ingestion_engine._save_meta(world_id, meta)
    ingestion_engine._save_safety_review_cache(
        world_id,
        {
            "reviews": [
                {
                    "review_id": chunk_id,
                    "world_id": world_id,
                    "source_id": source_id,
                    "book_number": 1,
                    "chunk_index": 0,
                    "chunk_id": chunk_id,
                    "status": "draft",
                    "original_error_kind": "safety_block",
                    "original_safety_reason": "Unsafe original chunk.",
                    "original_raw_text": "unsafe original text",
                    "original_prefixed_text": "[B1:C0] unsafe original text",
                    "overlap_raw_text": overlap_raw_text,
                    "review_origin": "safety_block",
                    "manual_rescue_fingerprint": None,
                    "draft_raw_text": draft_raw_text,
                    "last_test_outcome": "passed",
                    "last_test_error_kind": None,
                    "last_test_error_message": None,
                    "last_tested_at": "2026-03-23T00:00:00+00:00",
                    "test_attempt_count": 1,
                    "test_in_progress": False,
                    "has_active_override": (
                        bool(active_override_raw_text.strip()) if has_active_override is None else has_active_override
                    ),
                    "active_override_raw_text": active_override_raw_text,
                    "created_at": "2026-03-23T00:00:00+00:00",
                    "updated_at": "2026-03-23T00:00:00+00:00",
                }
            ]
        },
    )
    return chunk_id


def _seed_live_chunk_artifacts(world_id: str, chunk_id: str, live_text: str) -> dict:
    store = graph_store.GraphStore(world_id)
    store.graph.add_node(
        "live-node-a",
        node_id="live-node-a",
        display_name="Live A",
        normalized_id="live_a",
        description="Old live node A",
        claims=[
            {
                "claim_id": "claim-live-a",
                "text": "Old live fact",
                "source_book": 1,
                "source_chunk": 0,
                "sequence_id": 1,
            }
        ],
        source_chunks=[chunk_id],
        created_at="2026-03-23T00:00:00+00:00",
        updated_at="2026-03-23T00:00:00+00:00",
    )
    store.graph.add_node(
        "live-node-b",
        node_id="live-node-b",
        display_name="Live B",
        normalized_id="live_b",
        description="Old live node B",
        claims=[],
        source_chunks=[chunk_id],
        created_at="2026-03-23T00:00:00+00:00",
        updated_at="2026-03-23T00:00:00+00:00",
    )
    store.graph.add_edge(
        "live-node-a",
        "live-node-b",
        key="edge-live",
        edge_id="edge-live",
        source_node_id="live-node-a",
        target_node_id="live-node-b",
        description="Old live relation",
        strength=5,
        source_book=1,
        source_chunk=0,
        created_at="2026-03-23T00:00:00+00:00",
    )
    store.save()

    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    chunk_store.upsert_document_embedding(
        document_id=chunk_id,
        text=f"[B1:C0] {live_text}",
        metadata={
            "world_id": world_id,
            "source_id": "source-a",
            "book_number": 1,
            "chunk_index": 0,
            "char_start": 0,
            "char_end": len(live_text),
            "display_label": "Book 1 > Chunk 0",
        },
        embedding=[0.11, 0.22, 0.33],
    )

    unique_store = vector_store.VectorStore(
        world_id,
        embedding_model=TEST_EMBEDDING_MODEL,
        collection_suffix="unique_nodes",
    )
    unique_store.upsert_documents_embeddings(
        document_ids=["live-node-a", "live-node-b"],
        texts=["Live unique node A", "Live unique node B"],
        metadatas=[
            {"display_name": "Live A", "normalized_id": "live_a", "node_id": "live-node-a"},
            {"display_name": "Live B", "normalized_id": "live_b", "node_id": "live-node-b"},
        ],
        embeddings=[[0.41, 0.42], [0.51, 0.52]],
    )

    return {
        "chunk_store": chunk_store,
        "unique_store": unique_store,
    }


class _SafetyBlockGraphArchitect:
    def __init__(self, *, world_id: str | None = None) -> None:
        self.world_id = world_id

    async def run(self, extraction_chunk_text: str):
        raise AgentCallError("safety_block", "Provider safety block: unsafe", safety_reason="unsafe")

    async def run_glean(self, extraction_chunk_text: str, previous_nodes, previous_edges):
        raise AssertionError("Glean should not run when extraction is blocked.")


class _PassingGraphArchitect:
    def __init__(self, *, world_id: str | None = None) -> None:
        self.world_id = world_id

    async def run(self, extraction_chunk_text: str):
        output = GraphArchitectOutput(
            nodes=[
                NodeOut(node_id="candidate_a", display_name="Candidate A", description="Fresh candidate A"),
                NodeOut(node_id="candidate_b", display_name="Candidate B", description="Fresh candidate B"),
            ],
            edges=[
                EdgeOut(
                    source_node_id="candidate_a",
                    target_node_id="candidate_b",
                    description="Fresh candidate relation",
                    strength=6,
                )
            ],
        )
        return output, {}

    async def run_glean(self, extraction_chunk_text: str, previous_nodes, previous_edges):
        return GraphArchitectOutput(nodes=[], edges=[]), {}


class _CapturingGraphArchitect(_PassingGraphArchitect):
    last_payload: str | None = None

    async def run(self, extraction_chunk_text: str):
        type(self).last_payload = extraction_chunk_text
        return await super().run(extraction_chunk_text)


class _DummyKeyManager:
    api_keys = ["test-key"]
    key_count = 1

    def get_active_key(self):
        return ("test-key", 0)

    async def await_active_key(self):
        return ("test-key", 0)


def _embed_texts_with_collection_dims(self, texts, api_key):
    if self.collection_suffix == "unique_nodes":
        return [[float(index + 1), float(len(text))] for index, text in enumerate(texts)]
    return [[float(index + 1), float(len(text)), float(len(text) + 10)] for index, text in enumerate(texts)]


def test_failed_retest_restores_live_artifacts_after_extraction_failure(monkeypatch):
    world_id = "world-safety-review-extraction-fail"
    _prepare_world(monkeypatch, world_id)
    old_live_text = "old repaired text"
    new_draft_text = "new risky draft"
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text=old_live_text,
        draft_raw_text=new_draft_text,
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, old_live_text)
    monkeypatch.setattr(ingestion_engine, "_load_source_temporal_chunks", lambda *args, **kwargs: [_make_temporal_chunk(world_id, "source-a", "unsafe original text")])
    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _SafetyBlockGraphArchitect)

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    reloaded_graph = graph_store.GraphStore(world_id)
    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    unique_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL, collection_suffix="unique_nodes")

    assert review["active_override_raw_text"] == old_live_text
    assert review["draft_raw_text"] == new_draft_text
    assert review["last_test_outcome"] == "still_safety_blocked"
    assert review["status"] == "draft"
    assert sorted(reloaded_graph.graph.nodes()) == ["live-node-a", "live-node-b"]
    assert any(attrs.get("edge_id") == "edge-live" for _, _, attrs in reloaded_graph._iter_edge_rows())
    chunk_records = chunk_store.get_records_by_ids([chunk_id], include_documents=True, include_embeddings=True)
    unique_records = unique_store.get_records_by_ids(["live-node-a", "live-node-b"], include_documents=True, include_embeddings=True)
    assert len(chunk_records) == 1
    assert chunk_records[0]["document"] == "[B1:C0] old repaired text"
    assert len(unique_records) == 2
    assert {record["id"] for record in unique_records} == {"live-node-a", "live-node-b"}


def test_failed_retest_restores_live_artifacts_after_embedding_failure(monkeypatch):
    world_id = "world-safety-review-embedding-fail"
    _prepare_world(monkeypatch, world_id)
    old_live_text = "old repaired text"
    new_draft_text = "new repair draft"
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text=old_live_text,
        draft_raw_text=new_draft_text,
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, old_live_text)
    monkeypatch.setattr(ingestion_engine, "_load_source_temporal_chunks", lambda *args, **kwargs: [_make_temporal_chunk(world_id, "source-a", "unsafe original text")])
    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _PassingGraphArchitect)
    monkeypatch.setattr(ingestion_engine, "get_key_manager", lambda: _DummyKeyManager())
    monkeypatch.setattr(
        vector_store.VectorStore,
        "embed_texts",
        lambda self, texts, api_key: (_ for _ in ()).throw(RuntimeError("embedding boom")),
    )

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    reloaded_graph = graph_store.GraphStore(world_id)
    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    unique_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL, collection_suffix="unique_nodes")

    assert review["active_override_raw_text"] == old_live_text
    assert review["draft_raw_text"] == new_draft_text
    assert review["last_test_outcome"] == "other_failure"
    assert review["last_test_error_message"] == "embedding boom"
    assert review["status"] == "draft"
    assert sorted(reloaded_graph.graph.nodes()) == ["live-node-a", "live-node-b"]
    assert all(node_data["display_name"].startswith("Live") for node_data in (reloaded_graph.get_node("live-node-a"), reloaded_graph.get_node("live-node-b")) if node_data)
    assert chunk_store.get_records_by_ids([chunk_id], include_documents=True)[0]["document"] == "[B1:C0] old repaired text"
    unique_records = unique_store.get_records_by_ids(["live-node-a", "live-node-b"], include_documents=True)
    assert {record["id"] for record in unique_records} == {"live-node-a", "live-node-b"}


def test_successful_retest_replaces_live_override_and_vectors(monkeypatch):
    world_id = "world-safety-review-success"
    _prepare_world(monkeypatch, world_id)
    old_live_text = "old repaired text"
    new_draft_text = "clean replacement draft"
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text=old_live_text,
        draft_raw_text=new_draft_text,
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, old_live_text)
    monkeypatch.setattr(ingestion_engine, "_load_source_temporal_chunks", lambda *args, **kwargs: [_make_temporal_chunk(world_id, "source-a", "unsafe original text")])
    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _PassingGraphArchitect)
    monkeypatch.setattr(ingestion_engine, "get_key_manager", lambda: _DummyKeyManager())
    monkeypatch.setattr(
        vector_store.VectorStore,
        "embed_texts",
        _embed_texts_with_collection_dims,
    )

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    reloaded_graph = graph_store.GraphStore(world_id)
    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    unique_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL, collection_suffix="unique_nodes")

    assert review["active_override_raw_text"] == new_draft_text
    assert review["draft_raw_text"] == new_draft_text
    assert review["last_test_outcome"] == "passed"
    assert review["status"] == "resolved"
    assert not unique_store.has_document("live-node-a")
    assert not unique_store.has_document("live-node-b")
    assert chunk_store.get_records_by_ids([chunk_id], include_documents=True)[0]["document"] == "[B1:C0] clean replacement draft"
    assert reloaded_graph.get_node_count() == 2
    live_display_names = sorted(node["display_name"] for node in (reloaded_graph.get_node(node_id) for node_id in reloaded_graph.graph.nodes()) if node)
    assert live_display_names == ["Candidate A", "Candidate B"]


def test_reset_safety_review_clears_live_override_and_recreates_queue_owned_failure(monkeypatch):
    world_id = "world-safety-review-reset-live"
    _prepare_world(monkeypatch, world_id)
    old_live_text = "old repaired text"
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text=old_live_text,
        draft_raw_text=old_live_text,
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, old_live_text)

    result = asyncio.run(ingestion_engine.reset_safety_review(world_id, chunk_id))

    review = result["review"]
    meta = ingestion_engine._load_meta(world_id)
    source = meta["sources"][0]
    reloaded_graph = graph_store.GraphStore(world_id)
    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    unique_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL, collection_suffix="unique_nodes")
    extraction_failures = [failure for failure in source.get("stage_failures", []) if failure.get("stage") == "extraction"]
    embedding_failures = [failure for failure in source.get("stage_failures", []) if failure.get("stage") == "embedding" and failure.get("scope") == "chunk"]

    assert review["draft_raw_text"] == old_live_text
    assert review["active_override_raw_text"] == ""
    assert review["has_active_override"] is False
    assert review["status"] == "draft"
    assert review["last_test_outcome"] == "not_tested"
    assert source["status"] == "partial_failure"
    assert source["extracted_chunks"] == []
    assert source["embedded_chunks"] == []
    assert source["failed_chunks"] == [0]
    assert len(extraction_failures) == 1
    assert extraction_failures[0]["error_type"] == "coverage_gap"
    assert extraction_failures[0]["chunk_id"] == chunk_id
    assert len(embedding_failures) == 1
    assert embedding_failures[0]["error_type"] == "coverage_gap"
    assert reloaded_graph.get_node_count() == 0
    assert chunk_store.get_records_by_ids([chunk_id], include_documents=True) == []
    assert unique_store.get_records_by_ids(["live-node-a", "live-node-b"], include_documents=True) == []
    assert result["safety_review_summary"]["unresolved_reviews"] == 1
    assert result["safety_review_summary"]["active_override_reviews"] == 0
    assert result["reset_details"]["had_live_artifacts"] is True
    assert result["reset_details"]["requires_reingest_for_entity_descriptions"] is True


def test_reset_safety_review_replaces_embedding_failure_with_full_restart_failure(monkeypatch):
    world_id = "world-safety-review-reset-blocked"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="",
        draft_raw_text="unsafe original text",
        has_active_override=False,
    )
    meta = ingestion_engine._load_meta(world_id)
    source = meta["sources"][0]
    source["status"] = "partial_failure"
    source["extracted_chunks"] = [0]
    source["embedded_chunks"] = []
    source["stage_failures"] = [
        {
            "stage": "embedding",
            "scope": "chunk",
            "chunk_index": 0,
            "chunk_id": chunk_id,
            "parent_chunk_id": chunk_id,
            "source_id": "source-a",
            "book_number": 1,
            "error_type": "embedding_failed",
            "error_message": "old embedding failure",
            "attempt_count": 1,
            "last_attempt_at": "2026-03-23T00:00:00+00:00",
            "node_id": None,
            "node_display_name": None,
        }
    ]
    source["failed_chunks"] = [0]
    ingestion_engine._save_meta(world_id, meta)

    result = asyncio.run(ingestion_engine.reset_safety_review(world_id, chunk_id))

    review = result["review"]
    refreshed_meta = ingestion_engine._load_meta(world_id)
    refreshed_source = refreshed_meta["sources"][0]
    assert review["active_override_raw_text"] == ""
    assert review["has_active_override"] is False
    assert review["status"] == "blocked"
    assert refreshed_source["extracted_chunks"] == []
    assert refreshed_source["embedded_chunks"] == []
    assert refreshed_source["failed_chunks"] == [0]
    assert len(refreshed_source["stage_failures"]) == 2
    assert {failure["stage"] for failure in refreshed_source["stage_failures"]} == {"embedding", "extraction"}
    assert all(failure["error_type"] == "coverage_gap" for failure in refreshed_source["stage_failures"])
    assert result["reset_details"]["had_live_artifacts"] is False
    assert result["reset_details"]["requires_reingest_for_entity_descriptions"] is False


def test_blank_draft_is_preserved_when_saved(monkeypatch):
    world_id = "world-safety-review-blank-draft-save"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="old repaired text",
    )

    review = asyncio.run(ingestion_engine.update_safety_review_draft(world_id, chunk_id, ""))

    assert review["draft_raw_text"] == ""
    assert review["has_active_override"] is True
    assert review["status"] == "draft"


def test_blank_draft_failed_retest_keeps_blank_draft_and_live_override(monkeypatch):
    world_id = "world-safety-review-blank-draft-fail"
    _prepare_world(monkeypatch, world_id)
    old_live_text = "old repaired text"
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text=old_live_text,
        draft_raw_text="",
        has_active_override=True,
        overlap_raw_text="reference overlap only",
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, old_live_text)
    monkeypatch.setattr(
        ingestion_engine,
        "_load_source_temporal_chunks",
        lambda *args, **kwargs: [_make_temporal_chunk(world_id, "source-a", "unsafe original text", overlap_text="reference overlap only")],
    )
    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _SafetyBlockGraphArchitect)

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    assert review["draft_raw_text"] == ""
    assert review["active_override_raw_text"] == old_live_text
    assert review["has_active_override"] is True
    assert review["last_test_outcome"] == "still_safety_blocked"
    assert review["status"] == "draft"


def test_blank_draft_success_uses_overlap_only_and_persists_blank_override(monkeypatch):
    world_id = "world-safety-review-blank-draft-success"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="",
        has_active_override=True,
        overlap_raw_text="notice, I thought. Should I get something for you?",
    )
    monkeypatch.setattr(
        ingestion_engine,
        "_load_source_temporal_chunks",
        lambda *args, **kwargs: [
            _make_temporal_chunk(
                world_id,
                "source-a",
                "unsafe original text that should not be sent",
                overlap_text="notice, I thought. Should I get something for you?",
            )
        ],
    )
    _CapturingGraphArchitect.last_payload = None
    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _CapturingGraphArchitect)
    monkeypatch.setattr(ingestion_engine, "get_key_manager", lambda: _DummyKeyManager())
    monkeypatch.setattr(vector_store.VectorStore, "embed_texts", _embed_texts_with_collection_dims)

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    payload = _CapturingGraphArchitect.last_payload
    assert payload is not None
    assert "unsafe original text that should not be sent" not in payload
    assert "notice, I thought. Should I get something for you?" in payload
    assert "Chunk body to extract from:\n\n\nReference-only overlap context" in payload
    assert review["draft_raw_text"] == ""
    assert review["active_override_raw_text"] == ""
    assert review["has_active_override"] is True
    assert review["last_test_outcome"] == "passed"
    assert review["status"] == "resolved"
    assert ingestion_engine._get_active_override_map(world_id)[chunk_id] == ""
    assert chunk_store.get_records_by_ids([chunk_id], include_documents=True)[0]["document"] == "[B1:C0] notice, I thought. Should I get something for you?"


def test_safety_review_rate_limit_tries_each_key_once_and_stops(monkeypatch):
    world_id = "world-safety-review-rate-limit-multi"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="new repair draft",
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, "old repaired text")
    attempted_keys: list[str] = []

    monkeypatch.setattr(ingestion_engine, "_load_source_temporal_chunks", lambda *args, **kwargs: [_make_temporal_chunk(world_id, "source-a", "unsafe original text")])
    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key, world_id=None: "SYSTEM")
    monkeypatch.setattr(
        agents,
        "get_provider_pool",
        lambda provider: [
            {"api_key": "key-1"},
            {"api_key": "key-2"},
        ],
    )

    async def fake_completion(provider: str, payload: dict, *, api_key: str, base_url=None, timeout: float = 120.0):
        attempted_keys.append(api_key)
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion_for_api_key", fake_completion)

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    assert attempted_keys == ["key-1", "key-2"]
    assert review["test_in_progress"] is False
    assert review["last_test_outcome"] == "transient_failure"
    assert review["last_test_error_message"] == "429 Too Many Requests"
    assert review["status"] == "draft"


def test_single_key_rate_limit_does_not_leave_safety_review_testing(monkeypatch):
    world_id = "world-safety-review-rate-limit-single"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="new repair draft",
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, "old repaired text")
    attempted_keys: list[str] = []

    monkeypatch.setattr(ingestion_engine, "_load_source_temporal_chunks", lambda *args, **kwargs: [_make_temporal_chunk(world_id, "source-a", "unsafe original text")])
    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key, world_id=None: "SYSTEM")
    monkeypatch.setattr(agents, "get_provider_pool", lambda provider: [{"api_key": "only-key"}])

    async def fake_completion(provider: str, payload: dict, *, api_key: str, base_url=None, timeout: float = 120.0):
        attempted_keys.append(api_key)
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion_for_api_key", fake_completion)

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    assert attempted_keys == ["only-key"]
    assert review["test_in_progress"] is False
    assert review["last_test_outcome"] == "transient_failure"
    assert review["status"] == "draft"


def test_unexpected_safety_review_error_clears_testing_state(monkeypatch):
    world_id = "world-safety-review-unexpected-failure"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="new repair draft",
    )
    _seed_live_chunk_artifacts(world_id, chunk_id, "old repaired text")

    monkeypatch.setattr(ingestion_engine, "_review_editor_raw_text", lambda review: (_ for _ in ()).throw(RuntimeError("draft load exploded")))

    result = asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))

    review = result["review"]
    assert review["test_in_progress"] is False
    assert review["last_test_outcome"] == "other_failure"
    assert "draft load exploded" in review["last_test_error_message"]
    assert review["status"] == "draft"


def test_list_safety_reviews_auto_heals_orphaned_testing_state(monkeypatch):
    world_id = "world-safety-review-orphaned-testing"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="old repaired text",
        has_active_override=True,
    )
    cache = ingestion_engine._load_safety_review_cache(world_id)
    cache["reviews"][0]["test_in_progress"] = True
    cache["reviews"][0]["status"] = "testing"
    ingestion_engine._save_safety_review_cache(world_id, cache)

    reviews = ingestion_engine.list_safety_reviews(world_id)

    review = next(item for item in reviews if item["review_id"] == chunk_id)
    assert review["test_in_progress"] is False
    assert review["last_test_outcome"] == "other_failure"
    assert review["last_test_error_message"] == "Previous test did not finish cleanly. Retry the draft to test it again."
    assert review["status"] == "draft"


def test_list_safety_reviews_marks_live_override_locked_after_entity_resolution(monkeypatch):
    world_id = "world-safety-review-entity-lock"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="old repaired text",
        has_active_override=True,
    )
    meta = ingestion_engine._load_meta(world_id)
    meta["entity_resolution_last_completed_at"] = "2026-03-24T00:00:00+00:00"
    ingestion_engine._save_meta(world_id, meta)

    cache = ingestion_engine._load_safety_review_cache(world_id)
    cache["reviews"][0]["last_live_applied_at"] = "2026-03-23T00:00:00+00:00"
    ingestion_engine._save_safety_review_cache(world_id, cache)

    review = next(item for item in ingestion_engine.list_safety_reviews(world_id) if item["review_id"] == chunk_id)

    assert review["entity_resolution_locked"] is True
    assert "entity-resolution run" in review["entity_resolution_lock_reason"].lower()


def test_locked_safety_review_blocks_edit_test_and_reset(monkeypatch):
    world_id = "world-safety-review-entity-lock-guards"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="old repaired text",
        has_active_override=True,
    )
    meta = ingestion_engine._load_meta(world_id)
    meta["entity_resolution_last_completed_at"] = "2026-03-24T00:00:00+00:00"
    ingestion_engine._save_meta(world_id, meta)

    cache = ingestion_engine._load_safety_review_cache(world_id)
    cache["reviews"][0]["last_live_applied_at"] = "2026-03-23T00:00:00+00:00"
    ingestion_engine._save_safety_review_cache(world_id, cache)

    with pytest.raises(RuntimeError, match="entity-resolution run"):
        asyncio.run(ingestion_engine.update_safety_review_draft(world_id, chunk_id, "new draft"))
    with pytest.raises(RuntimeError, match="entity-resolution run"):
        asyncio.run(ingestion_engine.test_safety_review(world_id, chunk_id))
    with pytest.raises(RuntimeError, match="entity-resolution run"):
        asyncio.run(ingestion_engine.reset_safety_review(world_id, chunk_id))


def test_safety_review_without_durable_coverage_stays_editable_after_entity_resolution(monkeypatch):
    world_id = "world-safety-review-entity-lock-partial"
    _prepare_world(monkeypatch, world_id)
    chunk_id = _seed_review_state(
        world_id,
        active_override_raw_text="old repaired text",
        draft_raw_text="old repaired text",
        has_active_override=True,
    )
    meta = ingestion_engine._load_meta(world_id)
    meta["entity_resolution_last_completed_at"] = "2026-03-24T00:00:00+00:00"
    meta["sources"][0]["embedded_chunks"] = []
    ingestion_engine._save_meta(world_id, meta)

    cache = ingestion_engine._load_safety_review_cache(world_id)
    cache["reviews"][0]["last_live_applied_at"] = "2026-03-23T00:00:00+00:00"
    ingestion_engine._save_safety_review_cache(world_id, cache)

    updated = asyncio.run(ingestion_engine.update_safety_review_draft(world_id, chunk_id, "new draft"))

    assert updated["draft_raw_text"] == "new draft"
    assert updated["entity_resolution_locked"] is False


def test_legacy_reviews_infer_active_override_flag_from_text(monkeypatch):
    world_id = "world-safety-review-legacy-flag"
    _prepare_world(monkeypatch, world_id)
    source_id = "source-a"
    chunk_id = f"chunk_{world_id}_{source_id}_0"
    ingestion_engine._save_meta(
        world_id,
        {
            "world_id": world_id,
            "ingestion_status": "complete",
            "sources": [
                {
                    "source_id": source_id,
                    "display_name": "Book 1",
                    "status": "complete",
                    "book_number": 1,
                    "chunk_count": 1,
                    "failed_chunks": [],
                    "stage_failures": [],
                    "extracted_chunks": [0],
                    "embedded_chunks": [0],
                }
            ],
        },
    )
    ingestion_engine._save_safety_review_cache(
        world_id,
        {
            "reviews": [
                {
                    "review_id": chunk_id,
                    "world_id": world_id,
                    "source_id": source_id,
                    "book_number": 1,
                    "chunk_index": 0,
                    "chunk_id": chunk_id,
                    "status": "resolved",
                    "original_error_kind": "safety_block",
                    "original_safety_reason": "Unsafe original chunk.",
                    "original_raw_text": "unsafe original text",
                    "original_prefixed_text": "[B1:C0] unsafe original text",
                    "overlap_raw_text": "",
                    "review_origin": "safety_block",
                    "manual_rescue_fingerprint": None,
                    "draft_raw_text": "legacy repaired text",
                    "last_test_outcome": "passed",
                    "last_test_error_kind": None,
                    "last_test_error_message": None,
                    "last_tested_at": "2026-03-23T00:00:00+00:00",
                    "test_attempt_count": 1,
                    "test_in_progress": False,
                    "active_override_raw_text": "legacy repaired text",
                    "created_at": "2026-03-23T00:00:00+00:00",
                    "updated_at": "2026-03-23T00:00:00+00:00",
                }
            ]
        },
    )

    reviews = ingestion_engine.list_safety_reviews(world_id)
    summary = ingestion_engine.get_safety_review_summary(world_id)

    assert reviews[0]["has_active_override"] is True
    assert summary["active_override_reviews"] == 1


def test_start_ingestion_starts_chunk_and_node_embeddings_before_glean_finishes(monkeypatch):
    world_id = "world-ingest-early-embeds"
    ctx = _prepare_world(monkeypatch, world_id)
    sources_dir = ctx["meta_path"].parent / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "book1.txt").write_text("Candidate A meets Candidate B.", encoding="utf-8")
    monkeypatch.setattr(ingestion_engine, "world_sources_dir", lambda _world_id: sources_dir)
    monkeypatch.setattr(
        ingestion_engine,
        "load_settings",
        lambda: {
            "graph_extraction_concurrency": 1,
            "embedding_concurrency": 1,
            "graph_extraction_cooldown_seconds": 0,
            "embedding_cooldown_seconds": 0,
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 0,
            "glean_amount": 1,
        },
    )
    monkeypatch.setattr(
        ingestion_engine,
        "get_world_ingest_settings",
        lambda meta=None: {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 0,
            "embedding_model": TEST_EMBEDDING_MODEL,
            "glean_amount": 1,
        },
    )
    monkeypatch.setattr(ingestion_engine, "get_key_manager", lambda: _DummyKeyManager())
    monkeypatch.setattr(vector_store.VectorStore, "embed_texts", _embed_texts_with_collection_dims)

    state = {
        "chunk_embed_started": False,
        "node_embed_started": False,
        "glean_saw_chunk_embed": False,
        "glean_saw_node_embed": False,
    }

    original_upsert_documents_embeddings = vector_store.VectorStore.upsert_documents_embeddings

    def _tracking_upsert_documents_embeddings(self, *, document_ids, texts, metadatas, embeddings):
        if self.collection_suffix == "unique_nodes":
            state["node_embed_started"] = True
        else:
            state["chunk_embed_started"] = True
        return original_upsert_documents_embeddings(
            self,
            document_ids=document_ids,
            texts=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    monkeypatch.setattr(
        vector_store.VectorStore,
        "upsert_documents_embeddings",
        _tracking_upsert_documents_embeddings,
    )

    class _OrderingGraphArchitect:
        def __init__(self, *, world_id: str | None = None) -> None:
            self.world_id = world_id

        async def run(self, extraction_chunk_text: str):
            return (
                GraphArchitectOutput(
                    nodes=[
                        NodeOut(node_id="candidate_a", display_name="Candidate A", description="Fresh candidate A"),
                        NodeOut(node_id="candidate_b", display_name="Candidate B", description="Fresh candidate B"),
                    ],
                    edges=[
                        EdgeOut(
                            source_node_id="candidate_a",
                            target_node_id="candidate_b",
                            description="Fresh candidate relation",
                            strength=6,
                        )
                    ],
                ),
                {},
            )

        async def run_glean(self, extraction_chunk_text: str, previous_nodes, previous_edges):
            deadline = asyncio.get_running_loop().time() + 1.0
            while not (state["chunk_embed_started"] and state["node_embed_started"]):
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("Chunk and node embeddings should both have started before glean completed.")
                await asyncio.sleep(0.01)
            state["glean_saw_chunk_embed"] = state["chunk_embed_started"]
            state["glean_saw_node_embed"] = state["node_embed_started"]
            return (
                GraphArchitectOutput(
                    nodes=[NodeOut(node_id="candidate_c", display_name="Candidate C", description="Fresh candidate C")],
                    edges=[],
                ),
                {},
            )

    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _OrderingGraphArchitect)
    ingestion_engine._save_meta(
        world_id,
        {
            "world_id": world_id,
            "ingestion_status": "pending",
            "sources": [
                {
                    "source_id": "source-a",
                    "display_name": "Book 1",
                    "status": "pending",
                    "book_number": 1,
                    "vault_filename": "book1.txt",
                    "failed_chunks": [],
                    "stage_failures": [],
                    "extracted_chunks": [],
                    "embedded_chunks": [],
                }
            ],
        },
    )

    asyncio.run(ingestion_engine.start_ingestion(world_id))

    refreshed_meta = ingestion_engine._load_meta(world_id)
    refreshed_source = refreshed_meta["sources"][0]
    refreshed_graph = graph_store.GraphStore(world_id)
    unique_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL, collection_suffix="unique_nodes")

    assert state["glean_saw_chunk_embed"] is True
    assert state["glean_saw_node_embed"] is True
    assert refreshed_source["status"] == "complete"
    assert refreshed_source["extracted_chunks"] == [0]
    assert refreshed_source["embedded_chunks"] == [0]
    assert refreshed_graph.get_node_count() == 3
    assert unique_store.count() == 3


def test_start_ingestion_discards_staged_nodes_but_keeps_chunk_embedding_when_glean_fails(monkeypatch):
    world_id = "world-ingest-glean-fail"
    ctx = _prepare_world(monkeypatch, world_id)
    sources_dir = ctx["meta_path"].parent / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "book1.txt").write_text("Candidate A meets Candidate B.", encoding="utf-8")
    monkeypatch.setattr(ingestion_engine, "world_sources_dir", lambda _world_id: sources_dir)
    monkeypatch.setattr(
        ingestion_engine,
        "load_settings",
        lambda: {
            "graph_extraction_concurrency": 1,
            "embedding_concurrency": 1,
            "graph_extraction_cooldown_seconds": 0,
            "embedding_cooldown_seconds": 0,
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 0,
            "glean_amount": 1,
        },
    )
    monkeypatch.setattr(
        ingestion_engine,
        "get_world_ingest_settings",
        lambda meta=None: {
            "chunk_size_chars": 4000,
            "chunk_overlap_chars": 0,
            "embedding_model": TEST_EMBEDDING_MODEL,
            "glean_amount": 1,
        },
    )
    monkeypatch.setattr(ingestion_engine, "get_key_manager", lambda: _DummyKeyManager())
    monkeypatch.setattr(vector_store.VectorStore, "embed_texts", _embed_texts_with_collection_dims)

    state = {
        "chunk_embed_started": False,
        "node_embed_started": False,
    }

    original_upsert_documents_embeddings = vector_store.VectorStore.upsert_documents_embeddings

    def _tracking_upsert_documents_embeddings(self, *, document_ids, texts, metadatas, embeddings):
        if self.collection_suffix == "unique_nodes":
            state["node_embed_started"] = True
        else:
            state["chunk_embed_started"] = True
        return original_upsert_documents_embeddings(
            self,
            document_ids=document_ids,
            texts=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    monkeypatch.setattr(
        vector_store.VectorStore,
        "upsert_documents_embeddings",
        _tracking_upsert_documents_embeddings,
    )

    class _FailingGleanGraphArchitect:
        def __init__(self, *, world_id: str | None = None) -> None:
            self.world_id = world_id

        async def run(self, extraction_chunk_text: str):
            return (
                GraphArchitectOutput(
                    nodes=[NodeOut(node_id="candidate_a", display_name="Candidate A", description="Fresh candidate A")],
                    edges=[],
                ),
                {},
            )

        async def run_glean(self, extraction_chunk_text: str, previous_nodes, previous_edges):
            deadline = asyncio.get_running_loop().time() + 1.0
            while not (state["chunk_embed_started"] and state["node_embed_started"]):
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("Expected chunk and node embeddings to begin before glean failure.")
                await asyncio.sleep(0.01)
            raise RuntimeError("glean boom")

    monkeypatch.setattr(ingestion_engine, "GraphArchitectAgent", _FailingGleanGraphArchitect)
    ingestion_engine._save_meta(
        world_id,
        {
            "world_id": world_id,
            "ingestion_status": "pending",
            "sources": [
                {
                    "source_id": "source-a",
                    "display_name": "Book 1",
                    "status": "pending",
                    "book_number": 1,
                    "vault_filename": "book1.txt",
                    "failed_chunks": [],
                    "stage_failures": [],
                    "extracted_chunks": [],
                    "embedded_chunks": [],
                }
            ],
        },
    )

    asyncio.run(ingestion_engine.start_ingestion(world_id))

    refreshed_meta = ingestion_engine._load_meta(world_id)
    refreshed_source = refreshed_meta["sources"][0]
    chunk_id = f"chunk_{world_id}_source-a_0"
    refreshed_graph = graph_store.GraphStore(world_id)
    chunk_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL)
    unique_store = vector_store.VectorStore(world_id, embedding_model=TEST_EMBEDDING_MODEL, collection_suffix="unique_nodes")
    extraction_failures = [failure for failure in refreshed_source["stage_failures"] if failure["stage"] == "extraction"]

    assert refreshed_meta["ingestion_status"] == "partial_failure"
    assert refreshed_source["status"] == "partial_failure"
    assert refreshed_source["extracted_chunks"] == []
    assert refreshed_source["embedded_chunks"] == [0]
    assert len(extraction_failures) == 1
    assert refreshed_graph.get_node_count() == 0
    assert chunk_store.get_records_by_ids([chunk_id], include_documents=True) != []
    assert unique_store.count() == 0


def teardown_module(module):
    scratch_root = Path(__file__).resolve().parent / "_ingestion_safety_review_tmp"
    if scratch_root.exists():
        shutil.rmtree(scratch_root, ignore_errors=True)
