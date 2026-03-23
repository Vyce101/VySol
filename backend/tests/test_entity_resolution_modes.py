import asyncio
import json
from pathlib import Path

import pytest

from core import entity_resolution_engine as engine
from core import graph_store
from routers import entity_resolution as entity_resolution_router


def _prepare_world(tmp_path: Path, monkeypatch, world_id: str = "world-entity-resolution") -> tuple[Path, graph_store.GraphStore]:
    world_root = tmp_path / world_id
    world_root.mkdir(parents=True, exist_ok=True)
    meta_path = world_root / "meta.json"
    graph_path = world_root / "world_graph.gexf"
    meta_path.write_text(json.dumps({"ingestion_status": "complete"}), encoding="utf-8")

    monkeypatch.setattr(engine, "world_meta_path", lambda _: meta_path)
    monkeypatch.setattr(graph_store, "world_graph_path", lambda _: graph_path)
    monkeypatch.setattr(engine, "load_settings", lambda: {})

    engine._abort_events.clear()
    engine._sse_queues.clear()
    engine._sse_locks.clear()
    engine._states.clear()
    engine._state_locks.clear()
    engine._active_runs.clear()

    return meta_path, graph_store.GraphStore(world_id)


def test_exact_only_mode_stops_after_normalized_match_pass(tmp_path, monkeypatch):
    world_id = "world-exact-only"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    async def _fail_choose(*args, **kwargs):
        raise AssertionError("Chooser should not run in exact-only mode.")

    async def _fail_combine(*args, **kwargs):
        raise AssertionError("Combiner should not run in exact-only mode.")

    rebuild_calls: list[list[str]] = []

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        rebuild_calls.append(sorted(active_store.graph.nodes()))
        assert batch_size == 32
        assert cooldown_seconds == 0.0
        return object()

    monkeypatch.setattr(engine, "_choose_matches", _fail_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fail_combine)
    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = engine.get_resolution_status(world_id)
    events = engine.drain_sse_events(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "complete"
    assert status["resolution_mode"] == "exact_only"
    assert status["resolved_entities"] == 2
    assert status["unresolved_entities"] == 1
    assert status["auto_resolved_pairs"] == 1
    assert status["new_nodes_since_last_completed_resolution"] == 0
    assert reloaded.get_node_count() == 2
    assert rebuild_calls == [["node-a", "node-c"]]
    assert all(event.get("phase") not in {"candidate_search", "chooser", "combiner"} for event in events)


def test_exact_then_ai_mode_runs_chooser_and_combiner(tmp_path, monkeypatch):
    world_id = "world-exact-then-ai"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="Alicia", description="Possible duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    rebuild_calls: list[list[str]] = []
    refreshed_merges: list[tuple[str, list[str]]] = []
    fake_unique_node_store = object()

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        rebuild_calls.append(sorted(active_store.graph.nodes()))
        assert batch_size == 32
        assert cooldown_seconds == 0.0
        return fake_unique_node_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        winner_id,
        loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        refreshed_merges.append((winner_id, list(loser_ids)))
        assert batch_size == 32
        assert cooldown_seconds == 0.0

    async def _fake_query_candidates(active_store, unique_node_vector_store, anchor_id, remaining_ids, _top_k, abort_event=None):
        assert active_store.world_id == world_id
        assert unique_node_vector_store is fake_unique_node_store
        assert anchor_id == "node-a"
        assert "node-b" in remaining_ids
        candidate = engine._node_snapshot(active_store, "node-b")
        assert candidate is not None
        candidate["score"] = 0.12
        return [candidate]

    async def _fake_choose(anchor, candidates, *, world_id=None):
        assert anchor["node_id"] == "node-a"
        assert candidates[0]["node_id"] == "node-b"
        assert world_id == "world-exact-then-ai"
        return ["node-b"], "Matched by test chooser"

    async def _fake_combine(nodes, *, world_id=None):
        assert {node["node_id"] for node in nodes} == {"node-a", "node-b"}
        assert world_id == "world-exact-then-ai"
        return "Alice Combined", "Merged entity"

    monkeypatch.setattr(engine, "_query_candidates", _fake_query_candidates)
    monkeypatch.setattr(engine, "_choose_matches", _fake_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fake_combine)
    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)

    asyncio.run(engine.start_entity_resolution(world_id, 25, False, True, "exact_then_ai"))

    status = engine.get_resolution_status(world_id)
    events = engine.drain_sse_events(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "complete"
    assert status["resolution_mode"] == "exact_then_ai"
    assert status["resolved_entities"] == 3
    assert status["unresolved_entities"] == 0
    assert reloaded.get_node_count() == 2
    assert rebuild_calls == [["node-a", "node-b", "node-c"]]
    assert refreshed_merges == [("node-a", ["node-b"])]
    assert any(event.get("phase") == "chooser" for event in events)
    assert any(event.get("phase") == "combiner" for event in events)


def test_exact_then_ai_rebuilds_unique_index_after_exact_pass_before_candidate_search(tmp_path, monkeypatch):
    world_id = "world-exact-pass-index-refresh"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Alicia", description="Possible duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-d", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    rebuild_calls: list[list[str]] = []
    fake_unique_node_store = object()

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        rebuild_calls.append(sorted(active_store.graph.nodes()))
        assert batch_size == 32
        assert cooldown_seconds == 0.0
        return fake_unique_node_store

    async def _fake_query_candidates(active_store, unique_node_vector_store, anchor_id, remaining_ids, _top_k, abort_event=None):
        assert unique_node_vector_store is fake_unique_node_store
        assert sorted(active_store.graph.nodes()) == ["node-a", "node-c", "node-d"]
        assert anchor_id == "node-c"
        return []

    async def _fail_choose(*args, **kwargs):
        raise AssertionError("Chooser should not run when no candidates are returned.")

    async def _fail_combine(*args, **kwargs):
        raise AssertionError("Combiner should not run when no candidates are returned.")

    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)
    monkeypatch.setattr(engine, "_query_candidates", _fake_query_candidates)
    monkeypatch.setattr(engine, "_choose_matches", _fail_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fail_combine)

    asyncio.run(engine.start_entity_resolution(world_id, 25, False, True, "exact_then_ai"))

    status = engine.get_resolution_status(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "complete"
    assert reloaded.get_node_count() == 3
    assert rebuild_calls == [["node-a", "node-c", "node-d"]]


def test_legacy_metadata_without_resolution_mode_maps_safely(tmp_path, monkeypatch):
    world_id = "world-legacy-mode"
    meta_path, _ = _prepare_world(tmp_path, monkeypatch, world_id)
    meta_path.write_text(
        json.dumps(
            {
                "entity_resolution_status": "idle",
                "entity_resolution_phase": "waiting",
                "entity_resolution_exact_pass": False,
            }
        ),
        encoding="utf-8",
    )

    status = engine.get_resolution_status(world_id)

    assert status["resolution_mode"] == "ai_only"
    assert status["include_normalized_exact_pass"] is False


def test_entity_resolution_status_exposes_embedding_controls(tmp_path, monkeypatch):
    world_id = "world-embed-controls-status"
    meta_path, _ = _prepare_world(tmp_path, monkeypatch, world_id)
    meta_path.write_text(
        json.dumps(
            {
                "entity_resolution_status": "idle",
                "entity_resolution_phase": "waiting",
                "entity_resolution_embedding_batch_size": 7,
                "entity_resolution_embedding_cooldown_seconds": 1.5,
            }
        ),
        encoding="utf-8",
    )

    status = engine.get_resolution_status(world_id)

    assert status["embedding_batch_size"] == 7
    assert status["embedding_cooldown_seconds"] == 1.5


def test_entity_resolution_status_tracks_new_nodes_since_last_completed_run(tmp_path, monkeypatch):
    world_id = "world-new-nodes-since-resolution"
    meta_path, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.save()

    async def _fail_choose(*args, **kwargs):
        raise AssertionError("Chooser should not run in exact-only mode.")

    async def _fail_combine(*args, **kwargs):
        raise AssertionError("Combiner should not run in exact-only mode.")

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        assert batch_size == 32
        assert cooldown_seconds == 0.0
        return object()

    monkeypatch.setattr(engine, "_choose_matches", _fail_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fail_combine)
    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = engine.get_resolution_status(world_id)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert status["new_nodes_since_last_completed_resolution"] == 0
    assert meta["entity_resolution_last_completed_graph_nodes"] == 1

    grown = graph_store.GraphStore(world_id)
    grown.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    grown.graph.add_node("node-d", display_name="Cara", description="Other", claims=[], source_chunks=[])
    grown.save()

    refreshed_status = engine.get_resolution_status(world_id)

    assert refreshed_status["new_nodes_since_last_completed_resolution"] == 2


def test_entity_resolution_status_leaves_new_nodes_unavailable_without_completion_baseline(tmp_path, monkeypatch):
    world_id = "world-new-nodes-no-baseline"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.save()

    status = engine.get_resolution_status(world_id)

    assert status["new_nodes_since_last_completed_resolution"] is None


def test_entity_resolution_start_uses_custom_embedding_controls(tmp_path, monkeypatch):
    world_id = "world-custom-embed-controls"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.save()

    rebuild_calls: list[tuple[list[str], int, float]] = []

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        rebuild_calls.append((sorted(active_store.graph.nodes()), batch_size, cooldown_seconds))
        return object()

    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only", 5, 1.25))

    status = engine.get_resolution_status(world_id)

    assert rebuild_calls == [(["node-a"], 5, 1.25)]
    assert status["embedding_batch_size"] == 5
    assert status["embedding_cooldown_seconds"] == 1.25


def test_abort_entity_resolution_preserves_non_running_state(tmp_path, monkeypatch):
    world_id = "world-abort-preserves-status"
    meta_path, _ = _prepare_world(tmp_path, monkeypatch, world_id)
    meta_path.write_text(
        json.dumps(
            {
                "ingestion_status": "complete",
                "entity_resolution_status": "complete",
                "entity_resolution_phase": "complete",
                "entity_resolution_message": "Entity resolution complete.",
            }
        ),
        encoding="utf-8",
    )

    engine.abort_entity_resolution(world_id)

    status = engine.get_resolution_status(world_id)

    assert status["status"] == "complete"
    assert status["phase"] == "complete"
    assert engine.drain_sse_events(world_id) == []


def test_abort_entity_resolution_emits_aborting_then_finishes_aborted(tmp_path, monkeypatch):
    world_id = "world-abort-active-run"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    engine.begin_entity_resolution_run(world_id, 50, False, True, "exact_only")
    engine.abort_entity_resolution(world_id)

    aborting_status = engine.get_resolution_status(world_id)
    aborting_events = engine.drain_sse_events(world_id)

    assert aborting_status["status"] == "in_progress"
    assert aborting_status["phase"] == "aborting"
    assert aborting_events[-1]["event"] == "status"
    assert aborting_events[-1]["phase"] == "aborting"

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    final_status = engine.get_resolution_status(world_id)
    final_events = engine.drain_sse_events(world_id)

    assert final_status["status"] == "aborted"
    assert any(event.get("event") == "aborted" for event in final_events)


def test_entity_resolution_startup_failure_clears_active_run_and_marks_error(tmp_path, monkeypatch):
    world_id = "world-startup-failure"
    _prepare_world(tmp_path, monkeypatch, world_id)

    engine.begin_entity_resolution_run(world_id, 50, False, True, "exact_only")
    monkeypatch.setattr(engine, "GraphStore", lambda _world_id: (_ for _ in ()).throw(RuntimeError("graph boom")))

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = engine.get_resolution_status(world_id)
    events = engine.drain_sse_events(world_id)

    assert status["status"] == "error"
    assert status["reason"] == "graph boom"
    assert any(event.get("event") == "error" for event in events)
    assert world_id not in engine._active_runs
    assert world_id not in engine._abort_events


def test_exact_only_failure_rolls_back_live_graph(tmp_path, monkeypatch):
    world_id = "world-exact-only-rollback"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    async def _boom_rebuild(*args, **kwargs):
        raise RuntimeError("rebuild failed")

    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _boom_rebuild)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = engine.get_resolution_status(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "error"
    assert status["reason"] == "rebuild failed"
    assert reloaded.get_node_count() == 3


def test_chooser_failure_fails_closed_without_live_graph_mutation(tmp_path, monkeypatch):
    world_id = "world-chooser-fail-closed"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="Alicia", description="Possible duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    fake_unique_node_store = object()

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        return fake_unique_node_store

    async def _fake_query_candidates(active_store, unique_node_vector_store, anchor_id, remaining_ids, _top_k, abort_event=None):
        candidate = engine._node_snapshot(active_store, "node-b")
        assert candidate is not None
        candidate["score"] = 0.1
        return [candidate]

    async def _boom_choose(*args, **kwargs):
        raise RuntimeError("chooser boom")

    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)
    monkeypatch.setattr(engine, "_query_candidates", _fake_query_candidates)
    monkeypatch.setattr(engine, "_choose_matches", _boom_choose)

    asyncio.run(engine.start_entity_resolution(world_id, 25, False, True, "exact_then_ai"))

    status = engine.get_resolution_status(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "error"
    assert status["reason"] == "chooser boom"
    assert reloaded.get_node_count() == 3


def test_exact_only_events_label_current_exact_match_group(tmp_path, monkeypatch):
    world_id = "world-exact-only-anchor-label"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.save()

    async def _fake_rebuild_unique_node_index(_vector_store, active_store, batch_size, cooldown_seconds, abort_event=None):
        return object()

    monkeypatch.setattr(engine, "_rebuild_unique_node_index", _fake_rebuild_unique_node_index)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    events = engine.drain_sse_events(world_id)

    assert any(event.get("current_anchor_label") == "Current Exact Match Group" for event in events)


def test_entity_resolution_router_thread_start_failure_rolls_back_run(tmp_path, monkeypatch):
    world_id = "world-router-thread-start-failure"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(entity_resolution_router, "_load_meta", lambda _world_id: {"ingestion_status": "complete", "sources": [{"status": "complete"}]})
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(entity_resolution_router, "audit_ingestion_integrity", lambda _world_id, **kwargs: {"world": {"failed_records": 0}})
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 0})

    class BrokenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(entity_resolution_router.threading, "Thread", BrokenThread)

    with pytest.raises(entity_resolution_router.HTTPException) as exc:
        asyncio.run(
            entity_resolution_router.entity_resolution_start(
                world_id,
                entity_resolution_router.EntityResolutionStartRequest(),
            )
        )

    status = engine.get_resolution_status(world_id)

    assert exc.value.status_code == 500
    assert status["status"] == "error"
    assert status["message"] == "Entity resolution failed to start."
    assert world_id not in engine._active_runs
    assert world_id not in engine._abort_events


def test_upsert_unique_node_snapshots_obeys_cooldown_and_abort(monkeypatch):
    class _FakeVectorStore:
        def __init__(self):
            self.upsert_calls: list[list[str]] = []

        def upsert_documents_embeddings(self, document_ids, texts, metadatas, embeddings):
            self.upsert_calls.append(list(document_ids))

    vector_store = _FakeVectorStore()
    node_snapshots = [
        {"node_id": "node-a", "display_name": "Alice", "description": "", "normalized_name": "alice"},
        {"node_id": "node-b", "display_name": "Bob", "description": "", "normalized_name": "bob"},
        {"node_id": "node-c", "display_name": "Cara", "description": "", "normalized_name": "cara"},
    ]
    abort_event = engine.threading.Event()
    sleep_calls: list[float] = []

    async def _fake_sleep_with_abort(expected_event, seconds):
        sleep_calls.append(seconds)
        expected_event.set()
        raise asyncio.CancelledError()

    embed_calls: list[list[str]] = []

    async def _fake_embed_texts_abortable(_vector_store, texts, *, abort_event=None):
        embed_calls.append(list(texts))
        return [[0.1] for _ in texts]

    monkeypatch.setattr(engine, "_embed_texts_abortable", _fake_embed_texts_abortable)
    monkeypatch.setattr(engine, "_sleep_with_abort", _fake_sleep_with_abort)

    try:
        asyncio.run(engine._upsert_unique_node_snapshots(vector_store, node_snapshots, 2, 0.5, abort_event))
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("Expected the cooldown abort to cancel the batch loop.")

    assert len(embed_calls) == 1
    assert len(vector_store.upsert_calls) == 1
    assert sleep_calls == [0.5]
