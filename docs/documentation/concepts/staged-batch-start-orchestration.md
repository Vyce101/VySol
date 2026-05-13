# Staged Batch Start Orchestration

Staged Batch Start Orchestration is VySol's backend ingestion boundary for turning a valid temporary staging context into one running ingestion attempt. It checks the staged source list before attempt creation, blocks duplicate concurrent starts, and keeps the staged batch tied to the active attempt while it is running.

This page is for developers, power users, and AI coding agents that need to understand how Start behavior coordinates source staging and attempt state before changing ingestion orchestration, source staging, future route handlers, one-button UI behavior, or logging.

## Why It Exists

VySol needs Start to be stricter than a raw state transition. A staging context can contain unsupported source types that should remain visible to the user, but those invalid entries must block ingestion before parsers, splitters, hashing, temporary workspaces, or commit systems begin.

The orchestration layer keeps that policy out of lower-level attempt state. Attempt state owns lifecycle transitions, while start orchestration owns the staged-batch checks and the active link between a running attempt and the staging context that produced it.

## Ownership Boundary

Staged Batch Start Orchestration owns:

- Reading the requested temporary staging context.
- Requiring explicit attempt target metadata that identifies whether the attempt is for a new-world draft or an existing committed world.
- Rejecting missing, empty, or invalid staged batches before a new attempt starts.
- Rejecting blank or invalid attempt target metadata before a new attempt starts.
- Returning safe invalid-source summaries that future UI or route layers can surface.
- Blocking a second Start request while an attempt is already `RUNNING`.
- Calling Ingestion Attempt State only after the staged batch is valid.
- Recording the active attempt's staging context ID, staged entry ID snapshot, attempt kind, and target ID.
- Logging successful attempt start at `INFO`.
- Logging duplicate running starts at `WARNING`.
- Logging unexpected start orchestration failures at `ERROR`.

Staged Batch Start Orchestration does not own:

- Rendering UI controls, source list warnings, progress, or toasts.
- Creating, removing, or reordering staged source entries.
- Checking file access, parsing source files, hashing source bytes, duplicate checking, splitting chunks, assigning book numbers, or committing sources.
- Completing, cancelling, pausing, or resuming attempt work beyond respecting the current running state.
- Persisting attempt state, staging state, active-batch links, source metadata, chunks, or failure records.

## Normal Flow

A caller passes a staging context ID and attempt target metadata to the start orchestration API. The target metadata states whether the attempt belongs to a new-world draft or an existing committed world, and carries the draft ID or committed world ID that app-close cancellation must use later. The orchestrator first checks the current attempt state. If an attempt is already running, the request is rejected as a duplicate start and the existing attempt remains unchanged.

If no attempt is running, the orchestrator validates the attempt target metadata and reads the staging context. Blank target IDs, unsupported attempt kinds, a missing context, an empty staging list, or any staged entry with `is_valid == False` block start before a temporary workspace or attempt ID is created. Invalid entries are summarized by staging entry ID, source type, and staging error message so a future UI can notify the user without exposing local paths.

When every staged entry and the target metadata are valid, the orchestrator starts a fresh ingestion attempt through Ingestion Attempt State. That creates the attempt ID, creates the temporary workspace, and moves the state to `RUNNING`. The orchestrator then records the active staged-batch link with the attempt state, staging context ID, staged entry ID snapshot, attempt kind, and target ID.

While that active link points to the current running attempt, Temporary Source Staging State blocks adding more sources to the same staging context. This keeps the batch that started the attempt stable until the running attempt is no longer current. Once cooperative cancellation has finished and the attempt is `PAUSED`, the active running link clears and staged sources can be edited again while the paused attempt keeps its Deep Pause workspace.

## Inputs

The start orchestration API receives a staging context ID and attempt target metadata. It reads in-memory temporary staging state and current in-memory attempt state.

It does not receive raw source text, parser output, chunk rows, source hashes, database connections, provider responses, saved manifests, or UI request objects.

## Outputs

On success, the system returns an active staged-batch attempt object containing:

- The running ingestion attempt state.
- The staging context ID used to start the attempt.
- The staged entry IDs that were part of the batch at start time.
- The attempt kind and target ID needed by app-close cancellation.

On validation failure, the system raises a domain validation error that can carry safe invalid-entry summaries. On duplicate running starts, it raises a duplicate-start error. It does not create committed source rows, chunks, source file copies, durable attempt records, HTTP responses, or UI state directly.

## Saved State And Resume Behavior

The active staged-batch link is in memory only. It is scoped to the currently running attempt and is cleared when the linked attempt is no longer the current running attempt.

This keeps source-add blocking from getting stuck after completion, cancellation to idle, or a later attempt replacing the original attempt. Durable resume behavior and crash recovery remain outside this start boundary.

## Failure Behavior

Expected start blockers are logged at `WARNING` and leave attempt state unchanged. These include duplicate running starts, invalid attempt target metadata, missing staging contexts, empty staging lists, and invalid staged sources.

Unexpected orchestration failures are logged at `ERROR` with safe metadata and raised as start orchestration errors. Logs must not include raw source paths, filenames, source text, parsed text, local machine details, or temporary workspace paths.

## System Interactions

Staged Batch Start Orchestration interacts with:

- Temporary Source Staging State, which supplies staged entries and blocks adding more sources to the linked running context.
- Source Type Selection Filter, which sets each staged entry's `is_valid` value and error message before Start is requested.
- Ingestion Attempt State, which owns attempt IDs, lifecycle state, and the `RUNNING` transition.
- Temporary Ingestion Workspace, which is created through attempt state only after staged batch validation succeeds.
- App-close cancellation, which uses the active attempt metadata to discard the right draft or staged additions without assuming the staging context ID matches the target ID.
- Future route handlers or UI state, which can surface the domain errors and active attempt state without owning the orchestration policy.
- The central logger, which records path-safe start summaries and blockers.

It must stay separate from staged file access validation, source hashing, duplicate preflight, parser internals, split output preparation, committed source storage, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Missing staging contexts block start before an attempt ID or workspace is created.
- Empty staging lists block start before an attempt ID or workspace is created.
- Blank target IDs or unsupported attempt kinds block start before an attempt ID or workspace is created.
- Any invalid staged entry blocks the whole batch.
- Invalid-source summaries expose staging entry IDs, source types, and error messages only.
- Duplicate starts while `RUNNING` leave the original attempt and workspace unchanged.
- Successful starts preserve the staged entry order by snapshotting entry IDs in current staging order.
- Successful starts preserve the explicit attempt kind and target ID separately from the staging context ID.
- Unexpected start failures are wrapped in an orchestration error after safe `ERROR` logging.

Cross-system edge cases:

- Temporary Source Staging State must reject adding more sources only for the staging context tied to the current running attempt.
- App-close cancellation must use the recorded attempt kind and target ID instead of assuming the staging context ID is the draft ID or committed world ID.
- The active staged-batch link must not keep a staging context locked after its attempt is no longer running, including after cancellation completion moves the attempt to `PAUSED`.
- Attempt state remains responsible for rejecting non-running lifecycle transitions outside this start flow.
- Future file access validation, hashing, parsing, splitting, and commit systems must run only after this start boundary succeeds.
- Start success must not imply that file paths still exist, file contents are parseable, hashes are unique, chunks can be generated, or commit work will succeed.
- Logs must remain safe even though staging entries contain local path references.

## Invariants

- Start must not create an attempt or temporary workspace for an invalid staged batch.
- Only one running staged-batch attempt may exist at a time.
- A running attempt must stay tied to the staging context, staged entry IDs, attempt kind, and target ID that started it.
- The attempt target ID must remain explicit metadata and must not be inferred from the staging context ID.
- A staging context tied to the current running attempt must not accept additional sources.
- A staging context must become editable again after the linked attempt is no longer `RUNNING`.
- Invalid staged entries must remain staging data; Start must not silently drop them.
- Start orchestration must not parse, hash, copy, split, commit, persist, assign book numbers, or create chunks.
- Active-batch state must remain in memory for this system.
- Logs must not include raw source paths, filenames, source text, parsed text, full workspace paths, or local machine details.
- No database migration is required for staged batch start orchestration.

## Implementation Landmarks

- `app/ingestion/attempt_start.py` owns staged-batch start orchestration, validation errors, duplicate-start blocking, active-batch recording, and start logging.
- `app/ingestion/active_staged_batch.py` owns the in-memory active-batch link and running-context lock checks.
- `app/ingestion/staging/source_staging_state.py` asks the active-batch registry before adding source file paths.
- `tests/test_ingestion_attempt_start.py` covers valid starts, validation blockers, duplicate starts, source-add blocking, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Staged Batch Start Orchestration, check:

- Whether the change belongs in start orchestration or in attempt state, source staging, file access validation, parser routing, splitting, commit logic, routes, or UI behavior.
- Whether invalid staged entries still block start without disappearing from staging.
- Whether attempt target metadata is still required, nonblank, and stored separately from the staging context ID.
- Whether duplicate starts still leave the original running attempt unchanged.
- Whether source-add blocking is scoped only to the staging context tied to the current running attempt.
- Whether active-batch state clears when the linked attempt is no longer running, including after cancellation completion reaches `PAUSED`.
- Whether Start still runs before file access, hashing, parsing, splitting, and commit work.
- Whether logs avoid raw source paths, filenames, source text, workspace paths, provider output, local machine details, and user data.
