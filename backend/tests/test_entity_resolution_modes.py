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

    bootstrap_calls: list[str] = []
    refreshed_merges: list[tuple[str, list[str], int, float]] = []

    async def _fake_bootstrap_staged_unique_node_index(world_id_arg, stage_vector_store):
        bootstrap_calls.append(world_id_arg)
        return stage_vector_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        winner_id,
        loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        refreshed_merges.append((winner_id, list(loser_ids), batch_size, cooldown_seconds))
        assert batch_size == 32
        assert cooldown_seconds == 0.0

    monkeypatch.setattr(engine, "_choose_matches", _fail_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fail_combine)
    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = engine.get_resolution_status(world_id)
    events = engine.drain_sse_events(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "complete"
    assert status["resolution_mode"] == "exact_only"
    assert status["resolved_entities"] == 2
    assert status["unresolved_entities"] == 1
    assert status["embedding_completed_entities"] == 1
    assert status["embedding_total_entities"] == 1
    assert status["auto_resolved_pairs"] == 1
    assert status["new_nodes_since_last_completed_resolution"] == 0
    assert reloaded.get_node_count() == 2
    assert bootstrap_calls == [world_id]
    assert refreshed_merges == [("node-a", ["node-b"], 32, 0.0)]
    assert all(event.get("phase") not in {"candidate_search", "chooser", "combiner"} for event in events)


def test_exact_then_ai_mode_runs_chooser_and_combiner(tmp_path, monkeypatch):
    world_id = "world-exact-then-ai"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="Alicia", description="Possible duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    bootstrap_calls: list[str] = []
    refreshed_merges: list[tuple[str, list[str]]] = []
    fake_unique_node_store = object()

    async def _fake_bootstrap_staged_unique_node_index(world_id_arg, _stage_vector_store):
        bootstrap_calls.append(world_id_arg)
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

    async def _fake_query_candidates(active_store, unique_node_vector_store, anchor_id, remaining_ids, _top_k, abort_event=None, wait_callback=None):
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
    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)

    asyncio.run(engine.start_entity_resolution(world_id, 25, False, True, "exact_then_ai"))

    status = engine.get_resolution_status(world_id)
    events = engine.drain_sse_events(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "complete"
    assert status["resolution_mode"] == "exact_then_ai"
    assert status["resolved_entities"] == 3
    assert status["unresolved_entities"] == 0
    assert status["embedding_completed_entities"] == 1
    assert status["embedding_total_entities"] == 1
    assert reloaded.get_node_count() == 2
    assert bootstrap_calls == [world_id]
    assert refreshed_merges == [("node-a", ["node-b"])]
    assert any(event.get("phase") == "chooser" for event in events)
    assert any(event.get("phase") == "combiner" for event in events)


def test_exact_then_ai_uses_cloned_staged_index_after_exact_pass_before_candidate_search(tmp_path, monkeypatch):
    world_id = "world-exact-pass-stage-clone"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Alicia", description="Possible duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-d", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    bootstrap_calls: list[str] = []
    refreshed_merges: list[tuple[str, list[str]]] = []
    fake_unique_node_store = object()

    async def _fake_bootstrap_staged_unique_node_index(world_id_arg, _stage_vector_store):
        bootstrap_calls.append(world_id_arg)
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

    async def _fake_query_candidates(active_store, unique_node_vector_store, anchor_id, remaining_ids, _top_k, abort_event=None, wait_callback=None):
        assert unique_node_vector_store is fake_unique_node_store
        assert sorted(active_store.graph.nodes()) == ["node-a", "node-c", "node-d"]
        assert anchor_id == "node-c"
        return []

    async def _fail_choose(*args, **kwargs):
        raise AssertionError("Chooser should not run when no candidates are returned.")

    async def _fail_combine(*args, **kwargs):
        raise AssertionError("Combiner should not run when no candidates are returned.")

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)
    monkeypatch.setattr(engine, "_query_candidates", _fake_query_candidates)
    monkeypatch.setattr(engine, "_choose_matches", _fail_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fail_combine)

    asyncio.run(engine.start_entity_resolution(world_id, 25, False, True, "exact_then_ai"))

    status = engine.get_resolution_status(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "complete"
    assert reloaded.get_node_count() == 3
    assert bootstrap_calls == [world_id]
    assert refreshed_merges == [("node-a", ["node-b"])]


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


def test_fresh_world_without_saved_mode_defaults_status_to_exact_only(tmp_path, monkeypatch):
    world_id = "world-fresh-default-exact-only"
    _prepare_world(tmp_path, monkeypatch, world_id)

    status = engine.get_resolution_status(world_id)

    assert status["status"] == "idle"
    assert status["resolution_mode"] == "exact_only"
    assert status["include_normalized_exact_pass"] is True


def test_legacy_completed_metadata_without_resolution_mode_preserves_inferred_mode(tmp_path, monkeypatch):
    world_id = "world-legacy-complete-mode"
    meta_path, _ = _prepare_world(tmp_path, monkeypatch, world_id)
    meta_path.write_text(
        json.dumps(
            {
                "entity_resolution_status": "complete",
                "entity_resolution_phase": "complete",
                "entity_resolution_exact_pass": True,
            }
        ),
        encoding="utf-8",
    )

    status = engine.get_resolution_status(world_id)

    assert status["resolution_mode"] == "exact_then_ai"
    assert status["include_normalized_exact_pass"] is True


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
                "entity_resolution_embedding_completed_entities": 4,
                "entity_resolution_embedding_total_entities": 9,
            }
        ),
        encoding="utf-8",
    )

    status = engine.get_resolution_status(world_id)

    assert status["embedding_batch_size"] == 7
    assert status["embedding_cooldown_seconds"] == 1.5
    assert status["embedding_completed_entities"] == 4
    assert status["embedding_total_entities"] == 9


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

    async def _fake_bootstrap_staged_unique_node_index(_world_id, stage_vector_store):
        return stage_vector_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        _winner_id,
        _loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        assert batch_size == 32
        assert cooldown_seconds == 0.0

    monkeypatch.setattr(engine, "_choose_matches", _fail_choose)
    monkeypatch.setattr(engine, "_combine_entities", _fail_combine)
    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)

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

    refresh_calls: list[tuple[str, list[str], int, float]] = []

    async def _fake_bootstrap_staged_unique_node_index(_world_id, stage_vector_store):
        return stage_vector_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        winner_id,
        loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        refresh_calls.append((winner_id, list(loser_ids), batch_size, cooldown_seconds))

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only", 5, 1.25))

    status = engine.get_resolution_status(world_id)

    assert refresh_calls == [("node-a", ["node-b"], 5, 1.25)]
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

    async def _fake_bootstrap_staged_unique_node_index(_world_id, stage_vector_store):
        return stage_vector_store

    async def _boom_refresh(*args, **kwargs):
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _boom_refresh)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = engine.get_resolution_status(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "error"
    assert status["reason"] == "refresh failed"
    assert reloaded.get_node_count() == 3


def test_chooser_failure_fails_closed_without_live_graph_mutation(tmp_path, monkeypatch):
    world_id = "world-chooser-fail-closed"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="Alicia", description="Possible duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    fake_unique_node_store = object()

    async def _fake_bootstrap_staged_unique_node_index(_world_id, _stage_vector_store):
        return fake_unique_node_store

    async def _fake_query_candidates(active_store, unique_node_vector_store, anchor_id, remaining_ids, _top_k, abort_event=None, wait_callback=None):
        candidate = engine._node_snapshot(active_store, "node-b")
        assert candidate is not None
        candidate["score"] = 0.1
        return [candidate]

    async def _boom_choose(*args, **kwargs):
        raise RuntimeError("chooser boom")

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_query_candidates", _fake_query_candidates)
    monkeypatch.setattr(engine, "_choose_matches", _boom_choose)

    asyncio.run(engine.start_entity_resolution(world_id, 25, False, True, "exact_then_ai"))

    status = engine.get_resolution_status(world_id)
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "error"
    assert status["reason"] == "chooser boom"
    assert reloaded.get_node_count() == 3


def test_exact_only_commit_pending_recovery_finishes_truthfully_after_meta_write_failure(tmp_path, monkeypatch):
    world_id = "world-commit-pending-recovery"
    meta_path, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    async def _fake_bootstrap_staged_unique_node_index(_world_id, stage_vector_store):
        return stage_vector_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        _winner_id,
        _loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        assert batch_size == 32
        assert cooldown_seconds == 0.0

    original_update_meta_from_state = engine._update_meta_from_state
    failed_once = {"value": False}

    def _flaky_update_meta_from_state(world_id_arg: str, state: dict, graph_store_arg=None):
        original_update_meta_from_state(world_id_arg, state, graph_store_arg)
        if state.get("commit_state") == "committed" and not failed_once["value"]:
            failed_once["value"] = True
            raise PermissionError("Access is denied")

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)
    monkeypatch.setattr(engine, "_update_meta_from_state", _flaky_update_meta_from_state)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    interrupted_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    interrupted_graph = graph_store.GraphStore(world_id)

    assert interrupted_meta["entity_resolution_commit_state"] == "commit_pending"
    assert interrupted_meta["entity_resolution_commit_pending"] is True
    assert interrupted_graph.get_node_count() == 2

    status = engine.get_resolution_status(world_id)
    final_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert status["status"] == "complete"
    assert status["commit_state"] == "committed"
    assert final_meta["entity_resolution_commit_state"] == "committed"
    assert "entity_resolution_commit_pending" not in final_meta


def test_staged_vector_snapshot_failure_leaves_live_graph_unmutated(tmp_path, monkeypatch):
    world_id = "world-staged-snapshot-failure"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.graph.add_node("node-c", display_name="Bob", description="Other", claims=[], source_chunks=[])
    store.save()

    replace_called = {"value": False}
    snapshot_calls = {"value": 0}

    async def _fake_bootstrap_staged_unique_node_index(_world_id, stage_vector_store):
        return stage_vector_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        _winner_id,
        _loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        assert batch_size == 32
        assert cooldown_seconds == 0.0

    def _boom_snapshot(*args, **kwargs):
        snapshot_calls["value"] += 1
        if snapshot_calls["value"] >= 2:
            raise RuntimeError("snapshot failed")
        return []

    def _record_replace(*args, **kwargs):
        replace_called["value"] = True

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)
    monkeypatch.setattr(engine, "_snapshot_vector_store_records", _boom_snapshot)
    monkeypatch.setattr(engine, "_replace_vector_store_records", _record_replace)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    status = dict(engine._states.get(world_id, {}))
    reloaded = graph_store.GraphStore(world_id)

    assert status["status"] == "error"
    assert status["reason"] == "snapshot failed"
    assert status["commit_state"] == "commit_pending"
    assert replace_called["value"] is False
    assert reloaded.get_node_count() == 3


def test_exact_only_events_label_current_exact_match_group(tmp_path, monkeypatch):
    world_id = "world-exact-only-anchor-label"
    _, store = _prepare_world(tmp_path, monkeypatch, world_id)
    store.graph.add_node("node-a", display_name="Alice", description="Primary", claims=[], source_chunks=[])
    store.graph.add_node("node-b", display_name="ALICE", description="Duplicate", claims=[], source_chunks=[])
    store.save()

    async def _fake_bootstrap_staged_unique_node_index(_world_id, stage_vector_store):
        return stage_vector_store

    async def _fake_refresh_unique_node_index_after_merge(
        _vector_store,
        _active_store,
        _winner_id,
        _loser_ids,
        batch_size,
        cooldown_seconds,
        abort_event=None,
    ):
        assert batch_size == 32
        assert cooldown_seconds == 0.0

    monkeypatch.setattr(engine, "_bootstrap_staged_unique_node_index", _fake_bootstrap_staged_unique_node_index)
    monkeypatch.setattr(engine, "_refresh_unique_node_index_after_merge", _fake_refresh_unique_node_index_after_merge)

    asyncio.run(engine.start_entity_resolution(world_id, 50, False, True, "exact_only"))

    events = engine.drain_sse_events(world_id)

    assert any(event.get("current_anchor_label") == "Current Exact Match Group" for event in events)


def test_entity_resolution_start_rejects_world_level_audit_blockers(tmp_path, monkeypatch):
    world_id = "world-router-blocking-issues"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(entity_resolution_router, "_load_meta", lambda _world_id: {"ingestion_status": "complete", "sources": [{"status": "complete"}]})
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 0,
                "current_unique_nodes": 4,
                "embedded_unique_nodes": 4,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [{
                "code": "unique_node_vector_store_unreadable",
                "message": "Could not read the unique-node index while auditing this world.",
            }],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 0})

    with pytest.raises(entity_resolution_router.HTTPException) as exc:
        asyncio.run(
            entity_resolution_router.entity_resolution_start(
                world_id,
                entity_resolution_router.EntityResolutionStartRequest(),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "Finish unique-node embedding repair before running Exact Only. "
        "Exact Only now requires every current graph node to already have a valid unique-node embedding."
    )


def test_entity_resolution_router_thread_start_failure_rolls_back_run(tmp_path, monkeypatch):
    world_id = "world-router-thread-start-failure"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(entity_resolution_router, "_load_meta", lambda _world_id: {"ingestion_status": "complete", "sources": [{"status": "complete"}]})
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 0,
                "current_unique_nodes": 1,
                "embedded_unique_nodes": 1,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [],
        },
    )
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
    assert exc.value.detail == "thread start failed"
    assert status["status"] == "error"
    assert status["message"] == "Entity resolution failed during startup. No graph changes were kept."
    assert status["reason"] == "thread start failed"
    assert world_id not in engine._active_runs
    assert world_id not in engine._abort_events


def test_entity_resolution_router_begin_run_failure_returns_structured_startup_error(tmp_path, monkeypatch):
    world_id = "world-router-begin-run-failure"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(entity_resolution_router, "_load_meta", lambda _world_id: {"ingestion_status": "complete", "sources": [{"status": "complete"}]})
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 0,
                "current_unique_nodes": 1,
                "embedded_unique_nodes": 1,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 0})
    monkeypatch.setattr(
        entity_resolution_router,
        "begin_entity_resolution_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("begin run failed")),
    )

    with pytest.raises(entity_resolution_router.HTTPException) as exc:
        asyncio.run(
            entity_resolution_router.entity_resolution_start(
                world_id,
                entity_resolution_router.EntityResolutionStartRequest(),
            )
        )

    status = engine.get_resolution_status(world_id)

    assert exc.value.status_code == 500
    assert exc.value.detail == "begin run failed"
    assert status["status"] == "error"
    assert status["message"] == "Entity resolution failed during startup. No graph changes were kept."
    assert status["reason"] == "begin run failed"
    assert world_id not in engine._active_runs
    assert world_id not in engine._abort_events


def test_entity_resolution_start_without_mode_defaults_to_exact_only(tmp_path, monkeypatch):
    world_id = "world-router-default-exact-only"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(entity_resolution_router, "_load_meta", lambda _world_id: {"ingestion_status": "complete", "sources": [{"status": "complete"}]})
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 0,
                "current_unique_nodes": 1,
                "embedded_unique_nodes": 1,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 0})

    captured: dict[str, object] = {}

    def _fake_begin_entity_resolution_run(*args, **kwargs):
        captured["begin_mode"] = args[4]
        return {"status": "in_progress", "resolution_mode": args[4]}

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured["thread_args"] = kwargs.get("args")

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(entity_resolution_router, "begin_entity_resolution_run", _fake_begin_entity_resolution_run)
    monkeypatch.setattr(entity_resolution_router.threading, "Thread", FakeThread)

    response = asyncio.run(
        entity_resolution_router.entity_resolution_start(
            world_id,
            entity_resolution_router.EntityResolutionStartRequest(),
        )
    )

    assert captured["begin_mode"] == "exact_only"
    assert captured["thread_args"][4] == "exact_only"
    assert response["state"]["resolution_mode"] == "exact_only"
    assert captured["thread_started"] is True


def test_entity_resolution_start_allows_exact_only_when_only_chunk_level_failures_remain(tmp_path, monkeypatch):
    world_id = "world-router-partial-exact-only"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(
        entity_resolution_router,
        "_load_meta",
        lambda _world_id: {
            "ingestion_status": "partial_failure",
            "sources": [{"status": "partial_failure"}],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 12,
                "current_unique_nodes": 4,
                "embedded_unique_nodes": 4,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [
                {"code": "chunk_vector_store_unreadable", "message": "chunk vectors are unreadable"},
            ],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 3})

    captured: dict[str, object] = {}

    def _fake_begin_entity_resolution_run(*args, **kwargs):
        captured["begin_mode"] = args[4]
        return {"status": "in_progress", "resolution_mode": args[4]}

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured["thread_args"] = kwargs.get("args")

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(entity_resolution_router, "begin_entity_resolution_run", _fake_begin_entity_resolution_run)
    monkeypatch.setattr(entity_resolution_router.threading, "Thread", FakeThread)

    response = asyncio.run(
        entity_resolution_router.entity_resolution_start(
            world_id,
            entity_resolution_router.EntityResolutionStartRequest(resolution_mode="exact_only"),
        )
    )

    assert captured["begin_mode"] == "exact_only"
    assert captured["thread_args"][4] == "exact_only"
    assert response["state"]["resolution_mode"] == "exact_only"
    assert captured["thread_started"] is True


def test_entity_resolution_start_rejects_exact_only_when_unique_node_embeddings_are_incomplete(tmp_path, monkeypatch):
    world_id = "world-router-partial-exact-only-unique-node-gap"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(
        entity_resolution_router,
        "_load_meta",
        lambda _world_id: {
            "ingestion_status": "partial_failure",
            "sources": [{"status": "partial_failure"}],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 12,
                "current_unique_nodes": 4,
                "embedded_unique_nodes": 3,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 3})

    with pytest.raises(entity_resolution_router.HTTPException) as exc:
        asyncio.run(
            entity_resolution_router.entity_resolution_start(
                world_id,
                entity_resolution_router.EntityResolutionStartRequest(resolution_mode="exact_only"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        "Finish unique-node embedding repair before running Exact Only. "
        "Exact Only now requires every current graph node to already have a valid unique-node embedding."
    )


def test_entity_resolution_start_rejects_partial_world_for_exact_then_ai(tmp_path, monkeypatch):
    world_id = "world-router-partial-exact-then-ai"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(
        entity_resolution_router,
        "_load_meta",
        lambda _world_id: {
            "ingestion_status": "partial_failure",
            "sources": [{"status": "partial_failure"}],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 2,
                "current_unique_nodes": 4,
                "embedded_unique_nodes": 4,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 0})

    with pytest.raises(entity_resolution_router.HTTPException) as exc:
        asyncio.run(
            entity_resolution_router.entity_resolution_start(
                world_id,
                entity_resolution_router.EntityResolutionStartRequest(resolution_mode="exact_then_ai"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Finish ingestion and repair source failures before running exact + chooser/combiner."


def test_entity_resolution_start_preserves_explicit_mode_selection(tmp_path, monkeypatch):
    world_id = "world-router-explicit-mode"
    _prepare_world(tmp_path, monkeypatch, world_id)

    monkeypatch.setattr(entity_resolution_router, "_load_meta", lambda _world_id: {"ingestion_status": "complete", "sources": [{"status": "complete"}]})
    monkeypatch.setattr(entity_resolution_router, "get_resolution_status", lambda _world_id: {"status": "idle"})
    monkeypatch.setattr(entity_resolution_router, "has_active_ingestion_run", lambda _world_id: False)
    monkeypatch.setattr(
        entity_resolution_router,
        "audit_ingestion_integrity",
        lambda _world_id, **kwargs: {
            "world": {
                "failed_records": 0,
                "current_unique_nodes": 1,
                "embedded_unique_nodes": 1,
                "stale_unique_node_vectors": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(entity_resolution_router, "get_safety_review_summary", lambda _world_id: {"unresolved_reviews": 0})

    captured: dict[str, object] = {}

    def _fake_begin_entity_resolution_run(*args, **kwargs):
        captured["begin_mode"] = args[4]
        return {"status": "in_progress", "resolution_mode": args[4]}

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured["thread_args"] = kwargs.get("args")

        def start(self):
            captured["thread_started"] = True

    monkeypatch.setattr(entity_resolution_router, "begin_entity_resolution_run", _fake_begin_entity_resolution_run)
    monkeypatch.setattr(entity_resolution_router.threading, "Thread", FakeThread)

    response = asyncio.run(
        entity_resolution_router.entity_resolution_start(
            world_id,
            entity_resolution_router.EntityResolutionStartRequest(resolution_mode="exact_then_ai"),
        )
    )

    assert captured["begin_mode"] == "exact_then_ai"
    assert captured["thread_args"][4] == "exact_then_ai"
    assert response["state"]["resolution_mode"] == "exact_then_ai"
    assert captured["thread_started"] is True


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

    async def _fake_embed_texts_abortable(_vector_store, texts, *, abort_event=None, wait_callback=None):
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
