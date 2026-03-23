import asyncio
from pathlib import Path
import shutil

from core import graph_store, ingestion_engine, vector_store
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


def _make_temporal_chunk(world_id: str, source_id: str, body: str) -> TemporalChunk:
    return TemporalChunk(
        prefixed_text=f"[B1:C0] {body}",
        raw_text=body,
        primary_text=body,
        overlap_text="",
        book_number=1,
        chunk_index=0,
        source_id=source_id,
        world_id=world_id,
        char_start=0,
        char_end=len(body),
        display_label="Book 1 > Chunk 0",
    )


def _seed_review_state(world_id: str, *, active_override_raw_text: str, draft_raw_text: str) -> str:
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
                    "overlap_raw_text": "",
                    "review_origin": "safety_block",
                    "manual_rescue_fingerprint": None,
                    "draft_raw_text": draft_raw_text,
                    "last_test_outcome": "passed",
                    "last_test_error_kind": None,
                    "last_test_error_message": None,
                    "last_tested_at": "2026-03-23T00:00:00+00:00",
                    "test_attempt_count": 1,
                    "test_in_progress": False,
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


class _DummyKeyManager:
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


def teardown_module(module):
    scratch_root = Path(__file__).resolve().parent / "_ingestion_safety_review_tmp"
    if scratch_root.exists():
        shutil.rmtree(scratch_root, ignore_errors=True)
