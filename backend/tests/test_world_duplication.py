import copy
import json
from pathlib import Path

from core import graph_store, ingestion_engine, vector_store, world_duplication


def _patch_world_paths(monkeypatch, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)

    def world_path(world_id: str) -> Path:
        return root / world_id

    def meta_path(world_id: str) -> Path:
        return world_path(world_id) / "meta.json"

    def checkpoint_path(world_id: str) -> Path:
        return world_path(world_id) / "checkpoint.json"

    def log_path(world_id: str) -> Path:
        return world_path(world_id) / "ingestion_log.json"

    def reviews_path(world_id: str) -> Path:
        return world_path(world_id) / "ingestion_safety_reviews.json"

    def graph_path(world_id: str) -> Path:
        return world_path(world_id) / "world_graph.gexf"

    def chroma_path(world_id: str) -> Path:
        path = world_path(world_id) / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_meta(world_id: str):
        path = meta_path(world_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    monkeypatch.setattr(world_duplication, "SAVED_WORLDS_DIR", root)
    monkeypatch.setattr(world_duplication, "world_dir", world_path)
    monkeypatch.setattr(world_duplication, "world_meta_path", meta_path)
    monkeypatch.setattr(world_duplication, "world_safety_reviews_path", reviews_path)
    monkeypatch.setattr(world_duplication, "load_world_meta", load_meta)
    monkeypatch.setattr(world_duplication, "_active_duplication_runs", {})

    monkeypatch.setattr(graph_store, "world_graph_path", graph_path)

    monkeypatch.setattr(vector_store, "world_chroma_dir", chroma_path)
    monkeypatch.setattr(vector_store, "get_world_embedding_model", lambda world_id: "test-embedding")
    monkeypatch.setattr(vector_store, "load_settings", lambda: {"embedding_model": "test-embedding"})
    monkeypatch.setattr(vector_store, "set_world_embedding_model", lambda world_id, model: None)

    monkeypatch.setattr(ingestion_engine, "world_meta_path", meta_path)
    monkeypatch.setattr(ingestion_engine, "world_checkpoint_path", checkpoint_path)
    monkeypatch.setattr(ingestion_engine, "world_log_path", log_path)
    monkeypatch.setattr(ingestion_engine, "world_safety_reviews_path", reviews_path)
    monkeypatch.setattr(ingestion_engine, "_active_runs", {})
    monkeypatch.setattr(ingestion_engine, "_abort_events", {})
    monkeypatch.setattr(ingestion_engine, "_sse_queues", {})
    monkeypatch.setattr(ingestion_engine, "_sse_locks", {})


def test_rewrite_safety_review_payload_rewrites_world_bound_chunk_ids():
    source_world_id = "source-world"
    target_world_id = "target-world"
    source_id = "source-a"
    original_chunk_id = f"chunk_{source_world_id}_{source_id}_7"
    payload = {
        "version": 1,
        "reviews": [
            {
                "review_id": original_chunk_id,
                "world_id": source_world_id,
                "source_id": source_id,
                "chunk_id": original_chunk_id,
                "manual_rescue_fingerprint": {
                    "chunk_id": original_chunk_id,
                    "chunk_index": 7,
                },
            }
        ],
    }

    rewritten = world_duplication._rewrite_safety_review_payload(
        payload,
        source_world_id=source_world_id,
        target_world_id=target_world_id,
    )

    review = rewritten["reviews"][0]
    expected_chunk_id = f"chunk_{target_world_id}_{source_id}_7"
    assert review["world_id"] == target_world_id
    assert review["chunk_id"] == expected_chunk_id
    assert review["review_id"] == expected_chunk_id
    assert review["manual_rescue_fingerprint"]["chunk_id"] == expected_chunk_id


def test_iter_regular_source_files_skips_transient_ingest_runtime_files(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "chats").mkdir(parents=True)
    (source_root / "chroma").mkdir()
    for relative_path in (
        "meta.json",
        "checkpoint.json",
        "ingestion_log.json",
        "ingestion_safety_reviews.json",
        "notes.txt",
        "chats/chat-1.json",
    ):
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    _, files = world_duplication._iter_regular_source_files(source_root)
    normalized = {path.as_posix() for path in files}

    assert normalized == {"notes.txt", "chats/chat-1.json"}


def test_run_world_duplication_rewrites_chunk_provenance_and_skips_runtime_files(monkeypatch, tmp_path):
    root = tmp_path / "saved_worlds"
    _patch_world_paths(monkeypatch, root)

    source_world_id = "source-world"
    target_world_id = "target-world"
    source_id = "source-a"
    source_root = root / source_world_id
    target_root = root / target_world_id
    source_root.mkdir(parents=True, exist_ok=True)
    target_root.mkdir(parents=True, exist_ok=True)
    (source_root / "sources").mkdir(exist_ok=True)
    (source_root / "chats").mkdir(exist_ok=True)
    (source_root / "sources" / "book-1.txt").write_text("hello world", encoding="utf-8")
    (source_root / "chats" / "chat-1.json").write_text('{"messages":[]}', encoding="utf-8")
    (source_root / "checkpoint.json").write_text('{"source_id":"source-a","last_completed_chunk_index":1}', encoding="utf-8")
    (source_root / "ingestion_log.json").write_text('{"events":["stale"]}', encoding="utf-8")

    source_meta = {
        "world_id": source_world_id,
        "world_name": "Source World",
        "created_at": "2026-03-23T00:00:00+00:00",
        "ingestion_status": "complete",
        "embedding_model": "test-embedding",
        "total_chunks": 2,
        "total_nodes": 2,
        "total_edges": 0,
        "embedded_unique_nodes": 2,
        "sources": [
            {
                "source_id": source_id,
                "book_number": 1,
                "display_name": "Book 1",
                "original_filename": "book-1.txt",
                "vault_filename": "book-1.txt",
                "status": "complete",
                "chunk_count": 2,
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0, 1],
                "embedded_chunks": [0, 1],
                "ingested_at": "2026-03-23T00:01:00+00:00",
                "ingest_snapshot": {
                    "vault_filename": "book-1.txt",
                    "chunk_size_chars": 4000,
                    "chunk_overlap_chars": 150,
                    "embedding_model": "test-embedding",
                    "captured_at": "2026-03-23T00:01:00+00:00",
                },
            }
        ],
    }
    world_duplication._save_meta(source_world_id, source_meta)

    source_graph = graph_store.GraphStore(source_world_id)
    source_graph.graph.add_node(
        "node-0",
        display_name="Node 0",
        normalized_id="node_0",
        description="",
        claims=[],
        source_chunks=[f"chunk_{source_world_id}_{source_id}_0"],
    )
    source_graph.graph.add_node(
        "node-1",
        display_name="Node 1",
        normalized_id="node_1",
        description="",
        claims=[],
        source_chunks=[f"chunk_{source_world_id}_{source_id}_1"],
    )
    source_graph.save()

    chunk_store = vector_store.VectorStore(source_world_id, embedding_model="test-embedding")
    chunk_store.upsert_documents_embeddings(
        document_ids=[
            f"chunk_{source_world_id}_{source_id}_0",
            f"chunk_{source_world_id}_{source_id}_1",
        ],
        texts=["[B1:C0] first chunk", "[B1:C1] second chunk"],
        metadatas=[
            {"world_id": source_world_id, "source_id": source_id, "book_number": 1, "chunk_index": 0},
            {"world_id": source_world_id, "source_id": source_id, "book_number": 1, "chunk_index": 1},
        ],
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
    )
    unique_node_store = vector_store.VectorStore(source_world_id, embedding_model="test-embedding", collection_suffix="unique_nodes")
    unique_node_store.upsert_documents_embeddings(
        document_ids=["node-0", "node-1"],
        texts=["Node 0", "Node 1"],
        metadatas=[{"node_id": "node-0"}, {"node_id": "node-1"}],
        embeddings=[[0.5, 0.6], [0.7, 0.8]],
    )

    created_at = "2026-03-23T00:05:00+00:00"
    run_id = "dup-run-1"
    initial_meta = world_duplication._build_initial_duplicate_meta(
        source_meta,
        world_id=target_world_id,
        world_name="Source World (Copy)",
        run_id=run_id,
        created_at=created_at,
    )
    world_duplication._save_meta(target_world_id, initial_meta)
    world_duplication._register_run(target_world_id, source_world_id=source_world_id, run_id=run_id)

    world_duplication._run_world_duplication(
        source_world_id=source_world_id,
        target_world_id=target_world_id,
        run_id=run_id,
        source_meta_snapshot=copy.deepcopy(source_meta),
        target_world_name="Source World (Copy)",
        created_at=created_at,
    )

    target_meta = world_duplication._load_meta(target_world_id)
    assert target_meta["world_id"] == target_world_id
    assert target_meta["ingestion_status"] == "complete"
    assert not target_meta.get("is_temporary_duplicate")
    assert not (target_root / "checkpoint.json").exists()
    assert not (target_root / "ingestion_log.json").exists()
    assert (target_root / "chats" / "chat-1.json").exists()

    target_graph = graph_store.GraphStore(target_world_id)
    target_chunk_ids = sorted(
        chunk_id
        for _, attrs in target_graph.graph.nodes(data=True)
        for chunk_id in attrs.get("source_chunks", [])
    )
    assert target_chunk_ids == [
        f"chunk_{target_world_id}_{source_id}_0",
        f"chunk_{target_world_id}_{source_id}_1",
    ]

    target_chunk_store = vector_store.VectorStore(target_world_id, embedding_model="test-embedding")
    target_chunk_records = sorted(target_chunk_store.get_all_chunk_records(), key=lambda row: row["id"])
    assert [row["id"] for row in target_chunk_records] == [
        f"chunk_{target_world_id}_{source_id}_0",
        f"chunk_{target_world_id}_{source_id}_1",
    ]
    assert {row["metadata"]["world_id"] for row in target_chunk_records} == {target_world_id}

    audit = ingestion_engine.audit_ingestion_integrity(target_world_id, synthesize_failures=True, persist=False)
    assert audit["world"]["failed_records"] == 0
    assert audit["world"]["extracted_chunks"] == 2
    assert audit["world"]["embedded_chunks"] == 2

    checkpoint_info = ingestion_engine.get_checkpoint_info(target_world_id)
    assert checkpoint_info["can_resume"] is False
    assert checkpoint_info["failures"] == []
