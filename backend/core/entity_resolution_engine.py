"""Post-ingestion entity resolution pipeline with SSE progress updates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .agents import _call_agent
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
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(str(tmp), str(path))


def _staging_graph_path(world_id: str) -> Path:
    return world_meta_path(world_id).parent / "entity_resolution_staging_graph.gexf"


def _new_staging_collection_suffix() -> str:
    return f"unique_nodes_staging_{uuid.uuid4().hex}"


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


def get_resolution_status(world_id: str) -> dict[str, Any]:
    with _get_lock(_state_locks, world_id):
        current = dict(_states.get(world_id, {}))

    if current:
        if world_id not in _active_runs and _is_commit_pending_state(current):
            return _recover_stale_run(world_id)
        if world_id not in _active_runs and _is_stale_in_progress(current):
            return _recover_stale_run(world_id)
        return _with_new_node_summary(world_id, current)

    if not world_meta_path(world_id).exists():
        return {}

    meta = _load_meta(world_id)
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
            "auto_resolved_pairs": meta.get("entity_resolution_auto_resolved_pairs", 0),
            "total_entities": meta.get("entity_resolution_total_entities", 0),
            "resolution_mode": resolution_mode,
            "review_mode": meta.get("entity_resolution_review_mode", False),
            "include_normalized_exact_pass": _mode_uses_exact_pass(resolution_mode),
            "can_resume": False,
            "current_anchor_label": meta.get(_META_CURRENT_ANCHOR_LABEL),
            "commit_state": _normalize_commit_state(meta.get(_META_COMMIT_STATE)),
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
        current_anchor_label=None,
        can_resume=False,
        staging_collection_suffix=None,
        staging_graph_path=None,
        commit_pending=False,
        commit_state="staging",
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
) -> tuple[str, int]:
    key_manager = get_key_manager()
    while True:
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError()
        try:
            return key_manager.get_active_key()
        except AllKeysInCooldownError as exc:
            await _sleep_with_abort(abort_event, jittered_delay(exc.retry_after_seconds))


async def _embed_texts_abortable(
    vector_store: VectorStore,
    texts: list[str],
    *,
    abort_event: threading.Event | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    candidates = vector_store._candidate_embedding_models()
    key_manager = get_key_manager()
    last_error: Exception | None = None
    current_api_key, current_key_index = await _await_available_key(abort_event)
    max_key_attempts = max(3, key_manager.key_count * 2)

    for attempt in range(max_key_attempts):
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError()
        client = vector_store._get_embed_client(current_api_key)
        rotate_key = False

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
                    current_api_key, current_key_index = await _await_available_key(abort_event)
                    rotate_key = True
                    break
                if ("not found" in message or "not supported" in message) and model_name != candidates[-1]:
                    continue
                rotate_key = False
                break

        if rotate_key:
            if attempt < max_key_attempts - 1:
                await _sleep_with_abort(abort_event, jittered_delay(0.5))
            continue
        break

    if last_error:
        raise last_error
    raise RuntimeError("Embedding generation failed with no model candidates.")


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

    total_written = 0
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


async def _query_candidates(
    graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    anchor_id: str,
    remaining_ids: list[str],
    top_k: int,
    *,
    abort_event: threading.Event | None = None,
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
    model_name = settings.get("default_model_entity_chooser", "gemini-flash-latest")
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
    model_name = settings.get("default_model_entity_combiner", "gemini-flash-lite-latest")
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
    elif state.get("status") in {"complete", "completed"}:
        current_total_nodes = _coerce_non_negative_int(meta.get("total_nodes"))
        if current_total_nodes is not None:
            meta["entity_resolution_last_completed_graph_nodes"] = current_total_nodes
    _save_meta(world_id, meta)
    baseline = _coerce_non_negative_int(meta.get("entity_resolution_last_completed_graph_nodes"))
    current_total = _coerce_non_negative_int(meta.get("total_nodes"))
    state["new_nodes_since_last_completed_resolution"] = None if baseline is None or current_total is None else max(0, current_total - baseline)


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
    return f"{base} No graph changes were kept."


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

        if include_exact_pass:
            state = _set_state(world_id, phase="exact_match_pass", message="Running exact match pass after normalization.")
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state})

            exact_groups = _group_exact_matches(working_graph_store, remaining_ids)
            for group in exact_groups:
                _ensure_not_aborted(world_id, abort_event)
                nodes = [snapshot for snapshot in (_node_snapshot(working_graph_store, node_id) for node_id in group) if snapshot]
                if len(nodes) < 2:
                    continue
                display_name, description = _combine_exact_match_group(nodes)
                winner_id = group[0]
                loser_ids = group[1:]
                _merge_group(working_graph_store, winner_id, loser_ids, display_name, description)

                processed_count += len(group)
                auto_resolved_pairs += len(loser_ids)
                remaining_ids = [node_id for node_id in remaining_ids if node_id not in group]

                state = _set_state(
                    world_id,
                    message=f"Auto-resolved exact normalized match group for {display_name}.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
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

            state = _set_state(
                world_id,
                phase="index_refresh",
                message="Refreshing staged unique node index after exact match pass.",
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
                current_anchor_label=current_anchor_label,
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state})
            stage_vector_store = await _rebuild_unique_node_index(
                stage_vector_store,
                working_graph_store,
                batch_size=normalized_embedding_batch_size,
                cooldown_seconds=normalized_embedding_cooldown_seconds,
                abort_event=abort_event,
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
                    "auto_resolved_pairs": auto_resolved_pairs,
                    "commit_state": "committed",
                },
            )
            return

        if not include_exact_pass:
            state = _set_state(
                world_id,
                phase="index_refresh",
                message="Preparing staged unique node index for AI candidate search.",
                resolved_entities=processed_count,
                unresolved_entities=len(remaining_ids),
                auto_resolved_pairs=auto_resolved_pairs,
                current_anchor_label=current_anchor_label,
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "progress", **state})
            stage_vector_store = await _rebuild_unique_node_index(
                stage_vector_store,
                working_graph_store,
                batch_size=normalized_embedding_batch_size,
                cooldown_seconds=normalized_embedding_cooldown_seconds,
                abort_event=abort_event,
            )

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
                remaining_ids = [node_id for node_id in remaining_ids if node_id not in group_ids]
                auto_resolved_pairs += len(chosen_ids)
                state = _set_state(
                    world_id,
                    phase="applied",
                    message=f"Merged {len(group_ids)} entities into {display_name}.",
                    resolved_entities=processed_count,
                    unresolved_entities=len(remaining_ids),
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
