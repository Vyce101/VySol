"""Post-ingestion entity resolution pipeline with SSE progress updates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from .agents import _call_agent
from .config import load_settings, world_meta_path
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def get_resolution_status(world_id: str) -> dict[str, Any]:
    with _get_lock(_state_locks, world_id):
        current = dict(_states.get(world_id, {}))

    if current:
        if world_id not in _active_runs and _is_stale_in_progress(current):
            return _mark_run_stale(world_id)
        return current

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
    return {
        "status": meta.get("entity_resolution_status", "idle"),
        "phase": meta.get("entity_resolution_phase"),
        "message": meta.get("entity_resolution_message"),
        "reason": meta.get("entity_resolution_reason"),
        "top_k": meta.get("entity_resolution_top_k", settings.get("entity_resolution_top_k", 50)),
        "resolved_entities": meta.get("entity_resolution_resolved_entities", 0),
        "unresolved_entities": meta.get("entity_resolution_unresolved_entities", 0),
        "auto_resolved_pairs": meta.get("entity_resolution_auto_resolved_pairs", 0),
        "total_entities": meta.get("entity_resolution_total_entities", 0),
        "review_mode": meta.get("entity_resolution_review_mode", False),
        "include_normalized_exact_pass": meta.get("entity_resolution_exact_pass", True),
        "can_resume": False,
    }


def get_resolution_current(world_id: str) -> dict[str, Any]:
    return get_resolution_status(world_id)


def abort_entity_resolution(world_id: str) -> None:
    if world_id not in _abort_events:
        _abort_events[world_id] = threading.Event()
    _abort_events[world_id].set()
    if world_id not in _active_runs and world_meta_path(world_id).exists():
        _mark_run_stale(world_id)


def begin_entity_resolution_run(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
) -> dict[str, Any]:
    """Mark a run as active immediately so status checks don't race the background task."""
    clear_sse_queue(world_id)
    _abort_events[world_id] = threading.Event()
    _active_runs.add(world_id)
    state = _set_state(
        world_id,
        status="in_progress",
        phase="preparing",
        message="Preparing entity resolution.",
        reason=None,
        top_k=top_k,
        review_mode=review_mode,
        include_normalized_exact_pass=include_normalized_exact_pass,
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
    display_name = str(node.get("display_name", "")).strip()
    description = str(node.get("description", "")).strip()
    if display_name and description:
        return f"{display_name}\n\n{description}"
    return display_name or description


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
    api_key, _ = get_key_manager().get_active_key()
    return api_key


def _rebuild_entity_index(
    world_id: str,
    graph_store: GraphStore,
    remaining_ids: list[str],
) -> VectorStore:
    vector_store = VectorStore(world_id, collection_suffix="entities")
    vector_store.drop_collection()

    if not remaining_ids:
        return vector_store

    api_key = _get_embedding_api_key()
    for node_id in remaining_ids:
        node = _node_snapshot(graph_store, node_id)
        if not node:
            continue
        vector_store.upsert_document(
            node_id,
            _entity_document(node),
            {
                "display_name": node["display_name"],
                "normalized_name": node["normalized_name"],
            },
            api_key,
        )
    return vector_store


def _query_candidates(
    world_id: str,
    graph_store: GraphStore,
    anchor_id: str,
    remaining_ids: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    anchor = _node_snapshot(graph_store, anchor_id)
    if not anchor:
        return []

    vector_store = _rebuild_entity_index(world_id, graph_store, remaining_ids)
    if vector_store.count() <= 1:
        return []

    api_key = _get_embedding_api_key()
    raw_results = vector_store.query(_entity_document(anchor), api_key=api_key, n_results=min(len(remaining_ids), top_k + 1))

    candidates: list[dict[str, Any]] = []
    for result in raw_results:
        node_id = result.get("id")
        if not isinstance(node_id, str) or node_id == anchor_id or node_id not in remaining_ids:
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


async def _combine_entities(nodes: list[dict[str, Any]]) -> tuple[str, str]:
    settings = load_settings()
    model_name = settings.get("default_model_entity_combiner", "gemini-flash-lite-latest")
    payload = json.dumps({"entities": nodes}, ensure_ascii=False)

    try:
        parsed, _ = await _call_agent(
            prompt_key="entity_resolution_combiner_prompt",
            user_content=payload,
            model_name=model_name,
            temperature=0.2,
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
    meta["entity_resolution_total_entities"] = state.get("total_entities", 0)
    meta["entity_resolution_resolved_entities"] = state.get("resolved_entities", 0)
    meta["entity_resolution_unresolved_entities"] = state.get("unresolved_entities", 0)
    meta["entity_resolution_auto_resolved_pairs"] = state.get("auto_resolved_pairs", 0)
    meta["entity_resolution_review_mode"] = state.get("review_mode", False)
    meta["entity_resolution_exact_pass"] = state.get("include_normalized_exact_pass", True)
    meta["entity_resolution_updated_at"] = state.get("updated_at")
    if graph_store is not None:
        meta["total_nodes"] = graph_store.get_node_count()
        meta["total_edges"] = graph_store.get_edge_count()
    _save_meta(world_id, meta)


async def start_entity_resolution(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
) -> None:
    abort_event = _abort_events.get(world_id)
    if abort_event is None:
        abort_event = threading.Event()
        _abort_events[world_id] = abort_event
    _active_runs.add(world_id)

    graph_store = GraphStore(world_id)
    initial_ids = list(graph_store.graph.nodes())
    initial_total = len(initial_ids)

    state = _set_state(
        world_id,
        status="in_progress",
        phase="preparing",
        message="Preparing entity resolution.",
        reason=None,
        top_k=top_k,
        review_mode=review_mode,
        include_normalized_exact_pass=include_normalized_exact_pass,
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

    try:
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

        if include_normalized_exact_pass:
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
                message=f"Building candidate index for {anchor['display_name']}.",
                current_anchor=anchor,
                current_candidates=[],
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, graph_store)
            push_sse_event(world_id, {"event": "progress", **state})

            candidates = _query_candidates(world_id, graph_store, anchor_id, remaining_ids, top_k)
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
                chosen_ids, chooser_reason = await _choose_matches(anchor, candidates)
                chosen_ids = [node_id for node_id in chosen_ids if node_id in remaining_ids and node_id != anchor_id]

            if chosen_ids:
                group_ids = [anchor_id, *chosen_ids]
                nodes = [snapshot for snapshot in (_node_snapshot(graph_store, node_id) for node_id in group_ids) if snapshot]
                state = _set_state(world_id, phase="combiner", message=f"Merging {len(group_ids)} entities for {anchor['display_name']}.")
                _update_meta_from_state(world_id, state, graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "reason": chooser_reason})

                display_name, description = await _combine_entities(nodes)
                _merge_group(graph_store, anchor_id, chosen_ids, display_name, description)
                graph_store.save()

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
        state = _set_state(
            world_id,
            status="error",
            phase="error",
            message="Entity resolution failed.",
            reason=str(exc),
            current_anchor=None,
            current_candidates=[],
        )
        _update_meta_from_state(world_id, state, graph_store)
        push_sse_event(world_id, {"event": "error", **state})
    finally:
        _active_runs.discard(world_id)
