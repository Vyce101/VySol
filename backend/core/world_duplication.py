"""Crash-safe world duplication helpers and activity tracking."""

from __future__ import annotations

import copy
import json
import logging
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb

from .config import (
    SAVED_WORLDS_DIR,
    load_world_meta,
    world_dir,
    world_meta_path,
    world_safety_reviews_path,
)
from .graph_store import GraphStore
from .ingestion_engine import audit_ingestion_integrity, has_active_ingestion_run, recover_stale_ingestion
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

_active_duplication_runs: dict[str, dict[str, str]] = {}
_duplication_lock = threading.RLock()
_VECTOR_BATCH_SIZE = 200
_POST_COPY_WORK_UNITS = 4
_SKIPPED_DUPLICATE_FILES = {
    "meta.json",
    "checkpoint.json",
    "ingestion_log.json",
    "ingestion_safety_reviews.json",
}
_DUPLICATION_META_FIELDS = (
    "is_temporary_duplicate",
    "duplication_status",
    "duplication_source_world_id",
    "duplication_source_world_name",
    "duplication_run_id",
    "duplication_started_at",
    "duplication_last_progress_at",
    "duplication_progress_percent",
    "duplication_total_work_units",
    "duplication_completed_work_units",
    "duplication_error",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_meta(world_id: str, meta: dict) -> None:
    path = world_meta_path(world_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    tmp.replace(path)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def _parse_chunk_id(world_id: str, chunk_id: str) -> tuple[str, int] | None:
    raw = str(chunk_id or "")
    prefix = f"chunk_{world_id}_"
    if not raw.startswith(prefix):
        return None
    tail = raw[len(prefix):]
    if "_" not in tail:
        return None
    source_id, index_raw = tail.rsplit("_", 1)
    try:
        index = int(index_raw)
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    return source_id, index


def _build_chunk_id(world_id: str, source_id: str, chunk_index: int) -> str:
    return f"chunk_{world_id}_{source_id}_{int(chunk_index)}"


def _rewrite_chunk_id(*, source_world_id: str, target_world_id: str, chunk_id: str) -> str:
    parsed = _parse_chunk_id(source_world_id, chunk_id)
    if not parsed:
        return str(chunk_id or "")
    source_id, chunk_index = parsed
    return _build_chunk_id(target_world_id, source_id, chunk_index)


def _sanitize_final_meta(meta: dict, *, world_id: str, world_name: str, created_at: str) -> dict:
    cleaned = copy.deepcopy(meta)
    cleaned["world_id"] = world_id
    cleaned["world_name"] = world_name
    cleaned["created_at"] = created_at
    cleaned.pop("active_ingestion_run", None)
    cleaned.pop("ingestion_abort_requested_at", None)
    cleaned.pop("ingestion_wait", None)
    cleaned.pop("ingestion_audit", None)
    for key in _DUPLICATION_META_FIELDS:
        cleaned.pop(key, None)
    return cleaned


def _build_initial_duplicate_meta(source_meta: dict, *, world_id: str, world_name: str, run_id: str, created_at: str) -> dict:
    meta = _sanitize_final_meta(source_meta, world_id=world_id, world_name=world_name, created_at=created_at)
    meta["is_temporary_duplicate"] = True
    meta["duplication_status"] = "in_progress"
    meta["duplication_source_world_id"] = str(source_meta.get("world_id") or "")
    meta["duplication_source_world_name"] = str(source_meta.get("world_name") or "")
    meta["duplication_run_id"] = run_id
    meta["duplication_started_at"] = created_at
    meta["duplication_last_progress_at"] = created_at
    meta["duplication_progress_percent"] = 0
    meta["duplication_total_work_units"] = 0
    meta["duplication_completed_work_units"] = 0
    meta["duplication_error"] = None
    return meta


def _copy_duplication_state(target_world_id: str, meta: dict) -> dict:
    try:
        current = _load_meta(target_world_id)
    except (OSError, json.JSONDecodeError):
        return meta
    updated = copy.deepcopy(meta)
    for key in _DUPLICATION_META_FIELDS:
        if key in current:
            updated[key] = copy.deepcopy(current[key])
    return updated


def _rewrite_stage_failure_record(record: dict, *, source_world_id: str, target_world_id: str) -> dict:
    updated = copy.deepcopy(record)
    for key in ("chunk_id", "parent_chunk_id"):
        value = updated.get(key)
        if value:
            updated[key] = _rewrite_chunk_id(
                source_world_id=source_world_id,
                target_world_id=target_world_id,
                chunk_id=str(value),
            )
    return updated


def _rewrite_source_stage_failures(source_rows: list[dict], *, source_world_id: str, target_world_id: str) -> list[dict]:
    rewritten: list[dict] = []
    for row in source_rows:
        if isinstance(row, dict):
            rewritten.append(
                _rewrite_stage_failure_record(
                    row,
                    source_world_id=source_world_id,
                    target_world_id=target_world_id,
                )
            )
    return rewritten


def _build_duplicate_working_meta(
    source_meta: dict,
    *,
    source_world_id: str,
    target_world_id: str,
    target_world_name: str,
    created_at: str,
) -> dict:
    transformed = _sanitize_final_meta(
        source_meta,
        world_id=target_world_id,
        world_name=target_world_name,
        created_at=created_at,
    )
    for source in transformed.get("sources", []):
        if not isinstance(source, dict):
            continue
        source["stage_failures"] = _rewrite_source_stage_failures(
            list(source.get("stage_failures", [])),
            source_world_id=source_world_id,
            target_world_id=target_world_id,
        )
    return transformed


def _failure_key(row: dict) -> tuple[str, str, str, int, str, str, str]:
    try:
        chunk_index = int(row.get("chunk_index", -1))
    except (TypeError, ValueError):
        chunk_index = -1
    return (
        str(row.get("stage") or ""),
        str(row.get("scope") or "chunk"),
        str(row.get("source_id") or ""),
        chunk_index,
        str(row.get("node_id") or ""),
        str(row.get("error_type") or ""),
        str(row.get("error_message") or ""),
    )


def _failure_keys_from_meta(meta: dict) -> set[tuple[str, str, str, int, str, str, str]]:
    output: set[tuple[str, str, str, int, str, str, str]] = set()
    for source in meta.get("sources", []):
        if not isinstance(source, dict):
            continue
        for row in source.get("stage_failures", []):
            if isinstance(row, dict):
                output.add(_failure_key(row))
    return output


def _list_existing_world_names() -> set[str]:
    names: set[str] = set()
    if not SAVED_WORLDS_DIR.exists():
        return names
    for directory in SAVED_WORLDS_DIR.iterdir():
        meta = load_world_meta(directory.name) if directory.is_dir() else None
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("world_name") or "").strip()
        if name:
            names.add(name)
    return names


def build_duplicate_world_name(source_world_name: str) -> str:
    base_name = str(source_world_name or "").strip() or "World"
    existing = _list_existing_world_names()
    candidate = f"{base_name} (Copy)"
    if candidate not in existing:
        return candidate
    index = 2
    while True:
        candidate = f"{base_name} (Copy {index})"
        if candidate not in existing:
            return candidate
        index += 1


def has_active_duplication_for_source(source_world_id: str) -> bool:
    normalized = str(source_world_id or "").strip()
    if not normalized:
        return False
    with _duplication_lock:
        if any(entry.get("source_world_id") == normalized for entry in _active_duplication_runs.values()):
            return True
    if not SAVED_WORLDS_DIR.exists():
        return False
    for directory in SAVED_WORLDS_DIR.iterdir():
        if not directory.is_dir():
            continue
        meta = load_world_meta(directory.name)
        if not isinstance(meta, dict):
            continue
        if not meta.get("is_temporary_duplicate"):
            continue
        if str(meta.get("duplication_status") or "") != "in_progress":
            continue
        if str(meta.get("duplication_source_world_id") or "") == normalized:
            return True
    return False


def has_active_duplication_run(world_id: str) -> bool:
    with _duplication_lock:
        return str(world_id or "").strip() in _active_duplication_runs


def is_world_involved_in_active_duplication(world_id: str) -> bool:
    normalized = str(world_id or "").strip()
    if not normalized:
        return False
    with _duplication_lock:
        if normalized in _active_duplication_runs:
            return True
        return any(entry.get("source_world_id") == normalized for entry in _active_duplication_runs.values())


def get_active_duplication_targets() -> set[str]:
    with _duplication_lock:
        return set(_active_duplication_runs.keys())


def _register_run(target_world_id: str, *, source_world_id: str, run_id: str) -> None:
    with _duplication_lock:
        _active_duplication_runs[target_world_id] = {
            "source_world_id": source_world_id,
            "run_id": run_id,
        }


def _clear_run(target_world_id: str, *, run_id: str) -> None:
    with _duplication_lock:
        current = _active_duplication_runs.get(target_world_id)
        if current and current.get("run_id") == run_id:
            _active_duplication_runs.pop(target_world_id, None)


def _is_live_run(target_world_id: str, run_id: str | None) -> bool:
    if not run_id:
        return False
    with _duplication_lock:
        current = _active_duplication_runs.get(target_world_id)
        return bool(current and current.get("run_id") == run_id)


def _update_progress_meta(target_world_id: str, run_id: str, *, completed: int, total: int) -> None:
    if not _is_live_run(target_world_id, run_id):
        return
    try:
        meta = _load_meta(target_world_id)
    except (OSError, json.JSONDecodeError):
        return
    if meta.get("duplication_run_id") != run_id:
        return
    safe_total = max(1, int(total))
    safe_completed = max(0, min(int(completed), safe_total))
    meta["duplication_status"] = "in_progress"
    meta["duplication_total_work_units"] = safe_total
    meta["duplication_completed_work_units"] = safe_completed
    meta["duplication_progress_percent"] = int(round((safe_completed / safe_total) * 100))
    meta["duplication_last_progress_at"] = _now_iso()
    meta["duplication_error"] = None
    _save_meta(target_world_id, meta)


def _mark_duplicate_failure(target_world_id: str, run_id: str, message: str) -> None:
    try:
        meta = _load_meta(target_world_id)
    except (OSError, json.JSONDecodeError):
        return
    if meta.get("duplication_run_id") != run_id:
        return
    meta["duplication_status"] = "error"
    meta["duplication_last_progress_at"] = _now_iso()
    meta["duplication_error"] = str(message or "Duplication failed.")
    _save_meta(target_world_id, meta)


def cleanup_incomplete_duplicate_worlds() -> None:
    active_targets = get_active_duplication_targets()
    if not SAVED_WORLDS_DIR.exists():
        return
    for directory in SAVED_WORLDS_DIR.iterdir():
        if not directory.is_dir():
            continue
        meta = load_world_meta(directory.name)
        if not isinstance(meta, dict):
            continue
        if not meta.get("is_temporary_duplicate"):
            continue
        if str(meta.get("duplication_status") or "").lower() == "complete":
            continue
        world_id = str(meta.get("world_id") or directory.name)
        if world_id in active_targets:
            continue
        try:
            shutil.rmtree(directory, ignore_errors=True)
        except Exception:
            logger.exception("Failed to clean incomplete duplicate world %s", world_id)


def _iter_regular_source_files(source_root: Path) -> tuple[list[Path], list[Path]]:
    directories: list[Path] = []
    files: list[Path] = []
    for path in source_root.rglob("*"):
        relative = path.relative_to(source_root)
        if relative.parts and relative.parts[0] == "chroma":
            continue
        if relative.as_posix() in _SKIPPED_DUPLICATE_FILES:
            continue
        if path.is_dir():
            directories.append(relative)
            continue
        files.append(relative)
    return directories, files


def _copy_regular_files(source_root: Path, target_root: Path):
    directories, files = _iter_regular_source_files(source_root)
    for relative_dir in directories:
        (target_root / relative_dir).mkdir(parents=True, exist_ok=True)

    completed_units = 0
    for relative_path in files:
        source_path = source_root / relative_path
        destination_path = target_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        completed_units += 1
        yield completed_units


def _load_collection_entries(world_id: str) -> list[dict[str, Any]]:
    manifest_path = world_dir(world_id) / "chroma" / "collections_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    collections = manifest.get("collections")
    if not isinstance(collections, dict):
        return []
    entries: list[dict[str, Any]] = []
    for collection_key, entry in collections.items():
        if not isinstance(entry, dict):
            continue
        entries.append(
            {
                "collection_key": str(collection_key),
                "embedding_model": str(entry.get("embedding_model") or ""),
                "collection_name": str(entry.get("collection_name") or ""),
            }
        )
    return entries


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        normalized = value.tolist()
        if normalized is None:
            return []
        return list(normalized)
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return list(value)


def _normalize_embedding_rows(value: Any) -> list[list[float]]:
    rows = _as_sequence(value)
    normalized: list[list[float]] = []
    for row in rows:
        if hasattr(row, "tolist"):
            row = row.tolist()
        if isinstance(row, tuple):
            row = list(row)
        if not isinstance(row, list):
            row = list(row)
        normalized.append([float(component) for component in row])
    return normalized


def _rewrite_vector_metadata(metadata: dict, *, source_world_id: str, target_world_id: str) -> dict:
    updated = dict(metadata)
    if "world_id" in updated and str(updated.get("world_id") or "") == source_world_id:
        updated["world_id"] = target_world_id
    return updated


def _rewrite_safety_review_payload(payload: dict, *, source_world_id: str, target_world_id: str) -> dict:
    rewritten = copy.deepcopy(payload) if isinstance(payload, dict) else {"version": 1, "reviews": []}
    reviews = rewritten.get("reviews")
    if not isinstance(reviews, list):
        rewritten["reviews"] = []
        return rewritten
    output_reviews: list[dict] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        updated = copy.deepcopy(review)
        chunk_id = _rewrite_chunk_id(
            source_world_id=source_world_id,
            target_world_id=target_world_id,
            chunk_id=str(updated.get("chunk_id") or ""),
        )
        updated["world_id"] = target_world_id
        if chunk_id:
            updated["chunk_id"] = chunk_id
            updated["review_id"] = chunk_id
        manual_fingerprint = updated.get("manual_rescue_fingerprint")
        if isinstance(manual_fingerprint, dict):
            manual_fingerprint = copy.deepcopy(manual_fingerprint)
            chunk_value = manual_fingerprint.get("chunk_id")
            if chunk_value:
                manual_fingerprint["chunk_id"] = _rewrite_chunk_id(
                    source_world_id=source_world_id,
                    target_world_id=target_world_id,
                    chunk_id=str(chunk_value),
                )
            updated["manual_rescue_fingerprint"] = manual_fingerprint
        output_reviews.append(updated)
    rewritten["reviews"] = output_reviews
    return rewritten


def _rewrite_graph_chunk_provenance(source_world_id: str, target_world_id: str) -> None:
    graph_store = GraphStore(target_world_id)
    changed = False
    for _, attrs in graph_store.graph.nodes(data=True):
        source_chunks = attrs.get("source_chunks", [])
        if isinstance(source_chunks, str):
            try:
                source_chunks = json.loads(source_chunks)
            except (json.JSONDecodeError, TypeError):
                source_chunks = []
        if not isinstance(source_chunks, list):
            source_chunks = list(source_chunks)
        rewritten_chunks = [
            _rewrite_chunk_id(
                source_world_id=source_world_id,
                target_world_id=target_world_id,
                chunk_id=str(chunk_id),
            )
            for chunk_id in source_chunks
        ]
        if rewritten_chunks != source_chunks:
            attrs["source_chunks"] = rewritten_chunks
            changed = True
    if changed:
        graph_store.save()


def _rewrite_safety_reviews(source_world_id: str, target_world_id: str) -> None:
    source_path = world_safety_reviews_path(source_world_id)
    payload = _load_json(source_path)
    if payload is None:
        return
    target_path = world_safety_reviews_path(target_world_id)
    rewritten = _rewrite_safety_review_payload(
        payload,
        source_world_id=source_world_id,
        target_world_id=target_world_id,
    )
    _save_json(target_path, rewritten)


def _clone_vector_collections(
    source_world_id: str,
    target_world_id: str,
    *,
    default_embedding_model: str,
    run_id: str,
    completed_offset: int,
    total_units: int,
) -> int:
    completed_units = completed_offset
    entries = _load_collection_entries(source_world_id)
    if not entries:
        return completed_units
    source_client = chromadb.PersistentClient(path=str(world_dir(source_world_id) / "chroma"))
    for entry in entries:
        collection_key = entry["collection_key"]
        embedding_model = entry["embedding_model"] or default_embedding_model
        collection_name = entry["collection_name"]
        if not collection_name:
            continue
        suffix = None if collection_key == "chunks" else collection_key
        try:
            source_collection = source_client.get_collection(name=collection_name)
        except Exception:
            logger.exception(
                "Failed to open source vector collection %s for world %s",
                collection_name,
                source_world_id,
            )
            continue
        target_store = VectorStore(target_world_id, embedding_model=embedding_model, collection_suffix=suffix)
        collection_count = source_collection.count()
        if collection_count <= 0:
            continue
        offset = 0
        while offset < collection_count:
            batch = source_collection.get(
                include=["documents", "metadatas", "embeddings"],
                limit=_VECTOR_BATCH_SIZE,
                offset=offset,
            )
            ids = [str(value) for value in _as_sequence(batch.get("ids"))]
            documents = [str(value) for value in _as_sequence(batch.get("documents"))]
            metadatas = [value if isinstance(value, dict) else {} for value in _as_sequence(batch.get("metadatas"))]
            embeddings = _normalize_embedding_rows(batch.get("embeddings"))
            if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
                raise RuntimeError(
                    "Duplicate copy received a malformed vector batch: "
                    f"ids={len(ids)}, documents={len(documents)}, metadatas={len(metadatas)}, embeddings={len(embeddings)}."
                )
            if collection_key == "chunks":
                ids = [
                    _rewrite_chunk_id(
                        source_world_id=source_world_id,
                        target_world_id=target_world_id,
                        chunk_id=record_id,
                    )
                    for record_id in ids
                ]
            metadatas = [
                _rewrite_vector_metadata(
                    metadata,
                    source_world_id=source_world_id,
                    target_world_id=target_world_id,
                )
                for metadata in metadatas
            ]
            if ids:
                target_store.upsert_documents_embeddings(
                    document_ids=ids,
                    texts=documents,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )
                completed_units += len(ids)
                _update_progress_meta(
                    target_world_id,
                    run_id,
                    completed=completed_units,
                    total=total_units,
                )
            offset += len(ids) if ids else _VECTOR_BATCH_SIZE
    return completed_units


def _count_total_work_units(source_world_id: str) -> int:
    source_root = world_dir(source_world_id)
    _, files = _iter_regular_source_files(source_root)
    total = len(files) + _POST_COPY_WORK_UNITS
    entries = _load_collection_entries(source_world_id)
    if not entries:
        return max(total, 1)
    source_client = chromadb.PersistentClient(path=str(source_root / "chroma"))
    for entry in entries:
        try:
            total += int(source_client.get_collection(name=entry["collection_name"]).count())
        except Exception:
            logger.exception(
                "Failed to count vector records for duplicate source world %s collection %s",
                source_world_id,
                entry["collection_key"],
            )
    return max(total, 1)


def _run_world_duplication(
    *,
    source_world_id: str,
    target_world_id: str,
    run_id: str,
    source_meta_snapshot: dict,
    target_world_name: str,
    created_at: str,
) -> None:
    try:
        source_root = world_dir(source_world_id)
        target_root = world_dir(target_world_id)
        source_failure_keys = _failure_keys_from_meta(source_meta_snapshot)
        total_units = _count_total_work_units(source_world_id)
        _update_progress_meta(target_world_id, run_id, completed=0, total=total_units)

        completed_units = 0
        for completed_file_units in _copy_regular_files(source_root, target_root):
            completed_units = completed_file_units
            _update_progress_meta(target_world_id, run_id, completed=completed_units, total=total_units)

        completed_units = _clone_vector_collections(
            source_world_id,
            target_world_id,
            default_embedding_model=str(source_meta_snapshot.get("embedding_model") or ""),
            run_id=run_id,
            completed_offset=completed_units,
            total_units=total_units,
        )

        _rewrite_graph_chunk_provenance(source_world_id, target_world_id)
        completed_units += 1
        _update_progress_meta(target_world_id, run_id, completed=completed_units, total=total_units)

        _rewrite_safety_reviews(source_world_id, target_world_id)
        completed_units += 1
        _update_progress_meta(target_world_id, run_id, completed=completed_units, total=total_units)

        working_meta = _build_duplicate_working_meta(
            source_meta_snapshot,
            source_world_id=source_world_id,
            target_world_id=target_world_id,
            target_world_name=target_world_name,
            created_at=created_at,
        )
        working_meta = _copy_duplication_state(target_world_id, working_meta)
        _save_meta(target_world_id, working_meta)
        completed_units += 1
        _update_progress_meta(target_world_id, run_id, completed=completed_units, total=total_units)

        audit_ingestion_integrity(target_world_id, synthesize_failures=True, persist=True)
        validated_meta = _load_meta(target_world_id)
        target_failure_keys = _failure_keys_from_meta(validated_meta)
        introduced_failures = sorted(target_failure_keys - source_failure_keys)
        if introduced_failures:
            preview = ", ".join(
                f"{stage}:{source_id}:chunk{chunk_index}:{error_type or 'unknown'}"
                for stage, _, source_id, chunk_index, _, error_type, _ in introduced_failures[:5]
            )
            raise RuntimeError(
                "Duplicate validation introduced new ingest failures"
                + (f": {preview}" if preview else ".")
            )
        if str(source_meta_snapshot.get("ingestion_status") or "") == "complete" and str(validated_meta.get("ingestion_status") or "") != "complete":
            raise RuntimeError("Duplicate validation left the copied world incomplete.")
        completed_units += 1
        _update_progress_meta(target_world_id, run_id, completed=completed_units, total=total_units)

        final_meta = _sanitize_final_meta(
            validated_meta,
            world_id=target_world_id,
            world_name=target_world_name,
            created_at=created_at,
        )
        _save_meta(target_world_id, final_meta)
    except Exception as exc:
        logger.exception(
            "World duplication failed from %s to %s",
            source_world_id,
            target_world_id,
        )
        _mark_duplicate_failure(target_world_id, run_id, str(exc))
    finally:
        _clear_run(target_world_id, run_id=run_id)


def start_world_duplication(source_world_id: str) -> dict:
    source_meta = recover_stale_ingestion(source_world_id)
    if source_meta.get("is_temporary_duplicate") or has_active_duplication_run(source_world_id):
        raise RuntimeError("Wait for the duplicate-in-progress world to finish before duplicating it again.")
    if has_active_ingestion_run(source_world_id) or source_meta.get("ingestion_status") == "in_progress":
        raise RuntimeError("Wait for the source world's active ingest work to finish before duplicating it.")
    if has_active_duplication_for_source(source_world_id):
        raise RuntimeError("A duplicate for this world is already in progress.")

    source_root = world_dir(source_world_id)
    if not source_root.exists():
        raise FileNotFoundError("World not found")

    target_world_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    target_world_name = build_duplicate_world_name(str(source_meta.get("world_name") or "World"))
    target_root = world_dir(target_world_id)
    target_root.mkdir(parents=True, exist_ok=True)
    created_at = _now_iso()

    initial_meta = _build_initial_duplicate_meta(
        source_meta,
        world_id=target_world_id,
        world_name=target_world_name,
        run_id=run_id,
        created_at=created_at,
    )
    _save_meta(target_world_id, initial_meta)
    _register_run(target_world_id, source_world_id=source_world_id, run_id=run_id)

    worker = threading.Thread(
        target=_run_world_duplication,
        kwargs={
            "source_world_id": source_world_id,
            "target_world_id": target_world_id,
            "run_id": run_id,
            "source_meta_snapshot": copy.deepcopy(source_meta),
            "target_world_name": target_world_name,
            "created_at": created_at,
        },
        daemon=True,
        name=f"duplicate-world-{target_world_id}",
    )
    worker.start()

    return initial_meta
