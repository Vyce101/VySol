"""Orchestrates ingestion with stage-aware failure tracking and retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from .agents import GraphArchitectAgent
from .chunker import RecursiveChunker
from .config import (
    get_world_ingest_settings,
    load_settings,
    world_checkpoint_path,
    world_log_path,
    world_meta_path,
    world_sources_dir,
)
from .entity_text import build_unique_node_document
from .graph_store import GraphStore
from .key_manager import get_key_manager
from .temporal_indexer import stamp_chunks
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

RetryStage = Literal["extraction", "embedding", "all"]
ChunkMode = Literal["full", "full_cleanup", "embedding_only"]
IngestOperation = Literal["default", "rechunk_reingest", "reembed_all"]
FailureScope = Literal["chunk", "node"]
_STALE_RUN_GRACE_SECONDS = 15
_UNIQUE_NODE_VECTOR_BATCH_SIZE = 8


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

    return {
        "progress_phase": phase,
        "completed_chunks_current_phase": completed,
        "total_chunks_current_phase": chunk_count,
        "progress_percent": percent,
        "active_operation": active_operation,
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
    for key in ("chunk_size_chars", "chunk_overlap_chars", "embedding_model"):
        if not override:
            continue
        value = override.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars"}:
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
                f"{display_name} was ingested before source snapshots were recorded. Run Re-ingest With Previous Settings or Rechunk And Re-ingest once before using Re-embed All.",
                requires_full_rebuild=True,
            )

        if not _source_snapshot_chunk_settings_match(snapshot, locked_settings):
            return _blocked(
                "chunk_settings_mismatch",
                f"{display_name} was ingested with different chunk settings than this world's locked ingest settings. Run Re-ingest With Previous Settings or Rechunk And Re-ingest.",
                requires_full_rebuild=True,
            )

        current_snapshot = _build_source_ingest_snapshot(world_id, source, locked_settings)
        if current_snapshot is None:
            return _blocked(
                "source_missing",
                f"{display_name}'s ingested source file is missing from the world vault. Run Re-ingest With Previous Settings or Rechunk And Re-ingest.",
                requires_full_rebuild=True,
            )

        if (
            str(current_snapshot.get("vault_filename") or "") != str(snapshot.get("vault_filename") or "")
            or int(current_snapshot.get("file_size", -1) or -1) != int(snapshot.get("file_size", -2) or -2)
            or str(current_snapshot.get("file_sha256") or "") != str(snapshot.get("file_sha256") or "")
        ):
            return _blocked(
                "source_changed",
                f"{display_name}'s ingested source file changed since the last clean ingest. Run Re-ingest With Previous Settings or Rechunk And Re-ingest.",
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
    for key in ("chunk_size_chars", "chunk_overlap_chars", "embedding_model"):
        value = ingest_settings.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars"}:
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
                source_nodes[str(node_id)] = {
                    "id": str(node_id),
                    "display_name": str(attrs.get("display_name", "")),
                    "normalized_id": str(attrs.get("normalized_id", "")),
                    "chunk_id": chunk_id,
                    "chunk_index": int(chunk_index),
                }
    return {
        source_id: sorted(records.values(), key=lambda record: (int(record["chunk_index"]), record["id"]))
        for source_id, records in by_source.items()
    }


def _collect_unique_node_embedding_ids(unique_node_vector_store: VectorStore) -> set[str]:
    return {
        str(rec.get("id", "")).strip()
        for rec in unique_node_vector_store.get_all_chunk_records()
        if str(rec.get("id", "")).strip()
    }


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
    embedded_unique_node_ids = _collect_unique_node_embedding_ids(unique_node_vector_store)
    orphan_graph_nodes = _collect_orphan_graph_nodes(world_id, graph_store)
    graph_node_ids = {str(node_id) for node_id in graph_store.graph.nodes()}

    summary_sources: list[dict] = []
    summary_failures: list[dict] = []
    expected_total = 0
    extracted_total = 0
    embedded_total = 0
    expected_node_total = len(graph_node_ids)
    embedded_node_total = len(graph_node_ids & embedded_unique_node_ids)
    failed_total = 0
    complete_sources = 0
    partial_sources = 0
    synthesized_total = 0

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
                    if node_id in embedded_unique_node_ids:
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
        source_expected_node_total = len(expected_nodes)
        source_embedded_node_total = sum(1 for node in expected_nodes if node["id"] in embedded_unique_node_ids)

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
                if node["id"] in embedded_unique_node_ids or ("embedding", idx, node["id"]) in existing_node_failure_keys:
                    continue
                source["stage_failures"].append(
                    {
                        "stage": "embedding",
                        "scope": "node",
                        "chunk_index": idx,
                        "chunk_id": node["chunk_id"],
                        "parent_chunk_id": node["chunk_id"],
                        "source_id": source_id,
                        "book_number": book_number,
                        "error_type": "coverage_gap",
                        "error_message": "Node missing embedding coverage in unique node vector store.",
                        "attempt_count": 0,
                        "last_attempt_at": _now_iso(),
                        "node_id": node["id"],
                        "node_display_name": node.get("display_name", ""),
                    }
                )
                existing_node_failure_keys.add(("embedding", idx, node["id"]))
                synthesized_total += 1

        for node in expected_nodes:
            if node["id"] in embedded_unique_node_ids:
                continue
            missing_node_vectors.append(
                {
                    "chunk_index": int(node["chunk_index"]),
                    "chunk_id": node["chunk_id"],
                    "node_id": node["id"],
                    "node_display_name": node.get("display_name", ""),
                }
            )

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

    summary = {
        "world": {
            "expected_chunks": expected_total,
            "extracted_chunks": extracted_total,
            "embedded_chunks": embedded_total,
            "expected_node_vectors": expected_node_total,
            "embedded_node_vectors": embedded_node_total,
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
) -> None:
    """Run the ingestion pipeline. Called from a BackgroundTask."""
    clear_sse_queue(world_id)

    my_event = threading.Event()
    _abort_events[world_id] = my_event
    _active_runs[world_id] = my_event

    operation_norm = _normalize_ingest_operation(operation)
    retry_stage_norm = _normalize_retry_stage(retry_stage)
    meta = _load_meta(world_id)
    settings = load_settings()
    world_ingest_settings = _resolve_world_ingest_settings(meta, ingest_settings_override)
    effective_resume = resume and operation_norm == "default"
    is_full_rebuild = operation_norm == "rechunk_reingest" or (not resume and operation_norm == "default")
    is_reembed_all = operation_norm == "reembed_all"
    meta.pop("ingestion_abort_requested_at", None)

    if is_full_rebuild:
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

    ga = GraphArchitectAgent()

    try:
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

            async with meta_lock:
                _mark_ingestion_live(meta, operation=operation_norm)
                _save_meta(world_id, meta)

            if mode in ("full", "full_cleanup"):
                extraction_slot: int | None = None
                try:
                    extraction_slot = await _extraction_scheduler.acquire(my_event)
                    _ensure_not_aborted(world_id, my_event)

                    if mode == "full_cleanup":
                        async with graph_lock:
                            cleanup = graph_store.remove_chunk_artifacts(
                                chunk_id=chunk,
                                source_book=book_number,
                                source_chunk=chunk_idx,
                            )
                        if any(cleanup.values()):
                            _append_log(
                                world_id,
                                {
                                    "event": "extraction_cleanup",
                                    "source_id": source_id,
                                    "book_number": book_number,
                                    "chunk_index": chunk_idx,
                                    **cleanup,
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
                    ga_output, ga_usage = await ga.run(tc.prefixed_text)
                    _ensure_not_aborted(world_id, my_event)
                    final_nodes = list(ga_output.nodes)
                    final_edges = list(ga_output.edges)

                    glean_amount = int(settings.get("glean_amount", 1))
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
                        glean_out, _ = await ga.run_glean(tc.prefixed_text, final_nodes, final_edges)
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
                    async with graph_lock:
                        node_records_for_embedding = _persist_chunk_graph_artifacts(
                            graph_store,
                            nodes=final_nodes,
                            edges=final_edges,
                            chunk_id=chunk,
                            book_number=book_number,
                            chunk_index=chunk_idx,
                        )
                    _ensure_not_aborted(world_id, my_event)

                    async with meta_lock:
                        _mark_stage_success(source, stage="extraction", chunk_index=chunk_idx, chunk_id=chunk)
                        _mark_ingestion_live(meta, operation=operation_norm)
                        _save_meta(world_id, meta)

                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    err_text = str(exc)
                    logger.error("Extraction failed for chunk %s (%s): %s", chunk_idx, source_id, err_text)
                    _append_log(
                        world_id,
                        {
                            "event": "extraction_error",
                            "source_id": source_id,
                            "book_number": book_number,
                            "chunk_index": chunk_idx,
                            "error": err_text,
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
                            error_type=type(exc).__name__,
                            error_message=err_text,
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
                            "message": f"Extraction failed for chunk {chunk_idx}: {err_text}",
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
                embedding_slot = await _embedding_scheduler.acquire(my_event)
                if not node_records_for_embedding:
                    async with graph_lock:
                        node_records_for_embedding = _chunk_node_records(graph_store, chunk)
                _ensure_not_aborted(world_id, my_event)

                km = get_key_manager()
                api_key, _ = km.get_active_key()
                chunk_embeddings = await asyncio.to_thread(
                    vector_store.embed_texts,
                    [tc.prefixed_text],
                    api_key=api_key,
                )
                _ensure_not_aborted(world_id, my_event)
                chunk_embedding = chunk_embeddings[0]
                unique_node_embedding_count = 0

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
                _ensure_not_aborted(world_id, my_event)

                async with meta_lock:
                    _mark_stage_success(source, stage="embedding", chunk_index=chunk_idx, chunk_id=chunk)
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
                err_text = str(exc)
                _append_log(
                    world_id,
                    {
                        "event": "vector_error",
                        "source_id": source_id,
                        "book_number": book_number,
                        "chunk_index": chunk_idx,
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
                        error_type=type(exc).__name__,
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
                        "message": f"Embedding failed for chunk {chunk_idx}: {err_text}",
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

            text = source_path.read_text(encoding="utf-8")
            raw_chunks = chunker.chunk(text)
            temporal_chunks = stamp_chunks(
                chunks=[
                    {
                        "text": c.text,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                        "index": c.index,
                    }
                    for c in raw_chunks
                ],
                book_number=book_number,
                source_id=source_id,
                world_id=world_id,
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
                km = get_key_manager()
                api_key, _ = km.get_active_key()
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
                    **_build_progress_event(world_id, refreshed),
                },
            )
        elif my_event.is_set() and is_current:
            refreshed = _load_meta(world_id)
            _mark_ingestion_terminal(refreshed, "aborted")
            _save_meta(world_id, refreshed)
            push_sse_event(
                world_id,
                {
                    "event": "aborted",
                    "world_id": world_id,
                    **_build_progress_event(world_id, refreshed),
                },
            )

    except Exception as exc:
        logger.exception("Ingestion failed for world %s", world_id)
        if _is_current_run(world_id, my_event):
            meta = _load_meta(world_id)
            _mark_ingestion_terminal(meta, "error")
            _save_meta(world_id, meta)
            push_sse_event(world_id, {"event": "error", "message": str(exc)})
    finally:
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
        _save_meta(world_id, meta)
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
            **progress_payload,
        }
