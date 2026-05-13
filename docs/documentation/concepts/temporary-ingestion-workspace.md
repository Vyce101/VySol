# Temporary Ingestion Workspace

Temporary Ingestion Workspace is VySol's backend contract for giving one ingestion attempt an isolated scratch folder. It creates an app-owned temporary workspace for a Start attempt, keeps that same directory available when the same paused attempt resumes, and removes temporary workspaces after terminal attempt outcomes or app startup cleanup.

This page is for developers, power users, and AI coding agents that need to understand temporary ingestion workspace behavior before changing ingestion orchestration, attempt state transitions, source staging integration, future parser handoff, source commit behavior, or logging.

## Why It Exists

Ingestion will eventually do multi-step work before source data becomes committed world data. That work may need temporary files or intermediate data, but failed or paused attempts must not make scratch data look like committed world source storage.

The workspace contract keeps attempt-specific scratch storage tied to an attempt ID and outside committed world folders. It gives future ingestion orchestration a place for temporary work while preserving the boundary between temporary processing and durable world data.

## Ownership Boundary

Temporary Ingestion Workspace owns:

- Creating one temporary workspace for a fresh Start attempt.
- Associating the workspace with the attempt ID created by Ingestion Attempt State.
- Returning the current workspace only for the current attempt ID.
- Preserving the same workspace when a paused attempt resumes with the same attempt ID.
- Keeping workspace paths outside committed world source storage.
- Holding workspace state in process memory.
- Cleaning up managed temporary workspaces after successful completion, terminal cancellation, registry lifetime end, and startup discovery of abandoned workspaces.
- Abandoning workspace registry ownership during app-close cancellation so shutdown does not need to delete temporary workspace folders.
- Logging successful workspace creation at `INFO` without full local paths.
- Logging successful cleanup at `INFO`, missing already-cleaned workspaces at `DEBUG`, and cleanup failures at `ERROR` without full local paths.
- Logging unrecoverable startup cleanup inconsistency at `CRITICAL`.
- Logging workspace creation failures at `ERROR` without full local paths.

Temporary Ingestion Workspace does not own:

- Choosing attempt statuses, generating attempt IDs, or validating lifecycle transitions.
- Selecting source files, staging source lists, or deciding whether staged work remains.
- Parsing sources, splitting chunks, hashing files, assigning book numbers, copying files, committing source metadata, embeddings, graph extraction, provider calls, or retrieval.
- Creating committed world folders, committed source folders, `world.sqlite`, `app.sqlite`, manifests, or durable failed-attempt records.
- Rendering UI controls, progress, warnings, or completion messages.

## Normal Flow

When a caller starts ingestion from an allowed state, Ingestion Attempt State generates a new attempt ID and asks Temporary Ingestion Workspace to create a workspace for that ID before the attempt moves to `RUNNING`.

The workspace registry creates an isolated directory under the app-owned ingestion workspace area, records it under the current attempt ID, logs creation without the local path, and returns a `Path` to backend callers that need scratch storage.

If the attempt is stopped and cancellation finishes with staged work remaining, the attempt becomes `PAUSED` and the workspace remains associated with that same attempt ID. This Deep Pause behavior preserves attempt-local intermediate data so Resume can continue from the same temporary work rather than restarting from selected source files. Resume verifies that the workspace still exists for the paused attempt ID before the state returns to `RUNNING`.

If cancellation finishes with no staged work remaining, the attempt returns to `IDLE` and the workspace is removed. If a running attempt completes successfully, the attempt moves to `COMPLETE` and the workspace is removed.

Fresh starts after `IDLE` or `COMPLETE` receive new attempt IDs and new isolated workspaces. Looking up an older attempt ID after a newer attempt has started returns no workspace. When the app starts, startup cleanup scans only the app-owned ingestion workspace area and removes abandoned temporary workspace folders left by an earlier process.

When the app closes during a current attempt, app-close cancellation abandons the workspace registry record but intentionally leaves the folder for the next startup cleanup pass. Shutdown is allowed to discard in-memory ownership quickly; startup cleanup is the reliable filesystem cleanup boundary for workspaces left by an interrupted process.

## Inputs

Temporary Ingestion Workspace receives attempt IDs from Ingestion Attempt State. It does not receive source file paths, source text, parser output, chunks, hashes, database connections, provider responses, UI request objects, or committed source metadata.

## Outputs

The system returns immutable workspace objects containing:

- The attempt ID the workspace belongs to.
- The temporary workspace `Path`.

It creates temporary folders under app-owned ignored storage. It does not create database rows, committed source files, committed world folders, chunks, provider calls, HTTP responses, or visible UI state.

## Saved State And Resume Behavior

Workspace ownership state is in memory only and is tied to the current app process. It is intended for Start/Pause/Resume behavior in the running process, not crash recovery or durable saved progress.

Resume keeps the same attempt ID and the same workspace. If the paused attempt no longer has a workspace, resume is rejected so future ingestion code does not continue with missing scratch storage.

Abandoned workspaces from an earlier process are not resumed. Startup cleanup removes them before a new app session continues.

Late completion results from a cancelled attempt must not remove the paused workspace. Only successful completion from `RUNNING`, terminal cancellation to `IDLE`, registry lifetime cleanup, and startup cleanup are allowed to remove managed temporary workspaces.

App-close cancellation is not restart resume. The workspace folder may remain on disk after shutdown, but it is abandoned temporary data and startup cleanup must remove it before normal app work continues.

## Failure Behavior

Workspace creation failure is logged at `ERROR` without the attempted full temp path and is raised to the caller. Ingestion Attempt State creates the workspace before committing the `RUNNING` state, so a workspace creation failure leaves the attempt state unchanged.

If attempt-state validation fails after a workspace is created, the workspace registry removes that newly created workspace before the failure leaves the Start call.

If cleanup is requested for a workspace that is already missing, the registry treats it as already cleaned and logs at `DEBUG`. If filesystem cleanup fails, the failure is logged at `ERROR` with safe metadata and the attempted lifecycle transition is not converted into a state failure.

Startup cleanup logs successful abandoned workspace cleanup at `INFO` and per-workspace cleanup failures at `ERROR`. If abandoned workspace folders remain after cleanup attempts, startup cleanup logs `CRITICAL` and fails startup with a cleanup inconsistency error so the app does not continue while stale attempt data remains.

Logs must not include full local temp paths, raw source paths, source text, provider output, local machine details, or user data.

## System Interactions

Temporary Ingestion Workspace currently interacts with:

- Ingestion Attempt State, which generates attempt IDs, starts fresh attempts, pauses attempts, and verifies workspace availability before resume.
- App-close cancellation, which abandons the current workspace record so shutdown does not delete the folder directly.
- Backend startup, which removes abandoned temporary ingestion workspaces from earlier app processes and fails startup if cleanup cannot make the temp area consistent.
- Temporary Source Staging State, whose staged-work signal can keep an attempt paused and therefore keep the workspace associated with that attempt.
- Temporary Parsed Source Outputs, which uses the active attempt workspace identity while keeping parsed text in memory.
- Future ingestion orchestration, which may use the workspace for attempt-specific temporary files before later parsing, chunking, hashing, provider, or commit systems run.
- Committed World Folder Bootstrap and Committed Source Storage, which must remain separate from this temporary scratch area.
- The central logger, which records workspace creation and creation failures without local path details.

It must stay separate from parser internals, source preflight checks, committed source storage, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- A fresh Start creates a workspace before the attempt enters `RUNNING`.
- Resume reuses the workspace for the paused attempt ID.
- Lookup with an older attempt ID returns no workspace after a newer attempt starts.
- Workspace creation failure leaves the attempt state unchanged.
- State failure after workspace creation removes the newly created workspace.
- Successful completion removes the workspace.
- Terminal cancellation to `IDLE` removes the workspace.
- Cancellation to `PAUSED` preserves the workspace for same-process resume.
- Late completion after cancellation is rejected by Ingestion Attempt State and does not remove the paused workspace.
- Registry cleanup removes managed temporary workspaces when the registry lifetime ends.
- Missing already-cleaned workspaces are treated as no-op cleanup.
- Workspace creation logs omit full local temporary paths.

Cross-system edge cases:

- Future ingestion orchestration must use the current attempt ID when requesting the workspace.
- Temporary parsed output preparation may use the workspace identity, but must not write parsed source text into the workspace.
- Future resume code must not create a new workspace for the same paused attempt.
- Future cancellation completion code must not clean the workspace when the attempt becomes `PAUSED`.
- Startup cleanup must only remove abandoned temporary ingestion workspace folders, not committed world folders, committed sources, uploaded assets, or source files outside the temporary workspace area.
- App-close cancellation must leave abandoned temporary workspace folder removal to startup cleanup instead of treating shutdown cleanup as required for correctness.
- Future source commit work must not treat workspace files as committed source files.
- Future failed-attempt handling must not expose workspace contents as durable world data.
- Attempt workspace behavior must not create or migrate app-global or per-world database tables.

## Invariants

- Each current Start/Resume attempt has at most one current temporary workspace.
- Resume must keep the existing attempt ID and workspace.
- Fresh starts must create isolated workspaces for new attempt IDs.
- Workspace lookup must be scoped to the current attempt ID.
- Workspaces must stay outside committed world source storage.
- Workspace state must remain in memory for this system.
- `PAUSED` workspaces must remain available for same-process resume.
- Rejected late completion results must not remove `PAUSED` workspaces.
- Terminal cancellation, successful completion, and startup cleanup must remove only temporary ingestion workspaces.
- App-close cancellation must abandon current workspace registry ownership without deleting committed world data or user-selected source files.
- Startup cleanup must fail loudly if abandoned temporary workspace folders remain after cleanup attempts.
- The system must not parse, hash, copy, commit, persist, create chunks, or assign book numbers for sources.
- No database migration is required for temporary ingestion workspace behavior.

## Implementation Landmarks

- `app/ingestion/attempt_workspace.py` owns temporary workspace creation, lookup, current-attempt scoping, app-close abandonment, cleanup, startup cleanup, and workspace logging.
- `app/ingestion/attempt_state.py` coordinates Start, Resume, completion cleanup, and terminal cancellation cleanup with the workspace registry.
- `app/ingestion/app_close_cancellation.py` coordinates app-close cancellation before the global database connection closes.
- `app/ingestion/__init__.py` exports the public workspace and startup cleanup APIs for backend callers.
- `app/main.py` calls startup cleanup during backend lifespan startup.
- `tests/test_ingestion_attempt_state.py` covers workspace creation, isolation, resume reuse, terminal cleanup, startup cleanup boundaries, stale lookup behavior, path-safe failure logging, and database non-persistence.

## What AI/Coders Must Check Before Changing This System

Before editing Temporary Ingestion Workspace, check:

- Whether the change belongs in workspace handling or in attempt state, ingestion orchestration, source staging, parser routing, commit logic, routes, or UI behavior.
- Whether Start still creates the workspace before committing the `RUNNING` state.
- Whether Resume still reuses the paused attempt's existing workspace.
- Whether terminal cancellation and successful completion still remove the workspace.
- Whether app-close cancellation still abandons workspace ownership and leaves filesystem cleanup to startup.
- Whether startup cleanup is scoped only to temporary ingestion workspaces.
- Whether startup cleanup still logs remaining abandoned workspaces at `CRITICAL` and fails startup.
- Whether stale attempt IDs still cannot retrieve the current workspace.
- Whether workspace paths still stay outside committed world source storage.
- Whether logs avoid full local paths, source paths, source text, provider output, local machine details, and user data.
- Whether the system remains independent of database schema, source commits, parser work, chunk storage, embeddings, graph extraction, and durable failed statuses.
