"""Post-ingestion entity resolution pipeline with SSE progress updates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Literal

from .agents import _call_agent
from .config import load_settings, world_meta_path
from .entity_text import build_unique_node_document
from .graph_store import GraphStore
from .key_manager import get_key_manager
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

_abort_events: dict[str, threading.Event] = {}
_sse_queues: dict[str, list[dict[str, Any]]] = {}
_sse_locks: dict[str, threading.Lock] = {}
_states: dict[str, dict[str, Any]] = {}
_state_locks: dict[str, threading.Lock] = {}
_active_runs: set[str] = set()
_STALE_RUN_GRACE_SECONDS = 15
_UNIQUE_NODE_REBUILD_BATCH_SIZE = 32
_UNIQUE_NODE_REBUILD_COOLDOWN_SECONDS = 0.0

EntityResolutionMode = Literal["exact_only", "exact_then_ai", "ai_only"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_embedding_batch_size(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return _UNIQUE_NODE_REBUILD_BATCH_SIZE


def _normalize_embedding_cooldown_seconds(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return _UNIQUE_NODE_REBUILD_COOLDOWN_SECONDS


def resolve_entity_resolution_mode(
    resolution_mode: str | None,
    include_normalized_exact_pass: bool = True,
) -> EntityResolutionMode:
    if resolution_mode == "exact_only":
        return "exact_only"
    if resolution_mode == "exact_then_ai":
        return "exact_then_ai"
    return "exact_then_ai" if include_normalized_exact_pass else "ai_only"


def _mode_uses_exact_pass(resolution_mode: EntityResolutionMode) -> bool:
    return resolution_mode != "ai_only"


def _mode_uses_ai_pass(resolution_mode: EntityResolutionMode) -> bool:
    return resolution_mode != "exact_only"


def _is_stale_in_progress(state: dict[str, Any]) -> bool:
    if state.get("status") != "in_progress":
        return False
    updated_at = state.get("updated_at")
    if not isinstance(updated_at, str):
        return False
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - updated).total_seconds() > _STALE_RUN_GRACE_SECONDS


def _get_lock(lock_map: dict[str, threading.Lock], world_id: str) -> threading.Lock:
    if world_id not in lock_map:
        lock_map[world_id] = threading.Lock()
    return lock_map[world_id]


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_meta(world_id: str, meta: dict) -> None:
    path = world_meta_path(world_id)
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(str(tmp), str(path))


def clear_sse_queue(world_id: str) -> None:
    with _get_lock(_sse_locks, world_id):
        _sse_queues[world_id] = []


def push_sse_event(world_id: str, event: dict[str, Any]) -> None:
    with _get_lock(_sse_locks, world_id):
        _sse_queues.setdefault(world_id, []).append(event)


def drain_sse_events(world_id: str) -> list[dict[str, Any]]:
    with _get_lock(_sse_locks, world_id):
        events = list(_sse_queues.get(world_id, []))
        _sse_queues[world_id] = []
        return events


def _set_state(world_id: str, **updates: Any) -> dict[str, Any]:
    with _get_lock(_state_locks, world_id):
        current = dict(_states.get(world_id, {}))
        current.update(updates)
        current["updated_at"] = _now_iso()
        _states[world_id] = current
        return current


def _mark_run_stale(world_id: str) -> dict[str, Any]:
    state = _set_state(
        world_id,
        status="aborted",
        phase="aborted",
        message="Previous entity-resolution run is no longer active.",
        reason="stale_run",
        current_anchor=None,
        current_candidates=[],
    )
    _update_meta_from_state(world_id, state)
    return state


def _coerce_non_negative_int(value: Any) -> int | None:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _get_current_graph_node_count(world_id: str, meta: dict[str, Any]) -> int | None:
    try:
        return GraphStore(world_id).get_node_count()
    except Exception:
        return _coerce_non_negative_int(meta.get("total_nodes"))


def _get_new_nodes_since_last_completed_resolution(world_id: str, meta: dict[str, Any]) -> int | None:
    baseline = _coerce_non_negative_int(meta.get("entity_resolution_last_completed_graph_nodes"))
    current_total = _get_current_graph_node_count(world_id, meta)
    if baseline is None or current_total is None:
        return None
    return max(0, current_total - baseline)


def _with_new_node_summary(world_id: str, payload: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    enriched = dict(payload)
    if meta is None:
        if not world_meta_path(world_id).exists():
            enriched["new_nodes_since_last_completed_resolution"] = None
            return enriched
        meta = _load_meta(world_id)
    enriched["new_nodes_since_last_completed_resolution"] = _get_new_nodes_since_last_completed_resolution(world_id, meta)
    return enriched


def get_resolution_status(world_id: str) -> dict[str, Any]:
    with _get_lock(_state_locks, world_id):
        current = dict(_states.get(world_id, {}))

    if current:
        if world_id not in _active_runs and _is_stale_in_progress(current):
            return _mark_run_stale(world_id)
        return _with_new_node_summary(world_id, current)

    if not world_meta_path(world_id).exists():
        return {}

    meta = _load_meta(world_id)
    meta_like_state = {
        "status": meta.get("entity_resolution_status"),
        "updated_at": meta.get("entity_resolution_updated_at"),
    }
    if world_id not in _active_runs and _is_stale_in_progress(meta_like_state):
        return _mark_run_stale(world_id)
    settings = load_settings()
    resolution_mode = resolve_entity_resolution_mode(
        meta.get("entity_resolution_mode"),
        meta.get("entity_resolution_exact_pass", True),
    )
    return _with_new_node_summary(
        world_id,
        {
        "status": meta.get("entity_resolution_status", "idle"),
        "phase": meta.get("entity_resolution_phase"),
        "message": meta.get("entity_resolution_message"),
        "reason": meta.get("entity_resolution_reason"),
        "top_k": meta.get("entity_resolution_top_k", settings.get("entity_resolution_top_k", 50)),
        "embedding_batch_size": _normalize_embedding_batch_size(
            meta.get("entity_resolution_embedding_batch_size", _UNIQUE_NODE_REBUILD_BATCH_SIZE)
        ),
        "embedding_cooldown_seconds": _normalize_embedding_cooldown_seconds(
            meta.get("entity_resolution_embedding_cooldown_seconds", _UNIQUE_NODE_REBUILD_COOLDOWN_SECONDS)
        ),
        "resolved_entities": meta.get("entity_resolution_resolved_entities", 0),
        "unresolved_entities": meta.get("entity_resolution_unresolved_entities", 0),
        "auto_resolved_pairs": meta.get("entity_resolution_auto_resolved_pairs", 0),
        "total_entities": meta.get("entity_resolution_total_entities", 0),
        "resolution_mode": resolution_mode,
        "review_mode": meta.get("entity_resolution_review_mode", False),
        "include_normalized_exact_pass": _mode_uses_exact_pass(resolution_mode),
        "can_resume": False,
        },
        meta,
    )


def get_resolution_current(world_id: str) -> dict[str, Any]:
    return get_resolution_status(world_id)


def abort_entity_resolution(world_id: str) -> None:
    if world_id not in _active_runs:
        return
    abort_event = _abort_events.get(world_id)
    if abort_event is None:
        abort_event = threading.Event()
        _abort_events[world_id] = abort_event
    abort_event.set()
    state = _set_state(
        world_id,
        status="in_progress",
        phase="aborting",
        message="Aborting entity resolution.",
        reason=None,
    )
    _update_meta_from_state(world_id, state)
    push_sse_event(world_id, {"event": "status", **state})


def fail_entity_resolution_startup(
    world_id: str,
    message: str,
    *,
    reason: str | None = None,
    graph_store: GraphStore | None = None,
) -> dict[str, Any]:
    state = _set_state(
        world_id,
        status="error",
        phase="error",
        message=message,
        reason=reason,
        current_anchor=None,
        current_candidates=[],
    )
    _update_meta_from_state(world_id, state, graph_store)
    push_sse_event(world_id, {"event": "error", **state})
    _active_runs.discard(world_id)
    _abort_events.pop(world_id, None)
    return state


def begin_entity_resolution_run(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
    resolution_mode: EntityResolutionMode,
    embedding_batch_size: int | None = None,
    embedding_cooldown_seconds: float | None = None,
) -> dict[str, Any]:
    """Mark a run as active immediately so status checks don't race the background task."""
    clear_sse_queue(world_id)
    _abort_events[world_id] = threading.Event()
    _active_runs.add(world_id)
    normalized_embedding_batch_size = _normalize_embedding_batch_size(embedding_batch_size)
    normalized_embedding_cooldown_seconds = _normalize_embedding_cooldown_seconds(embedding_cooldown_seconds)
    state = _set_state(
        world_id,
        status="in_progress",
        phase="preparing",
        message="Preparing entity resolution.",
        reason=None,
        top_k=top_k,
        embedding_batch_size=normalized_embedding_batch_size,
        embedding_cooldown_seconds=normalized_embedding_cooldown_seconds,
        resolution_mode=resolution_mode,
        review_mode=review_mode,
        include_normalized_exact_pass=_mode_uses_exact_pass(resolution_mode),
        total_entities=0,
        resolved_entities=0,
        unresolved_entities=0,
        auto_resolved_pairs=0,
        current_anchor=None,
        current_candidates=[],
        can_resume=False,
    )
    _update_meta_from_state(world_id, state)
    return state


def _normalize_display_name(value: str) -> str:
    normalized = value.casefold()
    normalized = re.sub(r"[_\-]+", " ", normalized)
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalized_id_from_name(value: str) -> str:
    normalized = _normalize_display_name(value)
    return normalized.replace(" ", "_")


def _dedupe_jsonable(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    output: list[Any] = []
    for item in items:
        token = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if token in seen:
            continue
        seen.add(token)
        output.append(item)
    return output


def _node_snapshot(graph_store: GraphStore, node_id: str) -> dict[str, Any] | None:
    graph = graph_store.graph
    if node_id not in graph.nodes:
        return None
    attrs = graph.nodes[node_id]
    claims = attrs.get("claims", [])
    source_chunks = attrs.get("source_chunks", [])
    if isinstance(claims, str):
        try:
            claims = json.loads(claims)
        except json.JSONDecodeError:
            claims = []
    if isinstance(source_chunks, str):
        try:
            source_chunks = json.loads(source_chunks)
        except json.JSONDecodeError:
            source_chunks = []
    return {
        "node_id": node_id,
        "display_name": attrs.get("display_name", ""),
        "description": attrs.get("description", ""),
        "normalized_name": _normalize_display_name(attrs.get("display_name", "")),
        "claims": claims,
        "source_chunks": source_chunks,
    }


def _entity_document(node: dict[str, Any]) -> str:
    return build_unique_node_document(node)


def _pick_fallback_name(nodes: list[dict[str, Any]]) -> str:
    return max(
        (str(node.get("display_name", "")).strip() for node in nodes if str(node.get("display_name", "")).strip()),
        key=len,
        default="Merged Entity",
    )


def _pick_fallback_description(nodes: list[dict[str, Any]]) -> str:
    descriptions = [str(node.get("description", "")).strip() for node in nodes if str(node.get("description", "")).strip()]
    if not descriptions:
        return ""
    unique = _dedupe_jsonable(descriptions)
    return "\n\n".join(unique)


def _combine_exact_match_group(nodes: list[dict[str, Any]]) -> tuple[str, str]:
    """Merge exact-normalized matches without spending model calls."""
    return _pick_fallback_name(nodes), _pick_fallback_description(nodes)


def _get_embedding_api_key() -> str:
    api_key, _ = get_key_manager().wait_for_available_key()
    return api_key


def _build_unique_node_metadata(node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("node_id", "")).strip()
    return {
        "node_id": node_id,
        "display_name": str(node.get("display_name", "")).strip(),
        "normalized_name": str(node.get("normalized_name", "")).strip(),
    }


def _get_unique_node_vector_store(world_id: str) -> VectorStore:
    return VectorStore(world_id, collection_suffix="unique_nodes")


async def _sleep_with_abort(expected_event: threading.Event, seconds: float) -> None:
    if seconds <= 0:
        return
    aborted = await asyncio.to_thread(expected_event.wait, seconds)
    if aborted:
        raise asyncio.CancelledError()


async def _upsert_unique_node_snapshots(
    unique_node_vector_store: VectorStore,
    node_snapshots: list[dict[str, Any]],
    batch_size: int,
    cooldown_seconds: float,
    abort_event: threading.Event | None = None,
) -> int:
    normalized_nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for node in node_snapshots:
        node_id = str(node.get("node_id", "")).strip()
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        normalized_nodes.append(node)

    if not normalized_nodes:
        return 0

    api_key = _get_embedding_api_key()
    total_written = 0
    normalized_batch_size = _normalize_embedding_batch_size(batch_size)
    normalized_cooldown_seconds = _normalize_embedding_cooldown_seconds(cooldown_seconds)
    for start in range(0, len(normalized_nodes), normalized_batch_size):
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError()
        batch = normalized_nodes[start:start + normalized_batch_size]
        texts = [_entity_document(node) for node in batch]
        embeddings = unique_node_vector_store.embed_texts(texts, api_key)
        unique_node_vector_store.upsert_documents_embeddings(
            document_ids=[str(node["node_id"]) for node in batch],
            texts=texts,
            metadatas=[_build_unique_node_metadata(node) for node in batch],
            embeddings=embeddings,
        )
        total_written += len(batch)
        has_more_batches = start + normalized_batch_size < len(normalized_nodes)
        if abort_event is not None and has_more_batches:
            await _sleep_with_abort(abort_event, normalized_cooldown_seconds)
    return total_written


async def _rebuild_unique_node_index(
    world_id: str,
    graph_store: GraphStore,
    batch_size: int,
    cooldown_seconds: float,
    abort_event: threading.Event | None = None,
) -> VectorStore:
    unique_node_vector_store = _get_unique_node_vector_store(world_id)
    unique_node_vector_store.drop_collection()

    node_snapshots = [
        node
        for node in (_node_snapshot(graph_store, node_id) for node_id in sorted(graph_store.graph.nodes()))
        if node
    ]
    await _upsert_unique_node_snapshots(
        unique_node_vector_store,
        node_snapshots,
        batch_size=batch_size,
        cooldown_seconds=cooldown_seconds,
        abort_event=abort_event,
    )
    return unique_node_vector_store


async def _refresh_unique_node_index_after_merge(
    unique_node_vector_store: VectorStore,
    graph_store: GraphStore,
    winner_id: str,
    loser_ids: list[str],
    batch_size: int,
    cooldown_seconds: float,
    abort_event: threading.Event | None = None,
) -> None:
    unique_node_vector_store.delete_documents(loser_ids)
    winner = _node_snapshot(graph_store, winner_id)
    if winner:
        await _upsert_unique_node_snapshots(
            unique_node_vector_store,
            [winner],
            batch_size=batch_size,
            cooldown_seconds=cooldown_seconds,
            abort_event=abort_event,
        )
    else:
        unique_node_vector_store.delete_document(winner_id)


def _query_candidates(
    graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    anchor_id: str,
    remaining_ids: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    anchor = _node_snapshot(graph_store, anchor_id)
    if not anchor:
        return []

    collection_count = unique_node_vector_store.count()
    if collection_count <= 1:
        return []

    api_key = _get_embedding_api_key()
    remaining_set = set(remaining_ids)
    raw_results = unique_node_vector_store.query(
        _entity_document(anchor),
        api_key=api_key,
        n_results=collection_count,
    )

    candidates: list[dict[str, Any]] = []
    for result in raw_results:
        metadata = result.get("metadata", {}) or {}
        node_id = result.get("id")
        if isinstance(metadata, dict):
            node_id = metadata.get("node_id") or node_id
        if not isinstance(node_id, str) or node_id == anchor_id or node_id not in remaining_set:
            continue
        node = _node_snapshot(graph_store, node_id)
        if not node:
            continue
        node["score"] = result.get("distance")
        candidates.append(node)
        if len(candidates) >= top_k:
            break
    return candidates


async def _choose_matches(
    anchor: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    world_id: str,
) -> tuple[list[str], str]:
    if not candidates:
        return [], "No candidates were available."

    settings = load_settings()
    model_name = settings.get("default_model_entity_chooser", "gemini-flash-latest")
    payload = json.dumps(
        {
            "anchor": anchor,
            "candidates": candidates,
        },
        ensure_ascii=False,
    )

    try:
        parsed, _ = await _call_agent(
            prompt_key="entity_resolution_chooser_prompt",
            user_content=payload,
            model_name=model_name,
            temperature=0.1,
            world_id=world_id,
        )
    except Exception as exc:
        logger.warning("Entity chooser failed, falling back to no matches: %s", exc)
        return [], f"Chooser failed: {exc}"

    chosen_ids = parsed.get("chosen_ids", []) if isinstance(parsed, dict) else []
    if not isinstance(chosen_ids, list):
        chosen_ids = []
    chosen_ids = [node_id for node_id in chosen_ids if isinstance(node_id, str)]
    reasoning = parsed.get("reasoning", "") if isinstance(parsed, dict) else ""
    if not isinstance(reasoning, str):
        reasoning = ""
    return chosen_ids, reasoning


async def _combine_entities(nodes: list[dict[str, Any]], *, world_id: str) -> tuple[str, str]:
    settings = load_settings()
    model_name = settings.get("default_model_entity_combiner", "gemini-flash-lite-latest")
    payload = json.dumps({"entities": nodes}, ensure_ascii=False)

    try:
        parsed, _ = await _call_agent(
            prompt_key="entity_resolution_combiner_prompt",
            user_content=payload,
            model_name=model_name,
            temperature=0.2,
            world_id=world_id,
        )
    except Exception as exc:
        logger.warning("Entity combiner failed, using fallback merge text: %s", exc)
        return _pick_fallback_name(nodes), _pick_fallback_description(nodes)

    display_name = parsed.get("display_name") if isinstance(parsed, dict) else None
    description = parsed.get("description") if isinstance(parsed, dict) else None
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = _pick_fallback_name(nodes)
    if not isinstance(description, str):
        description = _pick_fallback_description(nodes)
    return display_name.strip(), description.strip()


def _merge_group(
    graph_store: GraphStore,
    winner_id: str,
    loser_ids: list[str],
    display_name: str,
    description: str,
) -> None:
    graph = graph_store.graph
    if winner_id not in graph.nodes:
        return

    winner_attrs = graph.nodes[winner_id]
    merged_claims: list[Any] = list(winner_attrs.get("claims", []))
    merged_source_chunks: list[Any] = list(winner_attrs.get("source_chunks", []))

    for loser_id in loser_ids:
        if loser_id not in graph.nodes or loser_id == winner_id:
            continue

        loser_attrs = graph.nodes[loser_id]
        merged_claims.extend(loser_attrs.get("claims", []))
        merged_source_chunks.extend(loser_attrs.get("source_chunks", []))

        if graph.is_multigraph():
            incident_edges = [
                (u, v, dict(attrs))
                for u, v, _, attrs in list(graph.edges(keys=True, data=True))
                if u == loser_id or v == loser_id
            ]
        else:
            incident_edges = [
                (u, v, dict(attrs))
                for u, v, attrs in list(graph.edges(data=True))
                if u == loser_id or v == loser_id
            ]

        for source_id, target_id, attrs in incident_edges:
            rewired_source = winner_id if source_id == loser_id else source_id
            rewired_target = winner_id if target_id == loser_id else target_id
            graph.add_edge(rewired_source, rewired_target, **attrs)

        graph.remove_node(loser_id)

    winner_attrs = graph.nodes[winner_id]
    winner_attrs["display_name"] = display_name
    winner_attrs["description"] = description
    winner_attrs["normalized_id"] = _normalized_id_from_name(display_name)
    winner_attrs["claims"] = _dedupe_jsonable(merged_claims)
    winner_attrs["source_chunks"] = _dedupe_jsonable(merged_source_chunks)
    winner_attrs["updated_at"] = _now_iso()


def _group_exact_matches(graph_store: GraphStore, remaining_ids: list[str]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    graph = graph_store.graph
    for node_id in remaining_ids:
        if node_id not in graph.nodes:
            continue
        normalized = _normalize_display_name(graph.nodes[node_id].get("display_name", ""))
        if not normalized:
            continue
        groups.setdefault(normalized, []).append(node_id)
    return [group for group in groups.values() if len(group) > 1]


def _ensure_not_aborted(world_id: str, expected_event: threading.Event) -> None:
    if expected_event.is_set() or _abort_events.get(world_id) is not expected_event:
        raise asyncio.CancelledError()


def _update_meta_from_state(world_id: str, state: dict[str, Any], graph_store: GraphStore | None = None) -> None:
    meta = _load_meta(world_id)
    meta["entity_resolution_status"] = state.get("status")
    meta["entity_resolution_phase"] = state.get("phase")
    meta["entity_resolution_message"] = state.get("message")
    meta["entity_resolution_reason"] = state.get("reason")
    meta["entity_resolution_top_k"] = state.get("top_k")
    meta["entity_resolution_embedding_batch_size"] = _normalize_embedding_batch_size(
        state.get("embedding_batch_size", _UNIQUE_NODE_REBUILD_BATCH_SIZE)
    )
    meta["entity_resolution_embedding_cooldown_seconds"] = _normalize_embedding_cooldown_seconds(
        state.get("embedding_cooldown_seconds", _UNIQUE_NODE_REBUILD_COOLDOWN_SECONDS)
    )
    meta["entity_resolution_total_entities"] = state.get("total_entities", 0)
    meta["entity_resolution_resolved_entities"] = state.get("resolved_entities", 0)
    meta["entity_resolution_unresolved_entities"] = state.get("unresolved_entities", 0)
    meta["entity_resolution_auto_resolved_pairs"] = state.get("auto_resolved_pairs", 0)
    meta["entity_resolution_mode"] = state.get("resolution_mode")
    meta["entity_resolution_review_mode"] = state.get("review_mode", False)
    meta["entity_resolution_exact_pass"] = state.get("include_normalized_exact_pass", True)
    meta["entity_resolution_updated_at"] = state.get("updated_at")
    if graph_store is not None:
        current_total_nodes = graph_store.get_node_count()
        meta["total_nodes"] = current_total_nodes
        meta["total_edges"] = graph_store.get_edge_count()
        if state.get("status") in {"complete", "completed"}:
            meta["entity_resolution_last_completed_graph_nodes"] = current_total_nodes
    elif state.get("status") in {"complete", "completed"}:
        current_total_nodes = _coerce_non_negative_int(meta.get("total_nodes"))
        if current_total_nodes is not None:
            meta["entity_resolution_last_completed_graph_nodes"] = current_total_nodes
    _save_meta(world_id, meta)
    baseline = _coerce_non_negative_int(meta.get("entity_resolution_last_completed_graph_nodes"))
    current_total = _coerce_non_negative_int(meta.get("total_nodes"))
    state["new_nodes_since_last_completed_resolution"] = None if baseline is None or current_total is None else max(0, current_total - baseline)


async def start_entity_resolution(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
    resolution_mode: EntityResolutionMode,
    embedding_batch_size: int | None = None,
    embedding_cooldown_seconds: float | None = None,
) -> None:
    abort_event = _abort_events.get(world_id)
    if abort_event is None:
        abort_event = threading.Event()
        _abort_events[world_id] = abort_event
    _active_runs.add(world_id)
    graph_store: GraphStore | None = None
    try:
        graph_store = GraphStore(world_id)
        initial_ids = list(graph_store.graph.nodes())
        initial_total = len(initial_ids)
        normalized_resolution_mode = resolve_entity_resolution_mode(
            resolution_mode,
            include_normalized_exact_pass,
        )
        normalized_embedding_batch_size = _normalize_embedding_batch_size(embedding_batch_size)
        normalized_embedding_cooldown_seconds = _normalize_embedding_cooldown_seconds(embedding_cooldown_seconds)
        include_exact_pass = _mode_uses_exact_pass(normalized_resolution_mode)
        use_ai_pass = _mode_uses_ai_pass(normalized_resolution_mode)

        state = _set_state(
            world_id,
            status="in_progress",
            phase="preparing",
            message="Preparing entity resolution.",
            reason=None,
            top_k=top_k,
            embedding_batch_size=normalized_embedding_batch_size,
            embedding_cooldown_seconds=normalized_embedding_cooldown_seconds,
            resolution_mode=normalized_resolution_mode,
            review_mode=review_mode,
            include_normalized_exact_pass=include_exact_pass,
            total_entities=initial_total,
            resolved_entities=0,
            unresolved_entities=initial_total,
            auto_resolved_pairs=0,
            current_anchor=None,
            current_candidates=[],
            can_resume=False,
        )
        _update_meta_from_state(world_id, state, graph_store)
        push_sse_event(world_id, {"event": "status", **state})
        _ensure_not_aborted(world_id, abort_event)

        if initial_total == 0:
            state = _set_state(
                world_id,
                status="complete",
                phase="complete",
                message="No entities are available for resolution.",
                unresolved_entities=0,
                current_anchor=None,
                current_candidates=[],
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "complete", **state})
            return

        remaining_ids = list(initial_ids)
        processed_count = 0
        auto_resolved_pairs = 0
        unique_node_vector_store: VectorStore | None = None

        if include_exact_pass:
            state = _set_state(world_id, phase="exact_match_pass", message="Running exact match pass after normalization.")
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "progress", **state})

            exact_groups = _group_exact_matches(graph_store, remaining_ids)
            pending_exact_saves = 0
            for group in exact_groups:
                _ensure_not_aborted(world_id, abort_event)
                nodes = [snapshot for snapshot in (_node_snapshot(graph_store, node_id) for node_id in group) if snapshot]
                if len(nodes) < 2:
                    continue
                display_name, description = _combine_exact_match_group(nodes)
                winner_id = group[0]
                loser_ids = group[1:]
                _merge_group(graph_store, winner_id, loser_ids, display_name, description)
                pending_exact_saves += 1

                processed_count += len(group)
                auto_resolved_pairs += len(loser_ids)
                remaining_ids = [node_id for node_id in remaining_ids if node_id not in group]

                state = _set_state(
                    world_id,
                    message=f"Auto-resolved exact normalized match group for {display_name}.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
                    auto_resolved_pairs=auto_resolved_pairs,
                )
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(
                    world_id,
                    {
                        "event": "progress",
                        **state,
                        "current_anchor": {"node_id": winner_id, "display_name": display_name},
                    },
                )
                if pending_exact_saves >= 10:
                    graph_store.save()
                    pending_exact_saves = 0

            if pending_exact_saves:
                graph_store.save()

            state = _set_state(
                world_id,
                phase="index_refresh",
                message="Refreshing unique node index after exact match pass.",
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "progress", **state})
            unique_node_vector_store = await _rebuild_unique_node_index(
                world_id,
                graph_store,
                batch_size=normalized_embedding_batch_size,
                cooldown_seconds=normalized_embedding_cooldown_seconds,
                abort_event=abort_event,
            )

        if not use_ai_pass:
            state = _set_state(
                world_id,
                status="complete",
                phase="complete",
                message="Exact-only entity resolution complete.",
                reason=None,
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                current_anchor=None,
                current_candidates=[],
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "complete", **state})
            return

        if unique_node_vector_store is None:
            state = _set_state(
                world_id,
                phase="index_refresh",
                message="Preparing unique node index for AI candidate search.",
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "progress", **state})
            unique_node_vector_store = await _rebuild_unique_node_index(
                world_id,
                graph_store,
                batch_size=normalized_embedding_batch_size,
                cooldown_seconds=normalized_embedding_cooldown_seconds,
                abort_event=abort_event,
            )

        while remaining_ids:
            _ensure_not_aborted(world_id, abort_event)

            anchor_id = remaining_ids[0]
            anchor = _node_snapshot(graph_store, anchor_id)
            if not anchor:
                remaining_ids.pop(0)
                processed_count += 1
                continue

            if len(remaining_ids) == 1:
                processed_count += 1
                remaining_ids = remaining_ids[1:]
                state = _set_state(
                    world_id,
                    phase="applied",
                    message=f"No remaining candidates for {anchor['display_name']}.",
                    reason="Only one unresolved entity remained.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
                    current_anchor=anchor,
                    current_candidates=[],
                )
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(world_id, {"event": "progress", **state})
                continue

            state = _set_state(
                world_id,
                phase="candidate_search",
                message=f"Searching candidate entities for {anchor['display_name']}.",
                current_anchor=anchor,
                current_candidates=[],
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "progress", **state})

            candidates = _query_candidates(graph_store, unique_node_vector_store, anchor_id, remaining_ids, top_k)
            state = _set_state(
                world_id,
                phase="candidate_search",
                message=f"Evaluating {len(candidates)} candidates for {anchor['display_name']}.",
                current_anchor=anchor,
                current_candidates=candidates,
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "progress", **state})

            chosen_ids: list[str] = []
            chooser_reason = "No candidates were selected."
            if candidates:
                state = _set_state(world_id, phase="chooser", message=f"Chooser evaluating {len(candidates)} candidate entities.")
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(world_id, {"event": "progress", **state})
                chosen_ids, chooser_reason = await _choose_matches(anchor, candidates, world_id=world_id)
                chosen_ids = [node_id for node_id in chosen_ids if node_id in remaining_ids and node_id != anchor_id]

            if chosen_ids:
                group_ids = [anchor_id, *chosen_ids]
                nodes = [snapshot for snapshot in (_node_snapshot(graph_store, node_id) for node_id in group_ids) if snapshot]
                state = _set_state(world_id, phase="combiner", message=f"Merging {len(group_ids)} entities for {anchor['display_name']}.")
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "reason": chooser_reason})

                display_name, description = await _combine_entities(nodes, world_id=world_id)
                _merge_group(graph_store, anchor_id, chosen_ids, display_name, description)
                graph_store.save()
                await _refresh_unique_node_index_after_merge(
                    unique_node_vector_store,
                    graph_store,
                    anchor_id,
                    chosen_ids,
                    batch_size=normalized_embedding_batch_size,
                    cooldown_seconds=normalized_embedding_cooldown_seconds,
                    abort_event=abort_event,
                )

                processed_count += len(group_ids)
                remaining_ids = [node_id for node_id in remaining_ids if node_id not in group_ids]
                state = _set_state(
                    world_id,
                    phase="applied",
                    message=f"Merged {len(group_ids)} entities into {display_name}.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
                    current_anchor={"node_id": anchor_id, "display_name": display_name, "description": description},
                    current_candidates=[],
                )
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "reason": chooser_reason})
            else:
                processed_count += 1
                remaining_ids = remaining_ids[1:]
                state = _set_state(
                    world_id,
                    phase="applied",
                    message=f"No merge selected for {anchor['display_name']}.",
                    reason=chooser_reason,
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
                    current_anchor=anchor,
                    current_candidates=[],
                )
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(world_id, {"event": "progress", **state})

        state = _set_state(
            world_id,
            status="complete",
            phase="complete",
            message="Entity resolution complete.",
            reason=None,
            resolved_entities=initial_total,
            unresolved_entities=0,
            current_anchor=None,
            current_candidates=[],
            auto_resolved_pairs=auto_resolved_pairs,
        )
        _update_meta_from_state(world_id, state, graph_store)
        push_sse_event(world_id, {"event": "complete", **state})
    except asyncio.CancelledError:
        state = _set_state(
            world_id,
            status="aborted",
            phase="aborted",
            message="Entity resolution aborted.",
            current_anchor=None,
            current_candidates=[],
        )
        _update_meta_from_state(world_id, state, graph_store)
        push_sse_event(world_id, {"event": "aborted", **state})
    except Exception as exc:
        logger.exception("Entity resolution failed for %s", world_id)
        fail_entity_resolution_startup(world_id, "Entity resolution failed.", reason=str(exc), graph_store=graph_store)
    finally:
        _active_runs.discard(world_id)
        if _abort_events.get(world_id) is abort_event:
            _abort_events.pop(world_id, None)
