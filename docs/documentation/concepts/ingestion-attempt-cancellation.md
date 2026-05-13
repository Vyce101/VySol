# Ingestion Attempt Cancellation

Ingestion Attempt Cancellation is VySol's in-memory backend contract for recording whether cooperative cancellation has been requested for a specific ingestion attempt. It is the shared signal future ingestion orchestration can check before launching more work or allowing final commit.

This page is for developers, power users, and AI coding agents that need to understand pause-request behavior before changing ingestion orchestration, attempt state, commit boundaries, resume behavior, or logging.

## Why It Exists

Pause is cooperative. Pressing Pause should not claim that processing has already paused, and work that reaches a late commit boundary after cancellation should not be allowed to make durable world changes.

The cancellation flag keeps that concern separate from the attempt lifecycle state. Ingestion Attempt State owns `RUNNING`, `STOPPING`, `PAUSED`, and terminal transitions. Ingestion Attempt Cancellation owns the attempt-scoped signal that tells downstream work a pause request has happened.

## Ownership Boundary

Ingestion Attempt Cancellation owns:

- Holding in-memory cancellation flags keyed by ingestion attempt ID.
- Initializing a fresh flag when an attempt starts or resumes.
- Marking the current attempt as cancellation-requested when Pause is requested.
- Keeping the current cancellation flag requested when app-close cancellation discards an active or pausable attempt.
- Reporting whether cancellation has been requested for a specific attempt ID.
- Clearing attempt flags after terminal completion or terminal cancellation.

Ingestion Attempt Cancellation does not own:

- Choosing attempt lifecycle status values.
- Moving attempts from `RUNNING` to `STOPPING`, `PAUSED`, `IDLE`, or `COMPLETE`.
- Killing worker processes, interrupting parser internals, deleting staging entries, or removing selected source files.
- Parsing, hashing, splitting, copying, assigning book numbers, writing committed source records, or creating chunks.
- Rendering Pause, Resume, progress, status labels, route responses, or UI warnings.
- Persisting cancellation state to `app.sqlite`, `world.sqlite`, files, manifests, or saved-world data.

## Normal Flow

When an ingestion attempt starts, the cancellation flag for that attempt ID is initialized to not requested. When Pause is requested during `RUNNING`, Ingestion Attempt State asks this system to mark cancellation requested before moving the attempt to `STOPPING`.

Future ingestion work can check the flag between work-launch boundaries. Current durable commit boundaries also check it before creating or mutating world storage. If cancellation is requested, commit is rejected before source files, source rows, chunk rows, world folders, app index rows, or recent-use timestamps are written. If a late completion result returns for the same cancelled attempt, Ingestion Attempt State rejects it before it can move the attempt to `COMPLETE`.

If cooperative cancellation finishes with staged work remaining, the attempt can become `PAUSED` while the cancellation flag remains true. Resume reinitializes the same attempt ID's flag to not requested so work can continue. Terminal cancellation to `IDLE` and successful completion to `COMPLETE` clear the flag.

If the app closes while an attempt is `RUNNING`, `STOPPING`, or `PAUSED`, app-close cancellation requests or preserves the same cancellation flag and discards the attempt instead of treating it as a successful commit or restart-resumable pause. This keeps late completion and commit guards from writing durable data after shutdown cancellation has begun.

## Inputs

The system receives ingestion attempt IDs and pause/cancellation intent from Ingestion Attempt State or future orchestration callers.

It does not receive source paths, source text, parser output, chunk text, hashes, database connections, provider responses, route objects, or UI request bodies.

## Outputs

The system returns a boolean cancellation-requested signal for a given attempt ID. It does not create database rows, files, durable world data, HTTP responses, or visible UI directly.

## Saved State And Resume Behavior

Cancellation flags are in memory only. They describe the current app process and are not restart-persistent resume state.

A paused attempt keeps its temporary workspace and staged work through Ingestion Attempt State and Temporary Ingestion Workspace. Resume clears the cancellation signal for that same attempt ID so the resumed attempt is not immediately treated as cancelled.

## Retry, Pause, And Abort Behavior

Repeated Pause while an attempt is already `STOPPING` is an idempotent no-op at the attempt-state layer and leaves the cancellation flag requested.

Invalid pause requests from non-running states are rejected by Ingestion Attempt State and do not set a new flag. This system does not kill workers or discard staged files; callers must cooperatively check the flag and stop launching additional work.

App-close cancellation uses the same attempt-scoped signal but has a different lifecycle meaning from Pause. Pause can lead to same-process resume after cooperative cancellation finishes. App close discards the attempt and leaves startup cleanup to remove abandoned temporary workspace folders.

## Failure Behavior

If marking the cancellation flag fails, Ingestion Attempt State logs the failure at `ERROR`, leaves the attempt `RUNNING`, and raises a cancellation error so callers do not believe cancellation was requested when the signal was not recorded.

Logs must not include raw source paths, filenames, source text, parsed text, chunk text, provider output, full workspace paths, or local machine details.

## System Interactions

Ingestion Attempt Cancellation interacts with:

- Ingestion Attempt State, which initializes, sets, clears, and resumes cancellation state as part of lifecycle transitions.
- Staged Batch Start Orchestration, which creates the running attempt that receives an initialized cancellation flag.
- App-close cancellation, which requests or preserves cancellation before discarding draft or staged state.
- New World Batch Commit and Existing World Batch Commit, which reject cancelled attempts before durable commit work begins.
- Future ingestion orchestration, which can check the flag before starting parsing, hashing, splitting, provider calls, or commit work.
- The central logger, which records pause-request and flag-failure behavior without user-owned content.

It must stay separate from source staging, parser internals, splitter internals, hash preflight, duplicate preflight, committed source storage, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- New attempts initialize cancellation to not requested.
- Pause requests mark cancellation requested before the attempt enters `STOPPING`.
- Repeated Pause while `STOPPING` leaves state and flag unchanged.
- Resume clears the previous cancellation request for the same attempt ID.
- Terminal cancellation and successful completion clear the attempt flag.
- App-close cancellation keeps the current attempt cancelled so late completion or commit work remains rejected.
- Missing or unknown attempt IDs read as not cancelled.
- Invalid blank attempt IDs are rejected.

Cross-system edge cases:

- Commit boundaries must check cancellation before creating or mutating durable world storage.
- A paused attempt may still have staged work and a temporary workspace even though cancellation has been requested.
- Future orchestration must check the flag between units of work because this system does not interrupt running parser, splitter, provider, or file-copy calls by itself.
- Late completion remains rejected by Ingestion Attempt State once Pause has moved the attempt to `STOPPING`, including after cancellation completion exposes `PAUSED`.
- App-close cancellation must use this signal before draft or staging state is discarded so final commit boundaries cannot race into durable writes.

## Invariants

- Cancellation flags must remain in memory.
- Cancellation must be scoped by attempt ID.
- Pause must not move directly to `PAUSED`.
- A cancellation flag failure must not silently move the attempt to `STOPPING`.
- Commit boundaries must not write durable world data for an attempt whose cancellation flag is requested.
- Resuming a paused attempt must clear the cancellation signal before work continues.
- App-close cancellation must not clear the cancellation signal in a way that permits late commit.
- Late completion from a cancelled current attempt must not clear the cancellation signal or clean the paused workspace.
- The system must not delete staged files, committed files, user-selected files, workspaces, or database rows.
- No database migration is required for ingestion attempt cancellation.

## Implementation Landmarks

- `app/ingestion/attempt_cancellation.py` owns the in-memory cancellation registry and public helpers.
- `app/ingestion/attempt_state.py` coordinates cancellation state with Start, Pause, Resume, terminal cancellation, and completion.
- `app/ingestion/new_world_commit.py` and `app/ingestion/existing_world_commit.py` guard durable commit entrypoints against cancelled attempts.
- `tests/test_ingestion_attempt_state.py`, `tests/test_new_world_commit.py`, and `tests/test_existing_world_commit.py` cover pause flag behavior and commit blocking.

## What AI/Coders Must Check Before Changing This System

Before editing Ingestion Attempt Cancellation, check:

- Whether the change belongs in cancellation state, attempt lifecycle state, ingestion orchestration, commit orchestration, routes, or UI behavior.
- Whether Pause still moves `RUNNING` to `STOPPING` without claiming `PAUSED`.
- Whether repeated Pause remains idempotent while `STOPPING`.
- Whether cancellation flag failures still leave the attempt `RUNNING`.
- Whether cancelled attempts still cannot reach durable commit.
- Whether Resume clears cancellation for the same paused attempt ID.
- Whether terminal cleanup clears flags without deleting staged source references.
- Whether logs avoid raw paths, filenames, source text, chunk text, provider output, and local machine details.
