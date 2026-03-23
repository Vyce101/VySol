"""Worlds & Sources CRUD — /worlds endpoints."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from core.config import (
    SAVED_WORLDS_DIR,
    get_world_ingest_settings,
    load_settings,
    world_dir,
    world_meta_path,
    world_graph_path,
    world_sources_dir,
)
from core.ingestion_engine import audit_ingestion_integrity
from core.ingestion_engine import (
    get_checkpoint_info,
    get_reembed_eligibility,
    get_safety_review_summary,
    has_active_ingestion_run,
    recover_stale_ingestion,
)
from core.world_duplication import (
    has_active_duplication_run,
    is_world_involved_in_active_duplication,
    start_world_duplication,
)

router = APIRouter()


class CreateWorldRequest(BaseModel):
    world_name: str


class UpdateWorldRequest(BaseModel):
    world_name: str


class UpdateSourceRequest(BaseModel):
    display_name: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="World not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_meta(world_id: str, meta: dict) -> None:
    path = world_meta_path(world_id)
    tmp = path.with_suffix(".tmp.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(str(tmp), str(path))


def _with_effective_ingest_settings(meta: dict) -> dict:
    meta["ingest_settings"] = get_world_ingest_settings(meta=meta)
    meta["embedding_model"] = meta["ingest_settings"]["embedding_model"]
    return meta


def _is_duplicate_in_progress(meta: dict) -> bool:
    return bool(meta.get("is_temporary_duplicate")) and str(meta.get("duplication_status") or "") == "in_progress"


def _collect_worlds() -> list[dict]:
    worlds = []
    if SAVED_WORLDS_DIR.exists():
        for d in SAVED_WORLDS_DIR.iterdir():
            meta_path = d / "meta.json"
            if d.is_dir() and meta_path.exists():
                try:
                    world_id = d.name
                    meta = recover_stale_ingestion(world_id)
                    meta["active_ingestion_run"] = has_active_ingestion_run(world_id)
                    meta["active_duplication_run"] = has_active_duplication_run(world_id)
                    worlds.append(_with_effective_ingest_settings(meta))
                except (json.JSONDecodeError, OSError):
                    continue
    locked_source_ids = {
        str(meta.get("duplication_source_world_id") or "")
        for meta in worlds
        if _is_duplicate_in_progress(meta)
    }
    for meta in worlds:
        world_id = str(meta.get("world_id") or "")
        meta["duplication_locked"] = world_id in locked_source_ids
    worlds.sort(key=lambda w: w.get("created_at", ""), reverse=True)
    return worlds


# ── World CRUD ─────────────────────────────────────────────────────────

@router.get("")
async def list_worlds():
    """List all worlds sorted by created_at desc."""
    return _collect_worlds()


@router.get("/activities")
async def list_world_activities():
    activities: list[dict] = []
    for meta in _collect_worlds():
        world_id = str(meta.get("world_id") or "")
        if meta.get("active_ingestion_run") or meta.get("ingestion_status") == "in_progress":
            activities.append({
                "activity_id": f"ingestion:{world_id}",
                "kind": "ingestion",
                "world_id": world_id,
                "world_name": meta.get("world_name"),
                "link_href": f"/worlds/{world_id}/ingest",
                "ingestion_status": meta.get("ingestion_status"),
                "checkpoint": get_checkpoint_info(world_id),
            })

        if _is_duplicate_in_progress(meta):
            activities.append({
                "activity_id": f"duplication:{world_id}",
                "kind": "duplication",
                "world_id": world_id,
                "world_name": meta.get("world_name"),
                "source_world_id": meta.get("duplication_source_world_id"),
                "source_world_name": meta.get("duplication_source_world_name"),
                "duplication_status": meta.get("duplication_status"),
                "phase": "copying",
                "progress_percent": int(meta.get("duplication_progress_percent") or 0),
                "completed_work_units": int(meta.get("duplication_completed_work_units") or 0),
                "total_work_units": int(meta.get("duplication_total_work_units") or 0),
            })
    return activities


@router.post("")
async def create_world(req: CreateWorldRequest):
    """Create a new world."""
    wid = str(uuid.uuid4())
    wdir = world_dir(wid)
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "sources").mkdir(exist_ok=True)
    settings = load_settings()

    meta = {
        "world_id": wid,
        "world_name": req.world_name,
        "created_at": _now_iso(),
        "ingestion_status": "pending",
        "total_chunks": 0,
        "total_nodes": 0,
        "total_edges": 0,
        "embedding_model": settings.get("embedding_model", "gemini-embedding-2-preview"),
        "ingest_settings": {
            "locked_at": None,
            "last_ingest_settings_at": None,
        },
        "sources": [],
    }
    _save_meta(wid, meta)

    # Write empty GEXF
    import networkx as nx
    g = nx.MultiDiGraph()
    nx.write_gexf(g, str(world_graph_path(wid)))

    return meta


@router.post("/{world_id}/duplicate")
async def duplicate_world(world_id: str):
    try:
        meta = start_world_duplication(world_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="World not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "accepted", "world": _with_effective_ingest_settings(meta)}


@router.get("/{world_id}")
async def get_world(world_id: str):
    meta = recover_stale_ingestion(world_id)
    if meta.get("is_temporary_duplicate"):
        meta["active_duplication_run"] = has_active_duplication_run(world_id)
        meta["active_ingestion_run"] = False
        return _with_effective_ingest_settings(meta)
    audit = None
    try:
        allow_synthesis = meta.get("ingestion_status") != "in_progress"
        audit = audit_ingestion_integrity(world_id, synthesize_failures=allow_synthesis, persist=True)
        meta = _load_meta(world_id)
        meta["ingestion_audit"] = audit
    except Exception:
        # Never block world retrieval on audit issues.
        pass
    try:
        meta["reembed_eligibility"] = get_reembed_eligibility(world_id, meta=meta, audit_summary=audit)
    except Exception:
        meta["reembed_eligibility"] = {
            "can_reembed_all": False,
            "reason_code": "eligibility_unavailable",
            "message": "Could not verify whether Re-embed All is safe for this world.",
            "ignored_pending_sources_count": 0,
            "requires_full_rebuild": False,
            "eligible_source_ids": [],
            "eligible_sources_count": 0,
        }
    meta["safety_review_summary"] = get_safety_review_summary(world_id)
    meta["active_ingestion_run"] = has_active_ingestion_run(world_id)
    return _with_effective_ingest_settings(meta)


@router.patch("/{world_id}")
async def update_world(world_id: str, req: UpdateWorldRequest):
    meta = _load_meta(world_id)
    meta["world_name"] = req.world_name
    _save_meta(world_id, meta)
    return _with_effective_ingest_settings(meta)


@router.delete("/{world_id}")
async def delete_world(world_id: str):
    meta = recover_stale_ingestion(world_id)
    if has_active_ingestion_run(world_id) and meta.get("ingestion_status") == "in_progress":
        raise HTTPException(status_code=409, detail="Abort ingestion before deleting this world.")
    if is_world_involved_in_active_duplication(world_id):
        raise HTTPException(status_code=409, detail="Wait for the active duplicate job to finish before deleting this world.")
    wdir = world_dir(world_id)
    shutil.rmtree(str(wdir), ignore_errors=True)
    return {"ok": True}


# ── Source CRUD ─────────────────────────────────────────────────────────

@router.get("/{world_id}/sources")
async def list_sources(world_id: str):
    meta = recover_stale_ingestion(world_id)
    try:
        allow_synthesis = meta.get("ingestion_status") != "in_progress"
        audit_ingestion_integrity(world_id, synthesize_failures=allow_synthesis, persist=True)
        meta = _load_meta(world_id)
    except Exception:
        pass
    return meta.get("sources", [])


@router.post("/{world_id}/sources")
async def upload_source(world_id: str, file: UploadFile = File(...)):
    """Upload a .txt source file."""
    if not file.filename or not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Only .txt files are supported.")

    meta = _load_meta(world_id)
    sources_dir = world_sources_dir(world_id)

    # Determine vault filename (handle duplicates)
    base_name = file.filename
    vault_name = base_name
    counter = 2
    while (sources_dir / vault_name).exists():
        name, ext = os.path.splitext(base_name)
        vault_name = f"{name}_v{counter}{ext}"
        counter += 1

    # Save to vault
    vault_path = sources_dir / vault_name
    content = await file.read()
    with open(vault_path, "wb") as f:
        f.write(content)

    # Create source entry
    source_id = str(uuid.uuid4())
    book_number = len(meta.get("sources", [])) + 1

    source = {
        "source_id": source_id,
        "original_filename": file.filename,
        "vault_filename": vault_name,
        "book_number": book_number,
        "display_name": f"Book {book_number}",
        "status": "pending",
        "chunk_count": 0,
        "ingested_at": None,
    }
    meta.setdefault("sources", []).append(source)
    _save_meta(world_id, meta)

    return source


@router.patch("/{world_id}/sources/{source_id}")
async def update_source(world_id: str, source_id: str, req: UpdateSourceRequest):
    meta = _load_meta(world_id)
    for s in meta.get("sources", []):
        if s["source_id"] == source_id:
            s["display_name"] = req.display_name
            _save_meta(world_id, meta)
            return s
    raise HTTPException(status_code=404, detail="Source not found")


@router.delete("/{world_id}/sources/{source_id}")
async def delete_source(world_id: str, source_id: str):
    meta = _load_meta(world_id)
    for i, s in enumerate(meta.get("sources", [])):
        if s["source_id"] == source_id:
            if s["status"] != "pending":
                raise HTTPException(status_code=409, detail="Cannot delete a source that has been ingested.")
            # Delete vault file
            vault_path = world_sources_dir(world_id) / s["vault_filename"]
            if vault_path.exists():
                os.remove(str(vault_path))
            meta["sources"].pop(i)
            _save_meta(world_id, meta)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Source not found")
