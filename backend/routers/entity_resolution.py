"""Entity-resolution endpoints for post-ingestion merge workflows."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.config import world_meta_path
from core.entity_resolution_engine import (
    abort_entity_resolution,
    begin_entity_resolution_run,
    drain_sse_events,
    fail_entity_resolution_startup,
    get_resolution_current,
    get_resolution_status,
    resolve_entity_resolution_mode,
    start_entity_resolution,
)
from core.ingestion_engine import (
    audit_ingestion_integrity,
    get_safety_review_summary,
    has_active_ingestion_run,
)

router = APIRouter()


class EntityResolutionStartRequest(BaseModel):
    top_k: int = 50
    review_mode: bool = False
    include_normalized_exact_pass: bool = True
    resolution_mode: Literal["exact_only", "exact_then_ai"] | None = None
    embedding_batch_size: int | None = None
    embedding_cooldown_seconds: float | None = None


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="World not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_entity_resolution_in_thread(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
    resolution_mode: str | None,
    embedding_batch_size: int | None,
    embedding_cooldown_seconds: float | None,
) -> None:
    asyncio.run(
        start_entity_resolution(
            world_id,
            top_k,
            review_mode,
            include_normalized_exact_pass,
            resolve_entity_resolution_mode(resolution_mode, include_normalized_exact_pass),
            embedding_batch_size,
            embedding_cooldown_seconds,
        )
    )


@router.post("/{world_id}/entity-resolution/start")
async def entity_resolution_start(world_id: str, req: EntityResolutionStartRequest):
    meta = _load_meta(world_id)
    if meta.get("ingestion_status") == "in_progress" or has_active_ingestion_run(world_id):
        raise HTTPException(status_code=409, detail="Finish ingestion before resolving entities.")
    current_status = get_resolution_status(world_id)
    if current_status.get("status") == "in_progress":
        raise HTTPException(status_code=409, detail="Entity resolution is already in progress.")

    audit = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
    meta = _load_meta(world_id)
    sources = list(meta.get("sources", []))
    if not sources:
        raise HTTPException(status_code=409, detail="Ingest at least one complete source before resolving entities.")
    if any(str(source.get("status") or "").lower() != "complete" for source in sources):
        raise HTTPException(status_code=409, detail="Finish ingestion and repair source failures before resolving entities.")
    if int(audit.get("world", {}).get("failed_records", 0) or 0) > 0 or str(meta.get("ingestion_status") or "").lower() == "partial_failure":
        raise HTTPException(status_code=409, detail="Resolve retryable ingest failures before running entity resolution.")
    safety_review_summary = get_safety_review_summary(world_id)
    if int(safety_review_summary.get("unresolved_reviews", 0) or 0) > 0:
        raise HTTPException(status_code=409, detail="Resolve or discard pending safety review items before running entity resolution.")

    resolution_mode = resolve_entity_resolution_mode(
        req.resolution_mode,
        req.include_normalized_exact_pass,
    )
    state = begin_entity_resolution_run(
        world_id,
        max(1, req.top_k),
        req.review_mode,
        req.include_normalized_exact_pass,
        resolution_mode,
        req.embedding_batch_size,
        req.embedding_cooldown_seconds,
    )
    thread = threading.Thread(
        target=_run_entity_resolution_in_thread,
        args=(
            world_id,
            max(1, req.top_k),
            req.review_mode,
            req.include_normalized_exact_pass,
            resolution_mode,
            req.embedding_batch_size,
            req.embedding_cooldown_seconds,
        ),
        daemon=True,
        name=f"entity-resolution-{world_id}",
    )
    try:
        thread.start()
    except Exception as exc:
        fail_entity_resolution_startup(
            world_id,
            "Entity resolution failed to start.",
            reason=str(exc),
        )
        raise HTTPException(status_code=500, detail="Unable to start entity resolution.") from exc
    return {"status": "accepted", "world_id": world_id, "state": state}


@router.post("/{world_id}/entity-resolution/abort")
async def entity_resolution_abort(world_id: str):
    _load_meta(world_id)
    abort_entity_resolution(world_id)
    return {"ok": True}


@router.get("/{world_id}/entity-resolution/status")
async def entity_resolution_status(world_id: str):
    _load_meta(world_id)
    return get_resolution_status(world_id)


@router.get("/{world_id}/entity-resolution/current")
async def entity_resolution_current(world_id: str):
    _load_meta(world_id)
    return get_resolution_current(world_id)


@router.get("/{world_id}/entity-resolution/events")
async def entity_resolution_events(world_id: str):
    _load_meta(world_id)

    async def event_generator():
        while True:
            events = drain_sse_events(world_id)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("event") in ("complete", "aborted", "error"):
                    return

            status = get_resolution_status(world_id)
            if status.get("status") in ("complete", "aborted", "error") and not events:
                yield f"data: {json.dumps({'event': status.get('status'), **status})}\n\n"
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
