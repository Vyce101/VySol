"""Post-ingestion entity resolution pipeline with SSE progress updates."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from .agents import _call_agent
from .atomic_json import dump_json_atomic
from .config import load_settings, world_meta_path
from .entity_text import build_unique_node_document
from .graph_store import GraphStore
from .key_manager import (
    AllKeysInCooldownError,
    classify_transient_provider_error,
    get_key_manager,
    jittered_delay,
)
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
_VECTOR_DELETE_BATCH_SIZE = 1000
_RECOVERY_JOURNAL_FILE = "entity_resolution_recovery.json"

_META_STAGE_GRAPH_PATH = "entity_resolution_staging_graph_path"
_META_STAGE_COLLECTION_SUFFIX = "entity_resolution_staging_collection_suffix"
_META_COMMIT_PENDING = "entity_resolution_commit_pending"
_META_COMMIT_STATE = "entity_resolution_commit_state"
_META_CURRENT_ANCHOR_LABEL = "entity_resolution_current_anchor_label"

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
    *,
    missing_default: EntityResolutionMode | None = None,
) -> EntityResolutionMode:
    if resolution_mode == "exact_only":
        return "exact_only"
    if resolution_mode == "exact_then_ai":
        return "exact_then_ai"
    if missing_default is not None:
        return missing_default
    return "exact_then_ai" if include_normalized_exact_pass else "ai_only"


def _mode_uses_exact_pass(resolution_mode: EntityResolutionMode) -> bool:
    return resolution_mode != "ai_only"


def _mode_uses_ai_pass(resolution_mode: EntityResolutionMode) -> bool:
    return resolution_mode != "exact_only"


def _current_anchor_label_for_mode(resolution_mode: EntityResolutionMode) -> str:
    return "Current Exact Match Group" if resolution_mode == "exact_only" else "Current Anchor"


def _normalize_commit_state(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"staging", "commit_pending", "committed"}:
        return normalized
    return None


def _is_commit_pending_state(state: dict[str, Any]) -> bool:
    return bool(state.get("commit_pending")) or _normalize_commit_state(state.get("commit_state")) == "commit_pending"


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


def _should_default_missing_mode_to_exact_only(meta: dict[str, Any]) -> bool:
    if str(meta.get("entity_resolution_mode") or "").strip():
        return False
    if meta.get("entity_resolution_exact_pass") is not None:
        return False
    if meta.get("entity_resolution_updated_at"):
        return False
    status = str(meta.get("entity_resolution_status") or "").strip().lower()
    if status and status != "idle":
        return False
    if meta.get(_META_COMMIT_PENDING) or _normalize_commit_state(meta.get(_META_COMMIT_STATE)):
        return False
    return True


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_meta(world_id: str, meta: dict) -> None:
    path = world_meta_path(world_id)
    dump_json_atomic(path, meta)


def _staging_graph_path(world_id: str) -> Path:
    return world_meta_path(world_id).parent / "entity_resolution_staging_graph.gexf"


def _new_staging_collection_suffix() -> str:
    return f"unique_nodes_staging_{uuid.uuid4().hex}"


def _recovery_journal_path(world_id: str) -> Path:
    return world_meta_path(world_id).parent / _RECOVERY_JOURNAL_FILE


def _load_recovery_journal(world_id: str) -> dict[str, Any] | None:
    path = _recovery_journal_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read entity-resolution recovery journal for %s", world_id, exc_info=True)
        return None
    return payload if isinstance(payload, dict) else None


def _save_recovery_journal(world_id: str, journal: dict[str, Any]) -> dict[str, Any]:
    payload = dict(journal)
    payload["updated_at"] = _now_iso()
    dump_json_atomic(_recovery_journal_path(world_id), payload)
    return payload


def _delete_recovery_journal(world_id: str) -> None:
    path = _recovery_journal_path(world_id)
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        logger.warning("Failed to delete entity-resolution recovery journal for %s", world_id, exc_info=True)


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


def _cleanup_staging_artifacts(world_id: str, meta: dict[str, Any] | None = None) -> None:
    local_meta = dict(meta or _load_meta(world_id))
    stage_suffix = str(local_meta.get(_META_STAGE_COLLECTION_SUFFIX) or "").strip()
    stage_graph_path = str(local_meta.get(_META_STAGE_GRAPH_PATH) or "").strip()
    if stage_suffix:
        try:
            _get_unique_node_vector_store(world_id, collection_suffix=stage_suffix).drop_collection()
        except Exception:
            logger.warning("Failed to drop staged entity-resolution collection for %s", world_id, exc_info=True)
    if stage_graph_path:
        try:
            path = Path(stage_graph_path)
            if path.exists():
                path.unlink()
        except Exception:
            logger.warning("Failed to remove staged entity-resolution graph for %s", world_id, exc_info=True)


def _recover_stale_run(world_id: str) -> dict[str, Any]:
    meta = _load_meta(world_id)
    stage_suffix = str(meta.get(_META_STAGE_COLLECTION_SUFFIX) or "").strip()
    stage_graph_path = str(meta.get(_META_STAGE_GRAPH_PATH) or "").strip()
    commit_pending = bool(meta.get(_META_COMMIT_PENDING))
    commit_state = _normalize_commit_state(meta.get(_META_COMMIT_STATE))

    try:
        if (commit_pending or commit_state == "commit_pending") and stage_suffix and stage_graph_path:
            live_graph_store = GraphStore(world_id)
            state = _set_state(
                world_id,
                status="in_progress",
                phase="commit_recovery",
                message="Recovering an interrupted entity-resolution commit.",
                reason="stale_run_commit_recovery",
                commit_state="commit_pending",
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            _finalize_resolution_commit(
                world_id,
                live_graph_store=live_graph_store,
                stage_suffix=stage_suffix,
                stage_graph_path=Path(stage_graph_path),
                final_state_updates={
                    "status": "complete",
                    "phase": "complete",
                    "message": "Recovered and finalized the interrupted entity-resolution run.",
                    "reason": None,
                    "commit_state": "committed",
                },
                push_terminal_event=False,
            )
            recovered_state = dict(_states.get(world_id, {}))
            recovered_state["message"] = "Recovered and finalized the interrupted entity-resolution run."
            _states[world_id] = recovered_state
            push_sse_event(world_id, {"event": "complete", **recovered_state, "recovered": True})
            return recovered_state
    except Exception as exc:
        logger.exception("Failed to recover stale entity-resolution commit for %s", world_id)
        _cleanup_staging_artifacts(world_id, meta)
        state = _set_state(
            world_id,
            status="error",
            phase="error",
            message="A stale entity-resolution run could not be recovered.",
            reason=str(exc),
            current_anchor=None,
            current_candidates=[],
            current_anchor_label=None,
            staging_collection_suffix=None,
            staging_graph_path=None,
            commit_pending=False,
            commit_state=None,
        )
        _update_meta_from_state(world_id, state)
        push_sse_event(world_id, {"event": "error", **state, "recovered": True})
        return state

    _cleanup_staging_artifacts(world_id, meta)
    state = _set_state(
        world_id,
        status="aborted",
        phase="aborted",
        message="Previous entity-resolution run was interrupted before commit. No graph changes were kept.",
        reason="stale_run",
        current_anchor=None,
        current_candidates=[],
        current_anchor_label=None,
        staging_collection_suffix=None,
        staging_graph_path=None,
        commit_pending=False,
        commit_state=None,
    )
    _update_meta_from_state(world_id, state)
    push_sse_event(world_id, {"event": "aborted", **state, "recovered": True})
    return state


def _status_payload_from_meta(world_id: str, meta: dict[str, Any], *, can_resume: bool) -> dict[str, Any]:
    settings = load_settings()
    missing_default = "exact_only" if _should_default_missing_mode_to_exact_only(meta) else None
    resolution_mode = resolve_entity_resolution_mode(
        meta.get("entity_resolution_mode"),
        meta.get("entity_resolution_exact_pass", True),
        missing_default=missing_default,
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
            "embedding_completed_entities": meta.get("entity_resolution_embedding_completed_entities", 0),
            "embedding_total_entities": meta.get("entity_resolution_embedding_total_entities", 0),
            "auto_resolved_pairs": meta.get("entity_resolution_auto_resolved_pairs", 0),
            "total_entities": meta.get("entity_resolution_total_entities", 0),
            "resolution_mode": resolution_mode,
            "review_mode": meta.get("entity_resolution_review_mode", False),
            "include_normalized_exact_pass": _mode_uses_exact_pass(resolution_mode),
            "can_resume": can_resume,
            "current_anchor_label": meta.get(_META_CURRENT_ANCHOR_LABEL),
            "commit_state": _normalize_commit_state(meta.get(_META_COMMIT_STATE)),
        },
        meta,
    )


def get_resolution_status(world_id: str) -> dict[str, Any]:
    with _get_lock(_state_locks, world_id):
        current = dict(_states.get(world_id, {}))

    if current:
        if world_id not in _active_runs:
            journal = _load_recovery_journal(world_id)
            if journal:
                live_graph_store = GraphStore(world_id)
                unique_node_vector_store = _get_unique_node_vector_store(world_id)
                journal, _ = _recover_in_flight_transaction(world_id, journal, live_graph_store, unique_node_vector_store)
                if not _journal_has_pending_work(journal):
                    _delete_recovery_journal(world_id)
                elif _is_stale_in_progress(current):
                    message = _resume_status_message(journal, prefix="Entity resolution was interrupted")
                    return _persist_state_from_journal(
                        world_id,
                        journal,
                        graph_store=live_graph_store,
                        status="aborted",
                        phase="aborted",
                        message=message,
                        reason="stale_run",
                        push_event="aborted",
                    )
                current["can_resume"] = _journal_has_pending_work(journal)
        if world_id not in _active_runs and _is_commit_pending_state(current):
            return _recover_stale_run(world_id)
        if world_id not in _active_runs and _is_stale_in_progress(current):
            return _recover_stale_run(world_id)
        return _with_new_node_summary(world_id, current)

    if not world_meta_path(world_id).exists():
        return {}

    meta = _load_meta(world_id)
    journal = _load_recovery_journal(world_id)
    if journal and world_id not in _active_runs:
        live_graph_store = GraphStore(world_id)
        unique_node_vector_store = _get_unique_node_vector_store(world_id)
        journal, _ = _recover_in_flight_transaction(world_id, journal, live_graph_store, unique_node_vector_store)
        if not _journal_has_pending_work(journal):
            _delete_recovery_journal(world_id)
        else:
            meta_like_state = {
                "status": meta.get("entity_resolution_status"),
                "updated_at": meta.get("entity_resolution_updated_at"),
                "commit_pending": meta.get(_META_COMMIT_PENDING),
                "commit_state": meta.get(_META_COMMIT_STATE),
            }
            if _is_stale_in_progress(meta_like_state):
                message = _resume_status_message(journal, prefix="Entity resolution was interrupted")
                return _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="aborted",
                    phase="aborted",
                    message=message,
                    reason="stale_run",
                    push_event="aborted",
                )
            return _status_payload_from_meta(world_id, meta, can_resume=True)

    meta_like_state = {
        "status": meta.get("entity_resolution_status"),
        "updated_at": meta.get("entity_resolution_updated_at"),
        "commit_pending": meta.get(_META_COMMIT_PENDING),
        "commit_state": meta.get(_META_COMMIT_STATE),
    }
    if world_id not in _active_runs and _is_commit_pending_state(meta_like_state):
        return _recover_stale_run(world_id)
    if world_id not in _active_runs and _is_stale_in_progress(meta_like_state):
        return _recover_stale_run(world_id)
    return _status_payload_from_meta(world_id, meta, can_resume=False)


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
    _cleanup_staging_artifacts(world_id)
    state = _set_state(
        world_id,
        status="error",
        phase="error",
        message=message,
        reason=reason,
        current_anchor=None,
        current_candidates=[],
        current_anchor_label=None,
        can_resume=_journal_has_pending_work(_load_recovery_journal(world_id)),
        staging_collection_suffix=None,
        staging_graph_path=None,
        commit_pending=False,
        commit_state=None,
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
    _cleanup_staging_artifacts(world_id)
    _abort_events[world_id] = threading.Event()
    _active_runs.add(world_id)
    normalized_embedding_batch_size = _normalize_embedding_batch_size(embedding_batch_size)
    normalized_embedding_cooldown_seconds = _normalize_embedding_cooldown_seconds(embedding_cooldown_seconds)
    journal = _load_recovery_journal(world_id)
    if journal and _journal_has_pending_work(journal):
        journal = dict(journal)
        journal["top_k"] = max(1, top_k)
        journal["review_mode"] = bool(review_mode)
        journal["embedding_batch_size"] = normalized_embedding_batch_size
        journal["embedding_cooldown_seconds"] = normalized_embedding_cooldown_seconds
        journal["reason"] = None
        journal["message"] = "Resuming entity resolution from saved progress."
        journal["phase"] = "preparing"
        journal = _save_recovery_journal(world_id, journal)
        state = _set_state(
            world_id,
            **_state_payload_from_journal(
                journal,
                status="in_progress",
                phase="preparing",
                message="Resuming entity resolution from saved progress.",
                reason=None,
                can_resume=True,
            ),
        )
        _update_meta_from_state(world_id, state)
        return state

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
        embedding_completed_entities=0,
        embedding_total_entities=0,
        auto_resolved_pairs=0,
        current_anchor=None,
        current_candidates=[],
        current_anchor_label=None,
        can_resume=False,
        staging_collection_suffix=None,
        staging_graph_path=None,
        commit_pending=False,
        commit_state=None,
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
    merge_provenance = attrs.get("merge_provenance", [])
    if isinstance(merge_provenance, str):
        try:
            merge_provenance = json.loads(merge_provenance)
        except json.JSONDecodeError:
            merge_provenance = []
    return {
        "node_id": node_id,
        "display_name": attrs.get("display_name", ""),
        "description": attrs.get("description", ""),
        "normalized_name": _normalize_display_name(attrs.get("display_name", "")),
        "normalized_id": attrs.get("normalized_id", _normalized_id_from_name(attrs.get("display_name", ""))),
        "claims": claims,
        "source_chunks": source_chunks,
        "merge_provenance": merge_provenance if isinstance(merge_provenance, list) else [],
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


def _build_unique_node_metadata(node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("node_id", "")).strip()
    return {
        "node_id": node_id,
        "display_name": str(node.get("display_name", "")).strip(),
        "normalized_name": str(node.get("normalized_name", "")).strip(),
    }


def _get_unique_node_vector_store(world_id: str, *, collection_suffix: str = "unique_nodes") -> VectorStore:
    return VectorStore(world_id, collection_suffix=collection_suffix)


def _working_graph_store(world_id: str, source_graph_store: GraphStore) -> GraphStore:
    store = GraphStore(world_id)
    store.path = _staging_graph_path(world_id)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.graph = source_graph_store.graph.copy(as_view=False)
    return store


def _load_staged_graph_store(world_id: str, stage_graph_path: Path) -> GraphStore:
    store = GraphStore(world_id)
    store.path = stage_graph_path
    store.graph = store._load()
    return store


def _save_graph_store(store: GraphStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.save()


async def _sleep_with_abort(expected_event: threading.Event | None, seconds: float) -> None:
    if seconds <= 0:
        return
    if expected_event is None:
        await asyncio.sleep(seconds)
        return
    aborted = await asyncio.to_thread(expected_event.wait, seconds)
    if aborted:
        raise asyncio.CancelledError()


async def _await_available_key(
    abort_event: threading.Event | None,
    tried_indices: set[int] | None = None,
    wait_callback: Callable[[float], Awaitable[None] | None] | None = None,
) -> tuple[str, int]:
    key_manager = get_key_manager()
    excluded = set(tried_indices or ())
    while True:
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError()
        try:
            return key_manager.get_request_key(excluded)
        except AllKeysInCooldownError as exc:
            if excluded:
                raise
            if wait_callback is not None:
                wait_result = wait_callback(exc.retry_after_seconds)
                if asyncio.iscoroutine(wait_result):
                    await wait_result
            await _sleep_with_abort(abort_event, jittered_delay(exc.retry_after_seconds))


async def _embed_texts_abortable(
    vector_store: VectorStore,
    texts: list[str],
    *,
    abort_event: threading.Event | None = None,
    wait_callback: Callable[[float], Awaitable[None] | None] | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    candidates = vector_store._candidate_embedding_models()
    key_manager = get_key_manager()
    last_error: Exception | None = None
    tried_key_indices: set[int] = set()
    current_api_key, current_key_index = await _await_available_key(
        abort_event,
        tried_key_indices,
        wait_callback=wait_callback,
    )

    while True:
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError()
        client = vector_store._get_embed_client(current_api_key)

        for model_name in candidates:
            if abort_event is not None and abort_event.is_set():
                raise asyncio.CancelledError()
            try:
                payload: str | list[str] = texts if len(texts) > 1 else texts[0]
                result = await asyncio.to_thread(client.models.embed_content, model=model_name, contents=payload)
                embeddings = [list(item.values) for item in (result.embeddings or [])]
                if len(embeddings) != len(texts):
                    raise RuntimeError(
                        f"Embedding API returned {len(embeddings)} embeddings for {len(texts)} texts."
                    )
                vector_store._record_effective_embedding_model(candidates, model_name)
                return embeddings
            except Exception as exc:
                last_error = exc
                message = str(exc).lower()
                transient_kind = classify_transient_provider_error(exc)
                if transient_kind and current_key_index is not None:
                    key_manager.report_error(current_key_index, transient_kind)
                    tried_key_indices.add(current_key_index)
                    await _sleep_with_abort(abort_event, jittered_delay(0.5))
                    try:
                        current_api_key, current_key_index = await _await_available_key(
                            abort_event,
                            tried_key_indices,
                            wait_callback=wait_callback,
                        )
                    except AllKeysInCooldownError as cooldown_exc:
                        if wait_callback is not None:
                            wait_result = wait_callback(cooldown_exc.retry_after_seconds)
                            if asyncio.iscoroutine(wait_result):
                                await wait_result
                        raise
                    break
                if ("not found" in message or "not supported" in message) and model_name != candidates[-1]:
                    continue
                raise
        else:
            break
        continue

    if last_error:
        raise last_error
    raise RuntimeError("Embedding generation failed with no model candidates.")


async def _upsert_unique_node_snapshots(
    unique_node_vector_store: VectorStore,
    node_snapshots: list[dict[str, Any]],
    batch_size: int,
    cooldown_seconds: float,
    abort_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], Awaitable[None] | None] | None = None,
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
        if progress_callback is not None:
            progress_result = progress_callback(0, 0)
            if asyncio.iscoroutine(progress_result):
                await progress_result
        return 0

    total_written = 0
    total_nodes = len(normalized_nodes)
    normalized_batch_size = _normalize_embedding_batch_size(batch_size)
    normalized_cooldown_seconds = _normalize_embedding_cooldown_seconds(cooldown_seconds)
    for start in range(0, len(normalized_nodes), normalized_batch_size):
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError()
        batch = normalized_nodes[start:start + normalized_batch_size]
        texts = [_entity_document(node) for node in batch]
        embeddings = await _embed_texts_abortable(unique_node_vector_store, texts, abort_event=abort_event)
        unique_node_vector_store.upsert_documents_embeddings(
            document_ids=[str(node["node_id"]) for node in batch],
            texts=texts,
            metadatas=[_build_unique_node_metadata(node) for node in batch],
            embeddings=embeddings,
        )
        total_written += len(batch)
        if progress_callback is not None:
            progress_result = progress_callback(total_written, total_nodes)
            if asyncio.iscoroutine(progress_result):
                await progress_result
        has_more_batches = start + normalized_batch_size < len(normalized_nodes)
        if has_more_batches:
            await _sleep_with_abort(abort_event, normalized_cooldown_seconds)
    return total_written


async def _rebuild_unique_node_index(
    unique_node_vector_store: VectorStore,
    graph_store: GraphStore,
    batch_size: int,
    cooldown_seconds: float,
    abort_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], Awaitable[None] | None] | None = None,
) -> VectorStore:
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
        progress_callback=progress_callback,
    )
    return unique_node_vector_store


async def _bootstrap_staged_unique_node_index(
    world_id: str,
    stage_vector_store: VectorStore,
) -> VectorStore:
    live_unique_node_store = _get_unique_node_vector_store(world_id)
    try:
        records = _snapshot_vector_store_records(live_unique_node_store)
    except RuntimeError as exc:
        raise RuntimeError(
            "Unable to clone the current unique-node index for staged entity resolution. "
            "Repair unique-node embeddings and try again."
        ) from exc
    _replace_vector_store_records(stage_vector_store, records)
    return stage_vector_store


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


async def _query_candidates(
    graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    anchor_id: str,
    remaining_ids: list[str],
    top_k: int,
    *,
    abort_event: threading.Event | None = None,
    wait_callback: Callable[[float], Awaitable[None] | None] | None = None,
) -> list[dict[str, Any]]:
    anchor = _node_snapshot(graph_store, anchor_id)
    if not anchor:
        return []

    collection_count = unique_node_vector_store.count()
    if collection_count <= 1:
        return []

    query_embeddings = await _embed_texts_abortable(
        unique_node_vector_store,
        [_entity_document(anchor)],
        abort_event=abort_event,
        wait_callback=wait_callback,
    )
    raw_results = unique_node_vector_store.query_by_embedding(
        query_embeddings[0],
        n_results=collection_count,
    )

    remaining_set = set(remaining_ids)
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
    model_name = settings.get("default_model_entity_chooser", "gemini-3.1-flash-lite-preview")
    payload = json.dumps(
        {
            "anchor": anchor,
            "candidates": candidates,
        },
        ensure_ascii=False,
    )

    parsed, _ = await _call_agent(
        prompt_key="entity_resolution_chooser_prompt",
        user_content=payload,
        model_name=model_name,
        temperature=0.1,
        world_id=world_id,
    )

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
    model_name = settings.get("default_model_entity_combiner", "gemini-3.1-flash-lite-preview")
    payload = json.dumps({"entities": nodes}, ensure_ascii=False)

    parsed, _ = await _call_agent(
        prompt_key="entity_resolution_combiner_prompt",
        user_content=payload,
        model_name=model_name,
        temperature=0.2,
        world_id=world_id,
    )

    display_name = parsed.get("display_name") if isinstance(parsed, dict) else None
    description = parsed.get("description") if isinstance(parsed, dict) else None
    if not isinstance(display_name, str) or not display_name.strip():
        raise RuntimeError("Entity combiner returned no merged display_name.")
    if not isinstance(description, str):
        raise RuntimeError("Entity combiner returned no merged description.")
    return display_name.strip(), description.strip()


def _normalize_provenance_entry(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(snapshot.get("node_id", "")).strip(),
        "display_name": str(snapshot.get("display_name", "")).strip(),
        "description": str(snapshot.get("description", "")).strip(),
        "normalized_id": str(snapshot.get("normalized_id", "")).strip(),
        "claims": deepcopy(snapshot.get("claims", [])) if isinstance(snapshot.get("claims"), list) else [],
        "source_chunks": deepcopy(snapshot.get("source_chunks", []))
        if isinstance(snapshot.get("source_chunks"), list)
        else [],
    }


def _snapshot_provenance_entries(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not snapshot:
        return []
    existing = snapshot.get("merge_provenance")
    if isinstance(existing, list) and existing:
        return [
            _normalize_provenance_entry(entry)
            for entry in existing
            if isinstance(entry, dict) and str(entry.get("node_id", "")).strip()
        ]
    if str(snapshot.get("node_id", "")).strip():
        return [_normalize_provenance_entry(snapshot)]
    return []


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

    winner_snapshot = _node_snapshot(graph_store, winner_id)
    winner_attrs = graph.nodes[winner_id]
    merged_claims: list[Any] = list(winner_attrs.get("claims", []))
    merged_source_chunks: list[Any] = list(winner_attrs.get("source_chunks", []))
    merged_provenance: list[Any] = _snapshot_provenance_entries(winner_snapshot)

    for loser_id in loser_ids:
        if loser_id not in graph.nodes or loser_id == winner_id:
            continue

        loser_snapshot = _node_snapshot(graph_store, loser_id)
        loser_attrs = graph.nodes[loser_id]
        merged_claims.extend(loser_attrs.get("claims", []))
        merged_source_chunks.extend(loser_attrs.get("source_chunks", []))
        merged_provenance.extend(_snapshot_provenance_entries(loser_snapshot))

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
            rewired_attrs = dict(attrs)
            rewired_attrs["source_node_id"] = rewired_source
            rewired_attrs["target_node_id"] = rewired_target
            graph.add_edge(rewired_source, rewired_target, **rewired_attrs)

        graph.remove_node(loser_id)

    winner_attrs = graph.nodes[winner_id]
    winner_attrs["display_name"] = display_name
    winner_attrs["description"] = description
    winner_attrs["normalized_id"] = _normalized_id_from_name(display_name)
    winner_attrs["claims"] = _dedupe_jsonable(merged_claims)
    winner_attrs["source_chunks"] = _dedupe_jsonable(merged_source_chunks)
    winner_attrs["merge_provenance"] = _dedupe_jsonable(
        [entry for entry in merged_provenance if isinstance(entry, dict) and str(entry.get("node_id", "")).strip()]
    )
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


def _create_recovery_journal(
    *,
    world_id: str,
    top_k: int,
    review_mode: bool,
    resolution_mode: EntityResolutionMode,
    include_normalized_exact_pass: bool,
    embedding_batch_size: int,
    embedding_cooldown_seconds: float,
    total_entities: int,
    current_anchor_label: str | None,
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "version": 1,
        "run_id": uuid.uuid4().hex,
        "world_id": world_id,
        "top_k": int(top_k),
        "review_mode": bool(review_mode),
        "resolution_mode": resolution_mode,
        "include_normalized_exact_pass": bool(include_normalized_exact_pass),
        "embedding_batch_size": _normalize_embedding_batch_size(embedding_batch_size),
        "embedding_cooldown_seconds": _normalize_embedding_cooldown_seconds(embedding_cooldown_seconds),
        "initial_total_entities": int(total_entities),
        "resolved_entities": 0,
        "unresolved_entities": int(total_entities),
        "embedding_completed_entities": 0,
        "embedding_total_entities": 0,
        "auto_resolved_pairs": 0,
        "committed_merge_count": 0,
        "phase": "preparing",
        "message": "Preparing entity resolution.",
        "reason": None,
        "current_anchor_label": current_anchor_label,
        "pending_exact_groups": [],
        "pending_exact_merges": [],
        "pending_ai_merges": [],
        "ai_remaining_ids": None,
        "exact_plan_complete": not include_normalized_exact_pass,
        "exact_phase_complete": not include_normalized_exact_pass,
        "ai_phase_complete": not _mode_uses_ai_pass(resolution_mode),
        "in_flight_transaction": None,
        "created_at": now,
        "updated_at": now,
    }


def _merge_status(entry: dict[str, Any]) -> str:
    status = str(entry.get("status") or "").strip().lower()
    if status in {"pending_embedding", "complete"}:
        return status
    return "pending_embedding"


def _pending_merge_entries(journal: dict[str, Any]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for key in ("pending_exact_merges", "pending_ai_merges"):
        for entry in journal.get(key, []) or []:
            if isinstance(entry, dict) and _merge_status(entry) != "complete":
                pending.append(entry)
    return pending


def _pending_merge_count(journal: dict[str, Any]) -> int:
    pending_exact_groups = sum(
        1
        for group in journal.get("pending_exact_groups", []) or []
        if isinstance(group, list) and len([str(node_id).strip() for node_id in group if str(node_id).strip()]) > 1
    )
    return len(_pending_merge_entries(journal)) + pending_exact_groups


def _journal_has_pending_work(journal: dict[str, Any] | None) -> bool:
    if not isinstance(journal, dict):
        return False
    if isinstance(journal.get("in_flight_transaction"), dict):
        return True
    if _pending_merge_count(journal) > 0:
        return True
    if journal.get("include_normalized_exact_pass") and not journal.get("exact_plan_complete"):
        return True
    if journal.get("include_normalized_exact_pass") and not journal.get("exact_phase_complete"):
        return True
    if _mode_uses_ai_pass(resolve_entity_resolution_mode(journal.get("resolution_mode"), True)) and not journal.get("ai_phase_complete"):
        return True
    return False


def _resume_status_message(journal: dict[str, Any], *, prefix: str) -> str:
    committed_merges = max(0, int(journal.get("committed_merge_count") or 0))
    pending_merges = _pending_merge_count(journal)
    if pending_merges > 0:
        return f"{prefix} after committing {committed_merges} merges; {pending_merges} merges remain pending."
    if _mode_uses_ai_pass(resolve_entity_resolution_mode(journal.get('resolution_mode'), True)) and not journal.get("ai_phase_complete"):
        return f"{prefix} after committing {committed_merges} merges. Resume will continue from the current live world state."
    return f"{prefix} after committing {committed_merges} merges."


def _state_payload_from_journal(
    journal: dict[str, Any],
    *,
    status: str,
    phase: str | None = None,
    message: str | None = None,
    reason: str | None = None,
    current_anchor: dict[str, Any] | None = None,
    current_candidates: list[dict[str, Any]] | None = None,
    can_resume: bool | None = None,
) -> dict[str, Any]:
    resolution_mode = resolve_entity_resolution_mode(
        journal.get("resolution_mode"),
        bool(journal.get("include_normalized_exact_pass", True)),
        missing_default="exact_only",
    )
    return {
        "status": status,
        "phase": phase if phase is not None else journal.get("phase"),
        "message": message if message is not None else journal.get("message"),
        "reason": reason if reason is not None else journal.get("reason"),
        "top_k": int(journal.get("top_k") or 50),
        "embedding_batch_size": _normalize_embedding_batch_size(journal.get("embedding_batch_size")),
        "embedding_cooldown_seconds": _normalize_embedding_cooldown_seconds(journal.get("embedding_cooldown_seconds")),
        "resolution_mode": resolution_mode,
        "review_mode": bool(journal.get("review_mode")),
        "include_normalized_exact_pass": bool(journal.get("include_normalized_exact_pass", True)),
        "total_entities": int(journal.get("initial_total_entities") or 0),
        "resolved_entities": int(journal.get("resolved_entities") or 0),
        "unresolved_entities": int(journal.get("unresolved_entities") or 0),
        "embedding_completed_entities": int(journal.get("embedding_completed_entities") or 0),
        "embedding_total_entities": int(journal.get("embedding_total_entities") or 0),
        "auto_resolved_pairs": int(journal.get("auto_resolved_pairs") or 0),
        "current_anchor": current_anchor,
        "current_candidates": current_candidates or [],
        "current_anchor_label": journal.get("current_anchor_label"),
        "can_resume": _journal_has_pending_work(journal) if can_resume is None else bool(can_resume),
        "staging_collection_suffix": None,
        "staging_graph_path": None,
        "commit_pending": False,
        "commit_state": None,
    }


def _set_entry_status(entries: list[dict[str, Any]], entry_id: str, status: str) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("entry_id")) == entry_id:
            next_entry = dict(entry)
            next_entry["status"] = status
            updated.append(next_entry)
        else:
            updated.append(entry)
    return updated


def _update_journal_entry(journal: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    entry_id = str(entry.get("entry_id") or "").strip()
    if not entry_id:
        return journal
    next_journal = dict(journal)
    replaced = False
    for key in ("pending_exact_merges", "pending_ai_merges"):
        next_entries: list[dict[str, Any]] = []
        for existing in next_journal.get(key, []) or []:
            if isinstance(existing, dict) and str(existing.get("entry_id")) == entry_id:
                next_entries.append(dict(entry))
                replaced = True
            else:
                next_entries.append(existing)
        next_journal[key] = next_entries
    if not replaced:
        pending_ai = list(next_journal.get("pending_ai_merges", []) or [])
        pending_ai.append(dict(entry))
        next_journal["pending_ai_merges"] = pending_ai
    return next_journal


def _remove_completed_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if isinstance(entry, dict) and _merge_status(entry) != "complete"]


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
    meta["entity_resolution_embedding_completed_entities"] = state.get("embedding_completed_entities", 0)
    meta["entity_resolution_embedding_total_entities"] = state.get("embedding_total_entities", 0)
    meta["entity_resolution_auto_resolved_pairs"] = state.get("auto_resolved_pairs", 0)
    meta["entity_resolution_mode"] = state.get("resolution_mode")
    meta["entity_resolution_review_mode"] = state.get("review_mode", False)
    meta["entity_resolution_exact_pass"] = state.get("include_normalized_exact_pass", True)
    meta["entity_resolution_updated_at"] = state.get("updated_at")
    meta[_META_CURRENT_ANCHOR_LABEL] = state.get("current_anchor_label")

    stage_suffix = state.get("staging_collection_suffix")
    if stage_suffix:
        meta[_META_STAGE_COLLECTION_SUFFIX] = stage_suffix
    else:
        meta.pop(_META_STAGE_COLLECTION_SUFFIX, None)

    stage_graph_path = state.get("staging_graph_path")
    if stage_graph_path:
        meta[_META_STAGE_GRAPH_PATH] = stage_graph_path
    else:
        meta.pop(_META_STAGE_GRAPH_PATH, None)

    meta[_META_COMMIT_PENDING] = bool(state.get("commit_pending"))
    if not meta[_META_COMMIT_PENDING]:
        meta.pop(_META_COMMIT_PENDING, None)

    commit_state = _normalize_commit_state(state.get("commit_state"))
    if commit_state:
        meta[_META_COMMIT_STATE] = commit_state
    else:
        meta.pop(_META_COMMIT_STATE, None)

    if graph_store is not None:
        current_total_nodes = graph_store.get_node_count()
        meta["total_nodes"] = current_total_nodes
        meta["total_edges"] = graph_store.get_edge_count()
        if state.get("status") in {"complete", "completed"}:
            meta["entity_resolution_last_completed_graph_nodes"] = current_total_nodes
            meta["entity_resolution_last_completed_at"] = state.get("updated_at")
    elif state.get("status") in {"complete", "completed"}:
        current_total_nodes = _coerce_non_negative_int(meta.get("total_nodes"))
        if current_total_nodes is not None:
            meta["entity_resolution_last_completed_graph_nodes"] = current_total_nodes
        meta["entity_resolution_last_completed_at"] = state.get("updated_at")
    _save_meta(world_id, meta)
    baseline = _coerce_non_negative_int(meta.get("entity_resolution_last_completed_graph_nodes"))
    current_total = _coerce_non_negative_int(meta.get("total_nodes"))
    state["new_nodes_since_last_completed_resolution"] = None if baseline is None or current_total is None else max(0, current_total - baseline)


def _persist_state_from_journal(
    world_id: str,
    journal: dict[str, Any],
    *,
    graph_store: GraphStore | None,
    status: str,
    phase: str | None = None,
    message: str | None = None,
    reason: str | None = None,
    current_anchor: dict[str, Any] | None = None,
    current_candidates: list[dict[str, Any]] | None = None,
    push_event: str | None = None,
) -> dict[str, Any]:
    payload = _state_payload_from_journal(
        journal,
        status=status,
        phase=phase,
        message=message,
        reason=reason,
        current_anchor=current_anchor,
        current_candidates=current_candidates,
    )
    state = _set_state(world_id, **payload)
    _update_meta_from_state(world_id, state, graph_store)
    if push_event:
        push_sse_event(world_id, {"event": push_event, **state})
    return state


def _recover_in_flight_transaction(
    world_id: str,
    journal: dict[str, Any],
    live_graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
) -> tuple[dict[str, Any], bool]:
    transaction = journal.get("in_flight_transaction")
    if not isinstance(transaction, dict):
        return journal, False

    entries: list[dict[str, Any]] = []
    winner_records: list[dict[str, Any]] = []
    if isinstance(transaction.get("entries"), list) and isinstance(transaction.get("winner_records"), list):
        entries = [dict(entry) for entry in transaction.get("entries", []) or [] if isinstance(entry, dict)]
        winner_records = [
            dict(record) for record in transaction.get("winner_records", []) or [] if isinstance(record, dict)
        ]
    else:
        entry = transaction.get("entry")
        expected_record = transaction.get("winner_record")
        if isinstance(entry, dict) and isinstance(expected_record, dict):
            entries = [dict(entry)]
            winner_records = [dict(expected_record)]

    if not entries or len(entries) != len(winner_records):
        journal = dict(journal)
        journal["in_flight_transaction"] = None
        return _save_recovery_journal(world_id, journal), True

    graph_applied = all(_merge_matches_snapshot(live_graph_store, entry) for entry in entries)
    try:
        vector_applied = all(
            _vector_matches_snapshot(unique_node_vector_store, entry, winner_records[index])
            for index, entry in enumerate(entries)
        )
    except Exception:
        vector_applied = False

    journal = dict(journal)
    if graph_applied and vector_applied:
        resolved_delta = 0
        auto_resolved_pairs_delta = 0
        exact_completed = 0
        ai_completed = 0
        for entry in entries:
            strategy = str(entry.get("strategy") or "exact")
            if strategy == "exact":
                journal["pending_exact_merges"] = _set_entry_status(
                    list(journal.get("pending_exact_merges", []) or []),
                    str(entry.get("entry_id")),
                    "complete",
                )
                exact_completed += 1
            else:
                journal["pending_ai_merges"] = _set_entry_status(
                    list(journal.get("pending_ai_merges", []) or []),
                    str(entry.get("entry_id")),
                    "complete",
                )
                ai_completed += 1
            resolved_delta += int(entry.get("group_size") or 0)
            auto_resolved_pairs_delta += int(entry.get("auto_resolved_pairs_delta") or 0)
        completed_count = exact_completed + ai_completed
        journal["committed_merge_count"] = int(journal.get("committed_merge_count") or 0) + completed_count
        journal["resolved_entities"] = int(journal.get("resolved_entities") or 0) + resolved_delta
        journal["unresolved_entities"] = max(
            0,
            int(journal.get("unresolved_entities") or 0) - resolved_delta,
        )
        journal["embedding_completed_entities"] = int(journal.get("embedding_completed_entities") or 0) + completed_count
        journal["auto_resolved_pairs"] = int(journal.get("auto_resolved_pairs") or 0) + auto_resolved_pairs_delta
        journal["in_flight_transaction"] = None
        journal["pending_exact_merges"] = _remove_completed_entries(list(journal.get("pending_exact_merges", []) or []))
        journal["pending_ai_merges"] = _remove_completed_entries(list(journal.get("pending_ai_merges", []) or []))
        return _save_recovery_journal(world_id, journal), True

    _restore_pending_merge_after_failure(live_graph_store, unique_node_vector_store, transaction)
    for entry in entries:
        strategy = str(entry.get("strategy") or "exact")
        if strategy == "exact":
            journal["pending_exact_merges"] = _set_entry_status(
                list(journal.get("pending_exact_merges", []) or []),
                str(entry.get("entry_id")),
                "pending_embedding",
            )
        else:
            journal["pending_ai_merges"] = _set_entry_status(
                list(journal.get("pending_ai_merges", []) or []),
                str(entry.get("entry_id")),
                "pending_embedding",
            )
    journal["in_flight_transaction"] = None
    return _save_recovery_journal(world_id, journal), True


def _commit_embedded_merge(
    world_id: str,
    journal: dict[str, Any],
    live_graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    entry: dict[str, Any],
    winner_record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    rollback_ids = [
        str(entry.get("winner_id") or "").strip(),
        *[str(node_id).strip() for node_id in entry.get("loser_ids", []) or [] if str(node_id).strip()],
    ]
    transaction = {
        "entry": deepcopy(entry),
        "winner_record": deepcopy(winner_record),
        "rollback_ids": rollback_ids,
        "rollback_graph_snapshot": _capture_merge_graph_snapshot(live_graph_store, rollback_ids),
        "rollback_vector_records": _snapshot_vector_records_for_ids(unique_node_vector_store, rollback_ids),
    }
    journal = dict(journal)
    journal["in_flight_transaction"] = transaction
    journal = _save_recovery_journal(world_id, journal)

    try:
        committed_anchor = _apply_merge_to_live_graph(live_graph_store, entry)
        _delete_vector_documents_batched(unique_node_vector_store, rollback_ids)
        unique_node_vector_store.upsert_records([winner_record])
    except Exception:
        _restore_pending_merge_after_failure(live_graph_store, unique_node_vector_store, transaction)
        raise

    strategy = str(entry.get("strategy") or "exact")
    if strategy == "exact":
        journal["pending_exact_merges"] = _set_entry_status(
            list(journal.get("pending_exact_merges", []) or []),
            str(entry.get("entry_id")),
            "complete",
        )
    else:
        journal["pending_ai_merges"] = _set_entry_status(
            list(journal.get("pending_ai_merges", []) or []),
            str(entry.get("entry_id")),
            "complete",
        )
    journal["committed_merge_count"] = int(journal.get("committed_merge_count") or 0) + 1
    journal["resolved_entities"] = int(journal.get("resolved_entities") or 0) + int(entry.get("group_size") or 0)
    journal["unresolved_entities"] = max(0, int(journal.get("unresolved_entities") or 0) - int(entry.get("group_size") or 0))
    journal["embedding_completed_entities"] = int(journal.get("embedding_completed_entities") or 0) + 1
    journal["auto_resolved_pairs"] = int(journal.get("auto_resolved_pairs") or 0) + int(
        entry.get("auto_resolved_pairs_delta") or 0
    )
    journal["in_flight_transaction"] = None
    journal["pending_exact_merges"] = _remove_completed_entries(list(journal.get("pending_exact_merges", []) or []))
    journal["pending_ai_merges"] = _remove_completed_entries(list(journal.get("pending_ai_merges", []) or []))
    return _save_recovery_journal(world_id, journal), committed_anchor


def _commit_embedded_exact_batch(
    world_id: str,
    journal: dict[str, Any],
    live_graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    entries: list[dict[str, Any]],
    winner_records: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any] | None]]:
    normalized_entries = [dict(entry) for entry in entries if isinstance(entry, dict)]
    normalized_winner_records = [dict(record) for record in winner_records if isinstance(record, dict)]
    if not normalized_entries:
        return journal, []
    if len(normalized_entries) != len(normalized_winner_records):
        raise ValueError("Exact batch commit requires one winner record per entry.")

    rollback_ids: list[str] = []
    for entry in normalized_entries:
        rollback_ids.extend(
            [
                str(entry.get("winner_id") or "").strip(),
                *[str(node_id).strip() for node_id in entry.get("loser_ids", []) or [] if str(node_id).strip()],
            ]
        )
    rollback_ids = [node_id for node_id in dict.fromkeys(rollback_ids) if node_id]
    transaction = {
        "entries": deepcopy(normalized_entries),
        "winner_records": deepcopy(normalized_winner_records),
        "rollback_ids": rollback_ids,
        "rollback_graph_snapshot": _capture_merge_graph_snapshot(live_graph_store, rollback_ids),
        "rollback_vector_records": _snapshot_vector_records_for_ids(unique_node_vector_store, rollback_ids),
    }
    journal = dict(journal)
    journal["in_flight_transaction"] = transaction
    journal = _save_recovery_journal(world_id, journal)

    committed_anchors: list[dict[str, Any] | None] = []
    try:
        for entry in normalized_entries:
            committed_anchors.append(_apply_merge_to_live_graph(live_graph_store, entry, save=False))
        live_graph_store.save()
        _delete_vector_documents_batched(unique_node_vector_store, rollback_ids)
        unique_node_vector_store.upsert_records(normalized_winner_records)
    except Exception:
        _restore_pending_merge_after_failure(live_graph_store, unique_node_vector_store, transaction)
        raise

    resolved_delta = sum(int(entry.get("group_size") or 0) for entry in normalized_entries)
    auto_resolved_pairs_delta = sum(int(entry.get("auto_resolved_pairs_delta") or 0) for entry in normalized_entries)
    for entry in normalized_entries:
        journal["pending_exact_merges"] = _set_entry_status(
            list(journal.get("pending_exact_merges", []) or []),
            str(entry.get("entry_id")),
            "complete",
        )
    journal["committed_merge_count"] = int(journal.get("committed_merge_count") or 0) + len(normalized_entries)
    journal["resolved_entities"] = int(journal.get("resolved_entities") or 0) + resolved_delta
    journal["unresolved_entities"] = max(0, int(journal.get("unresolved_entities") or 0) - resolved_delta)
    journal["embedding_completed_entities"] = int(journal.get("embedding_completed_entities") or 0) + len(normalized_entries)
    journal["auto_resolved_pairs"] = int(journal.get("auto_resolved_pairs") or 0) + auto_resolved_pairs_delta
    journal["in_flight_transaction"] = None
    journal["pending_exact_merges"] = _remove_completed_entries(list(journal.get("pending_exact_merges", []) or []))
    journal["pending_ai_merges"] = _remove_completed_entries(list(journal.get("pending_ai_merges", []) or []))
    return _save_recovery_journal(world_id, journal), committed_anchors


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return converted if isinstance(converted, list) else list(converted)
    try:
        return list(value)
    except TypeError:
        return []


def _normalize_embedding_rows(value: Any) -> list[list[float]]:
    rows = _as_sequence(value)
    normalized: list[list[float]] = []
    for row in rows:
        if row is None:
            normalized.append([])
            continue
        if hasattr(row, "tolist"):
            row = row.tolist()
        if isinstance(row, tuple):
            row = list(row)
        if not isinstance(row, list):
            row = list(row)
        normalized.append([float(item) for item in row])
    return normalized


def _snapshot_vector_store_records(vector_store: VectorStore) -> list[dict[str, Any]]:
    try:
        data = vector_store.collection.get(include=["documents", "metadatas", "embeddings"])
    except Exception as exc:
        raise RuntimeError(
            f"Unable to snapshot staged collection '{vector_store.collection_name}' during entity resolution commit."
        ) from exc

    ids = [str(record_id) for record_id in _as_sequence(data.get("ids")) if str(record_id).strip()]
    documents = _as_sequence(data.get("documents"))
    metadatas = _as_sequence(data.get("metadatas"))
    embeddings = _normalize_embedding_rows(data.get("embeddings"))
    if not ids:
        return []
    if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
        raise RuntimeError("Unique-node vector snapshot returned mismatched record lengths during entity resolution.")
    return [
        {
            "id": ids[index],
            "document": str(documents[index] or ""),
            "metadata": metadatas[index] if isinstance(metadatas[index], dict) else {},
            "embedding": embeddings[index],
        }
        for index in range(len(ids))
    ]


def _replace_vector_store_records(vector_store: VectorStore, records: list[dict[str, Any]]) -> None:
    vector_store.drop_collection()
    if not records:
        return
    vector_store.upsert_documents_embeddings(
        document_ids=[str(record["id"]) for record in records],
        texts=[str(record.get("document") or "") for record in records],
        metadatas=[
            record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            for record in records
        ],
        embeddings=[
            [float(value) for value in list(record.get("embedding") or [])]
            for record in records
        ],
    )


def _snapshot_vector_records_for_ids(vector_store: VectorStore, document_ids: list[str]) -> list[dict[str, Any]]:
    normalized_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
    if not normalized_ids:
        return []
    return vector_store.get_records_by_ids(
        normalized_ids,
        include_documents=True,
        include_embeddings=True,
        raise_on_error=True,
    )


def _delete_vector_documents_batched(vector_store: VectorStore, document_ids: list[str]) -> None:
    normalized_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
    if not normalized_ids:
        return
    batch_size = vector_store._get_max_upsert_batch_size() or _VECTOR_DELETE_BATCH_SIZE
    batch_size = max(1, int(batch_size))
    for start in range(0, len(normalized_ids), batch_size):
        vector_store.delete_documents(normalized_ids[start:start + batch_size])


def _restore_vector_records_snapshot(
    vector_store: VectorStore,
    document_ids: list[str],
    records: list[dict[str, Any]],
) -> None:
    normalized_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
    if normalized_ids:
        _delete_vector_documents_batched(vector_store, normalized_ids)
    if records:
        vector_store.upsert_records(records)


def _capture_merge_graph_snapshot(graph_store: GraphStore, node_ids: list[str]) -> dict[str, Any]:
    graph = graph_store.graph
    affected_ids = [str(node_id).strip() for node_id in node_ids if str(node_id).strip()]
    nodes: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    for node_id in affected_ids:
        if node_id in seen_nodes or node_id not in graph.nodes:
            continue
        seen_nodes.add(node_id)
        nodes.append(
            {
                "node_id": node_id,
                "attrs": deepcopy(dict(graph.nodes[node_id])),
            }
        )

    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[Any, ...]] = set()
    if graph.is_multigraph():
        if graph.is_directed():
            iterables = []
            for node_id in affected_ids:
                iterables.extend(
                    [
                        graph.out_edges(node_id, keys=True, data=True),
                        graph.in_edges(node_id, keys=True, data=True),
                    ]
                )
            for iterable in iterables:
                for source_id, target_id, edge_key, attrs in iterable:
                    token = (source_id, target_id, edge_key)
                    if token in seen_edges:
                        continue
                    seen_edges.add(token)
                    edges.append(
                        {
                            "source": source_id,
                            "target": target_id,
                            "key": edge_key,
                            "attrs": deepcopy(dict(attrs)),
                        }
                    )
        else:
            for node_id in affected_ids:
                for source_id, target_id, edge_key, attrs in graph.edges(node_id, keys=True, data=True):
                    token = (source_id, target_id, edge_key)
                    if token in seen_edges:
                        continue
                    seen_edges.add(token)
                    edges.append(
                        {
                            "source": source_id,
                            "target": target_id,
                            "key": edge_key,
                            "attrs": deepcopy(dict(attrs)),
                        }
                    )
    else:
        if graph.is_directed():
            iterables = []
            for node_id in affected_ids:
                iterables.extend([graph.out_edges(node_id, data=True), graph.in_edges(node_id, data=True)])
            for iterable in iterables:
                for source_id, target_id, attrs in iterable:
                    token = (source_id, target_id)
                    if token in seen_edges:
                        continue
                    seen_edges.add(token)
                    edges.append(
                        {
                            "source": source_id,
                            "target": target_id,
                            "attrs": deepcopy(dict(attrs)),
                        }
                    )
        else:
            for node_id in affected_ids:
                for source_id, target_id, attrs in graph.edges(node_id, data=True):
                    token = tuple(sorted((str(source_id), str(target_id))))
                    if token in seen_edges:
                        continue
                    seen_edges.add(token)
                    edges.append(
                        {
                            "source": source_id,
                            "target": target_id,
                            "attrs": deepcopy(dict(attrs)),
                        }
                    )

    return {
        "node_ids": affected_ids,
        "nodes": nodes,
        "edges": edges,
    }


def _restore_merge_graph_snapshot(graph_store: GraphStore, snapshot: dict[str, Any]) -> None:
    graph = graph_store.graph
    affected_ids = [str(node_id).strip() for node_id in snapshot.get("node_ids", []) or [] if str(node_id).strip()]
    for node_id in affected_ids:
        if node_id in graph.nodes:
            graph.remove_node(node_id)

    for node in snapshot.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id", "")).strip()
        if not node_id:
            continue
        attrs = deepcopy(node.get("attrs") if isinstance(node.get("attrs"), dict) else {})
        graph.add_node(node_id, **attrs)

    for edge in snapshot.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        source_id = edge.get("source")
        target_id = edge.get("target")
        attrs = deepcopy(edge.get("attrs") if isinstance(edge.get("attrs"), dict) else {})
        if graph.is_multigraph():
            edge_key = edge.get("key")
            if edge_key is None:
                graph.add_edge(source_id, target_id, **attrs)
            else:
                graph.add_edge(source_id, target_id, key=edge_key, **attrs)
        else:
            graph.add_edge(source_id, target_id, **attrs)


def _reconcile_live_unique_node_drift(
    world_id: str,
    live_graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
) -> dict[str, Any]:
    records = unique_node_vector_store.get_all_records(raise_on_error=True)
    graph_ids = {str(node_id) for node_id in live_graph_store.graph.nodes()}
    vector_ids = {str(record.get("id")) for record in records if str(record.get("id", "")).strip()}
    orphan_ids = sorted(vector_ids - graph_ids)
    if orphan_ids:
        logger.warning(
            "Pruning %s orphan unique-node vector records before entity resolution for %s",
            len(orphan_ids),
            world_id,
        )
        _delete_vector_documents_batched(unique_node_vector_store, orphan_ids)
    missing_ids = sorted(graph_ids - vector_ids)
    return {
        "orphaned_records_removed": len(orphan_ids),
        "missing_graph_node_ids": missing_ids,
    }


def _build_exact_merge_entry(graph_store: GraphStore, group: list[str]) -> dict[str, Any] | None:
    nodes = [snapshot for snapshot in (_node_snapshot(graph_store, node_id) for node_id in group) if snapshot]
    if len(nodes) < 2:
        return None
    display_name, description = _combine_exact_match_group(nodes)
    winner_id = str(group[0])
    loser_ids = [str(node_id) for node_id in group[1:]]
    merged_claims: list[Any] = []
    merged_source_chunks: list[Any] = []
    merged_provenance: list[Any] = []
    for snapshot in nodes:
        merged_claims.extend(snapshot.get("claims", []) if isinstance(snapshot.get("claims"), list) else [])
        merged_source_chunks.extend(
            snapshot.get("source_chunks", []) if isinstance(snapshot.get("source_chunks"), list) else []
        )
        merged_provenance.extend(_snapshot_provenance_entries(snapshot))

    winner_snapshot = dict(nodes[0])
    winner_snapshot["display_name"] = display_name
    winner_snapshot["description"] = description
    winner_snapshot["normalized_name"] = _normalize_display_name(display_name)
    winner_snapshot["normalized_id"] = _normalized_id_from_name(display_name)
    winner_snapshot["claims"] = _dedupe_jsonable(merged_claims)
    winner_snapshot["source_chunks"] = _dedupe_jsonable(merged_source_chunks)
    winner_snapshot["merge_provenance"] = _dedupe_jsonable(
        [entry for entry in merged_provenance if isinstance(entry, dict) and str(entry.get("node_id", "")).strip()]
    )
    return {
        "entry_id": uuid.uuid4().hex,
        "strategy": "exact",
        "status": "pending_embedding",
        "winner_id": winner_id,
        "loser_ids": loser_ids,
        "group_ids": [str(node_id) for node_id in group],
        "group_size": len(group),
        "auto_resolved_pairs_delta": len(loser_ids),
        "winner_snapshot": winner_snapshot,
        "source_snapshots": nodes,
    }


def _build_exact_merge_plan(
    graph_store: GraphStore,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    exact_groups = _group_exact_matches(graph_store, list(graph_store.graph.nodes()))
    total_groups = len(exact_groups)
    for index, group in enumerate(exact_groups, start=1):
        entry = _build_exact_merge_entry(graph_store, group)
        if not entry:
            if progress_callback is not None and (index == total_groups or index % 25 == 0):
                progress_callback(index, total_groups)
            continue
        plan.append(entry)
        if progress_callback is not None and (index == total_groups or index % 25 == 0):
            progress_callback(index, total_groups)
    return plan


def _winner_vector_record(entry: dict[str, Any], embedding: list[float]) -> dict[str, Any]:
    winner_snapshot = entry.get("winner_snapshot") if isinstance(entry.get("winner_snapshot"), dict) else {}
    winner_id = str(winner_snapshot.get("node_id") or entry.get("winner_id") or "").strip()
    return {
        "id": winner_id,
        "document": _entity_document(winner_snapshot),
        "metadata": _build_unique_node_metadata(winner_snapshot),
        "embedding": [float(value) for value in list(embedding or [])],
    }


def _merge_matches_snapshot(graph_store: GraphStore, entry: dict[str, Any]) -> bool:
    winner_snapshot = entry.get("winner_snapshot") if isinstance(entry.get("winner_snapshot"), dict) else None
    if not winner_snapshot:
        return False
    winner_id = str(entry.get("winner_id") or winner_snapshot.get("node_id") or "").strip()
    if not winner_id:
        return False
    loser_ids = [str(node_id) for node_id in entry.get("loser_ids", []) or [] if str(node_id).strip()]
    for loser_id in loser_ids:
        if loser_id in graph_store.graph.nodes:
            return False
    live_winner = _node_snapshot(graph_store, winner_id)
    if not live_winner:
        return False
    comparable_keys = ("display_name", "description", "claims", "source_chunks", "merge_provenance")
    for key in comparable_keys:
        if json.dumps(live_winner.get(key), sort_keys=True, ensure_ascii=False) != json.dumps(
            winner_snapshot.get(key), sort_keys=True, ensure_ascii=False
        ):
            return False
    return True


def _vector_matches_snapshot(unique_node_vector_store: VectorStore, entry: dict[str, Any], expected_record: dict[str, Any]) -> bool:
    loser_ids = [str(node_id) for node_id in entry.get("loser_ids", []) or [] if str(node_id).strip()]
    winner_id = str(expected_record.get("id") or "").strip()
    current_records = unique_node_vector_store.get_records_by_ids(
        [winner_id, *loser_ids],
        include_documents=True,
        include_embeddings=False,
        raise_on_error=True,
    )
    current_by_id = {str(record.get("id")): record for record in current_records}
    if any(loser_id in current_by_id for loser_id in loser_ids):
        return False
    winner_record = current_by_id.get(winner_id)
    if not winner_record:
        return False
    return str(winner_record.get("document") or "") == str(expected_record.get("document") or "")


def _restore_pending_merge_after_failure(
    live_graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    transaction: dict[str, Any],
) -> None:
    graph_snapshot = transaction.get("rollback_graph_snapshot") if isinstance(transaction.get("rollback_graph_snapshot"), dict) else {}
    vector_snapshot = transaction.get("rollback_vector_records") if isinstance(transaction.get("rollback_vector_records"), list) else []
    rollback_ids = [str(node_id) for node_id in transaction.get("rollback_ids", []) or [] if str(node_id).strip()]
    _restore_merge_graph_snapshot(live_graph_store, graph_snapshot)
    live_graph_store.save()
    _restore_vector_records_snapshot(unique_node_vector_store, rollback_ids, vector_snapshot)


def _apply_merge_to_live_graph(
    live_graph_store: GraphStore,
    entry: dict[str, Any],
    *,
    save: bool = True,
) -> dict[str, Any] | None:
    winner_snapshot = entry.get("winner_snapshot") if isinstance(entry.get("winner_snapshot"), dict) else None
    if not winner_snapshot:
        return None
    winner_id = str(entry.get("winner_id") or winner_snapshot.get("node_id") or "").strip()
    loser_ids = [str(node_id) for node_id in entry.get("loser_ids", []) or [] if str(node_id).strip()]
    _merge_group(
        live_graph_store,
        winner_id,
        loser_ids,
        str(winner_snapshot.get("display_name") or "").strip(),
        str(winner_snapshot.get("description") or "").strip(),
    )
    if winner_id not in live_graph_store.graph.nodes:
        return None
    winner_attrs = live_graph_store.graph.nodes[winner_id]
    winner_attrs["display_name"] = str(winner_snapshot.get("display_name") or "").strip()
    winner_attrs["description"] = str(winner_snapshot.get("description") or "").strip()
    winner_attrs["normalized_id"] = str(winner_snapshot.get("normalized_id") or _normalized_id_from_name(winner_attrs["display_name"]))
    winner_attrs["claims"] = deepcopy(winner_snapshot.get("claims", [])) if isinstance(winner_snapshot.get("claims"), list) else []
    winner_attrs["source_chunks"] = (
        deepcopy(winner_snapshot.get("source_chunks", []))
        if isinstance(winner_snapshot.get("source_chunks"), list)
        else []
    )
    winner_attrs["merge_provenance"] = (
        deepcopy(winner_snapshot.get("merge_provenance", []))
        if isinstance(winner_snapshot.get("merge_provenance"), list)
        else []
    )
    winner_attrs["updated_at"] = _now_iso()
    if save:
        live_graph_store.save()
    return _node_snapshot(live_graph_store, winner_id)


def _finalize_resolution_commit(
    world_id: str,
    *,
    live_graph_store: GraphStore,
    stage_suffix: str,
    stage_graph_path: Path,
    final_state_updates: dict[str, Any],
    push_terminal_event: bool = True,
) -> dict[str, Any]:
    staged_graph_store = _load_staged_graph_store(world_id, stage_graph_path)
    staged_vector_store = _get_unique_node_vector_store(world_id, collection_suffix=stage_suffix)
    staged_records = _snapshot_vector_store_records(staged_vector_store)

    live_graph_store.graph = staged_graph_store.graph.copy(as_view=False)
    live_graph_store.save()

    live_unique_node_store = _get_unique_node_vector_store(world_id)
    _replace_vector_store_records(live_unique_node_store, staged_records)

    state_payload = dict(_states.get(world_id, {}))
    state_payload.update(
        {
            "current_anchor": None,
            "current_candidates": [],
            "current_anchor_label": None,
            "staging_collection_suffix": None,
            "staging_graph_path": None,
            "commit_pending": False,
            **final_state_updates,
        }
    )
    state_payload["updated_at"] = _now_iso()
    _update_meta_from_state(world_id, state_payload, live_graph_store)
    state = _set_state(world_id, **state_payload)
    _cleanup_staging_artifacts(
        world_id,
        {
            _META_STAGE_COLLECTION_SUFFIX: stage_suffix,
            _META_STAGE_GRAPH_PATH: str(stage_graph_path),
        },
    )
    if push_terminal_event:
        terminal_event = "complete" if state.get("status") == "complete" else str(state.get("status") or "status")
        push_sse_event(world_id, {"event": terminal_event, **state})
    return state


def _resolution_failure_message(base: str) -> str:
    return base


async def start_entity_resolution(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
    resolution_mode: EntityResolutionMode,
    embedding_batch_size: int | None = None,
    embedding_cooldown_seconds: float | None = None,
) -> None:
    from .entity_resolution_incremental import start_entity_resolution_incremental

    return await start_entity_resolution_incremental(
        world_id,
        top_k,
        review_mode,
        include_normalized_exact_pass,
        resolution_mode,
        embedding_batch_size,
        embedding_cooldown_seconds,
    )
    abort_event = _abort_events.get(world_id)
    if abort_event is None:
        abort_event = threading.Event()
        _abort_events[world_id] = abort_event
    _active_runs.add(world_id)
    live_graph_store: GraphStore | None = None
    stage_suffix: str | None = None
    try:
        live_graph_store = GraphStore(world_id)
        working_graph_store = _working_graph_store(world_id, live_graph_store)
        initial_ids = list(working_graph_store.graph.nodes())
        initial_total = len(initial_ids)
        normalized_resolution_mode = resolve_entity_resolution_mode(
            resolution_mode,
            include_normalized_exact_pass,
        )
        normalized_embedding_batch_size = _normalize_embedding_batch_size(embedding_batch_size)
        normalized_embedding_cooldown_seconds = _normalize_embedding_cooldown_seconds(embedding_cooldown_seconds)
        include_exact_pass = _mode_uses_exact_pass(normalized_resolution_mode)
        use_ai_pass = _mode_uses_ai_pass(normalized_resolution_mode)
        current_anchor_label = _current_anchor_label_for_mode(normalized_resolution_mode)
        stage_suffix = _new_staging_collection_suffix()
        stage_vector_store = _get_unique_node_vector_store(world_id, collection_suffix=stage_suffix)

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
            embedding_completed_entities=0,
            embedding_total_entities=0,
            auto_resolved_pairs=0,
            current_anchor=None,
            current_candidates=[],
            current_anchor_label=current_anchor_label,
            staging_collection_suffix=stage_suffix,
            staging_graph_path=str(_staging_graph_path(world_id)),
            commit_pending=False,
            commit_state="staging",
            can_resume=False,
        )
        _update_meta_from_state(world_id, state, live_graph_store)
        push_sse_event(world_id, {"event": "status", **state})
        _ensure_not_aborted(world_id, abort_event)

        if initial_total == 0:
            _save_graph_store(working_graph_store)
            _finalize_resolution_commit(
                world_id,
                live_graph_store=live_graph_store,
                stage_suffix=stage_suffix,
                stage_graph_path=working_graph_store.path,
                final_state_updates={
                    "status": "complete",
                    "phase": "complete",
                    "message": "No entities are available for resolution.",
                    "reason": None,
                    "top_k": top_k,
                    "embedding_batch_size": normalized_embedding_batch_size,
                    "embedding_cooldown_seconds": normalized_embedding_cooldown_seconds,
                    "resolution_mode": normalized_resolution_mode,
                    "review_mode": review_mode,
                    "include_normalized_exact_pass": include_exact_pass,
                    "total_entities": 0,
                    "resolved_entities": 0,
                    "unresolved_entities": 0,
                    "auto_resolved_pairs": 0,
                    "commit_state": "committed",
                },
            )
            return

        remaining_ids = list(initial_ids)
        processed_count = 0
        auto_resolved_pairs = 0
        embedding_completed_entities = 0
        embedding_total_entities = 0

        state = _set_state(
            world_id,
            phase="preparing",
            message="Cloning the staged unique node index from the current world state.",
            resolved_entities=processed_count,
            unresolved_entities=len(remaining_ids),
            embedding_completed_entities=embedding_completed_entities,
            embedding_total_entities=embedding_total_entities,
            auto_resolved_pairs=auto_resolved_pairs,
            current_anchor_label=current_anchor_label,
        )
        _update_meta_from_state(world_id, state, live_graph_store)
        push_sse_event(world_id, {"event": "progress", **state})
        stage_vector_store = await _bootstrap_staged_unique_node_index(world_id, stage_vector_store)

        if include_exact_pass:
            exact_groups = [
                group
                for group in _group_exact_matches(working_graph_store, remaining_ids)
                if len([snapshot for snapshot in (_node_snapshot(working_graph_store, node_id) for node_id in group) if snapshot]) >= 2
            ]
            embedding_total_entities += len(exact_groups)
            state = _set_state(world_id, phase="exact_match_pass", message="Running exact match pass after normalization.")
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state})

            for group in exact_groups:
                _ensure_not_aborted(world_id, abort_event)
                nodes = [snapshot for snapshot in (_node_snapshot(working_graph_store, node_id) for node_id in group) if snapshot]
                if len(nodes) < 2:
                    continue
                display_name, description = _combine_exact_match_group(nodes)
                winner_id = group[0]
                loser_ids = group[1:]
                _merge_group(working_graph_store, winner_id, loser_ids, display_name, description)
                await _refresh_unique_node_index_after_merge(
                    stage_vector_store,
                    working_graph_store,
                    winner_id,
                    loser_ids,
                    batch_size=normalized_embedding_batch_size,
                    cooldown_seconds=normalized_embedding_cooldown_seconds,
                    abort_event=abort_event,
                )

                processed_count += len(group)
                auto_resolved_pairs += len(loser_ids)
                embedding_completed_entities += 1
                remaining_ids = [node_id for node_id in remaining_ids if node_id not in group]

                state = _set_state(
                    world_id,
                    message=f"Auto-resolved exact normalized match group for {display_name}.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
                    embedding_completed_entities=embedding_completed_entities,
                    embedding_total_entities=embedding_total_entities,
                    auto_resolved_pairs=auto_resolved_pairs,
                    current_anchor_label=current_anchor_label,
                )
                _update_meta_from_state(world_id, state, live_graph_store)
                push_sse_event(
                    world_id,
                    {
                        "event": "progress",
                        **state,
                        "current_anchor": {"node_id": winner_id, "display_name": display_name},
                        "current_anchor_label": current_anchor_label,
                    },
                )

        if not use_ai_pass:
            _save_graph_store(working_graph_store)
            state = _set_state(
                world_id,
                phase="committing",
                message="Finalizing exact-only entity resolution.",
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
                current_anchor=None,
                current_candidates=[],
                current_anchor_label=current_anchor_label,
                staging_collection_suffix=stage_suffix,
                staging_graph_path=str(working_graph_store.path),
                commit_pending=True,
                commit_state="commit_pending",
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state})
            _finalize_resolution_commit(
                world_id,
                live_graph_store=live_graph_store,
                stage_suffix=stage_suffix,
                stage_graph_path=working_graph_store.path,
                final_state_updates={
                    "status": "complete",
                    "phase": "complete",
                    "message": "Exact-only entity resolution complete.",
                    "reason": None,
                    "top_k": top_k,
                    "embedding_batch_size": normalized_embedding_batch_size,
                    "embedding_cooldown_seconds": normalized_embedding_cooldown_seconds,
                    "resolution_mode": normalized_resolution_mode,
                    "review_mode": review_mode,
                    "include_normalized_exact_pass": include_exact_pass,
                    "total_entities": initial_total,
                    "resolved_entities": processed_count,
                    "unresolved_entities": len(remaining_ids),
                    "embedding_completed_entities": embedding_completed_entities,
                    "embedding_total_entities": embedding_total_entities,
                    "auto_resolved_pairs": auto_resolved_pairs,
                    "commit_state": "committed",
                },
            )
            return

        while remaining_ids:
            _ensure_not_aborted(world_id, abort_event)

            anchor_id = remaining_ids[0]
            anchor = _node_snapshot(working_graph_store, anchor_id)
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
                    current_anchor_label=current_anchor_label,
                )
                _update_meta_from_state(world_id, state, live_graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "current_anchor_label": current_anchor_label})
                continue

            state = _set_state(
                world_id,
                phase="candidate_search",
                message=f"Searching candidate entities for {anchor['display_name']}.",
                current_anchor=anchor,
                current_candidates=[],
                current_anchor_label=current_anchor_label,
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state, "current_anchor_label": current_anchor_label})

            _ensure_not_aborted(world_id, abort_event)
            candidates = await _query_candidates(
                working_graph_store,
                stage_vector_store,
                anchor_id,
                remaining_ids,
                top_k,
                abort_event=abort_event,
            )
            _ensure_not_aborted(world_id, abort_event)
            state = _set_state(
                world_id,
                phase="candidate_search",
                message=f"Evaluating {len(candidates)} candidates for {anchor['display_name']}.",
                current_anchor=anchor,
                current_candidates=candidates,
                current_anchor_label=current_anchor_label,
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state, "current_anchor_label": current_anchor_label})

            chosen_ids: list[str] = []
            chooser_reason = "No candidates were selected."
            if candidates:
                _ensure_not_aborted(world_id, abort_event)
                state = _set_state(
                    world_id,
                    phase="chooser",
                    message=f"Chooser evaluating {len(candidates)} candidate entities.",
                    current_anchor_label=current_anchor_label,
                )
                _update_meta_from_state(world_id, state, live_graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "current_anchor_label": current_anchor_label})
                chosen_ids, chooser_reason = await _choose_matches(anchor, candidates, world_id=world_id)
                _ensure_not_aborted(world_id, abort_event)
                chosen_ids = [node_id for node_id in chosen_ids if node_id in remaining_ids and node_id != anchor_id]

            if chosen_ids:
                group_ids = [anchor_id, *chosen_ids]
                nodes = [snapshot for snapshot in (_node_snapshot(working_graph_store, node_id) for node_id in group_ids) if snapshot]
                state = _set_state(
                    world_id,
                    phase="combiner",
                    message=f"Merging {len(group_ids)} entities for {anchor['display_name']}.",
                    current_anchor_label=current_anchor_label,
                )
                _update_meta_from_state(world_id, state, live_graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "reason": chooser_reason, "current_anchor_label": current_anchor_label})

                _ensure_not_aborted(world_id, abort_event)
                display_name, description = await _combine_entities(nodes, world_id=world_id)
                _ensure_not_aborted(world_id, abort_event)
                _merge_group(working_graph_store, anchor_id, chosen_ids, display_name, description)
                await _refresh_unique_node_index_after_merge(
                    stage_vector_store,
                    working_graph_store,
                    anchor_id,
                    chosen_ids,
                    batch_size=normalized_embedding_batch_size,
                    cooldown_seconds=normalized_embedding_cooldown_seconds,
                    abort_event=abort_event,
                )

                processed_count += len(group_ids)
                embedding_total_entities += 1
                embedding_completed_entities += 1
                remaining_ids = [node_id for node_id in remaining_ids if node_id not in group_ids]
                auto_resolved_pairs += len(chosen_ids)
                state = _set_state(
                    world_id,
                    phase="applied",
                    message=f"Merged {len(group_ids)} entities into {display_name}.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
                    embedding_completed_entities=embedding_completed_entities,
                    embedding_total_entities=embedding_total_entities,
                    auto_resolved_pairs=auto_resolved_pairs,
                    current_anchor={"node_id": anchor_id, "display_name": display_name, "description": description},
                    current_candidates=[],
                    current_anchor_label=current_anchor_label,
                )
                _update_meta_from_state(world_id, state, live_graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "reason": chooser_reason, "current_anchor_label": current_anchor_label})
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
                    current_anchor_label=current_anchor_label,
                )
                _update_meta_from_state(world_id, state, live_graph_store)
                push_sse_event(world_id, {"event": "progress", **state, "current_anchor_label": current_anchor_label})

        _save_graph_store(working_graph_store)
        state = _set_state(
            world_id,
            phase="committing",
            message="Finalizing entity resolution.",
            resolved_entities=processed_count,
            unresolved_entities=len(remaining_ids),
            auto_resolved_pairs=auto_resolved_pairs,
            current_anchor=None,
            current_candidates=[],
            current_anchor_label=current_anchor_label,
            staging_collection_suffix=stage_suffix,
            staging_graph_path=str(working_graph_store.path),
            commit_pending=True,
            commit_state="commit_pending",
        )
        _update_meta_from_state(world_id, state, live_graph_store)
        push_sse_event(world_id, {"event": "progress", **state})

        final_unique_entity_count = working_graph_store.get_node_count()
        _finalize_resolution_commit(
            world_id,
            live_graph_store=live_graph_store,
            stage_suffix=stage_suffix,
            stage_graph_path=working_graph_store.path,
            final_state_updates={
                "status": "complete",
                "phase": "complete",
                "message": "Entity resolution complete.",
                "reason": None,
                "top_k": top_k,
                "embedding_batch_size": normalized_embedding_batch_size,
                "embedding_cooldown_seconds": normalized_embedding_cooldown_seconds,
                "resolution_mode": normalized_resolution_mode,
                "review_mode": review_mode,
                "include_normalized_exact_pass": include_exact_pass,
                "total_entities": initial_total,
                "resolved_entities": initial_total,
                "unresolved_entities": 0,
                "embedding_completed_entities": embedding_completed_entities,
                "embedding_total_entities": embedding_total_entities,
                "auto_resolved_pairs": auto_resolved_pairs,
                "commit_state": "committed",
            },
        )
    except asyncio.CancelledError:
        if stage_suffix:
            _cleanup_staging_artifacts(
                world_id,
                {
                    _META_STAGE_COLLECTION_SUFFIX: stage_suffix,
                    _META_STAGE_GRAPH_PATH: str(_staging_graph_path(world_id)),
                },
            )
        state = _set_state(
            world_id,
            status="aborted",
            phase="aborted",
            message=_resolution_failure_message("Entity resolution aborted."),
            reason="aborted",
            current_anchor=None,
            current_candidates=[],
            current_anchor_label=None,
            staging_collection_suffix=None,
            staging_graph_path=None,
            commit_pending=False,
            commit_state=None,
        )
        _update_meta_from_state(world_id, state, live_graph_store)
        push_sse_event(world_id, {"event": "aborted", **state})
    except Exception as exc:
        logger.exception("Entity resolution failed for %s", world_id)
        current_state = dict(_states.get(world_id, {}))
        if stage_suffix and not _is_commit_pending_state(current_state):
            _cleanup_staging_artifacts(
                world_id,
                {
                    _META_STAGE_COLLECTION_SUFFIX: stage_suffix,
                    _META_STAGE_GRAPH_PATH: str(_staging_graph_path(world_id)),
                },
            )
        if _is_commit_pending_state(current_state):
            state = _set_state(
                world_id,
                status="error",
                phase="commit_pending",
                message="Entity-resolution commit finalization was interrupted. Recovery will verify the committed result.",
                reason=str(exc),
                current_anchor=None,
                current_candidates=[],
                current_anchor_label=None,
                staging_collection_suffix=stage_suffix,
                staging_graph_path=str(_staging_graph_path(world_id)) if stage_suffix else None,
                commit_pending=True,
                commit_state="commit_pending",
            )
            try:
                _update_meta_from_state(world_id, state, live_graph_store)
            except Exception:
                logger.warning("Failed to persist commit-pending entity-resolution recovery state for %s", world_id, exc_info=True)
            push_sse_event(world_id, {"event": "error", **state})
        else:
            fail_entity_resolution_startup(
                world_id,
                _resolution_failure_message("Entity resolution failed."),
                reason=str(exc),
                graph_store=live_graph_store,
            )
    finally:
        _active_runs.discard(world_id)
        if _abort_events.get(world_id) is abort_event:
            _abort_events.pop(world_id, None)
