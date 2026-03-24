"""Ingestion endpoints: start, retry, abort, status (SSE), checkpoint."""

from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal

from core.config import (
    PROVIDER_REGISTRY,
    SLOT_EMBEDDING,
    get_world_ingest_prompt_states,
    get_world_ingest_settings,
    resolve_slot_provider,
    set_world_ingest_prompt_overrides,
    set_world_ingest_settings,
)
from core.config import world_meta_path
from core.ingestion_engine import (
    audit_ingestion_integrity,
    abort_ingestion,
    drain_sse_events,
    get_actionable_resume_sources,
    get_reembed_eligibility,
    get_checkpoint_info,
    get_safety_review_rebuild_guard,
    get_safety_review_summary,
    get_unresolved_safety_review_chunk_ids,
    has_active_ingestion_run,
    list_safety_reviews,
    manual_rescue_safety_reviews,
    recover_stale_ingestion,
    reset_safety_review,
    start_ingestion,
    test_safety_review,
    update_safety_review_draft,
)

router = APIRouter()


class IngestStartRequest(BaseModel):
    resume: bool = True
    operation: Literal["default", "rechunk_reingest", "reembed_all"] = "default"
    ingest_settings: dict | None = None
    prompt_overrides: dict | None = None
    use_active_chunk_overrides: bool = False


class IngestRetryRequest(BaseModel):
    stage: Literal["extraction", "embedding", "all"] = "all"
    source_id: str | None = None


class SafetyReviewPatchRequest(BaseModel):
    draft_raw_text: str


class ManualSafetyReviewRescueRequest(BaseModel):
    source_id: str
    chunk_indices: list[int]


def _load_meta(world_id: str) -> dict:
    path = world_meta_path(world_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="World not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _merge_requested_ingest_settings(current: dict, override: dict | None) -> dict:
    merged = dict(current)
    if not isinstance(override, dict):
        return merged
    for key in ("chunk_size_chars", "chunk_overlap_chars", "embedding_provider", "embedding_openai_compatible_provider", "embedding_model", "glean_amount"):
        value = override.get(key)
        if value in (None, ""):
            continue
        if key in {"chunk_size_chars", "chunk_overlap_chars", "glean_amount"}:
            try:
                merged[key] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            merged[key] = str(value)
    return merged


def _ensure_supported_embedding_backend(ingest_settings: dict) -> None:
    provider = resolve_slot_provider(ingest_settings, SLOT_EMBEDDING)
    provider_info = PROVIDER_REGISTRY.get(provider, {})
    if not provider_info.get("supports_embedding", False):
        raise HTTPException(
            status_code=400,
            detail=f"{provider_info.get('display_name', provider)} is not available for embeddings yet. Choose a supported embedding provider first.",
        )


def _same_chunk_map(left: dict, right: dict) -> bool:
    try:
        return (
            int(left.get("chunk_size_chars", -1)) == int(right.get("chunk_size_chars", -2))
            and int(left.get("chunk_overlap_chars", -1)) == int(right.get("chunk_overlap_chars", -2))
        )
    except (TypeError, ValueError):
        return False


@router.get("/{world_id}/ingest/config")
async def ingest_config(world_id: str):
    meta = recover_stale_ingestion(world_id)
    summary = get_safety_review_summary(world_id)
    return {
        "ingest_settings": get_world_ingest_settings(meta=meta),
        "prompts": get_world_ingest_prompt_states(meta=meta),
        "has_active_chunk_overrides": int(summary.get("active_override_reviews", 0) or 0) > 0,
        "active_chunk_override_count": int(summary.get("active_override_reviews", 0) or 0),
        "safety_review_summary": summary,
    }


@router.post("/{world_id}/ingest/start")
async def ingest_start(world_id: str, req: IngestStartRequest, bg: BackgroundTasks):
    meta = recover_stale_ingestion(world_id)
    operation = req.operation
    current_world_settings = get_world_ingest_settings(meta=meta)
    requested_world_settings = _merge_requested_ingest_settings(current_world_settings, req.ingest_settings)
    _ensure_supported_embedding_backend(requested_world_settings)
    has_active_chunk_overrides = int(get_safety_review_summary(world_id).get("active_override_reviews", 0) or 0) > 0
    allow_active_chunk_overrides = bool(req.use_active_chunk_overrides) and has_active_chunk_overrides

    if has_active_ingestion_run(world_id) and meta.get("ingestion_status") == "in_progress":
        raise HTTPException(status_code=409, detail="Ingestion already in progress.")

    if operation == "rechunk_reingest" or (operation == "default" and not req.resume):
        if allow_active_chunk_overrides and not _same_chunk_map(current_world_settings, requested_world_settings):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Active repaired chunks can only be reused when chunk size and overlap stay the same. "
                    "Turn off repaired chunk reuse or keep the current chunk settings."
                ),
            )
        review_guard = get_safety_review_rebuild_guard(world_id, allow_active_overrides=allow_active_chunk_overrides)
        if not review_guard.get("can_rebuild"):
            raise HTTPException(
                status_code=400,
                detail=str(review_guard.get("message") or "Safety review work is still pending for this world."),
            )
        if req.ingest_settings:
            set_world_ingest_settings(world_id, req.ingest_settings, lock=False, touch=False)
        if req.prompt_overrides is not None:
            set_world_ingest_prompt_overrides(world_id, req.prompt_overrides)

    if operation == "reembed_all":
        audit = audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
        meta = _load_meta(world_id)
        if not meta.get("sources"):
            raise HTTPException(status_code=400, detail="No sources available to re-embed.")

        locked_settings = get_world_ingest_settings(meta=meta)
        if req.ingest_settings:
            for key in ("chunk_size_chars", "chunk_overlap_chars", "embedding_provider", "embedding_openai_compatible_provider"):
                value = req.ingest_settings.get(key)
                if value in (None, ""):
                    continue
                try:
                    if key in {"chunk_size_chars", "chunk_overlap_chars"}:
                        if int(value) != int(locked_settings.get(key)):
                            raise HTTPException(
                                status_code=400,
                                detail="Re-embed All uses this world's locked chunk settings. Run Re-ingest to change chunk settings.",
                            )
                    elif str(value) != str(locked_settings.get(key)):
                        raise HTTPException(
                            status_code=400,
                            detail="Re-embed All uses this world's locked embedding provider. Run Re-ingest to change embedding backends.",
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
        bg.add_task(start_ingestion, world_id, False, "all", None, False, operation, req.ingest_settings, False)
        return {"status": "accepted", "world_id": world_id, "operation": operation}

    # Check for pending sources (or start-over resets them)
    if req.resume and operation == "default":
        audit_ingestion_integrity(world_id, synthesize_failures=True, persist=True)
        meta = _load_meta(world_id)
        actionable_sources = get_actionable_resume_sources(world_id, sources=meta.get("sources", []))
        if not actionable_sources:
            summary = get_safety_review_summary(world_id)
            if int(summary.get("unresolved_reviews") or 0) > 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Resume is unavailable because the remaining failed chunks are already in the Safety Queue. "
                        "Continue testing or fixing them there instead."
                    ),
                )
            cp = get_checkpoint_info(world_id)
            if not cp.get("can_resume"):
                raise HTTPException(status_code=400, detail="No pending sources to ingest and no resumable checkpoint.")

    # Launch background task
    bg.add_task(
        start_ingestion,
        world_id,
        req.resume,
        "all",
        None,
        False,
        operation,
        req.ingest_settings,
        allow_active_chunk_overrides,
    )
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

    unresolved_review_chunk_ids = get_unresolved_safety_review_chunk_ids(world_id)
    retryable_failures: list[dict] = []
    skipped_safety_review_failures: list[dict] = []
    for source in sources:
        for failure in source.get("stage_failures") or []:
            if not isinstance(failure, dict):
                continue
            failure_stage = str(failure.get("stage", "")).lower()
            if stage == "all":
                if failure_stage not in {"extraction", "embedding"}:
                    continue
            elif failure_stage != stage:
                continue
            if str(failure.get("chunk_id") or "") in unresolved_review_chunk_ids:
                skipped_safety_review_failures.append(failure)
                continue
            retryable_failures.append(failure)

    if not retryable_failures and skipped_safety_review_failures:
        raise HTTPException(
            status_code=400,
            detail="These failures are already in the Safety Queue. Edit and test those chunks there instead of retrying them from source.",
        )
    if not retryable_failures:
        raise HTTPException(status_code=400, detail="No retryable failures for the requested stage.")

    bg.add_task(start_ingestion, world_id, True, stage, source_id, True)
    skipped_count = len(skipped_safety_review_failures)
    retry_notice = None
    if skipped_count > 0:
        retry_notice = (
            f"Skipped {skipped_count} failure(s) that are already in the Safety Queue. "
            "Edit and test those chunks from the review panel instead."
        )
    return {
        "status": "accepted",
        "world_id": world_id,
        "retry_stage": stage,
        "source_id": source_id,
        "skipped_safety_review_chunks": skipped_count,
        "retry_notice": retry_notice,
    }


@router.post("/{world_id}/ingest/abort")
async def ingest_abort(world_id: str):
    _load_meta(world_id)
    abort_ingestion(world_id)
    return {"ok": True}


@router.get("/{world_id}/ingest/status")
async def ingest_status(world_id: str):
    """SSE stream of ingestion events."""

    async def event_generator():
        while True:
            meta = _load_meta(world_id)
            if meta.get("ingestion_status") == "in_progress":
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


@router.get("/{world_id}/ingest/safety-reviews")
async def ingest_safety_reviews(world_id: str):
    _load_meta(world_id)
    return {
        "reviews": list_safety_reviews(world_id),
        "summary": get_safety_review_summary(world_id),
    }


@router.patch("/{world_id}/ingest/safety-reviews/{review_id}")
async def ingest_safety_review_update(world_id: str, review_id: str, req: SafetyReviewPatchRequest):
    _load_meta(world_id)
    try:
        review = await update_safety_review_draft(world_id, review_id, req.draft_raw_text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status_code = 409 if "active ingest run" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return {
        "review": review,
        "summary": get_safety_review_summary(world_id),
    }


@router.post("/{world_id}/ingest/safety-reviews/manual-rescue")
async def ingest_safety_review_manual_rescue(world_id: str, req: ManualSafetyReviewRescueRequest):
    _load_meta(world_id)
    try:
        return await manual_rescue_safety_reviews(
            world_id,
            source_id=req.source_id,
            chunk_indices=req.chunk_indices,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status_code = 409 if "active ingest run" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{world_id}/ingest/safety-reviews/{review_id}/test")
async def ingest_safety_review_test(world_id: str, review_id: str):
    _load_meta(world_id)
    try:
        return await test_safety_review(world_id, review_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status_code = 409 if "active ingest run" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{world_id}/ingest/safety-reviews/{review_id}/reset")
async def ingest_safety_review_reset(world_id: str, review_id: str):
    _load_meta(world_id)
    try:
        return await reset_safety_review(world_id, review_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status_code = 409 if "active ingest run" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/{world_id}/ingest/safety-reviews/{review_id}/discard")
async def ingest_safety_review_discard(world_id: str, review_id: str):
    return await ingest_safety_review_reset(world_id, review_id)
