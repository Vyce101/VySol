# Draft World Leave Safety

Draft World Leave Safety is VySol's backend contract for deciding whether leaving an uncommitted draft world is safe, should warn first, or should discard temporary draft setup after the user confirms leaving.

This page is for developers, power users, and AI coding agents that need to understand draft leave behavior before changing World Detail navigation guards, draft cleanup, ingestion phase tracking, or temporary source staging.

## Why It Exists

Creating a world has a risky gap before source text and chunks are committed to durable storage. During that gap, leaving World Detail can discard the draft name state, customization dirty state, staged source entries, and pre-commit ingestion progress. After the text/chunk commit has succeeded, leaving should not interrupt backend work just because later processing may still be running.

This contract gives UI code a simple backend-owned decision point. The UI can ask whether leaving should warn, and if the user confirms a dangerous leave, the backend can discard only the temporary draft state it owns.

## Ownership Boundary

Draft World Leave Safety owns:

- Reporting whether leaving the draft should warn before navigation.
- Reporting whether confirmed leave should discard the draft and matching temporary source staging context.
- Treating any unsaved customization dirty state as a warning condition.
- Treating ingestion phases before durable text commit as warning conditions.
- Treating `text_committed` as safe to leave when there are no unsaved customization changes.
- Discarding only in-memory draft and matching temporary staging state after confirmed dangerous leave.

Draft World Leave Safety does not own:

- Browser confirmation UI, modals, route interception, tab switching, or visible navigation behavior.
- Draft name, description, or customization field storage beyond the temporary dirty-state flag.
- Source parsing, splitting, hashing, copying, committed source storage, chunk storage, or world visibility.
- Uploaded global asset deletion.
- Committed world deletion, committed source deletion, world folder cleanup, or `world.sqlite` cleanup.
- App-close cancellation, which has its own shutdown-specific cancellation boundary.

## Normal Flow

World Detail navigation guard code asks the backend for the draft's leave state. The backend reads the draft world, its unsaved customization flag, and the current ingestion attempt state. If the draft has unsaved customization changes, the response says leaving should warn regardless of ingestion phase.

If there are no unsaved customization changes, the ingestion phase decides the storage safety boundary. Before `text_committed`, leaving is dangerous because the draft and staged work are still temporary. At `text_committed`, source text and chunks are considered durably stored, so leaving is safe and the backend must not discard the draft through the leave endpoint.

If Draft Abandon Confirmation UI shows a warning and the user confirms leaving while the leave state is dangerous, the confirmed-leave endpoint discards the draft world and matching temporary staging context. If the leave state is safe, confirmed leave returns without discarding that state.

## Inputs

Draft World Leave Safety receives a draft ID from route or service code. It reads in-memory draft-world state, the draft's unsaved customization dirty flag, matching temporary staging state for discard, and the current in-memory ingestion attempt state.

It does not receive raw source paths, source text, parsed text, chunk text, uploaded asset files, committed world records, or browser navigation events directly.

## Outputs

The leave-state response exposes:

- Whether future UI should warn before leaving.
- Whether confirmed leave should discard temporary draft state.
- Whether leaving is safe.
- Whether the draft has unsaved customization changes.
- The current ingestion attempt status.
- The current ingestion attempt phase.

The confirmed-leave response includes the same leave decision plus whether the backend actually discarded the draft.

## Failure Behavior

Missing draft IDs return `404`. Missing temporary staging state does not block draft discard because staging state may already have been cleared or may not exist for a partially created draft.

Unexpected discard-state failures must be logged at `ERROR` if backend state is involved. Normal dangerous-leave discard does not require app logging.

## System Interactions

Draft World Leave Safety interacts with:

- Draft World Detail API, which exposes the HTTP routes and the temporary unsaved customization flag.
- Draft Abandon Confirmation UI, which presents the warning and calls confirmed-leave only after user confirmation.
- Ingestion Attempt State, which provides the current lifecycle status and phase.
- Temporary Source Staging State, which holds staged source entries that are discarded only after confirmed dangerous leave.
- New World Batch Commit, which is the boundary that later ingestion code should mark as `text_committed` after text sources and chunks are durably stored.
- World Detail Page Shell, which hosts the parent navigation that can trigger the frontend guard.

It must stay separate from asset storage, committed world index storage, committed source storage, chunk storage, graph extraction, retrieval, chat behavior, and browser prompt rendering.

## Current Edge Cases

Internal edge cases:

- Drafts default to no unsaved customization changes.
- Unsaved customization changes force a warning even after text has committed.
- `not_started`, `preflight`, `parsing`, `splitting`, and `atomic_text_commit` are dangerous phases.
- `text_committed` is safe only when the draft has no unsaved customization changes.
- Confirmed dangerous leave discards the draft and matching staging context.
- Confirmed safe leave leaves draft and staging state intact.
- Missing draft IDs fail clearly instead of silently creating or discarding state.

Cross-system edge cases:

- Switching between Customize and Ingestion tabs must not call leave-state or confirmed-leave behavior.
- Browser refresh and tab close must not call leave-state or confirmed-leave behavior.
- Confirmed draft discard must not delete uploaded global assets.
- Confirmed draft discard must not delete committed worlds, committed source files, world folders, world databases, or app index rows.
- Leave safety depends on future ingestion orchestration setting `text_committed` immediately after the atomic SQLite text/chunk commit succeeds.
- Paused or stopping attempts are safe only if their phase has already reached `text_committed` and no customization changes are dirty.

## Invariants

- The backend must be the source of truth for draft leave safety.
- The durable text commit boundary is represented by the `text_committed` ingestion phase.
- Unsaved customization changes must override phase safety and require a warning.
- Confirmed dangerous leave must discard only temporary draft and staging state.
- Safe-zone leave must not discard draft or staging state.
- Uploaded assets and committed world data must never be deleted by draft leave handling.
- Leave safety state must remain temporary and must not require app or world database migrations.

## Implementation Landmarks

- `app/draft_worlds/routes.py` owns leave-state and confirmed-leave response shaping.
- `app/draft_worlds/registry.py` owns the in-memory draft dirty-state flag.
- `app/ingestion/attempt_state.py` owns ingestion phase state.
- `frontend/src/draft-world-api.ts` exposes API helpers for navigation guard UI.
- `frontend/src/draft-abandon-navigation.ts` owns the frontend hook that consumes leave-state and confirmed-leave.
- `tests/test_draft_world_routes.py` covers the leave safety route contract.

## What AI/Coders Must Check Before Changing This System

Before editing Draft World Leave Safety, check:

- Whether the change belongs in leave safety rather than browser prompt UI, tab rendering, source staging, ingestion orchestration, or commit storage.
- Whether `text_committed` is still the only phase that makes leave safe when customization is clean.
- Whether dirty customization state still forces warning.
- Whether confirmed dangerous leave still avoids deleting uploaded assets and committed world data.
- Whether tab switching remains internal to World Detail and does not trigger leave/discard behavior.
- Whether response data stays free of raw paths, source text, chunk text, secrets, and user-owned file contents.
