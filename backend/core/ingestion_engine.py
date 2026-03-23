"""Orchestrates ingestion with stage-aware failure tracking and retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from .agents import AgentCallError, GraphArchitectAgent
from .chunker import RecursiveChunker
from .config import (
    get_world_ingest_settings,
    load_settings,
    world_checkpoint_path,
    world_log_path,
    world_meta_path,
    world_safety_reviews_path,
    world_sources_dir,
)
from .entity_text import build_unique_node_document
from .graph_store import GraphStore
from .key_manager import AllKeysInCooldownError, get_key_manager, jittered_delay
from .temporal_indexer import TemporalChunk, stamp_chunks
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

# Module-level abort events per world
_abort_events: dict[str, threading.Event] = {}
# Module-level active run registry per world
_active_runs: dict[str, threading.Event] = {}
# Module-level SSE queues per world
_sse_queues: dict[str, list[dict]] = {}
_sse_locks: dict[str, threading.Lock] = {}

# Locks for resource safety during concurrent ingestion
_graph_locks: dict[str, asyncio.Lock] = {}
_vector_locks: dict[str, asyncio.Lock] = {}
_meta_locks: dict[str, asyncio.Lock] = {}
_active_waits: dict[str, dict[str, dict[str, Any]]] = {}
_active_waits_lock = threading.RLock()

RetryStage = Literal["extraction", "embedding", "all"]
ChunkMode = Literal["full", "full_cleanup", "embedding_only"]
IngestOperation = Literal["default", "rechunk_reingest", "reembed_all"]
FailureScope = Literal["chunk", "node"]
SafetyReviewStatus = Literal["blocked", "draft", "testing", "resolved"]
SafetyReviewOutcome = Literal["not_tested", "still_safety_blocked", "transient_failure", "other_failure", "passed"]
WaitState = Literal["queued_for_extraction_slot", "queued_for_embedding_slot", "waiting_for_api_key"]
WaitStage = Literal["extracting", "embedding"]
_STALE_RUN_GRACE_SECONDS = 15
_UNIQUE_NODE_VECTOR_BATCH_SIZE = 8
_WAIT_LOG_THRESHOLD_SECONDS = 2.0
_WAIT_STATE_PRIORITY: dict[str, int] = {
    "queued_for_extraction_slot": 1,
    "queued_for_embedding_slot": 2,
    "waiting_for_api_key": 3,
}


class ExtractionCoverageError(RuntimeError):
    """Raised when extraction completed without producing durable graph coverage."""


class _StageScheduler:
    """App-wide slot scheduler with per-slot cooldowns."""

    def __init__(self, label: str):
        self.label = label
        self._condition = asyncio.Condition()
        self._concurrency = 1
        self._cooldown_seconds = 0.0
        self._slots: list[dict[str, Any]] = []

    async def configure(self, *, concurrency: int, cooldown_seconds: float) -> None:
        async with self._condition:
            self._concurrency = max(1, int(concurrency))
            self._cooldown_seconds = max(0.0, float(cooldown_seconds))
            while len(self._slots) < self._concurrency:
                self._slots.append({"busy": False, "available_at": 0.0})
            self._condition.notify_all()

    async def try_acquire(self) -> int | None:
        async with self._condition:
            loop = asyncio.get_running_loop()
            now = loop.time()
            for index in range(self._concurrency):
                slot = self._slots[index]
                if not slot["busy"] and float(slot["available_at"]) <= now:
                    slot["busy"] = True
                    return index
        return None

    async def acquire(self, abort_event: threading.Event) -> int:
        while True:
            if abort_event.is_set():
                raise asyncio.CancelledError()

            async with self._condition:
                loop = asyncio.get_running_loop()
                now = loop.time()

                for index in range(self._concurrency):
                    slot = self._slots[index]
                    if not slot["busy"] and float(slot["available_at"]) <= now:
                        slot["busy"] = True
                        return index

                idle_waits = [
                    max(0.0, float(self._slots[index]["available_at"]) - now)
                    for index in range(self._concurrency)
                    if not self._slots[index]["busy"]
                ]
                wait_timeout = min(idle_waits) if idle_waits else None

                try:
                    if wait_timeout is None:
                        await self._condition.wait()
                    else:
                        await asyncio.wait_for(self._condition.wait(), timeout=wait_timeout)
                except asyncio.TimeoutError:
                    pass

    async def release(self, slot_index: int, *, aborted: bool = False) -> None:
        async with self._condition:
            loop = asyncio.get_running_loop()
            slot = self._slots[slot_index]
            slot["busy"] = False
            slot["available_at"] = loop.time() if aborted else loop.time() + self._cooldown_seconds
            self._condition.notify_all()

    async def wake_all(self) -> None:
        async with self._condition:
            self._condition.notify_all()


_extraction_scheduler = _StageScheduler("graph_extraction")
_embedding_scheduler = _StageScheduler("embedding")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_current_run(world_id: str, expected_event: threading.Event) -> bool:
    return _abort_events.get(world_id) is expected_event and _active_runs.get(world_id) is expected_event


def has_active_ingestion_run(world_id: str) -> bool:
    return world_id in _active_runs


def _ensure_not_aborted(world_id: str, expected_event: threading.Event) -> None:
    if expected_event.is_set() or not _is_current_run(world_id, expected_event):
        raise asyncio.CancelledError()


def _wake_stage_schedulers() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_extraction_scheduler.wake_all())
    loop.create_task(_embedding_scheduler.wake_all())


def _mark_ingestion_live(
    meta: dict,
    *,
    operation: str | None = None,
    started: bool = False,
) -> None:
    now = _now_iso()
    meta["ingestion_status"] = "in_progress"
    meta["ingestion_updated_at"] = now
    if started or not meta.get("ingestion_started_at"):
        meta["ingestion_started_at"] = now
    if operation:
        meta["ingestion_operation"] = operation


def _mark_ingestion_terminal(meta: dict, status: str) -> None:
    meta["ingestion_status"] = status
    meta["ingestion_updated_at"] = _now_iso()
    meta.pop("ingestion_wait", None)
    meta.pop("ingestion_abort_requested_at", None)


def _blank_wait_fields() -> dict[str, Any]:
    return {
        "wait_state": None,
        "wait_stage": None,
        "wait_label": None,
        "wait_retry_after_seconds": None,
    }


def _wait_label_for(wait_state: str | None) -> str | None:
    if wait_state == "queued_for_extraction_slot":
        return "Queued for extraction slot"
    if wait_state == "queued_for_embedding_slot":
        return "Queued for embedding slot"
    if wait_state == "waiting_for_api_key":
        return "Waiting for API key cooldown"
    return None


def _serialize_wait_snapshot(snapshot: dict | None) -> dict | None:
    if not snapshot:
        return None
    retry_after = snapshot.get("wait_retry_after_seconds")
    if retry_after is not None:
        try:
            retry_after = max(0.0, float(retry_after))
        except (TypeError, ValueError):
            retry_after = None
    return {
        "wait_state": snapshot.get("wait_state"),
        "wait_stage": snapshot.get("wait_stage"),
        "wait_label": snapshot.get("wait_label"),
        "wait_retry_after_seconds": retry_after,
    }


def _wait_fields_from_meta(meta: dict) -> dict[str, Any]:
    raw = meta.get("ingestion_wait")
    if not isinstance(raw, dict):
        return _blank_wait_fields()
    return {
        "wait_state": raw.get("wait_state"),
        "wait_stage": raw.get("wait_stage"),
        "wait_label": raw.get("wait_label"),
        "wait_retry_after_seconds": raw.get("wait_retry_after_seconds"),
    }


def _set_wait_snapshot(meta: dict, snapshot: dict | None) -> bool:
    next_payload = _serialize_wait_snapshot(snapshot)
    current_payload = _serialize_wait_snapshot(meta.get("ingestion_wait") if isinstance(meta.get("ingestion_wait"), dict) else None)
    if current_payload == next_payload:
        return False
    if next_payload is None:
        meta.pop("ingestion_wait", None)
    else:
        meta["ingestion_wait"] = next_payload
    return True


def _select_representative_wait_unlocked(world_id: str) -> dict | None:
    waits = list(_active_waits.get(world_id, {}).values())
    if not waits:
        return None

    def wait_sort_key(entry: dict) -> tuple[int, float]:
        return (
            int(_WAIT_STATE_PRIORITY.get(str(entry.get("wait_state") or ""), 0)),
            -float(entry.get("started_monotonic") or 0.0),
        )

    active_wait = max(waits, key=wait_sort_key)
    return _serialize_wait_snapshot(active_wait)


def _clear_active_waits(world_id: str) -> None:
    with _active_waits_lock:
        _active_waits.pop(world_id, None)


async def _sync_wait_snapshot(world_id: str, meta: dict, meta_lock: asyncio.Lock) -> None:
    with _active_waits_lock:
        snapshot = _select_representative_wait_unlocked(world_id)
    async with meta_lock:
        if _set_wait_snapshot(meta, snapshot):
            if meta.get("ingestion_status") == "in_progress":
                meta["ingestion_updated_at"] = _now_iso()
            _save_meta(world_id, meta)


async def _begin_wait(
    world_id: str,
    meta: dict,
    meta_lock: asyncio.Lock,
    *,
    wait_key: str,
    wait_state: WaitState,
    wait_stage: WaitStage,
    source_id: str | None,
    book_number: int | None,
    chunk_index: int | None,
    active_agent: str | None,
    wait_retry_after_seconds: float | None = None,
) -> None:
    with _active_waits_lock:
        world_waits = _active_waits.setdefault(world_id, {})
        world_waits[wait_key] = {
            "wait_state": wait_state,
            "wait_stage": wait_stage,
            "wait_label": _wait_label_for(wait_state),
            "wait_retry_after_seconds": None if wait_retry_after_seconds is None else max(0.0, float(wait_retry_after_seconds)),
            "source_id": source_id,
            "book_number": book_number,
            "chunk_index": chunk_index,
            "active_agent": active_agent,
            "started_monotonic": time.monotonic(),
        }
    await _sync_wait_snapshot(world_id, meta, meta_lock)
    push_sse_event(
        world_id,
        {
            "event": "status",
            "source_id": source_id,
            "book_number": book_number,
            "chunk_index": chunk_index,
            "active_agent": active_agent,
            **_build_progress_event(
                world_id,
                meta,
                source_id=source_id,
                active_agent=active_agent,
            ),
        },
    )


async def _update_wait_retry_after(
    world_id: str,
    meta: dict,
    meta_lock: asyncio.Lock,
    *,
    wait_key: str,
    wait_retry_after_seconds: float | None,
) -> None:
    with _active_waits_lock:
        wait_entry = _active_waits.get(world_id, {}).get(wait_key)
        if wait_entry is None:
            return
        next_retry = None if wait_retry_after_seconds is None else max(0.0, float(wait_retry_after_seconds))
        current_retry = wait_entry.get("wait_retry_after_seconds")
        if current_retry == next_retry:
            return
        wait_entry["wait_retry_after_seconds"] = next_retry
        payload = {
            "source_id": wait_entry.get("source_id"),
            "book_number": wait_entry.get("book_number"),
            "chunk_index": wait_entry.get("chunk_index"),
            "active_agent": wait_entry.get("active_agent"),
        }
    await _sync_wait_snapshot(world_id, meta, meta_lock)
    push_sse_event(
        world_id,
        {
            "event": "status",
            **payload,
            **_build_progress_event(
                world_id,
                meta,
                source_id=payload.get("source_id"),
                active_agent=payload.get("active_agent"),
            ),
        },
    )


async def _finish_wait(
    world_id: str,
    meta: dict,
    meta_lock: asyncio.Lock,
    *,
    wait_key: str,
    emit_log: bool,
) -> None:
    wait_entry = None
    with _active_waits_lock:
        world_waits = _active_waits.get(world_id)
        if world_waits is not None:
            wait_entry = world_waits.pop(wait_key, None)
            if not world_waits:
                _active_waits.pop(world_id, None)
    if wait_entry is None:
        return
    await _sync_wait_snapshot(world_id, meta, meta_lock)
    push_sse_event(
        world_id,
        {
            "event": "status",
            "source_id": wait_entry.get("source_id"),
            "book_number": wait_entry.get("book_number"),
            "chunk_index": wait_entry.get("chunk_index"),
            "active_agent": wait_entry.get("active_agent"),
            **_build_progress_event(
                world_id,
                meta,
                source_id=wait_entry.get("source_id"),
                active_agent=wait_entry.get("active_agent"),
            ),
        },
    )
    if not emit_log:
        return
    wait_duration_seconds = max(0.0, time.monotonic() - float(wait_entry.get("started_monotonic") or 0.0))
    if wait_duration_seconds < _WAIT_LOG_THRESHOLD_SECONDS:
        return
    push_sse_event(
        world_id,
        {
            "event": "waiting",
            "source_id": wait_entry.get("source_id"),
            "book_number": wait_entry.get("book_number"),
            "chunk_index": wait_entry.get("chunk_index"),
            "active_agent": wait_entry.get("active_agent"),
            "wait_state": wait_entry.get("wait_state"),
            "wait_stage": wait_entry.get("wait_stage"),
            "wait_label": wait_entry.get("wait_label"),
            "wait_retry_after_seconds": wait_entry.get("wait_retry_after_seconds"),
            "wait_duration_seconds": wait_duration_seconds,
        },
    )


def _progress_source(meta: dict, source_id: str | None = None) -> dict | None:
    sources = list(meta.get("sources", []))
    if not sources:
        return None
    if source_id:
        for source in sources:
            if source.get("source_id") == source_id:
                return source
    for source in sources:
        if source.get("status") == "ingesting":
            return source
    return sources[0]


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _live_stage_counters(meta: dict) -> dict[str, int]:
    sources = list(meta.get("sources", []))
    expected_chunks = 0
    extracted_chunks = 0
    embedded_chunks = 0
    sources_complete = 0
    sources_partial_failure = 0

    for source in sources:
        chunk_count = max(0, int(source.get("chunk_count") or 0))
        expected_chunks += chunk_count
        extracted_chunks += len(_normalize_index_list(source.get("extracted_chunks", [])))
        embedded_chunks += len(_normalize_index_list(source.get("embedded_chunks", [])))

        status = str(source.get("status") or "")
        if status == "complete":
            sources_complete += 1
        elif status == "partial_failure":
            sources_partial_failure += 1

    failed_records = sum(len(list(source.get("stage_failures", []))) for source in sources)
    current_unique_nodes = _coerce_non_negative_int(meta.get("total_nodes"))
    embedded_unique_nodes = _coerce_non_negative_int(meta.get("embedded_unique_nodes"))
    if current_unique_nodes > 0:
        embedded_unique_nodes = min(embedded_unique_nodes, current_unique_nodes)
    return {
        "expected_chunks": expected_chunks,
        "extracted_chunks": extracted_chunks,
        "embedded_chunks": embedded_chunks,
        "current_unique_nodes": current_unique_nodes,
        "embedded_unique_nodes": embedded_unique_nodes,
        "failed_records": failed_records,
        "sources_total": len(sources),
        "sources_complete": sources_complete,
        "sources_partial_failure": sources_partial_failure,
    }


def _progress_source_summary(source: dict | None) -> dict[str, Any]:
    if not source:
        return {
            "progress_source_id": None,
            "progress_source_display_name": None,
            "progress_source_book_number": None,
        }
    return {
        "progress_source_id": source.get("source_id"),
        "progress_source_display_name": source.get("display_name"),
        "progress_source_book_number": source.get("book_number"),
    }


def _progress_phase_from_agent(active_agent: str | None) -> str | None:
    agent = str(active_agent or "").strip().lower()
    if not agent:
        return None
    if any(token in agent for token in ("embed", "vector")):
        return "embedding"
    return "extracting"


def _build_progress_snapshot(
    world_id: str,
    meta: dict,
    *,
    source_id: str | None = None,
    active_agent: str | None = None,
    total_chunks: int | None = None,
    aborting: bool = False,
) -> dict:
    source = _progress_source(meta, source_id=source_id)
    active_operation = str(meta.get("ingestion_operation") or "default")
    chunk_count = int(total_chunks or (source.get("chunk_count") if source else 0) or 0)
    extracted_chunks = len(_normalize_index_list((source or {}).get("extracted_chunks", [])))
    embedded_chunks = len(_normalize_index_list((source or {}).get("embedded_chunks", [])))

    phase = "aborting" if aborting or meta.get("ingestion_abort_requested_at") else _progress_phase_from_agent(active_agent)
    if not phase:
        if active_operation == "reembed_all":
            phase = "embedding"
        elif chunk_count > 0 and extracted_chunks < chunk_count:
            phase = "extracting"
        elif chunk_count > 0 and embedded_chunks < chunk_count:
            phase = "embedding"
        else:
            phase = "idle"

    if phase == "extracting":
        completed = extracted_chunks
    elif phase in {"embedding", "aborting"}:
        completed = embedded_chunks
    else:
        completed = embedded_chunks if chunk_count > 0 else extracted_chunks

    completed = max(0, min(completed, chunk_count)) if chunk_count > 0 else 0
    percent = (completed / chunk_count * 100.0) if chunk_count > 0 else 0.0
    wait_fields = _wait_fields_from_meta(meta)

    return {
        "progress_phase": phase,
        "completed_chunks_current_phase": completed,
        "total_chunks_current_phase": chunk_count,
        "progress_percent": percent,
        "active_operation": active_operation,
        **wait_fields,
    }


def _build_progress_event(
    world_id: str,
    meta: dict,
    *,
    source_id: str | None = None,
    active_agent: str | None = None,
    total_chunks: int | None = None,
    aborting: bool = False,
) -> dict:
    payload = _build_progress_snapshot(
        world_id,
        meta,
        source_id=source_id,
        active_agent=active_agent,
        total_chunks=total_chunks,
        aborting=aborting,
    )
    payload["ingestion_status"] = meta.get("ingestion_status")
    payload["active_ingestion_run"] = has_active_ingestion_run(world_id)
    payload["stage_counters"] = _live_stage_counters(meta)
    payload.update(_progress_source_summary(_progress_source(meta, source_id=source_id)))
    return payload


def _is_stale_in_progress(meta: dict) -> bool:
    if meta.get("ingestion_status") != "in_progress":
        return False
    updated = _parse_iso(meta.get("ingestion_updated_at")) or _parse_iso(meta.get("ingestion_started_at"))
    if updated is None:
        # Older worlds won't have heartbeat fields. If they are still marked
        # in_progress without a live worker, treat them as stale and recover.
        return True
    return (datetime.now(timezone.utc) - updated).total_seconds() > _STALE_RUN_GRACE_SECONDS


def get_abort_event(world_id: str) -> threading.Event:
    if world_id not in _abort_events:
        _abort_events[world_id] = threading.Event()
    return _abort_events[world_id]


def get_sse_queue(world_id: str) -> list[dict]:
    if world_id not in _sse_queues:
        _sse_queues[world_id] = []
        _sse_locks[world_id] = threading.Lock()
    return _sse_queues[world_id]


def push_sse_event(world_id: str, event: dict) -> None:
    if world_id not in _sse_queues:
        _sse_queues[world_id] = []
        _sse_locks[world_id] = threading.Lock()
    with _sse_locks[world_id]:
        _sse_queues[world_id].append(event)


def _get_async_lock(world_id: str, lock_dict: dict[str, asyncio.Lock]) -> asyncio.Lock:
    if world_id not in lock_dict:
        lock_dict[world_id] = asyncio.Lock()
    return lock_dict[world_id]


def drain_sse_events(world_id: str) -> list[dict]:
    if world_id not in _sse_queues:
        return []
    with _sse_locks[world_id]:
        events = list(_sse_queues[world_id])
        _sse_queues[world_id].clear()
        return events


def clear_sse_queue(world_id: str) -> None:
    if world_id in _sse_queues:
        with _sse_locks[world_id]:
            _sse_queues[world_id].clear()


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


def _load_checkpoint(world_id: str) -> dict | None:
    path = world_checkpoint_path(world_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_checkpoint(world_id: str, data: dict) -> None:
    path = world_checkpoint_path(world_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(str(tmp), str(path))


def _clear_checkpoint(world_id: str) -> None:
    path = world_checkpoint_path(world_id)
    if path.exists():
        os.remove(str(path))


def _load_safety_review_cache(world_id: str) -> dict:
    path = world_safety_reviews_path(world_id)
    if not path.exists():
        return {"version": 1, "reviews": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "reviews": []}
    if not isinstance(data, dict):
        return {"version": 1, "reviews": []}
    reviews = data.get("reviews")
    if not isinstance(reviews, list):
        data["reviews"] = []
    data["version"] = 1
    return data


def _save_safety_review_cache(world_id: str, data: dict) -> None:
    path = world_safety_reviews_path(world_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "reviews": list(data.get("reviews", [])) if isinstance(data, dict) else [],
    }
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(str(tmp), str(path))


def _review_id_for_chunk(chunk_id: str) -> str:
    return str(chunk_id)


def _sorted_safety_reviews(reviews: list[dict]) -> list[dict]:
    status_order = {"blocked": 0, "draft": 1, "testing": 2, "resolved": 3}
    return sorted(
        [review for review in reviews if isinstance(review, dict)],
        key=lambda review: (
            status_order.get(str(review.get("status") or "blocked"), 99),
            int(review.get("book_number", 0) or 0),
            int(review.get("chunk_index", 0) or 0),
            str(review.get("source_id") or ""),
        ),
    )


def _safety_review_summary_from_reviews(reviews: list[dict]) -> dict:
    total_reviews = len(reviews)
    unresolved_reviews = 0
    resolved_reviews = 0
    active_override_reviews = 0
    blocked_reviews = 0
    draft_reviews = 0
    testing_reviews = 0
    blocking_unresolved_reviews = 0
    blocking_active_override_reviews = 0

    for review in reviews:
        status = str(review.get("status") or "blocked")
        if status == "resolved":
            resolved_reviews += 1
        else:
            unresolved_reviews += 1
        if status == "blocked":
            blocked_reviews += 1
        elif status == "draft":
            draft_reviews += 1
        elif status == "testing":
            testing_reviews += 1
        has_active_override = bool(str(review.get("active_override_raw_text") or "").strip())
        if has_active_override:
            active_override_reviews += 1
        if status != "resolved":
            blocking_unresolved_reviews += 1
        if has_active_override:
            blocking_active_override_reviews += 1

    blocks_rebuild = blocking_unresolved_reviews > 0 or blocking_active_override_reviews > 0
    blocking_message = None
    if blocks_rebuild:
        if blocking_unresolved_reviews > 0 and blocking_active_override_reviews > 0:
            blocking_message = (
                "Safety review work is still pending and this world also has active repaired-chunk overrides. "
                "Resolve or discard the review queue before running Re-ingest."
            )
        elif blocking_unresolved_reviews > 0:
            blocking_message = (
                "This world has unresolved safety review items. Resolve or discard them before running Re-ingest."
            )
        else:
            blocking_message = (
                "This world has active repaired-chunk overrides. Re-ingest can only reuse them when the current chunk size and overlap stay the same."
            )

    return {
        "total_reviews": total_reviews,
        "unresolved_reviews": unresolved_reviews,
        "resolved_reviews": resolved_reviews,
        "active_override_reviews": active_override_reviews,
        "blocked_reviews": blocked_reviews,
        "draft_reviews": draft_reviews,
        "testing_reviews": testing_reviews,
        "blocks_rebuild": blocks_rebuild,
        "blocking_message": blocking_message,
    }


def _manual_rescue_fingerprint(
    world_id: str,
    source: dict,
    ingest_settings: dict,
) -> dict | None:
    snapshot = _build_source_ingest_snapshot(world_id, source, ingest_settings)
    if snapshot is None:
        return None
    return {
        "source_id": str(source.get("source_id") or ""),
        "vault_filename": str(snapshot.get("vault_filename") or ""),
        "file_size": int(snapshot.get("file_size", 0) or 0),
        "file_sha256": str(snapshot.get("file_sha256") or ""),
        "chunk_size_chars": int(snapshot.get("chunk_size_chars", 0) or 0),
        "chunk_overlap_chars": int(snapshot.get("chunk_overlap_chars", 0) or 0),
    }


def _source_has_chunk_stage_failure(
    source: dict,
    *,
    stage: Literal["extraction", "embedding"],
    chunk_id: str,
    chunk_index: int,
) -> bool:
    for failure in _stage_failures_for(source, stage):
        try:
            failure_index = int(failure.get("chunk_index", -1))
        except (TypeError, ValueError, AttributeError):
            continue
        if failure_index != int(chunk_index):
            continue
        if str(failure.get("chunk_id") or "") == str(chunk_id or ""):
            return True
    return False


def _prune_stale_manual_rescue_reviews(world_id: str, *, meta: dict | None = None) -> bool:
    cache = _load_safety_review_cache(world_id)
    reviews = list(cache.get("reviews", []))
    if not reviews:
        return False

    meta_data = meta or _load_meta(world_id)
    source_lookup = {
        str(source.get("source_id") or ""): source
        for source in meta_data.get("sources", [])
        if isinstance(source, dict)
    }
    world_ingest_settings = get_world_ingest_settings(meta=meta_data)
    changed = False
    kept_reviews: list[dict] = []

    for review in reviews:
        if not isinstance(review, dict):
            changed = True
            continue
        if str(review.get("review_origin") or "") != "manual_rescue":
            kept_reviews.append(review)
            continue

        source_id = str(review.get("source_id") or "")
        source = source_lookup.get(source_id)
        if source is None:
            changed = True
            continue

        stored_fingerprint = review.get("manual_rescue_fingerprint")
        current_fingerprint = _manual_rescue_fingerprint(world_id, source, world_ingest_settings)
        if not isinstance(stored_fingerprint, dict) or current_fingerprint is None:
            changed = True
            continue
        if any(stored_fingerprint.get(key) != current_fingerprint.get(key) for key in current_fingerprint.keys()):
            changed = True
            continue

        chunk_id = str(review.get("chunk_id") or "")
        try:
            chunk_index = int(review.get("chunk_index", -1))
        except (TypeError, ValueError):
            changed = True
            continue

        if str(review.get("status") or "") != "resolved" and not _source_has_chunk_stage_failure(
            source,
            stage="extraction",
            chunk_id=chunk_id,
            chunk_index=chunk_index,
        ):
            changed = True
            continue

        kept_reviews.append(review)

    if changed:
        cache["reviews"] = kept_reviews
        _save_safety_review_cache(world_id, cache)
    return changed


def _clear_manual_rescue_reviews(world_id: str) -> int:
    cache = _load_safety_review_cache(world_id)
    before = len(cache.get("reviews", []))
    cache["reviews"] = [
        review
        for review in cache.get("reviews", [])
        if str(review.get("review_origin") or "") != "manual_rescue"
    ]
    removed = before - len(cache.get("reviews", []))
    if removed > 0:
        _save_safety_review_cache(world_id, cache)
    return removed


def get_safety_review_summary(world_id: str) -> dict:
    _prune_stale_manual_rescue_reviews(world_id)
    cache = _load_safety_review_cache(world_id)
    changed = False
    for review in cache.get("reviews", []):
        if isinstance(review, dict) and _set_review_pending_status(review):
            changed = True
    if changed:
        _save_safety_review_cache(world_id, cache)
    reviews = _sorted_safety_reviews(list(cache.get("reviews", [])))
    return _safety_review_summary_from_reviews(reviews)


def get_safety_review_rebuild_guard(world_id: str, *, allow_active_overrides: bool = False) -> dict:
    summary = get_safety_review_summary(world_id)
    unresolved_reviews = int(summary.get("unresolved_reviews", 0) or 0)
    blocks_for_unresolved = unresolved_reviews > 0
    if blocks_for_unresolved:
        message = "This world has unresolved safety review items. Resolve or discard them before running Re-ingest."
    else:
        message = summary.get("blocking_message")
    return {
        "can_rebuild": not blocks_for_unresolved,
        "message": message,
        **summary,
    }


def list_safety_reviews(world_id: str) -> list[dict]:
    meta = _load_meta(world_id)
    _prune_stale_manual_rescue_reviews(world_id, meta=meta)
    meta = _load_meta(world_id)
    source_lookup = {
        str(source.get("source_id") or ""): source
        for source in meta.get("sources", [])
        if isinstance(source, dict)
    }
    cache = _load_safety_review_cache(world_id)
    changed = False
    for review in cache.get("reviews", []):
        if isinstance(review, dict) and _set_review_pending_status(review):
            changed = True
    if changed:
        _save_safety_review_cache(world_id, cache)
    output: list[dict] = []
    for review in _sorted_safety_reviews(list(cache.get("reviews", []))):
        source_id = str(review.get("source_id") or "")
        source = source_lookup.get(source_id, {})
        output.append(
            {
                **review,
                "display_name": str(source.get("display_name") or source_id or "Unknown source"),
                "source_status": str(source.get("status") or ""),
                "prefix_label": f"[B{int(review.get('book_number', 0) or 0)}:C{int(review.get('chunk_index', 0) or 0)}]",
            }
        )
    return output


def _normalize_review_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n")


def _review_baseline_raw_text(review: dict) -> str:
    active_override_raw_text = _normalize_review_text(review.get("active_override_raw_text"))
    if active_override_raw_text.strip():
        return active_override_raw_text
    return _normalize_review_text(review.get("original_raw_text"))


def _review_overlap_raw_text(review: dict) -> str:
    return _normalize_review_text(review.get("overlap_raw_text"))


def _review_editor_raw_text(review: dict) -> str:
    draft_raw_text = _normalize_review_text(review.get("draft_raw_text"))
    if draft_raw_text.strip():
        return draft_raw_text
    return _review_baseline_raw_text(review)


def _set_review_pending_status(review: dict) -> bool:
    changed = False
    original_raw_text = _normalize_review_text(review.get("original_raw_text"))
    if review.get("original_raw_text") != original_raw_text:
        review["original_raw_text"] = original_raw_text
        changed = True

    original_prefixed_text = _normalize_review_text(review.get("original_prefixed_text"))
    if review.get("original_prefixed_text") != original_prefixed_text:
        review["original_prefixed_text"] = original_prefixed_text
        changed = True

    overlap_raw_text = _review_overlap_raw_text(review)
    if review.get("overlap_raw_text") != overlap_raw_text:
        review["overlap_raw_text"] = overlap_raw_text
        changed = True

    active_override_raw_text = _normalize_review_text(review.get("active_override_raw_text"))
    if review.get("active_override_raw_text") != active_override_raw_text:
        review["active_override_raw_text"] = active_override_raw_text
        changed = True

    draft_raw_text = _review_editor_raw_text(review)
    if review.get("draft_raw_text") != draft_raw_text:
        review["draft_raw_text"] = draft_raw_text
        changed = True

    test_in_progress = bool(review.get("test_in_progress"))
    if review.get("test_in_progress") != test_in_progress:
        review["test_in_progress"] = test_in_progress
        changed = True

    next_status: SafetyReviewStatus
    if test_in_progress:
        next_status = "testing"
    elif active_override_raw_text.strip() and draft_raw_text == active_override_raw_text:
        next_status = "resolved"
    elif draft_raw_text != _review_baseline_raw_text(review):
        next_status = "draft"
    else:
        next_status = "blocked"

    if review.get("status") != next_status:
        review["status"] = next_status
        changed = True

    return changed


def _get_safety_review_item(world_id: str, review_id: str) -> dict | None:
    for review in list_safety_reviews(world_id):
        if str(review.get("review_id") or "") == str(review_id or ""):
            return review
    return None


def _append_log(world_id: str, entry: dict) -> None:
    path = world_log_path(world_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except (json.JSONDecodeError, OSError):
            logs = []
    entry["timestamp"] = _now_iso()
    logs.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)


def recover_stale_ingestion(world_id: str) -> dict:
    """
    Convert a persisted-but-no-longer-live in_progress ingestion run into a
    durable terminal state derived from actual graph/vector coverage.
    """
    meta = _load_meta(world_id)
    if meta.get("ingestion_status") != "in_progress":
        return meta
    if has_active_ingestion_run(world_id):
        return meta
    if not _is_stale_in_progress(meta):
        return meta

    audit = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
    refreshed = _load_meta(world_id)
    world_summary = audit.get("world", {})
    is_complete = (
        int(world_summary.get("expected_chunks", 0)) == int(world_summary.get("extracted_chunks", 0))
        and int(world_summary.get("expected_chunks", 0)) == int(world_summary.get("embedded_chunks", 0))
        and int(world_summary.get("failed_records", 0)) == 0
    )
    _clear_active_waits(world_id)
    _mark_ingestion_terminal(refreshed, "complete" if is_complete else "partial_failure")
    refreshed["ingestion_recovered_at"] = refreshed["ingestion_updated_at"]
    _save_meta(world_id, refreshed)
    return refreshed


def _normalize_retry_stage(stage: str | None) -> RetryStage:
    normalized = str(stage or "all").strip().lower()
    if normalized not in {"extraction", "embedding", "all"}:
        return "all"
    return normalized  # type: ignore[return-value]


def _normalize_ingest_operation(operation: str | None) -> IngestOperation:
    normalized = str(operation or "default").strip().lower()
    if normalized not in {"default", "rechunk_reingest", "reembed_all"}:
        return "default"
    return normalized  # type: ignore[return-value]


def _chunk_id(world_id: str, source_id: str, chunk_idx: int) -> str:
    return f"chunk_{world_id}_{source_id}_{chunk_idx}"


def _parse_chunk_id(world_id: str, chunk_id: str) -> tuple[str, int] | None:
    raw = str(chunk_id)
    prefix = f"chunk_{world_id}_"
    if not raw.startswith(prefix):
        return None
    tail = raw[len(prefix):]
    if "_" not in tail:
        return None
    source_id, idx_raw = tail.rsplit("_", 1)
    try:
        idx = int(idx_raw)
    except (TypeError, ValueError):
        return None
    if idx < 0:
        return None
    return source_id, idx


def _build_prefixed_chunk_text(book_number: int, chunk_index: int, raw_text: str) -> str:
    return f"[B{book_number}:C{chunk_index}] {raw_text}"


def _combine_chunk_raw_text(overlap_text: str, primary_text: str) -> str:
    normalized_overlap = _normalize_review_text(overlap_text).strip()
    normalized_primary = _normalize_review_text(primary_text).strip()
    if normalized_overlap and normalized_primary:
        return f"{normalized_overlap} {normalized_primary}"
    return normalized_overlap or normalized_primary


def _build_chunk_prefixed_text(book_number: int, chunk_index: int, overlap_text: str, primary_text: str) -> str:
    return _build_prefixed_chunk_text(
        book_number,
        chunk_index,
        _combine_chunk_raw_text(overlap_text, primary_text),
    )


def _build_graph_extraction_payload(primary_text: str, overlap_text: str = "") -> str:
    normalized_primary = _normalize_review_text(primary_text).strip()
    normalized_overlap = _normalize_review_text(overlap_text).strip()
    if not normalized_overlap:
        return normalized_primary
    return (
        "Chunk body to extract from:\n"
        f"{normalized_primary}\n\n"
        "Reference-only overlap context from the previous chunk:\n"
        f"{normalized_overlap}\n\n"
        "Use the overlap context only to resolve references inside the chunk body. "
        "Do not extract entities or relationships that appear only in the overlap context."
    )


def _build_graph_extraction_payload_for_chunk(chunk: TemporalChunk) -> str:
    return _build_graph_extraction_payload(chunk.primary_text, chunk.overlap_text)


def _replace_temporal_chunk_body(chunk: TemporalChunk, primary_text: str) -> TemporalChunk:
    combined_raw_text = _combine_chunk_raw_text(chunk.overlap_text, primary_text)
    return chunk.model_copy(
        update={
            "primary_text": _normalize_review_text(primary_text),
            "raw_text": combined_raw_text,
            "prefixed_text": _build_chunk_prefixed_text(
                chunk.book_number,
                chunk.chunk_index,
                chunk.overlap_text,
                primary_text,
            ),
        }
    )


def _classify_exception_kind(exc: Exception) -> str:
    if isinstance(exc, ExtractionCoverageError):
        return "no_extraction_coverage"
    if isinstance(exc, AgentCallError):
        return exc.kind
    message = str(exc).lower()
    if "429" in message or "resource has been exhausted" in message or "rate limit" in message:
        return "rate_limit"
    if "empty_response" in message:
        return "empty_response"
    if isinstance(exc, json.JSONDecodeError) or ("json" in message and "parse" in message):
        return "parse_error"
    return "provider_error"


def _review_outcome_for_error_kind(error_kind: str) -> SafetyReviewOutcome:
    if error_kind == "safety_block":
        return "still_safety_blocked"
    if error_kind == "rate_limit":
        return "transient_failure"
    return "other_failure"


def _find_safety_review(cache: dict, review_id: str) -> dict | None:
    normalized_review_id = str(review_id or "")
    for review in cache.get("reviews", []):
        if str(review.get("review_id") or "") == normalized_review_id:
            return review
    return None


def _unresolved_safety_review_chunk_ids(world_id: str) -> set[str]:
    _prune_stale_manual_rescue_reviews(world_id)
    cache = _load_safety_review_cache(world_id)
    changed = False
    for review in cache.get("reviews", []):
        if isinstance(review, dict) and _set_review_pending_status(review):
            changed = True
    if changed:
        _save_safety_review_cache(world_id, cache)
    return {
        str(review.get("chunk_id") or "")
        for review in cache.get("reviews", [])
        if str(review.get("status") or "") in {"blocked", "draft", "testing"}
    }


def _get_active_override_map(world_id: str) -> dict[str, str]:
    cache = _load_safety_review_cache(world_id)
    output: dict[str, str] = {}
    for review in cache.get("reviews", []):
        chunk_id = str(review.get("chunk_id") or "")
        override_text = _normalize_review_text(review.get("active_override_raw_text"))
        if chunk_id and override_text.strip():
            output[chunk_id] = override_text
    return output


def _upsert_safety_review(
    world_id: str,
    *,
    source_id: str,
    book_number: int,
    chunk_index: int,
    chunk_id: str,
    original_raw_text: str,
    original_prefixed_text: str,
    safety_reason: str,
    overlap_raw_text: str = "",
    original_error_kind: str = "safety_block",
    review_origin: str = "safety_block",
    manual_rescue_fingerprint: dict | None = None,
) -> dict:
    cache = _load_safety_review_cache(world_id)
    reviews = list(cache.get("reviews", []))
    review_id = _review_id_for_chunk(chunk_id)
    now = _now_iso()
    review = _find_safety_review({"reviews": reviews}, review_id)

    if review is None:
        review = {
            "review_id": review_id,
            "world_id": world_id,
            "source_id": source_id,
            "book_number": int(book_number),
            "chunk_index": int(chunk_index),
            "chunk_id": chunk_id,
            "status": "blocked",
            "original_error_kind": original_error_kind,
            "original_safety_reason": safety_reason,
            "original_raw_text": _normalize_review_text(original_raw_text),
            "original_prefixed_text": _normalize_review_text(original_prefixed_text),
            "overlap_raw_text": _normalize_review_text(overlap_raw_text),
            "review_origin": review_origin,
            "manual_rescue_fingerprint": manual_rescue_fingerprint if isinstance(manual_rescue_fingerprint, dict) else None,
            "draft_raw_text": _normalize_review_text(original_raw_text),
            "last_test_outcome": "not_tested",
            "last_test_error_kind": None,
            "last_test_error_message": None,
            "last_tested_at": None,
            "test_attempt_count": 0,
            "test_in_progress": False,
            "active_override_raw_text": "",
            "created_at": now,
            "updated_at": now,
        }
        reviews.append(review)
    else:
        review["world_id"] = world_id
        review["source_id"] = source_id
        review["book_number"] = int(book_number)
        review["chunk_index"] = int(chunk_index)
        review["chunk_id"] = chunk_id
        review["original_error_kind"] = original_error_kind
        review["original_safety_reason"] = safety_reason
        if not _normalize_review_text(review.get("original_raw_text")).strip():
            review["original_raw_text"] = _normalize_review_text(original_raw_text)
        if not _normalize_review_text(review.get("original_prefixed_text")).strip():
            review["original_prefixed_text"] = _normalize_review_text(original_prefixed_text)
        if "overlap_raw_text" in review:
            review["overlap_raw_text"] = _normalize_review_text(overlap_raw_text)
        review["review_origin"] = review_origin
        review["manual_rescue_fingerprint"] = manual_rescue_fingerprint if isinstance(manual_rescue_fingerprint, dict) else None
        if review.get("test_in_progress") is None:
            review["test_in_progress"] = False
        review["updated_at"] = now
        if review.get("last_test_outcome") == "passed" and str(review.get("status") or "") != "resolved":
            review["last_test_outcome"] = "not_tested"
            review["last_test_error_kind"] = None
            review["last_test_error_message"] = None
            review["last_tested_at"] = None

    _set_review_pending_status(review)

    cache["reviews"] = reviews
    _save_safety_review_cache(world_id, cache)
    return review


def _delete_safety_review(world_id: str, review_id: str) -> bool:
    cache = _load_safety_review_cache(world_id)
    before = len(cache.get("reviews", []))
    cache["reviews"] = [
        review
        for review in cache.get("reviews", [])
        if str(review.get("review_id") or "") != str(review_id or "")
    ]
    changed = len(cache.get("reviews", [])) != before
    if changed:
        _save_safety_review_cache(world_id, cache)
    return changed


def _apply_active_chunk_overrides(
    world_id: str,
    temporal_chunks: list[TemporalChunk],
) -> list[TemporalChunk]:
    override_map = _get_active_override_map(world_id)
    if not override_map:
        return temporal_chunks

    updated_chunks: list[TemporalChunk] = []
    for chunk in temporal_chunks:
        chunk_id = _chunk_id(world_id, chunk.source_id, chunk.chunk_index)
        override_text = override_map.get(chunk_id)
        if not override_text:
            updated_chunks.append(chunk)
            continue
        updated_chunks.append(_replace_temporal_chunk_body(chunk, override_text))
    return updated_chunks


def _chunk_node_ids(graph_store: GraphStore, chunk_id: str) -> list[str]:
    node_ids: list[str] = []
    for node_id, attrs in graph_store.graph.nodes(data=True):
        source_chunks = attrs.get("source_chunks", [])
        if isinstance(source_chunks, str):
            try:
                source_chunks = json.loads(source_chunks)
            except (json.JSONDecodeError, TypeError):
                source_chunks = []
        normalized_chunks = {str(raw_chunk_id) for raw_chunk_id in (source_chunks or [])}
        if chunk_id in normalized_chunks:
            node_ids.append(str(node_id))
    return sorted(set(node_ids))


def _chunk_node_records(graph_store: GraphStore, chunk_id: str) -> list[dict]:
    output: list[dict] = []
    for node_id in _chunk_node_ids(graph_store, chunk_id):
        node = graph_store.get_node(node_id)
        if node:
            output.append(node)
    return output


def _chunk_has_graph_coverage(graph_store: GraphStore, chunk_id: str) -> bool:
    return bool(_chunk_node_ids(graph_store, chunk_id))


async def _cleanup_chunk_retry_artifacts(
    *,
    graph_store: GraphStore,
    vector_store: VectorStore,
    unique_node_vector_store: VectorStore,
    chunk_id: str,
    source_book: int,
    source_chunk: int,
    graph_lock: asyncio.Lock,
    vector_lock: asyncio.Lock,
) -> dict:
    async with graph_lock:
        pre_cleanup_node_ids = set(_chunk_node_ids(graph_store, chunk_id))
        cleanup = graph_store.remove_chunk_artifacts(
            chunk_id=chunk_id,
            source_book=source_book,
            source_chunk=source_chunk,
        )
        remaining_node_ids = {node_id for node_id in pre_cleanup_node_ids if node_id in graph_store.graph.nodes}

    removed_node_ids = sorted(pre_cleanup_node_ids - remaining_node_ids)
    async with vector_lock:
        await asyncio.to_thread(vector_store.delete_document, chunk_id)
        if removed_node_ids:
            await asyncio.to_thread(unique_node_vector_store.delete_documents, removed_node_ids)

    return {
        **cleanup,
        "removed_chunk_vectors": 1,
        "removed_unique_node_vectors": len(removed_node_ids),
        "removed_node_ids": removed_node_ids,
    }


def _normalize_chunk_local_ref(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _persist_chunk_graph_artifacts(
    graph_store: GraphStore,
    *,
    nodes: list[Any],
    edges: list[Any],
    chunk_id: str,
    book_number: int,
    chunk_index: int,
) -> list[dict]:
    node_uuid_by_ref: dict[str, str] = {}
    node_uuid_by_display_ref: dict[str, str | None] = {}
    touched_node_ids: set[str] = set()

    for node in nodes:
        node_ref = _normalize_chunk_local_ref(getattr(node, "node_id", ""))
        display_ref = _normalize_chunk_local_ref(getattr(node, "display_name", ""))

        existing_uuid = node_uuid_by_ref.get(node_ref) if node_ref else None
        if existing_uuid is None:
            existing_uuid = graph_store.upsert_node(
                node_id=getattr(node, "node_id", ""),
                display_name=getattr(node, "display_name", ""),
                description=getattr(node, "description", ""),
                source_chunk_id=chunk_id,
            )
            if node_ref:
                node_uuid_by_ref[node_ref] = existing_uuid

        touched_node_ids.add(existing_uuid)

        if display_ref:
            if display_ref not in node_uuid_by_display_ref:
                node_uuid_by_display_ref[display_ref] = existing_uuid
            elif node_uuid_by_display_ref[display_ref] != existing_uuid:
                node_uuid_by_display_ref[display_ref] = None

    def resolve_uuid(raw_ref: str) -> str | None:
        normalized_ref = _normalize_chunk_local_ref(raw_ref)
        if not normalized_ref:
            return None
        return node_uuid_by_ref.get(normalized_ref) or node_uuid_by_display_ref.get(normalized_ref)

    for edge in edges:
        source_uuid = resolve_uuid(getattr(edge, "source_node_id", ""))
        target_uuid = resolve_uuid(getattr(edge, "target_node_id", ""))
        if not source_uuid or not target_uuid:
            logger.warning(
                "Edge skipped for chunk %s because one or both endpoints were not created in this chunk: %s -> %s",
                chunk_id,
                getattr(edge, "source_node_id", ""),
                getattr(edge, "target_node_id", ""),
            )
            continue
        graph_store.upsert_edge(
            source_node_id=source_uuid,
            target_node_id=target_uuid,
            description=getattr(edge, "description", ""),
            strength=getattr(edge, "strength", 5),
            source_book=book_number,
            source_chunk=chunk_index,
        )

    graph_store.save()

    node_records: list[dict] = []
    for node_id in sorted(touched_node_ids):
        node = graph_store.get_node(node_id)
        if node:
            node_records.append(node)
    return node_records


async def _upsert_unique_node_vectors(
    unique_node_vector_store: VectorStore,
    node_records: list[dict],
    api_key: str,
    *,
    embeddings: list[list[float]] | None = None,
    batch_size: int = _UNIQUE_NODE_VECTOR_BATCH_SIZE,
    vector_lock: asyncio.Lock | None = None,
    abort_check: Callable[[], None] | None = None,
) -> int:
    document_ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []
    seen_node_ids: set[str] = set()

    for node in node_records:
        node_id = str(node.get("id", "")).strip()
        if not node_id or node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        document_ids.append(node_id)
        texts.append(build_unique_node_document(node))
        metadatas.append(
            {
                "display_name": node.get("display_name", ""),
                "normalized_id": node.get("normalized_id", ""),
                "node_id": node_id,
            }
        )

    if not document_ids:
        return 0

    total_written = 0
    step = max(1, int(batch_size))

    for start in range(0, len(document_ids), step):
        if abort_check:
            abort_check()

        end = start + step
        batch_document_ids = document_ids[start:end]
        batch_texts = texts[start:end]
        batch_metadatas = metadatas[start:end]

        if embeddings is None:
            batch_embeddings = await asyncio.to_thread(
                unique_node_vector_store.embed_texts,
                batch_texts,
                api_key,
            )
        else:
            batch_embeddings = embeddings[start:end]

        if abort_check:
            abort_check()

        if vector_lock is None:
            await asyncio.to_thread(
                unique_node_vector_store.upsert_documents_embeddings,
                document_ids=batch_document_ids,
                texts=batch_texts,
                metadatas=batch_metadatas,
                embeddings=batch_embeddings,
            )
        else:
            async with vector_lock:
                if abort_check:
                    abort_check()
                await asyncio.to_thread(
                    unique_node_vector_store.upsert_documents_embeddings,
                    document_ids=batch_document_ids,
                    texts=batch_texts,
                    metadatas=batch_metadatas,
                    embeddings=batch_embeddings,
                )

        total_written += len(batch_document_ids)

        if abort_check:
            abort_check()

    return total_written


async def _rebuild_unique_node_vectors(
    graph_store: GraphStore,
    unique_node_vector_store: VectorStore,
    api_key: str,
    *,
    vector_lock: asyncio.Lock | None = None,
    abort_check: Callable[[], None] | None = None,
) -> int:
    node_records = []
    for node_id in sorted(graph_store.graph.nodes()):
        if abort_check:
            abort_check()
        node = graph_store.get_node(node_id)
        if node:
            node_records.append(node)

    unique_node_vector_store.drop_collection()
    if abort_check:
        abort_check()
    return await _upsert_unique_node_vectors(
        unique_node_vector_store,
        node_records,
        api_key,
        vector_lock=vector_lock,
        abort_check=abort_check,
    )


def _normalize_index_list(values: list[Any], *, max_index: int | None = None) -> list[int]:
    output: set[int] = set()
    for v in values or []:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv < 0:
            continue
        if max_index is not None and iv > max_index:
            continue
        output.add(iv)
    return sorted(output)


def _ensure_source_tracking(source: dict) -> None:
    if "failed_chunks" not in source or not isinstance(source.get("failed_chunks"), list):
        source["failed_chunks"] = []
    if "stage_failures" not in source or not isinstance(source.get("stage_failures"), list):
        source["stage_failures"] = []
    if "extracted_chunks" not in source or not isinstance(source.get("extracted_chunks"), list):
        source["extracted_chunks"] = []
    if "embedded_chunks" not in source or not isinstance(source.get("embedded_chunks"), list):
        source["embedded_chunks"] = []


def _sync_failed_chunks(source: dict, *, max_index: int | None = None) -> None:
    failed: list[int] = []
    for rec in source.get("stage_failures", []):
        try:
            failed.append(int(rec.get("chunk_index")))
        except (TypeError, ValueError, AttributeError):
            continue
    source["failed_chunks"] = _normalize_index_list(failed, max_index=max_index)


def _stage_failures_for(source: dict, stage: str | None = None) -> list[dict]:
    _ensure_source_tracking(source)
    if stage is None or stage == "all":
        return list(source.get("stage_failures", []))
    return [f for f in source.get("stage_failures", []) if str(f.get("stage", "")).lower() == stage]


def _record_stage_failure(
    source: dict,
    *,
    stage: Literal["extraction", "embedding"],
    chunk_index: int,
    chunk_id: str,
    source_id: str,
    book_number: int,
    error_type: str,
    error_message: str,
    scope: FailureScope = "chunk",
    node_id: str | None = None,
    node_display_name: str | None = None,
    parent_chunk_id: str | None = None,
) -> None:
    _ensure_source_tracking(source)
    stage_failures = source["stage_failures"]
    now = _now_iso()
    normalized_parent_chunk_id = parent_chunk_id or chunk_id

    existing = None
    for rec in stage_failures:
        if (
            str(rec.get("stage")) == stage
            and str(rec.get("scope", "chunk")) == scope
            and int(rec.get("chunk_index", -1)) == int(chunk_index)
            and str(rec.get("chunk_id")) == chunk_id
            and str(rec.get("parent_chunk_id", chunk_id)) == normalized_parent_chunk_id
            and str(rec.get("node_id") or "") == str(node_id or "")
        ):
            existing = rec
            break

    if existing:
        existing["error_type"] = error_type
        existing["error_message"] = error_message
        existing["attempt_count"] = int(existing.get("attempt_count", 0)) + 1
        existing["last_attempt_at"] = now
    else:
        stage_failures.append(
            {
                "stage": stage,
                "scope": scope,
                "chunk_index": int(chunk_index),
                "chunk_id": chunk_id,
                "parent_chunk_id": normalized_parent_chunk_id,
                "source_id": source_id,
                "book_number": int(book_number),
                "error_type": error_type,
                "error_message": error_message,
                "attempt_count": 1,
                "last_attempt_at": now,
                "node_id": node_id,
                "node_display_name": node_display_name,
            }
        )

    source["extracted_chunks"] = _normalize_index_list(source.get("extracted_chunks", []))
    source["embedded_chunks"] = _normalize_index_list(source.get("embedded_chunks", []))
    if stage == "extraction":
        source["extracted_chunks"] = [i for i in source["extracted_chunks"] if i != chunk_index]
        source["embedded_chunks"] = [i for i in source["embedded_chunks"] if i != chunk_index]
    else:
        source["embedded_chunks"] = [i for i in source["embedded_chunks"] if i != chunk_index]

    source["status"] = "partial_failure"
    _sync_failed_chunks(source)


def _clear_stage_failure(
    source: dict,
    *,
    stage: Literal["extraction", "embedding"],
    chunk_id: str,
) -> None:
    _ensure_source_tracking(source)
    source["stage_failures"] = [
        rec
        for rec in source.get("stage_failures", [])
        if not (
            str(rec.get("stage")) == stage
            and (
                str(rec.get("chunk_id")) == chunk_id
                or str(rec.get("parent_chunk_id", "")) == chunk_id
            )
        )
    ]
    _sync_failed_chunks(source)


def _mark_stage_success(
    source: dict,
    *,
    stage: Literal["extraction", "embedding"],
    chunk_index: int,
    chunk_id: str,
) -> None:
    _ensure_source_tracking(source)
    if stage == "extraction":
        source["extracted_chunks"] = _normalize_index_list(source.get("extracted_chunks", []) + [chunk_index])
        _clear_stage_failure(source, stage="extraction", chunk_id=chunk_id)
    else:
        source["embedded_chunks"] = _normalize_index_list(source.get("embedded_chunks", []) + [chunk_index])
        _clear_stage_failure(source, stage="embedding", chunk_id=chunk_id)


def _update_source_status_from_coverage(source: dict) -> None:
    _ensure_source_tracking(source)
    expected = max(0, int(source.get("chunk_count") or 0))
    extracted = len(set(source.get("extracted_chunks", [])))
    embedded = len(set(source.get("embedded_chunks", [])))
    has_failures = bool(source.get("stage_failures"))

    if expected > 0 and extracted >= expected and embedded >= expected and not has_failures:
        source["status"] = "complete"
        source["ingested_at"] = source.get("ingested_at") or _now_iso()
    elif has_failures:
        source["status"] = "partial_failure"
    elif expected == 0:
        source["status"] = "pending"
    else:
        source["status"] = "ingesting"

    _sync_failed_chunks(source, max_index=expected - 1 if expected > 0 else -1)


def _resolve_world_ingest_settings(meta: dict, override: dict | None = None) -> dict:
    """Combine stored world settings with optional explicit overrides."""
    resolved = get_world_ingest_settings(meta=meta)
    for key in ("chunk_size_chars", "chunk_overlap_chars", "embedding_model", "glean_amount"):
        if not override:
            continue
        value = override.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars", "glean_amount"}:
            try:
                resolved[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            resolved[key] = str(value)
    return resolved


def _source_has_ingest_history(source: dict) -> bool:
    if max(0, int(source.get("chunk_count") or 0)) > 0:
        return True
    if source.get("ingested_at"):
        return True
    if source.get("failed_chunks") or source.get("stage_failures"):
        return True
    if source.get("extracted_chunks") or source.get("embedded_chunks"):
        return True
    return str(source.get("status") or "pending").lower() not in {"", "pending"}


def _compute_file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _build_source_ingest_snapshot(
    world_id: str,
    source: dict,
    ingest_settings: dict,
) -> dict | None:
    vault_filename = str(source.get("vault_filename") or "").strip()
    if not vault_filename:
        return None

    source_path = world_sources_dir(world_id) / vault_filename
    if not source_path.exists():
        return None

    try:
        file_size = int(source_path.stat().st_size)
    except OSError:
        return None

    return {
        "vault_filename": vault_filename,
        "file_size": file_size,
        "file_sha256": _compute_file_sha256(source_path),
        "chunk_size_chars": int(ingest_settings.get("chunk_size_chars", 0) or 0),
        "chunk_overlap_chars": int(ingest_settings.get("chunk_overlap_chars", 0) or 0),
        "embedding_model": str(ingest_settings.get("embedding_model", "") or ""),
        "captured_at": _now_iso(),
    }


def _load_source_temporal_chunks(
    world_id: str,
    source: dict,
    chunker: RecursiveChunker,
    *,
    apply_active_overrides: bool = True,
) -> list[TemporalChunk]:
    source_id = str(source.get("source_id") or "")
    book_number = int(source.get("book_number") or 0)
    vault_filename = str(source.get("vault_filename") or "")
    source_path = world_sources_dir(world_id) / vault_filename
    text = source_path.read_text(encoding="utf-8")
    raw_chunks = chunker.chunk(text)
    temporal_chunks = stamp_chunks(
        chunks=[
            {
                "text": chunk.text,
                "primary_text": chunk.primary_text,
                "overlap_text": chunk.overlap_text,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "index": chunk.index,
            }
            for chunk in raw_chunks
        ],
        book_number=book_number,
        source_id=source_id,
        world_id=world_id,
    )
    if not apply_active_overrides:
        return temporal_chunks
    return _apply_active_chunk_overrides(world_id, temporal_chunks)


def _source_snapshot_chunk_settings_match(snapshot: dict, ingest_settings: dict) -> bool:
    try:
        return (
            int(snapshot.get("chunk_size_chars", -1)) == int(ingest_settings.get("chunk_size_chars", -2))
            and int(snapshot.get("chunk_overlap_chars", -1)) == int(ingest_settings.get("chunk_overlap_chars", -2))
        )
    except (TypeError, ValueError):
        return False


def get_reembed_eligibility(
    world_id: str,
    *,
    meta: dict | None = None,
    audit_summary: dict | None = None,
) -> dict:
    review_summary = get_safety_review_summary(world_id)
    if int(review_summary.get("unresolved_reviews", 0) or 0) > 0:
        return {
            "can_reembed_all": False,
            "reason_code": "safety_review_pending",
            "message": (
                "This world has unresolved safety review items. Resolve or discard them before running Re-embed All."
            ),
            "ignored_pending_sources_count": 0,
            "requires_full_rebuild": False,
            "eligible_source_ids": [],
            "eligible_sources_count": 0,
        }

    if meta is None:
        audit_summary = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
        meta = _load_meta(world_id)
    elif audit_summary is None:
        audit_summary = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=False)

    sources = list(meta.get("sources", []))
    if not sources:
        return {
            "can_reembed_all": False,
            "reason_code": "no_sources",
            "message": "No sources are available to re-embed.",
            "ignored_pending_sources_count": 0,
            "requires_full_rebuild": False,
            "eligible_source_ids": [],
            "eligible_sources_count": 0,
        }

    source_summaries = {
        str(row.get("source_id")): row
        for row in (audit_summary.get("sources", []) if isinstance(audit_summary, dict) else [])
        if isinstance(row, dict) and row.get("source_id")
    }
    locked_settings = get_world_ingest_settings(meta=meta)
    eligible_source_ids: list[str] = []
    ignored_pending_sources_count = 0

    def _blocked(
        reason_code: str,
        message: str,
        *,
        requires_full_rebuild: bool,
    ) -> dict:
        return {
            "can_reembed_all": False,
            "reason_code": reason_code,
            "message": message,
            "ignored_pending_sources_count": ignored_pending_sources_count,
            "requires_full_rebuild": requires_full_rebuild,
            "eligible_source_ids": [],
            "eligible_sources_count": 0,
        }

    for source in sources:
        if not _source_has_ingest_history(source):
            ignored_pending_sources_count += 1
            continue

        source_id = str(source.get("source_id") or "")
        display_name = str(source.get("display_name") or source_id or "This source")
        source_status = str(source.get("status") or "").lower()
        summary = source_summaries.get(source_id, {})

        if source_status != "complete" or int(summary.get("failed_records", 0) or 0) > 0:
            return _blocked(
                "source_not_complete",
                f"{display_name} is not fully ingested yet. Use Resume or Retry before running Re-embed All.",
                requires_full_rebuild=False,
            )

        snapshot = source.get("ingest_snapshot")
        if not isinstance(snapshot, dict):
            return _blocked(
                "legacy_snapshot_missing",
                f"{display_name} was ingested before source snapshots were recorded. Run Re-ingest once before using Re-embed All.",
                requires_full_rebuild=True,
            )

        if not _source_snapshot_chunk_settings_match(snapshot, locked_settings):
            return _blocked(
                "chunk_settings_mismatch",
                f"{display_name} was ingested with different chunk settings than this world's locked ingest settings. Run Re-ingest.",
                requires_full_rebuild=True,
            )

        current_snapshot = _build_source_ingest_snapshot(world_id, source, locked_settings)
        if current_snapshot is None:
            return _blocked(
                "source_missing",
                f"{display_name}'s ingested source file is missing from the world vault. Run Re-ingest.",
                requires_full_rebuild=True,
            )

        if (
            str(current_snapshot.get("vault_filename") or "") != str(snapshot.get("vault_filename") or "")
            or int(current_snapshot.get("file_size", -1) or -1) != int(snapshot.get("file_size", -2) or -2)
            or str(current_snapshot.get("file_sha256") or "") != str(snapshot.get("file_sha256") or "")
        ):
            return _blocked(
                "source_changed",
                f"{display_name}'s ingested source file changed since the last clean ingest. Run Re-ingest.",
                requires_full_rebuild=True,
            )

        eligible_source_ids.append(source_id)

    if not eligible_source_ids:
        message = (
            "No previously fully ingested sources are available for Re-embed All. "
            "Use Resume to ingest new pending sources first."
            if ignored_pending_sources_count > 0
            else "No previously fully ingested sources are available for Re-embed All."
        )
        return {
            "can_reembed_all": False,
            "reason_code": "no_completed_sources",
            "message": message,
            "ignored_pending_sources_count": ignored_pending_sources_count,
            "requires_full_rebuild": False,
            "eligible_source_ids": [],
            "eligible_sources_count": 0,
        }

    message = (
        f"Ready to re-embed {len(eligible_source_ids)} fully ingested source(s). "
        f"{ignored_pending_sources_count} pending new source(s) will be ignored."
        if ignored_pending_sources_count > 0
        else f"Ready to re-embed {len(eligible_source_ids)} fully ingested source(s)."
    )
    return {
        "can_reembed_all": True,
        "reason_code": "ready",
        "message": message,
        "ignored_pending_sources_count": ignored_pending_sources_count,
        "requires_full_rebuild": False,
        "eligible_source_ids": eligible_source_ids,
        "eligible_sources_count": len(eligible_source_ids),
    }


def _apply_world_ingest_settings(meta: dict, ingest_settings: dict, *, lock: bool = False) -> dict:
    """Persist effective ingest settings on the in-memory world metadata payload."""
    current = get_world_ingest_settings(meta=meta)
    updated = dict(current)
    for key in ("chunk_size_chars", "chunk_overlap_chars", "embedding_model", "glean_amount"):
        value = ingest_settings.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars", "glean_amount"}:
            try:
                updated[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            updated[key] = str(value)

    now = _now_iso()
    updated["locked_at"] = updated.get("locked_at") or (now if lock else None)
    updated["last_ingest_settings_at"] = now
    meta["ingest_settings"] = updated
    meta["embedding_model"] = updated["embedding_model"]
    return updated


def _reset_source_tracking_for_full_rebuild(source: dict) -> None:
    source["status"] = "pending"
    source["chunk_count"] = 0
    source["ingested_at"] = None
    source.pop("ingest_snapshot", None)
    source["failed_chunks"] = []
    source["stage_failures"] = []
    source["extracted_chunks"] = []
    source["embedded_chunks"] = []


def _prepare_source_for_reembed(source: dict) -> None:
    _ensure_source_tracking(source)
    source["status"] = "ingesting"
    source["failed_chunks"] = []
    source["stage_failures"] = [
        failure
        for failure in source.get("stage_failures", [])
        if str(failure.get("stage", "")).lower() != "embedding"
    ]
    source["embedded_chunks"] = []
    expected = max(0, int(source.get("chunk_count") or 0))
    _sync_failed_chunks(source, max_index=expected - 1 if expected > 0 else -1)


def _collect_extracted_coverage(world_id: str, graph_store: GraphStore) -> dict[str, set[int]]:
    by_source: dict[str, set[int]] = {}
    for _, attrs in graph_store.graph.nodes(data=True):
        source_chunks = attrs.get("source_chunks", [])
        if isinstance(source_chunks, str):
            try:
                source_chunks = json.loads(source_chunks)
            except (json.JSONDecodeError, TypeError):
                source_chunks = []
        for raw_chunk_id in source_chunks or []:
            parsed = _parse_chunk_id(world_id, str(raw_chunk_id))
            if not parsed:
                continue
            source_id, idx = parsed
            by_source.setdefault(source_id, set()).add(idx)
    return by_source


def _collect_embedded_coverage(world_id: str, vector_store: VectorStore) -> dict[str, set[int]]:
    by_source: dict[str, set[int]] = {}
    for rec in vector_store.get_all_chunk_records():
        metadata = rec.get("metadata", {}) or {}
        source_id = metadata.get("source_id")
        chunk_index = metadata.get("chunk_index")
        if source_id is not None and chunk_index is not None:
            try:
                idx = int(chunk_index)
                if idx >= 0:
                    by_source.setdefault(str(source_id), set()).add(idx)
                    continue
            except (TypeError, ValueError):
                pass

        parsed = _parse_chunk_id(world_id, str(rec.get("id", "")))
        if not parsed:
            continue
        parsed_source_id, idx = parsed
        by_source.setdefault(parsed_source_id, set()).add(idx)
    return by_source


def _collect_expected_node_records_by_source(world_id: str, graph_store: GraphStore) -> dict[str, list[dict]]:
    by_source: dict[str, dict[str, dict]] = {}
    for node_id, attrs in graph_store.graph.nodes(data=True):
        source_chunks = attrs.get("source_chunks", [])
        if isinstance(source_chunks, str):
            try:
                source_chunks = json.loads(source_chunks)
            except (json.JSONDecodeError, TypeError):
                source_chunks = []

        for raw_chunk_id in source_chunks or []:
            chunk_id = str(raw_chunk_id)
            parsed = _parse_chunk_id(world_id, chunk_id)
            if not parsed:
                continue
            source_id, chunk_index = parsed
            source_nodes = by_source.setdefault(source_id, {})
            record = source_nodes.get(str(node_id))
            if record is None or int(record["chunk_index"]) > chunk_index:
                node_snapshot = {
                    "node_id": str(node_id),
                    "display_name": str(attrs.get("display_name", "")),
                    "description": str(attrs.get("description", "")),
                    "claims": attrs.get("claims", []),
                    "source_chunks": source_chunks,
                }
                source_nodes[str(node_id)] = {
                    "id": str(node_id),
                    "display_name": str(attrs.get("display_name", "")),
                    "normalized_id": str(attrs.get("normalized_id", "")),
                    "chunk_id": chunk_id,
                    "chunk_index": int(chunk_index),
                    "canonical_document": build_unique_node_document(node_snapshot),
                }
    return {
        source_id: sorted(records.values(), key=lambda record: (int(record["chunk_index"]), record["id"]))
        for source_id, records in by_source.items()
    }


def _collect_canonical_unique_node_documents(graph_store: GraphStore) -> dict[str, str]:
    documents: dict[str, str] = {}
    for node_id, attrs in graph_store.graph.nodes(data=True):
        snapshot = {
            "node_id": str(node_id),
            "display_name": str(attrs.get("display_name", "")),
            "description": str(attrs.get("description", "")),
            "claims": attrs.get("claims", []),
            "source_chunks": attrs.get("source_chunks", []),
        }
        documents[str(node_id)] = build_unique_node_document(snapshot)
    return documents


def _collect_unique_node_embedding_records(unique_node_vector_store: VectorStore) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    raw_records: list[dict[str, Any]]
    if hasattr(unique_node_vector_store, "get_all_records"):
        raw_records = unique_node_vector_store.get_all_records(include_documents=True)
    elif hasattr(unique_node_vector_store, "get_all_chunk_records"):
        raw_records = unique_node_vector_store.get_all_chunk_records()
    else:
        raw_records = []

    for rec in raw_records:
        record_id = str(rec.get("id", "")).strip()
        if not record_id:
            continue
        has_document = "document" in rec
        records[record_id] = {
            "id": record_id,
            "document": str(rec.get("document") or ""),
            "has_document": has_document,
            "metadata": rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {},
        }
    return records


def _collect_orphan_graph_nodes(world_id: str, graph_store: GraphStore) -> list[dict]:
    orphans: list[dict] = []
    for node_id, attrs in graph_store.graph.nodes(data=True):
        source_chunks = attrs.get("source_chunks", [])
        if isinstance(source_chunks, str):
            try:
                source_chunks = json.loads(source_chunks)
            except (json.JSONDecodeError, TypeError):
                source_chunks = []
        valid_chunks = [
            str(raw_chunk_id)
            for raw_chunk_id in (source_chunks or [])
            if _parse_chunk_id(world_id, str(raw_chunk_id))
        ]
        if valid_chunks:
            continue
        orphans.append(
            {
                "id": str(node_id),
                "display_name": str(attrs.get("display_name", "")),
                "normalized_id": str(attrs.get("normalized_id", "")),
            }
        )
    return orphans


def audit_ingestion_integrity(
    world_id: str,
    *,
    synthesize_failures: bool = True,
    persist: bool = True,
) -> dict:
    """
    Audit source coverage (expected vs extracted vs embedded) and optionally
    synthesize repairable stage failures for legacy worlds.
    """
    meta = _load_meta(world_id)
    graph_store = GraphStore(world_id)
    vector_store = VectorStore(world_id)
    unique_node_vector_store = VectorStore(world_id, collection_suffix="unique_nodes")

    extracted_by_source = _collect_extracted_coverage(world_id, graph_store)
    embedded_by_source = _collect_embedded_coverage(world_id, vector_store)
    expected_nodes_by_source = _collect_expected_node_records_by_source(world_id, graph_store)
    canonical_node_documents = _collect_canonical_unique_node_documents(graph_store)
    embedded_unique_node_records = _collect_unique_node_embedding_records(unique_node_vector_store)
    orphan_graph_nodes = _collect_orphan_graph_nodes(world_id, graph_store)
    graph_node_ids = {str(node_id) for node_id in graph_store.graph.nodes()}

    summary_sources: list[dict] = []
    summary_failures: list[dict] = []
    expected_total = 0
    extracted_total = 0
    embedded_total = 0
    expected_node_total = len(graph_node_ids)
    fresh_unique_node_ids = {
        node_id
        for node_id, document in canonical_node_documents.items()
        if node_id in embedded_unique_node_records
        and (
            not embedded_unique_node_records.get(node_id, {}).get("has_document")
            or str(embedded_unique_node_records.get(node_id, {}).get("document") or "") == str(document)
        )
    }
    stale_unique_node_ids = {
        node_id
        for node_id, document in canonical_node_documents.items()
        if node_id in embedded_unique_node_records
        and embedded_unique_node_records.get(node_id, {}).get("has_document")
        and str(embedded_unique_node_records.get(node_id, {}).get("document") or "") != str(document)
    }
    embedded_node_total = len(fresh_unique_node_ids)
    failed_total = 0
    complete_sources = 0
    partial_sources = 0
    synthesized_total = 0
    stale_total = len(stale_unique_node_ids)

    for source in meta.get("sources", []):
        _ensure_source_tracking(source)
        source_id = source.get("source_id", "")
        book_number = int(source.get("book_number") or 0)
        expected = max(0, int(source.get("chunk_count") or 0))
        expected_total += expected
        expected_range = set(range(expected))

        extracted_set = set(extracted_by_source.get(source_id, set()))
        embedded_set = set(embedded_by_source.get(source_id, set()))
        extracted_in_range = sorted(i for i in extracted_set if i in expected_range)
        embedded_in_range = sorted(i for i in embedded_set if i in expected_range)

        source["extracted_chunks"] = extracted_in_range
        source["embedded_chunks"] = embedded_in_range

        retained_failures = []
        for rec in source.get("stage_failures", []):
            if not isinstance(rec, dict):
                continue
            stage = str(rec.get("stage", "")).lower()
            scope = str(rec.get("scope", "chunk")).lower()
            node_id = str(rec.get("node_id") or "").strip()
            parent_chunk_id = str(rec.get("parent_chunk_id") or rec.get("chunk_id") or "").strip()
            try:
                idx = int(rec.get("chunk_index"))
            except (TypeError, ValueError):
                continue
            if idx not in expected_range:
                continue
            if stage == "extraction" and idx in extracted_set:
                continue
            if stage == "embedding":
                if scope == "node" and node_id:
                    expected_node = next((node for node in expected_nodes_by_source.get(source_id, []) if str(node.get("id")) == node_id), None)
                    record = embedded_unique_node_records.get(node_id)
                    if expected_node is not None and record and (
                        not record.get("has_document")
                        or str(record.get("document") or "") == str(expected_node.get("canonical_document") or "")
                    ):
                        continue
                elif idx in embedded_set:
                    continue
            retained_failures.append(rec)
        source["stage_failures"] = retained_failures
        _sync_failed_chunks(source, max_index=expected - 1 if expected > 0 else -1)

        existing_chunk_failure_keys: set[tuple[str, int, str]] = set()
        existing_node_failure_keys: set[tuple[str, int, str]] = set()
        for rec in source.get("stage_failures", []):
            if not isinstance(rec, dict):
                continue
            stage = str(rec.get("stage", "")).lower()
            scope = str(rec.get("scope", "chunk")).lower()
            try:
                idx = int(rec.get("chunk_index", -1))
            except (TypeError, ValueError):
                continue
            if scope == "node":
                node_id = str(rec.get("node_id") or "").strip()
                if node_id:
                    existing_node_failure_keys.add((stage, idx, node_id))
            else:
                existing_chunk_failure_keys.add((stage, idx, scope))

        expected_nodes = expected_nodes_by_source.get(source_id, [])
        missing_node_vectors: list[dict] = []
        stale_node_vectors: list[dict] = []
        source_expected_node_total = len(expected_nodes)
        fresh_node_ids: set[str] = set()
        stale_node_ids: set[str] = set()
        for node in expected_nodes:
            if node["id"] in fresh_unique_node_ids:
                fresh_node_ids.add(node["id"])
            elif node["id"] in stale_unique_node_ids:
                stale_node_ids.add(node["id"])

        source_embedded_node_total = len(fresh_node_ids)

        for idx in range(expected):
            chunk = _chunk_id(world_id, source_id, idx)
            if synthesize_failures:
                if idx not in extracted_set and ("extraction", idx, "chunk") not in existing_chunk_failure_keys:
                    source["stage_failures"].append(
                        {
                            "stage": "extraction",
                            "scope": "chunk",
                            "chunk_index": idx,
                            "chunk_id": chunk,
                            "parent_chunk_id": chunk,
                            "source_id": source_id,
                            "book_number": book_number,
                            "error_type": "coverage_gap",
                            "error_message": "Chunk missing extraction coverage in graph store.",
                            "attempt_count": 0,
                            "last_attempt_at": _now_iso(),
                            "node_id": None,
                            "node_display_name": None,
                        }
                    )
                    existing_chunk_failure_keys.add(("extraction", idx, "chunk"))
                    synthesized_total += 1

                if idx not in embedded_set and ("embedding", idx, "chunk") not in existing_chunk_failure_keys:
                    source["stage_failures"].append(
                        {
                            "stage": "embedding",
                            "scope": "chunk",
                            "chunk_index": idx,
                            "chunk_id": chunk,
                            "parent_chunk_id": chunk,
                            "source_id": source_id,
                            "book_number": book_number,
                            "error_type": "coverage_gap",
                            "error_message": "Chunk missing embedding coverage in vector store.",
                            "attempt_count": 0,
                            "last_attempt_at": _now_iso(),
                            "node_id": None,
                            "node_display_name": None,
                        }
                    )
                    existing_chunk_failure_keys.add(("embedding", idx, "chunk"))
                    synthesized_total += 1

        if synthesize_failures:
            for node in expected_nodes:
                idx = int(node["chunk_index"])
                if node["id"] in fresh_node_ids or ("embedding", idx, node["id"]) in existing_node_failure_keys:
                    continue
                is_stale = node["id"] in stale_node_ids
                source["stage_failures"].append(
                    {
                        "stage": "embedding",
                        "scope": "node",
                        "chunk_index": idx,
                        "chunk_id": node["chunk_id"],
                        "parent_chunk_id": node["chunk_id"],
                        "source_id": source_id,
                        "book_number": book_number,
                        "error_type": "stale_vector" if is_stale else "coverage_gap",
                        "error_message": "Node embedding is stale and no longer matches the current graph entity."
                        if is_stale
                        else "Node missing embedding coverage in unique node vector store.",
                        "attempt_count": 0,
                        "last_attempt_at": _now_iso(),
                        "node_id": node["id"],
                        "node_display_name": node.get("display_name", ""),
                    }
                )
                existing_node_failure_keys.add(("embedding", idx, node["id"]))
                synthesized_total += 1

        for node in expected_nodes:
            if node["id"] in fresh_node_ids:
                continue
            row = {
                "chunk_index": int(node["chunk_index"]),
                "chunk_id": node["chunk_id"],
                "node_id": node["id"],
                "node_display_name": node.get("display_name", ""),
            }
            if node["id"] in stale_node_ids:
                stale_node_vectors.append(row)
            else:
                missing_node_vectors.append(row)

        _sync_failed_chunks(source)
        _update_source_status_from_coverage(source)

        extracted_total += len(extracted_in_range)
        embedded_total += len(embedded_in_range)
        failed_total += len(source.get("stage_failures", []))

        if source.get("status") == "complete":
            complete_sources += 1
        if source.get("status") == "partial_failure":
            partial_sources += 1

        missing_extraction = sorted(i for i in range(expected) if i not in extracted_set)
        missing_embedding = sorted(i for i in range(expected) if i not in embedded_set)
        source_summary = {
            "source_id": source_id,
            "display_name": source.get("display_name"),
            "book_number": book_number,
            "expected_chunks": expected,
            "extracted_chunks": len(extracted_in_range),
            "embedded_chunks": len(embedded_in_range),
            "expected_node_vectors": source_expected_node_total,
            "embedded_node_vectors": source_embedded_node_total,
            "missing_extraction_chunks": missing_extraction,
            "missing_embedding_chunks": missing_embedding,
            "missing_node_vectors": missing_node_vectors,
            "stale_node_vectors": stale_node_vectors,
            "failed_records": len(source.get("stage_failures", [])),
            "status": source.get("status"),
            "stage_failures": list(source.get("stage_failures", [])),
        }
        summary_sources.append(source_summary)
        for rec in source.get("stage_failures", []):
            failure_row = dict(rec)
            failure_row["display_name"] = source.get("display_name")
            summary_failures.append(failure_row)

    blocking_issues: list[dict] = []

    any_failures = any(bool(s.get("stage_failures")) for s in meta.get("sources", []))
    all_complete = bool(meta.get("sources")) and all(s.get("status") == "complete" for s in meta.get("sources", []))
    if meta.get("ingestion_status") != "in_progress":
        if all_complete and not any_failures and not blocking_issues:
            meta["ingestion_status"] = "complete"
        elif any_failures or blocking_issues:
            meta["ingestion_status"] = "partial_failure"

    meta["total_chunks"] = sum(int(s.get("chunk_count") or 0) for s in meta.get("sources", []))
    meta["total_nodes"] = graph_store.get_node_count()
    meta["total_edges"] = graph_store.get_edge_count()
    meta["embedded_unique_nodes"] = embedded_node_total

    summary = {
        "world": {
            "expected_chunks": expected_total,
            "extracted_chunks": extracted_total,
            "embedded_chunks": embedded_total,
            "current_unique_nodes": meta["total_nodes"],
            "embedded_unique_nodes": embedded_node_total,
            "expected_node_vectors": expected_node_total,
            "embedded_node_vectors": embedded_node_total,
            "stale_unique_node_vectors": stale_total,
            "failed_records": failed_total,
            "sources_total": len(meta.get("sources", [])),
            "sources_complete": complete_sources,
            "sources_partial_failure": partial_sources,
            "synthesized_failures": synthesized_total,
            "orphan_graph_nodes": len(orphan_graph_nodes),
            "blocking_issues": len(blocking_issues),
        },
        "sources": summary_sources,
        "failures": summary_failures,
        "blocking_issues": blocking_issues,
        "orphan_graph_nodes": orphan_graph_nodes,
    }
    meta["ingestion_audit"] = summary

    if persist:
        _save_meta(world_id, meta)
    return summary


def _select_sources_for_run(
    meta: dict,
    *,
    resume: bool,
    retry_only: bool,
    retry_stage: RetryStage,
    retry_source_id: str | None,
) -> list[dict]:
    sources = list(meta.get("sources", []))
    for source in sources:
        _ensure_source_tracking(source)

    if retry_source_id:
        sources = [s for s in sources if s.get("source_id") == retry_source_id]

    if not resume:
        return sources

    if retry_only:
        filtered: list[dict] = []
        for source in sources:
            failures = _stage_failures_for(source, retry_stage)
            if failures:
                filtered.append(source)
        return filtered

    return [
        s
        for s in sources
        if s.get("status") in ("pending", "ingesting", "partial_failure")
        or s.get("failed_chunks")
        or s.get("stage_failures")
    ]


def _build_chunk_plan(
    world_id: str,
    source: dict,
    *,
    chunks_total: int,
    resume: bool,
    retry_only: bool,
    retry_stage: RetryStage,
    checkpoint: dict | None,
    reembed_all: bool = False,
) -> dict[int, ChunkMode]:
    _ensure_source_tracking(source)
    plan: dict[int, ChunkMode] = {}
    skipped_extraction_chunk_ids = _unresolved_safety_review_chunk_ids(world_id)

    if reembed_all:
        return {idx: "embedding_only" for idx in range(max(0, chunks_total))}

    if not retry_only:
        start_from = 0
        if resume and checkpoint and checkpoint.get("source_id") == source.get("source_id"):
            start_from = max(0, int(checkpoint.get("last_completed_chunk_index", -1)) + 1)
        for idx in range(start_from, chunks_total):
            plan[idx] = "full"

    if resume and source.get("failed_chunks") and not source.get("stage_failures"):
        for idx in _normalize_index_list(source.get("failed_chunks", []), max_index=chunks_total - 1):
            plan[idx] = "full_cleanup"

    stage_failures = _stage_failures_for(source, retry_stage)
    extraction_failed: set[int] = set()
    embedding_failed: set[int] = set()
    for rec in stage_failures:
        try:
            idx = int(rec.get("chunk_index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if idx < 0 or idx >= chunks_total:
            continue
        stage = str(rec.get("stage", "")).lower()
        if stage == "extraction":
            if str(rec.get("chunk_id") or "") in skipped_extraction_chunk_ids:
                continue
            extraction_failed.add(idx)
        elif stage == "embedding":
            embedding_failed.add(idx)

    for idx in extraction_failed:
        plan[idx] = "full_cleanup"
    for idx in embedding_failed:
        if plan.get(idx) != "full_cleanup":
            plan[idx] = "embedding_only"

    return {idx: plan[idx] for idx in sorted(plan.keys())}


async def start_ingestion(
    world_id: str,
    resume: bool = True,
    retry_stage: str = "all",
    retry_source_id: str | None = None,
    retry_only: bool = False,
    operation: str = "default",
    ingest_settings_override: dict | None = None,
    use_active_chunk_overrides: bool = False,
) -> None:
    """Run the ingestion pipeline. Called from a BackgroundTask."""
    clear_sse_queue(world_id)

    my_event = threading.Event()
    _abort_events[world_id] = my_event
    _active_runs[world_id] = my_event
    _clear_active_waits(world_id)
    try:
        operation_norm = _normalize_ingest_operation(operation)
        retry_stage_norm = _normalize_retry_stage(retry_stage)
        meta = _load_meta(world_id)
        settings = load_settings()
        world_ingest_settings = _resolve_world_ingest_settings(meta, ingest_settings_override)
        effective_resume = resume and operation_norm == "default"
        is_full_rebuild = operation_norm == "rechunk_reingest" or (not resume and operation_norm == "default")
        is_reembed_all = operation_norm == "reembed_all"
        allow_active_chunk_overrides = is_full_rebuild and bool(use_active_chunk_overrides)
        meta.pop("ingestion_abort_requested_at", None)
        meta.pop("ingestion_wait", None)

        if is_full_rebuild or is_reembed_all:
            review_guard = get_safety_review_rebuild_guard(
                world_id,
                allow_active_overrides=allow_active_chunk_overrides,
            )
            if not review_guard.get("can_rebuild"):
                raise RuntimeError(str(review_guard.get("message") or "Safety review work is still pending for this world."))

        if is_full_rebuild:
            _clear_manual_rescue_reviews(world_id)
            world_ingest_settings = _apply_world_ingest_settings(meta, world_ingest_settings, lock=True)
            _clear_checkpoint(world_id)
            log_path = world_log_path(world_id)
            if log_path.exists():
                os.remove(str(log_path))

            graph_store = GraphStore(world_id)
            graph_store.clear()
            vector_store = VectorStore(world_id, embedding_model=world_ingest_settings["embedding_model"])
            unique_node_vector_store = VectorStore(
                world_id,
                embedding_model=world_ingest_settings["embedding_model"],
                collection_suffix="unique_nodes",
            )
            vector_store.drop_collection()
            unique_node_vector_store.drop_collection()

            for source in meta.get("sources", []):
                _reset_source_tracking_for_full_rebuild(source)
            _mark_ingestion_live(meta, operation=operation_norm, started=True)
            meta["total_chunks"] = 0
            meta["total_nodes"] = 0
            meta["embedded_unique_nodes"] = 0
            meta["total_edges"] = 0
            _save_meta(world_id, meta)
        elif is_reembed_all:
            audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
            meta = _load_meta(world_id)
            reembed_eligibility = get_reembed_eligibility(world_id, meta=meta)
            if not reembed_eligibility.get("can_reembed_all"):
                raise RuntimeError(str(reembed_eligibility.get("message") or "Re-embed All is not currently safe for this world."))
            world_ingest_settings = _apply_world_ingest_settings(meta, world_ingest_settings, lock=True)

            _clear_checkpoint(world_id)
            log_path = world_log_path(world_id)
            if log_path.exists():
                os.remove(str(log_path))

            vector_store = VectorStore(world_id, embedding_model=world_ingest_settings["embedding_model"])
            unique_node_vector_store = VectorStore(
                world_id,
                embedding_model=world_ingest_settings["embedding_model"],
                collection_suffix="unique_nodes",
            )
            vector_store.drop_collection()
            unique_node_vector_store.drop_collection()

            eligible_source_ids = set(reembed_eligibility.get("eligible_source_ids", []))
            for source in meta.get("sources", []):
                if str(source.get("source_id") or "") in eligible_source_ids:
                    _prepare_source_for_reembed(source)
            _mark_ingestion_live(meta, operation=operation_norm, started=True)
            meta["embedded_unique_nodes"] = 0
            _save_meta(world_id, meta)
        else:
            # Resume/retry flow includes an audit pass that can synthesize
            # repairable failures for legacy mismatch worlds.
            audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
            meta = _load_meta(world_id)
            world_ingest_settings = _resolve_world_ingest_settings(meta, None)
            _apply_world_ingest_settings(meta, world_ingest_settings, lock=False)
            _mark_ingestion_live(meta, operation=operation_norm, started=True)
            _save_meta(world_id, meta)

        sources = (
            [
                source
                for source in meta.get("sources", [])
                if not is_reembed_all or str(source.get("source_id") or "") in eligible_source_ids
            ]
            if is_reembed_all
            else _select_sources_for_run(
                meta,
                resume=effective_resume,
                retry_only=retry_only,
                retry_stage=retry_stage_norm,
                retry_source_id=retry_source_id,
            )
        )

        chunk_size = int(world_ingest_settings.get("chunk_size_chars", settings.get("chunk_size_chars", 4000)))
        chunk_overlap = int(world_ingest_settings.get("chunk_overlap_chars", settings.get("chunk_overlap_chars", 150)))
        chunker = RecursiveChunker(chunk_size=chunk_size, overlap=chunk_overlap)

        graph_store = GraphStore(world_id)
        vector_store = VectorStore(world_id, embedding_model=world_ingest_settings["embedding_model"])
        unique_node_vector_store = VectorStore(
            world_id,
            embedding_model=world_ingest_settings["embedding_model"],
            collection_suffix="unique_nodes",
        )

        ga = GraphArchitectAgent(world_id=world_id)
        glean_amount = int(world_ingest_settings.get("glean_amount", settings.get("glean_amount", 1)))

        await _extraction_scheduler.configure(
            concurrency=int(settings.get("graph_extraction_concurrency", settings.get("ingestion_concurrency", 4))),
            cooldown_seconds=float(settings.get("graph_extraction_cooldown_seconds", 0)),
        )
        await _embedding_scheduler.configure(
            concurrency=int(settings.get("embedding_concurrency", 8)),
            cooldown_seconds=float(settings.get("embedding_cooldown_seconds", 0)),
        )

        graph_lock = _get_async_lock(world_id, _graph_locks)
        vector_lock = _get_async_lock(world_id, _vector_locks)
        meta_lock = _get_async_lock(world_id, _meta_locks)

        async def acquire_stage_slot(
            scheduler: _StageScheduler,
            *,
            wait_state: Literal["queued_for_extraction_slot", "queued_for_embedding_slot"],
            wait_stage: WaitStage,
            source_id: str | None,
            book_number: int | None,
            chunk_index: int | None,
            active_agent: str,
        ) -> int:
            slot = await scheduler.try_acquire()
            if slot is not None:
                return slot

            wait_key = f"{source_id or 'world'}:{book_number if book_number is not None else 'na'}:{chunk_index if chunk_index is not None else 'na'}:{wait_state}"
            await _begin_wait(
                world_id,
                meta,
                meta_lock,
                wait_key=wait_key,
                wait_state=wait_state,
                wait_stage=wait_stage,
                source_id=source_id,
                book_number=book_number,
                chunk_index=chunk_index,
                active_agent=active_agent,
            )
            acquired = False
            try:
                slot = await scheduler.acquire(my_event)
                acquired = True
                return slot
            finally:
                await _finish_wait(
                    world_id,
                    meta,
                    meta_lock,
                    wait_key=wait_key,
                    emit_log=acquired and not my_event.is_set() and _is_current_run(world_id, my_event),
                )

        async def acquire_gemini_key(
            *,
            source_id: str | None,
            book_number: int | None,
            chunk_index: int | None,
            active_agent: str,
        ) -> tuple[str, int]:
            km = get_key_manager()
            wait_key = f"{source_id or 'world'}:{book_number if book_number is not None else 'na'}:{chunk_index if chunk_index is not None else 'na'}:waiting_for_api_key:{active_agent}"
            wait_started = False
            acquired = False
            try:
                while True:
                    _ensure_not_aborted(world_id, my_event)
                    try:
                        api_key, key_index = km.get_active_key()
                        acquired = True
                        return api_key, key_index
                    except AllKeysInCooldownError as exc:
                        if not wait_started:
                            await _begin_wait(
                                world_id,
                                meta,
                                meta_lock,
                                wait_key=wait_key,
                                wait_state="waiting_for_api_key",
                                wait_stage="embedding",
                                source_id=source_id,
                                book_number=book_number,
                                chunk_index=chunk_index,
                                active_agent=active_agent,
                                wait_retry_after_seconds=exc.retry_after_seconds,
                            )
                            wait_started = True
                        else:
                            await _update_wait_retry_after(
                                world_id,
                                meta,
                                meta_lock,
                                wait_key=wait_key,
                                wait_retry_after_seconds=exc.retry_after_seconds,
                            )
                        await asyncio.sleep(jittered_delay(exc.retry_after_seconds))
            finally:
                if wait_started:
                    await _finish_wait(
                        world_id,
                        meta,
                        meta_lock,
                        wait_key=wait_key,
                        emit_log=acquired and not my_event.is_set() and _is_current_run(world_id, my_event),
                    )

        async def process_chunk(
            chunk_idx: int,
            tc: Any,
            source_id: str,
            book_number: int,
            temporal_chunks: list[Any],
            source: dict,
            mode: ChunkMode,
        ) -> None:
            if my_event.is_set() or not _is_current_run(world_id, my_event):
                return

            chunk = _chunk_id(world_id, source_id, chunk_idx)
            now = _now_iso()
            node_records_for_embedding: list[dict] = []
            embedding_wait_agent = (
                "embedding_rebuild"
                if is_reembed_all
                else ("embedding_retry" if mode == "embedding_only" else "node_embedding")
            )

            async with meta_lock:
                _mark_ingestion_live(meta, operation=operation_norm)
                _save_meta(world_id, meta)

            if mode in ("full", "full_cleanup"):
                extraction_slot: int | None = None
                try:
                    extraction_slot = await acquire_stage_slot(
                        _extraction_scheduler,
                        wait_state="queued_for_extraction_slot",
                        wait_stage="extracting",
                        source_id=source_id,
                        book_number=book_number,
                        chunk_index=chunk_idx,
                        active_agent="graph_architect",
                    )
                    _ensure_not_aborted(world_id, my_event)

                    if mode == "full_cleanup":
                        cleanup = await _cleanup_chunk_retry_artifacts(
                            graph_store=graph_store,
                            vector_store=vector_store,
                            unique_node_vector_store=unique_node_vector_store,
                            chunk_id=chunk,
                            source_book=book_number,
                            source_chunk=chunk_idx,
                            graph_lock=graph_lock,
                            vector_lock=vector_lock,
                        )
                        cleanup_log = {key: value for key, value in cleanup.items() if key != "removed_node_ids"}
                        if any(value for value in cleanup_log.values()):
                            _append_log(
                                world_id,
                                {
                                    "event": "extraction_cleanup",
                                    "source_id": source_id,
                                    "book_number": book_number,
                                    "chunk_index": chunk_idx,
                                    **cleanup_log,
                                },
                            )

                    push_sse_event(
                        world_id,
                        {
                            "event": "progress",
                            "chunk_index": chunk_idx,
                            "chunks_total": len(temporal_chunks),
                            "source_id": source_id,
                            "active_agent": "graph_architect",
                            "book_number": book_number,
                            **_build_progress_event(
                                world_id,
                                meta,
                                source_id=source_id,
                                active_agent="graph_architect",
                                total_chunks=len(temporal_chunks),
                            ),
                        },
                    )
                    extraction_payload = _build_graph_extraction_payload_for_chunk(tc)
                    ga_output, ga_usage = await ga.run(extraction_payload)
                    _ensure_not_aborted(world_id, my_event)
                    final_nodes = list(ga_output.nodes)
                    final_edges = list(ga_output.edges)

                    for g_idx in range(max(0, glean_amount)):
                        push_sse_event(
                            world_id,
                            {
                                "event": "progress",
                                "chunk_index": chunk_idx,
                                "chunks_total": len(temporal_chunks),
                                "source_id": source_id,
                                "active_agent": f"graph_architect_glean_{g_idx + 1}",
                                "book_number": book_number,
                                **_build_progress_event(
                                    world_id,
                                    meta,
                                    source_id=source_id,
                                    active_agent=f"graph_architect_glean_{g_idx + 1}",
                                    total_chunks=len(temporal_chunks),
                                ),
                            },
                        )
                        glean_out, _ = await ga.run_glean(extraction_payload, final_nodes, final_edges)
                        _ensure_not_aborted(world_id, my_event)
                        final_nodes.extend(glean_out.nodes)
                        final_edges.extend(glean_out.edges)

                    _append_log(
                        world_id,
                        {
                            "agent": "graph_architect",
                            "chunk_index": chunk_idx,
                            "book_number": book_number,
                            "status": "success",
                            "node_count": len(final_nodes),
                            "edge_count": len(final_edges),
                            "gleans": max(0, glean_amount),
                            **ga_usage,
                        },
                    )

                    _ensure_not_aborted(world_id, my_event)
                    live_total_nodes = 0
                    live_total_edges = 0
                    async with graph_lock:
                        node_records_for_embedding = _persist_chunk_graph_artifacts(
                            graph_store,
                            nodes=final_nodes,
                            edges=final_edges,
                            chunk_id=chunk,
                            book_number=book_number,
                            chunk_index=chunk_idx,
                        )
                        live_total_nodes = graph_store.get_node_count()
                        live_total_edges = graph_store.get_edge_count()
                    _ensure_not_aborted(world_id, my_event)

                    if not _chunk_has_graph_coverage(graph_store, chunk):
                        await _cleanup_chunk_retry_artifacts(
                            graph_store=graph_store,
                            vector_store=vector_store,
                            unique_node_vector_store=unique_node_vector_store,
                            chunk_id=chunk,
                            source_book=book_number,
                            source_chunk=chunk_idx,
                            graph_lock=graph_lock,
                            vector_lock=vector_lock,
                        )
                        raise ExtractionCoverageError("Chunk produced no extraction coverage in graph store.")

                    async with meta_lock:
                        _mark_stage_success(source, stage="extraction", chunk_index=chunk_idx, chunk_id=chunk)
                        meta["total_nodes"] = max(_coerce_non_negative_int(meta.get("total_nodes")), live_total_nodes)
                        meta["total_edges"] = max(_coerce_non_negative_int(meta.get("total_edges")), live_total_edges)
                        _mark_ingestion_live(meta, operation=operation_norm)
                        _save_meta(world_id, meta)

                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    error_kind = _classify_exception_kind(exc)
                    err_text = str(exc.safety_reason or exc) if isinstance(exc, AgentCallError) and exc.kind == "safety_block" else str(exc)
                    safety_reason = exc.safety_reason if isinstance(exc, AgentCallError) else None
                    logger.error("Extraction failed for chunk %s (%s): %s", chunk_idx, source_id, err_text)
                    _append_log(
                        world_id,
                        {
                            "event": "extraction_error",
                            "source_id": source_id,
                            "book_number": book_number,
                            "chunk_index": chunk_idx,
                            "error_type": error_kind,
                            "error": err_text,
                            "safety_reason": safety_reason,
                        },
                    )
                    async with meta_lock:
                        _record_stage_failure(
                            source,
                            stage="extraction",
                            chunk_index=chunk_idx,
                            chunk_id=chunk,
                            source_id=source_id,
                            book_number=book_number,
                            error_type=error_kind,
                            error_message=err_text,
                        )
                        review_item = None
                        if error_kind == "safety_block":
                            review_item = _upsert_safety_review(
                                world_id,
                                source_id=source_id,
                                book_number=book_number,
                                chunk_index=chunk_idx,
                                chunk_id=chunk,
                                original_raw_text=tc.primary_text,
                                original_prefixed_text=tc.prefixed_text,
                                overlap_raw_text=tc.overlap_text,
                                safety_reason=str(safety_reason or err_text),
                            )
                        _mark_ingestion_live(meta, operation=operation_norm)
                        _save_meta(world_id, meta)
                    push_sse_event(
                        world_id,
                        {
                            "event": "error",
                            "stage": "extraction",
                            "chunk_index": chunk_idx,
                            "book_number": book_number,
                            "source_id": source_id,
                            "error_type": error_kind,
                            "safety_reason": safety_reason,
                            "chunk_text": tc.prefixed_text if error_kind == "safety_block" else None,
                            "review_id": review_item.get("review_id") if isinstance(review_item, dict) else None,
                            "message": f"Extraction failed for chunk {chunk_idx}: {err_text}",
                            "safety_review_summary": get_safety_review_summary(world_id),
                            **_build_progress_event(
                                world_id,
                                meta,
                                source_id=source_id,
                                active_agent="graph_architect",
                                total_chunks=len(temporal_chunks),
                            ),
                        },
                    )
                    return
                finally:
                    if extraction_slot is not None:
                        await _extraction_scheduler.release(
                            extraction_slot,
                            aborted=my_event.is_set() or not _is_current_run(world_id, my_event),
                        )
            else:
                push_sse_event(
                    world_id,
                    {
                        "event": "progress",
                        "chunk_index": chunk_idx,
                        "chunks_total": len(temporal_chunks),
                        "source_id": source_id,
                        "active_agent": "embedding_rebuild" if is_reembed_all else "embedding_retry",
                        "book_number": book_number,
                        **_build_progress_event(
                            world_id,
                            meta,
                            source_id=source_id,
                            active_agent="embedding_rebuild" if is_reembed_all else "embedding_retry",
                            total_chunks=len(temporal_chunks),
                        ),
                    },
                )

            _ensure_not_aborted(world_id, my_event)

            # Embedding stage.
            embedding_slot: int | None = None
            try:
                embedding_slot = await acquire_stage_slot(
                    _embedding_scheduler,
                    wait_state="queued_for_embedding_slot",
                    wait_stage="embedding",
                    source_id=source_id,
                    book_number=book_number,
                    chunk_index=chunk_idx,
                    active_agent=embedding_wait_agent,
                )
                if not node_records_for_embedding:
                    async with graph_lock:
                        node_records_for_embedding = _chunk_node_records(graph_store, chunk)
                _ensure_not_aborted(world_id, my_event)

                api_key, _ = await acquire_gemini_key(
                    source_id=source_id,
                    book_number=book_number,
                    chunk_index=chunk_idx,
                    active_agent=embedding_wait_agent,
                )
                chunk_embeddings = await asyncio.to_thread(
                    vector_store.embed_texts,
                    [tc.prefixed_text],
                    api_key=api_key,
                )
                _ensure_not_aborted(world_id, my_event)
                chunk_embedding = chunk_embeddings[0]
                unique_node_embedding_count = 0
                embedded_unique_node_total = 0

                _ensure_not_aborted(world_id, my_event)
                async with vector_lock:
                    await asyncio.to_thread(
                        vector_store.upsert_document_embedding,
                        document_id=chunk,
                        text=tc.prefixed_text,
                        metadata={
                            "world_id": world_id,
                            "source_id": source_id,
                            "book_number": book_number,
                            "chunk_index": chunk_idx,
                            "char_start": tc.char_start,
                            "char_end": tc.char_end,
                            "display_label": tc.display_label,
                        },
                        embedding=chunk_embedding,
                    )
                    _ensure_not_aborted(world_id, my_event)
                _ensure_not_aborted(world_id, my_event)

                push_sse_event(
                    world_id,
                    {
                        "event": "progress",
                        "chunk_index": chunk_idx,
                        "chunks_total": len(temporal_chunks),
                        "source_id": source_id,
                        "active_agent": "node_embedding_rebuild" if is_reembed_all else "node_embedding",
                        "book_number": book_number,
                        **_build_progress_event(
                            world_id,
                            meta,
                            source_id=source_id,
                            active_agent="node_embedding_rebuild" if is_reembed_all else "node_embedding",
                            total_chunks=len(temporal_chunks),
                        ),
                    },
                )
                unique_node_embedding_count = await _upsert_unique_node_vectors(
                    unique_node_vector_store=unique_node_vector_store,
                    node_records=node_records_for_embedding,
                    api_key=api_key,
                    vector_lock=vector_lock,
                    abort_check=lambda: _ensure_not_aborted(world_id, my_event),
                )
                async with vector_lock:
                    embedded_unique_node_total = await asyncio.to_thread(unique_node_vector_store.count)
                _ensure_not_aborted(world_id, my_event)

                async with meta_lock:
                    _mark_stage_success(source, stage="embedding", chunk_index=chunk_idx, chunk_id=chunk)
                    current_unique_nodes = _coerce_non_negative_int(meta.get("total_nodes"))
                    if current_unique_nodes > 0:
                        embedded_unique_node_total = min(embedded_unique_node_total, current_unique_nodes)
                    meta["embedded_unique_nodes"] = embedded_unique_node_total
                    checkpoint = _load_checkpoint(world_id) or {}
                    last_completed = int(checkpoint.get("last_completed_chunk_index", -1))
                    _save_checkpoint(
                        world_id,
                        {
                            "source_id": source_id,
                            "last_completed_chunk_index": max(last_completed, chunk_idx),
                            "last_completed_agent": "vector",
                            "chunks_total": len(temporal_chunks),
                            "started_at": checkpoint.get("started_at", now),
                            "updated_at": _now_iso(),
                        },
                    )
                    _mark_ingestion_live(meta, operation=operation_norm)
                    _save_meta(world_id, meta)

                push_sse_event(
                    world_id,
                    {
                        "event": "agent_complete",
                        "chunk_index": chunk_idx,
                        "book_number": book_number,
                        "source_id": source_id,
                        "agent": "vector_rebuild" if is_reembed_all else "embedding",
                        "mode": mode,
                        "chunk_vector_count": 1,
                        "node_vector_count": unique_node_embedding_count,
                        "unique_node_vector_count": unique_node_embedding_count,
                        **_build_progress_event(
                            world_id,
                            meta,
                            source_id=source_id,
                            active_agent="node_embedding_rebuild" if is_reembed_all else "node_embedding",
                            total_chunks=len(temporal_chunks),
                        ),
                    },
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                error_kind = _classify_exception_kind(exc)
                err_text = str(exc)
                _append_log(
                    world_id,
                    {
                        "event": "vector_error",
                        "source_id": source_id,
                        "book_number": book_number,
                        "chunk_index": chunk_idx,
                        "error_type": error_kind,
                        "error": err_text,
                    },
                )
                async with meta_lock:
                    _record_stage_failure(
                        source,
                        stage="embedding",
                        chunk_index=chunk_idx,
                        chunk_id=chunk,
                        source_id=source_id,
                        book_number=book_number,
                        error_type=error_kind,
                        error_message=err_text,
                    )
                    _mark_ingestion_live(meta, operation=operation_norm)
                    _save_meta(world_id, meta)
                push_sse_event(
                    world_id,
                    {
                        "event": "error",
                        "stage": "embedding",
                        "chunk_index": chunk_idx,
                        "book_number": book_number,
                        "source_id": source_id,
                        "error_type": error_kind,
                        "message": f"Embedding failed for chunk {chunk_idx}: {err_text}",
                        "safety_review_summary": get_safety_review_summary(world_id),
                        **_build_progress_event(
                            world_id,
                            meta,
                            source_id=source_id,
                            active_agent="node_embedding_rebuild" if is_reembed_all else "node_embedding",
                            total_chunks=len(temporal_chunks),
                        ),
                    },
                )
            finally:
                if embedding_slot is not None:
                    await _embedding_scheduler.release(
                        embedding_slot,
                        aborted=my_event.is_set() or not _is_current_run(world_id, my_event),
                    )

        for source in sources:
            if my_event.is_set() or not _is_current_run(world_id, my_event):
                break

            source_id = source["source_id"]
            book_number = int(source["book_number"])
            vault_filename = source["vault_filename"]
            source_path = world_sources_dir(world_id) / vault_filename

            if not source_path.exists():
                push_sse_event(
                    world_id,
                    {
                        "event": "error",
                        "source_id": source_id,
                        "error_type": "file_missing",
                        "message": f"Source file '{vault_filename}' not found.",
                    },
                )
                source["status"] = "error"
                _save_meta(world_id, meta)
                continue

            temporal_chunks = _load_source_temporal_chunks(
                world_id,
                source,
                chunker,
                apply_active_overrides=(allow_active_chunk_overrides or not is_full_rebuild),
            )

            chunks_total = len(temporal_chunks)
            _ensure_source_tracking(source)
            source["chunk_count"] = chunks_total
            source["status"] = "ingesting"
            source["extracted_chunks"] = _normalize_index_list(source.get("extracted_chunks", []), max_index=chunks_total - 1)
            source["embedded_chunks"] = _normalize_index_list(source.get("embedded_chunks", []), max_index=chunks_total - 1)
            source["failed_chunks"] = _normalize_index_list(source.get("failed_chunks", []), max_index=chunks_total - 1)
            _save_meta(world_id, meta)

            checkpoint = _load_checkpoint(world_id)
            chunk_plan = _build_chunk_plan(
                world_id,
                source,
                chunks_total=chunks_total,
                resume=effective_resume,
                retry_only=retry_only,
                retry_stage=retry_stage_norm,
                checkpoint=checkpoint,
                reembed_all=is_reembed_all,
            )

            if not chunk_plan:
                _update_source_status_from_coverage(source)
                _save_meta(world_id, meta)
                continue

            tasks = [
                process_chunk(
                    idx,
                    temporal_chunks[idx],
                    source_id,
                    book_number,
                    temporal_chunks,
                    source,
                    mode,
                )
                for idx, mode in chunk_plan.items()
            ]
            if tasks:
                await asyncio.gather(*tasks)

            if not my_event.is_set() and _is_current_run(world_id, my_event):
                _update_source_status_from_coverage(source)
                if source.get("status") == "complete":
                    snapshot = _build_source_ingest_snapshot(world_id, source, world_ingest_settings)
                    if snapshot:
                        source["ingest_snapshot"] = snapshot
                _mark_ingestion_live(meta, operation=operation_norm)
                _save_meta(world_id, meta)

        is_current = _is_current_run(world_id, my_event)
        if not my_event.is_set() and is_current:
            if is_reembed_all:
                api_key, _ = await acquire_gemini_key(
                    source_id=None,
                    book_number=None,
                    chunk_index=None,
                    active_agent="node_embedding_rebuild",
                )
                await _rebuild_unique_node_vectors(
                    graph_store,
                    unique_node_vector_store,
                    api_key,
                    vector_lock=vector_lock,
                    abort_check=lambda: _ensure_not_aborted(world_id, my_event),
                )
            audit = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
            refreshed = _load_meta(world_id)
            has_failures = audit["world"]["failed_records"] > 0
            _clear_active_waits(world_id)
            _mark_ingestion_terminal(refreshed, "complete" if not has_failures else "partial_failure")
            _save_meta(world_id, refreshed)
            if not has_failures:
                _clear_checkpoint(world_id)
            for issue in audit.get("blocking_issues", []):
                push_sse_event(
                    world_id,
                    {
                        "event": "error",
                        "stage": "embedding",
                        "message": str(issue.get("message") or "Ingestion finished with unresolved graph/vector blockers."),
                    },
                )
            push_sse_event(
                world_id,
                {
                    "event": "complete",
                    "world_id": world_id,
                    "status": refreshed["ingestion_status"],
                    "stage_counters": audit["world"],
                    "safety_review_summary": get_safety_review_summary(world_id),
                    **_build_progress_event(world_id, refreshed),
                },
            )
        elif my_event.is_set() and is_current:
            refreshed = _load_meta(world_id)
            _clear_active_waits(world_id)
            _mark_ingestion_terminal(refreshed, "aborted")
            _save_meta(world_id, refreshed)
            push_sse_event(
                world_id,
                {
                    "event": "aborted",
                    "world_id": world_id,
                    "safety_review_summary": get_safety_review_summary(world_id),
                    **_build_progress_event(world_id, refreshed),
                },
            )

    except asyncio.CancelledError:
        if _is_current_run(world_id, my_event):
            refreshed = _load_meta(world_id)
            _clear_active_waits(world_id)
            _mark_ingestion_terminal(refreshed, "aborted")
            _save_meta(world_id, refreshed)
            push_sse_event(
                world_id,
                {
                    "event": "aborted",
                    "world_id": world_id,
                    "safety_review_summary": get_safety_review_summary(world_id),
                    **_build_progress_event(world_id, refreshed),
                },
            )
    except Exception as exc:
        logger.exception("Ingestion failed for world %s", world_id)
        if _is_current_run(world_id, my_event):
            meta = _load_meta(world_id)
            _clear_active_waits(world_id)
            _mark_ingestion_terminal(meta, "error")
            _save_meta(world_id, meta)
            push_sse_event(
                world_id,
                {
                    "event": "error",
                    "message": str(exc),
                    "safety_review_summary": get_safety_review_summary(world_id),
                },
            )
    finally:
        _clear_active_waits(world_id)
        if _abort_events.get(world_id) is my_event:
            _abort_events.pop(world_id, None)
        if _active_runs.get(world_id) is my_event:
            _active_runs.pop(world_id, None)


def abort_ingestion(world_id: str) -> None:
    """Signal the ingestion loop to stop."""
    if world_id in _abort_events:
        _abort_events[world_id].set()
    try:
        meta = _load_meta(world_id)
    except FileNotFoundError:
        return
    if has_active_ingestion_run(world_id):
        meta["ingestion_abort_requested_at"] = _now_iso()
        meta.pop("ingestion_wait", None)
        _save_meta(world_id, meta)
        _clear_active_waits(world_id)
        push_sse_event(
            world_id,
            {
                "event": "aborting",
                "world_id": world_id,
                **_build_progress_event(world_id, meta, aborting=True),
            },
        )
        _wake_stage_schedulers()
        return
    if meta.get("ingestion_status") != "in_progress":
        return
    audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
    meta = _load_meta(world_id)
    _clear_active_waits(world_id)
    _mark_ingestion_terminal(meta, "aborted")
    _save_meta(world_id, meta)
    push_sse_event(
        world_id,
        {
            "event": "aborted",
            "world_id": world_id,
            "recovered": True,
            **_build_progress_event(world_id, meta),
        },
    )


def get_checkpoint_info(world_id: str) -> dict:
    """Return checkpoint + audit status for the frontend."""
    recover_stale_ingestion(world_id)
    cp = _load_checkpoint(world_id)
    meta = _load_meta(world_id)
    allow_synthesis = meta.get("ingestion_status") != "in_progress"
    audit = audit_ingestion_integrity(world_id, synthesize_failures=allow_synthesis, persist=True)
    meta = _load_meta(world_id)
    sources = meta.get("sources", [])
    source_by_id = {s.get("source_id"): s for s in sources}
    cp_source = source_by_id.get(cp.get("source_id")) if cp else None
    active_run = has_active_ingestion_run(world_id)
    progress_source = cp_source or _progress_source(meta)
    progress_source_id = progress_source.get("source_id") if progress_source else None
    progress_total_chunks = int(progress_source.get("chunk_count") or (cp.get("chunks_total", 0) if cp else 0) or 0) if progress_source else int(cp.get("chunks_total", 0) if cp else 0)
    progress_payload = _build_progress_event(
        world_id,
        meta,
        source_id=progress_source_id,
        total_chunks=progress_total_chunks,
        aborting=bool(meta.get("ingestion_abort_requested_at")),
    )
    safety_review_summary = get_safety_review_summary(world_id)

    retryable_sources = [
        s
        for s in sources
        if s.get("status") in ("pending", "ingesting", "partial_failure")
        or s.get("failed_chunks")
        or s.get("stage_failures")
    ]

    if not retryable_sources:
        return {
            "can_resume": False,
            "chunk_index": 0,
            "chunks_total": 0,
            "reason": None,
            "stage_counters": audit["world"],
            "failures": audit["failures"],
            "safety_review_summary": safety_review_summary,
            **progress_payload,
        }

    try:
        source = cp_source if cp_source in retryable_sources else retryable_sources[0]
        failed_chunks = _normalize_index_list(source.get("failed_chunks", []))
        chunks_total = int(source.get("chunk_count") or (cp.get("chunks_total", 0) if cp else 0))
        cp_completed = (int(cp.get("last_completed_chunk_index", -1)) + 1) if cp else 0
        if chunks_total > 0:
            cp_completed = max(0, min(cp_completed, chunks_total))
        else:
            cp_completed = max(0, cp_completed)
        source_completed = max(0, chunks_total - len(failed_chunks)) if chunks_total else cp_completed
        completed_chunks = max(cp_completed, source_completed)
        reason = "failed_chunks" if failed_chunks else "pending_work"

        response = {
            "can_resume": True,
            "chunk_index": completed_chunks,
            "chunks_total": chunks_total,
            "source_id": source.get("source_id"),
            "reason": reason,
            "stage_counters": audit["world"],
            "failures": audit["failures"],
            "safety_review_summary": safety_review_summary,
            **progress_payload,
        }
        if active_run and response["total_chunks_current_phase"] > 0:
            response["chunk_index"] = response["completed_chunks_current_phase"]
            response["chunks_total"] = response["total_chunks_current_phase"]
        return response
    except Exception:
        return {
            "can_resume": False,
            "chunk_index": 0,
            "chunks_total": 0,
            "reason": "checkpoint_corrupted",
            "stage_counters": audit["world"],
            "failures": audit["failures"],
            "safety_review_summary": safety_review_summary,
            **progress_payload,
        }


async def update_safety_review_draft(world_id: str, review_id: str, draft_raw_text: str) -> dict:
    if has_active_ingestion_run(world_id):
        raise RuntimeError("Wait for the active ingest run to finish before editing safety review items.")

    meta_lock = _get_async_lock(world_id, _meta_locks)
    async with meta_lock:
        cache = _load_safety_review_cache(world_id)
        review = _find_safety_review(cache, review_id)
        if review is None:
            raise FileNotFoundError("Safety review item not found.")

        normalized_draft = _normalize_review_text(draft_raw_text)
        review["draft_raw_text"] = normalized_draft
        _set_review_pending_status(review)
        review["updated_at"] = _now_iso()
        _save_safety_review_cache(world_id, cache)

    item = _get_safety_review_item(world_id, review_id)
    if item is None:
        raise FileNotFoundError("Safety review item not found.")
    return item


async def discard_safety_review(world_id: str, review_id: str) -> dict:
    if has_active_ingestion_run(world_id):
        raise RuntimeError("Wait for the active ingest run to finish before discarding safety review items.")

    meta_lock = _get_async_lock(world_id, _meta_locks)
    async with meta_lock:
        deleted = _delete_safety_review(world_id, review_id)
    if not deleted:
        raise FileNotFoundError("Safety review item not found.")
    return {
        "ok": True,
        "review_id": review_id,
        "safety_review_summary": get_safety_review_summary(world_id),
    }


async def manual_rescue_safety_reviews(
    world_id: str,
    *,
    source_id: str,
    chunk_indices: list[int],
) -> dict:
    if has_active_ingestion_run(world_id):
        raise RuntimeError("Wait for the active ingest run to finish before rescuing safety review items.")

    normalized_source_id = str(source_id or "").strip()
    normalized_indices = _normalize_index_list(chunk_indices or [])
    if not normalized_source_id:
        raise RuntimeError("Choose a source before rescuing failed chunks for editing.")
    if not normalized_indices:
        raise RuntimeError("Choose at least one failed chunk to recover for editing.")

    meta_lock = _get_async_lock(world_id, _meta_locks)
    async with meta_lock:
        audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
        meta = _load_meta(world_id)
        _prune_stale_manual_rescue_reviews(world_id, meta=meta)
        meta = _load_meta(world_id)

        source = next(
            (row for row in meta.get("sources", []) if str(row.get("source_id") or "") == normalized_source_id),
            None,
        )
        if source is None:
            raise FileNotFoundError("The selected source no longer exists in this world.")

        world_ingest_settings = get_world_ingest_settings(meta=meta)
        chunker = RecursiveChunker(
            chunk_size=int(world_ingest_settings.get("chunk_size_chars", load_settings().get("chunk_size_chars", 4000))),
            overlap=int(world_ingest_settings.get("chunk_overlap_chars", load_settings().get("chunk_overlap_chars", 150))),
        )
        try:
            temporal_chunks = _load_source_temporal_chunks(
                world_id,
                source,
                chunker,
                apply_active_overrides=False,
            )
        except Exception as exc:
            raise RuntimeError(f"Could not load the saved source for rescue: {exc}") from exc

        rescue_fingerprint = _manual_rescue_fingerprint(world_id, source, world_ingest_settings)
        if rescue_fingerprint is None:
            raise RuntimeError("This world no longer has a saved source snapshot that can be used for manual rescue.")

        extraction_failures = {
            int(failure.get("chunk_index", -1)): failure
            for failure in _stage_failures_for(source, "extraction")
            if isinstance(failure, dict)
        }

        missing_indices: list[int] = []
        invalid_indices: list[int] = []
        rescue_candidates: list[tuple[int, str, TemporalChunk, dict]] = []
        for chunk_index in normalized_indices:
            if chunk_index < 0 or chunk_index >= len(temporal_chunks):
                invalid_indices.append(chunk_index)
                continue

            failure = extraction_failures.get(chunk_index)
            chunk_id = _chunk_id(world_id, normalized_source_id, chunk_index)
            if failure is None or str(failure.get("chunk_id") or "") != chunk_id:
                missing_indices.append(chunk_index)
                continue

            rescue_candidates.append((chunk_index, chunk_id, temporal_chunks[chunk_index], failure))

        if invalid_indices:
            joined = ", ".join(f"C{idx}" for idx in invalid_indices)
            raise RuntimeError(f"These chunks no longer exist in the current locked chunk map: {joined}.")
        if missing_indices:
            joined = ", ".join(f"C{idx}" for idx in missing_indices)
            raise RuntimeError(
                f"These chunks no longer have current extraction failures and cannot be recovered for editing: {joined}."
            )

        rescued_review_ids: list[str] = []
        for chunk_index, chunk_id, temporal_chunk, failure in rescue_candidates:
            rescued = _upsert_safety_review(
                world_id,
                source_id=normalized_source_id,
                book_number=int(source.get("book_number") or 0),
                chunk_index=chunk_index,
                chunk_id=chunk_id,
                original_raw_text=temporal_chunk.primary_text,
                original_prefixed_text=temporal_chunk.prefixed_text,
                overlap_raw_text=temporal_chunk.overlap_text,
                safety_reason=(
                    "Manual rescue for the current extraction failure: "
                    f"{failure.get('error_type', 'unknown')} - {failure.get('error_message', 'Unknown error.')}"
                ),
                original_error_kind="manual_rescue",
                review_origin="manual_rescue",
                manual_rescue_fingerprint={
                    **rescue_fingerprint,
                    "chunk_id": chunk_id,
                    "chunk_index": int(chunk_index),
                },
            )
            rescued_review_ids.append(str(rescued.get("review_id") or ""))

    rescued_reviews = [
        item
        for review_id in rescued_review_ids
        if review_id
        for item in [ _get_safety_review_item(world_id, review_id) ]
        if item is not None
    ]
    return {
        "reviews": rescued_reviews,
        "safety_review_summary": get_safety_review_summary(world_id),
        "checkpoint": get_checkpoint_info(world_id),
    }


async def test_safety_review(world_id: str, review_id: str) -> dict:
    if has_active_ingestion_run(world_id):
        raise RuntimeError("Wait for the active ingest run to finish before testing safety review items.")

    settings = load_settings()
    await _extraction_scheduler.configure(
        concurrency=int(settings.get("graph_extraction_concurrency", settings.get("ingestion_concurrency", 4))),
        cooldown_seconds=float(settings.get("graph_extraction_cooldown_seconds", 0)),
    )
    await _embedding_scheduler.configure(
        concurrency=int(settings.get("embedding_concurrency", 8)),
        cooldown_seconds=float(settings.get("embedding_cooldown_seconds", 0)),
    )

    meta_lock = _get_async_lock(world_id, _meta_locks)
    graph_lock = _get_async_lock(world_id, _graph_locks)
    vector_lock = _get_async_lock(world_id, _vector_locks)

    async def mark_review_failure(error_kind: str, error_message: str) -> dict:
        async with meta_lock:
            cache = _load_safety_review_cache(world_id)
            review = _find_safety_review(cache, review_id)
            if review is None:
                raise FileNotFoundError("Safety review item not found.")
            review["test_in_progress"] = False
            review["last_test_outcome"] = _review_outcome_for_error_kind(error_kind)
            review["last_test_error_kind"] = error_kind
            review["last_test_error_message"] = error_message
            review["last_tested_at"] = _now_iso()
            _set_review_pending_status(review)
            review["updated_at"] = _now_iso()
            _save_safety_review_cache(world_id, cache)

        item = _get_safety_review_item(world_id, review_id)
        if item is None:
            raise FileNotFoundError("Safety review item not found.")
        return {
            "review": item,
            "safety_review_summary": get_safety_review_summary(world_id),
            "checkpoint": get_checkpoint_info(world_id),
        }

    async with meta_lock:
        meta = _load_meta(world_id)
        cache = _load_safety_review_cache(world_id)
        review = _find_safety_review(cache, review_id)
        if review is None:
            raise FileNotFoundError("Safety review item not found.")

        source_id = str(review.get("source_id") or "")
        source = next((row for row in meta.get("sources", []) if str(row.get("source_id") or "") == source_id), None)
        if source is None:
            raise RuntimeError("The source for this safety review item no longer exists.")

        world_ingest_settings = get_world_ingest_settings(meta=meta)
        review["test_in_progress"] = True
        review["status"] = "testing"
        review["test_attempt_count"] = int(review.get("test_attempt_count", 0) or 0) + 1
        review["updated_at"] = _now_iso()
        _save_safety_review_cache(world_id, cache)

    candidate_raw_text = _review_editor_raw_text(review)

    chunker = RecursiveChunker(
        chunk_size=int(world_ingest_settings.get("chunk_size_chars", settings.get("chunk_size_chars", 4000))),
        overlap=int(world_ingest_settings.get("chunk_overlap_chars", settings.get("chunk_overlap_chars", 150))),
    )

    try:
        temporal_chunks = _load_source_temporal_chunks(world_id, source, chunker)
    except Exception as exc:
        return await mark_review_failure("provider_error", f"Could not load the saved source for this review item: {exc}")

    chunk_index = int(review.get("chunk_index", -1) or -1)
    book_number = int(review.get("book_number", 0) or 0)
    chunk_id = str(review.get("chunk_id") or "")
    if chunk_index < 0 or chunk_index >= len(temporal_chunks):
        return await mark_review_failure(
            "provider_error",
            "This review item no longer matches the current locked chunk map for the saved source. Run a full re-ingest if the source changed.",
        )

    base_chunk = temporal_chunks[chunk_index]
    test_chunk = _replace_temporal_chunk_body(base_chunk, candidate_raw_text)

    graph_store = GraphStore(world_id)
    vector_store = VectorStore(world_id, embedding_model=world_ingest_settings["embedding_model"])
    unique_node_vector_store = VectorStore(
        world_id,
        embedding_model=world_ingest_settings["embedding_model"],
        collection_suffix="unique_nodes",
    )
    ga = GraphArchitectAgent(world_id=world_id)

    cleanup_before_test = await _cleanup_chunk_retry_artifacts(
        graph_store=graph_store,
        vector_store=vector_store,
        unique_node_vector_store=unique_node_vector_store,
        chunk_id=chunk_id,
        source_book=book_number,
        source_chunk=chunk_index,
        graph_lock=graph_lock,
        vector_lock=vector_lock,
    )
    cleanup_log = {key: value for key, value in cleanup_before_test.items() if key != "removed_node_ids"}
    if any(value for value in cleanup_log.values()):
        _append_log(
            world_id,
            {
                "event": "safety_review_cleanup",
                "review_id": review_id,
                "source_id": source_id,
                "book_number": book_number,
                "chunk_index": chunk_index,
                **cleanup_log,
            },
        )

    extraction_slot: int | None = None
    final_nodes: list[Any] = []
    final_edges: list[Any] = []
    node_records_for_embedding: list[dict] = []
    dummy_abort_event = threading.Event()
    try:
        extraction_slot = await _extraction_scheduler.acquire(dummy_abort_event)
        extraction_payload = _build_graph_extraction_payload_for_chunk(test_chunk)
        ga_output, _ = await ga.run(extraction_payload)
        final_nodes = list(ga_output.nodes)
        final_edges = list(ga_output.edges)

        glean_amount = int(world_ingest_settings.get("glean_amount", settings.get("glean_amount", 1)))
        for _ in range(max(0, glean_amount)):
            glean_out, _ = await ga.run_glean(extraction_payload, final_nodes, final_edges)
            final_nodes.extend(glean_out.nodes)
            final_edges.extend(glean_out.edges)
    except Exception as exc:
        error_kind = _classify_exception_kind(exc)
        error_message = str(exc.safety_reason or exc) if isinstance(exc, AgentCallError) and exc.kind == "safety_block" else str(exc)
        return await mark_review_failure(error_kind, error_message)
    finally:
        if extraction_slot is not None:
            await _extraction_scheduler.release(extraction_slot, aborted=False)

    async with graph_lock:
        node_records_for_embedding = _persist_chunk_graph_artifacts(
            graph_store,
            nodes=final_nodes,
            edges=final_edges,
            chunk_id=chunk_id,
            book_number=book_number,
            chunk_index=chunk_index,
        )

    if not _chunk_has_graph_coverage(graph_store, chunk_id):
        await _cleanup_chunk_retry_artifacts(
            graph_store=graph_store,
            vector_store=vector_store,
            unique_node_vector_store=unique_node_vector_store,
            chunk_id=chunk_id,
            source_book=book_number,
            source_chunk=chunk_index,
            graph_lock=graph_lock,
            vector_lock=vector_lock,
        )
        return await mark_review_failure(
            "no_extraction_coverage",
            "Chunk produced no extraction coverage in graph store.",
        )

    embedding_slot: int | None = None
    try:
        embedding_slot = await _embedding_scheduler.acquire(dummy_abort_event)
        km = get_key_manager()
        api_key, _ = await km.await_active_key()
        chunk_embeddings = await asyncio.to_thread(
            vector_store.embed_texts,
            [test_chunk.prefixed_text],
            api_key=api_key,
        )
        chunk_embedding = chunk_embeddings[0]

        async with vector_lock:
            await asyncio.to_thread(
                vector_store.upsert_document_embedding,
                document_id=chunk_id,
                text=test_chunk.prefixed_text,
                metadata={
                    "world_id": world_id,
                    "source_id": source_id,
                    "book_number": book_number,
                    "chunk_index": chunk_index,
                    "char_start": test_chunk.char_start,
                    "char_end": test_chunk.char_end,
                    "display_label": test_chunk.display_label,
                },
                embedding=chunk_embedding,
            )
        await _upsert_unique_node_vectors(
            unique_node_vector_store=unique_node_vector_store,
            node_records=node_records_for_embedding,
            api_key=api_key,
            vector_lock=vector_lock,
        )
    except Exception as exc:
        await _cleanup_chunk_retry_artifacts(
            graph_store=graph_store,
            vector_store=vector_store,
            unique_node_vector_store=unique_node_vector_store,
            chunk_id=chunk_id,
            source_book=book_number,
            source_chunk=chunk_index,
            graph_lock=graph_lock,
            vector_lock=vector_lock,
        )
        error_kind = _classify_exception_kind(exc)
        return await mark_review_failure(error_kind, str(exc))
    finally:
        if embedding_slot is not None:
            await _embedding_scheduler.release(embedding_slot, aborted=False)

    async with meta_lock:
        meta = _load_meta(world_id)
        source = next((row for row in meta.get("sources", []) if str(row.get("source_id") or "") == source_id), None)
        if source is None:
            raise RuntimeError("The source for this safety review item no longer exists.")
        _mark_stage_success(source, stage="extraction", chunk_index=chunk_index, chunk_id=chunk_id)
        _mark_stage_success(source, stage="embedding", chunk_index=chunk_index, chunk_id=chunk_id)
        _update_source_status_from_coverage(source)
        if source.get("status") == "complete":
            snapshot = _build_source_ingest_snapshot(world_id, source, world_ingest_settings)
            if snapshot:
                source["ingest_snapshot"] = snapshot
        _save_meta(world_id, meta)

        cache = _load_safety_review_cache(world_id)
        review = _find_safety_review(cache, review_id)
        if review is None:
            raise FileNotFoundError("Safety review item not found.")
        review["test_in_progress"] = False
        review["draft_raw_text"] = candidate_raw_text
        review["last_test_outcome"] = "passed"
        review["last_test_error_kind"] = None
        review["last_test_error_message"] = None
        review["last_tested_at"] = _now_iso()
        review["active_override_raw_text"] = candidate_raw_text
        _set_review_pending_status(review)
        review["updated_at"] = _now_iso()
        _save_safety_review_cache(world_id, cache)

    _append_log(
        world_id,
        {
            "event": "safety_review_passed",
            "review_id": review_id,
            "source_id": source_id,
            "book_number": book_number,
            "chunk_index": chunk_index,
        },
    )

    item = _get_safety_review_item(world_id, review_id)
    if item is None:
        raise FileNotFoundError("Safety review item not found.")
    return {
        "review": item,
        "safety_review_summary": get_safety_review_summary(world_id),
        "checkpoint": get_checkpoint_info(world_id),
    }
