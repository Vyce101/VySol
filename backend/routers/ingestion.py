"""Ingestion endpoints: start, retry, abort, status (SSE), checkpoint."""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal

from core.config import get_world_ingest_settings
from core.config import world_meta_path
from core.ingestion_engine import (
    audit_ingestion_integrity,
    abort_ingestion,
    drain_sse_events,
    get_reembed_eligibility,
    get_checkpoint_info,
    has_active_ingestion_run,
    recover_stale_ingestion,
    start_ingestion,
)

router = APIRouter()


class IngestStartRequest(BaseModel):
    resume: bool = True
    operation: Literal["default", "rechunk_reingest", "reembed_all"] = "default"
    ingest_settings: dict | None = None


class IngestRetryRequest(BaseModel):
    stage: Literal["extraction", "embedding", "all"] = "all"
    source_id: str | None = None


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="World not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/{world_id}/ingest/start")
async def ingest_start(world_id: str, req: IngestStartRequest, bg: BackgroundTasks):
    meta = recover_stale_ingestion(world_id)
    operation = req.operation

    if has_active_ingestion_run(world_id) and meta.get("ingestion_status") == "in_progress":
        raise HTTPException(status_code=409, detail="Ingestion already in progress.")

    if operation == "reembed_all":
        audit = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
        meta = _load_meta(world_id)
        if not meta.get("sources"):
            raise HTTPException(status_code=400, detail="No sources available to re-embed.")

        locked_settings = get_world_ingest_settings(meta=meta)
        if req.ingest_settings:
            for key in ("chunk_size_chars", "chunk_overlap_chars"):
                value = req.ingest_settings.get(key)
                if value in (None, ""):
                    continue
                try:
                    if int(value) != int(locked_settings.get(key)):
                        raise HTTPException(
                            status_code=400,
                            detail="Re-embed All uses this world's locked chunk settings. Use Re-ingest With Previous Settings or Rechunk And Re-ingest to change chunk settings.",
                        )
                except (TypeError, ValueError):
                    raise HTTPException(
                        status_code=400,
                        detail="Re-embed All received invalid chunk settings. Use the locked world settings or run a full re-ingest.",
                    )

        eligibility = get_reembed_eligibility(world_id, meta=meta, audit_summary=audit)
        if not eligibility.get("can_reembed_all"):
            raise HTTPException(
                status_code=400,
                detail=str(eligibility.get("message") or "Re-embed All is not currently safe for this world."),
            )
        bg.add_task(start_ingestion, world_id, False, "all", None, False, operation, req.ingest_settings)
        return {"status": "accepted", "world_id": world_id, "operation": operation}

    # Check for pending sources (or start-over resets them)
    if req.resume and operation == "default":
        audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
        meta = _load_meta(world_id)
        has_work = any(
            s["status"] in ("pending", "ingesting", "partial_failure")
            or s.get("failed_chunks")
            or s.get("stage_failures")
            for s in meta.get("sources", [])
        )
        if not has_work:
            # Check if there's a checkpoint to resume from
            cp = get_checkpoint_info(world_id)
            if not cp.get("can_resume"):
                raise HTTPException(status_code=400, detail="No pending sources to ingest and no resumable checkpoint.")

    # Launch background task
    bg.add_task(start_ingestion, world_id, req.resume, "all", None, False, operation, req.ingest_settings)
    return {"status": "accepted", "world_id": world_id, "operation": operation}


@router.post("/{world_id}/ingest/retry")
async def ingest_retry(world_id: str, req: IngestRetryRequest, bg: BackgroundTasks):
    meta = recover_stale_ingestion(world_id)
    if has_active_ingestion_run(world_id) and meta.get("ingestion_status") == "in_progress":
        raise HTTPException(status_code=409, detail="Ingestion already in progress.")
    audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
    meta = _load_meta(world_id)

    source_id = req.source_id
    stage = req.stage
    sources = list(meta.get("sources", []))
    if source_id:
        sources = [s for s in sources if s.get("source_id") == source_id]
        if not sources:
            raise HTTPException(status_code=404, detail="Source not found for this world.")

    has_retryable = any(
        any(
            (stage == "all" and str(f.get("stage", "")).lower() in {"extraction", "embedding"})
            or str(f.get("stage", "")).lower() == stage
            for f in (s.get("stage_failures") or [])
        )
        for s in sources
    )
    if not has_retryable:
        raise HTTPException(status_code=400, detail="No retryable failures for the requested stage.")

    bg.add_task(start_ingestion, world_id, True, stage, source_id, True)
    return {"status": "accepted", "world_id": world_id, "retry_stage": stage, "source_id": source_id}


@router.post("/{world_id}/ingest/abort")
async def ingest_abort(world_id: str):
    abort_ingestion(world_id)
    return {"ok": True}


@router.get("/{world_id}/ingest/status")
async def ingest_status(world_id: str):
    """SSE stream of ingestion events."""

    async def event_generator():
        while True:
            meta = _load_meta(world_id)
            if not has_active_ingestion_run(world_id) and meta.get("ingestion_status") == "in_progress":
                meta = recover_stale_ingestion(world_id)

            events = drain_sse_events(world_id)
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"

                # If terminal event, end the stream
                if event.get("event") in ("complete", "aborted"):
                    return

            # Check if ingestion still running
            status = meta.get("ingestion_status", "pending")
            active = has_active_ingestion_run(world_id)
            if status in ("complete", "partial_failure", "error", "aborted") and not active and not events:
                # Send final status and close
                checkpoint = get_checkpoint_info(world_id)
                payload = {
                    "event": "status",
                    "ingestion_status": status,
                    **checkpoint,
                }
                yield f"data: {json.dumps(payload)}\n\n"
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


@router.get("/{world_id}/ingest/checkpoint")
async def ingest_checkpoint(world_id: str):
    _load_meta(world_id)  # validate world exists
    return get_checkpoint_info(world_id)
