# Ingestion Attempt State

Ingestion Attempt State is VySol's in-memory backend contract for representing one active source-ingestion attempt. It gives backend callers a truthful state model for whether ingestion has not started, is running, is stopping, is paused with resumable staged work, or has completed successfully.

This page is for developers, power users, and AI coding agents that need to understand ingestion attempt state before changing ingestion orchestration, cancellation handling, source staging integration, future route handlers, one-button UI behavior, or logging.

## Why It Exists

VySol's future ingestion UI is expected to use one primary control for start, pause or stop, resume, and complete feedback. That control needs backend state that does not pretend cancellation is instant and does not confuse a never-started flow with a successful finish.

The attempt state model keeps that lifecycle separate from parsing, chunking, source commits, and UI rendering. It also carries attempt IDs so late results from an older attempt can be rejected instead of mutating a newer attempt.

## Ownership Boundary

Ingestion Attempt State owns:

- Representing the single active backend ingestion attempt in process memory.
- Distinguishing `IDLE`, `RUNNING`, `STOPPING`, `PAUSED`, and `COMPLETE` attempt statuses.
- Creating a new attempt ID when a fresh attempt starts from `IDLE` or `COMPLETE`.
- Coordinating fresh attempt workspace creation before entering `RUNNING`.
- Coordinating attempt cancellation flag setup, pause requests, resume clearing, and terminal cleanup.
- Preserving the same attempt ID while a paused attempt resumes.
- Verifying that a paused attempt still has its temporary workspace before resume.
- Coordinating temporary workspace cleanup after successful completion and terminal cancellation to `IDLE`.
- Rejecting stale completion or cancellation results from old attempt IDs.
- Representing whether staged work remains when cooperative cancellation finishes.
- Logging valid state transitions at `INFO`.
- Logging invalid transitions and stale attempt results at `WARNING`.
- Logging unexpected state-model failures at `ERROR`.

Ingestion Attempt State does not own:

- Rendering the one-button UI or choosing button labels.
- Creating or managing temporary workspace directories beyond coordinating with Temporary Ingestion Workspace.
- Running parsers, source access checks, source hashing, duplicate checks, chunk generation, embeddings, graph extraction, provider calls, or source commits beyond rejecting lifecycle results that no longer match the current state.
- Persisting attempt state to `app.sqlite`, `world.sqlite`, files, manifests, or saved-world data.
- Creating durable failed source, failed world, or failed attempt statuses.
- Managing external job queues, worker processes, or background task scheduling.

## Normal Flow

Before ingestion starts, the registry reports `IDLE` with no attempt ID and no staged work remaining. When a caller starts a fresh attempt, a new attempt ID is generated, Temporary Ingestion Workspace creates scratch storage for that ID, the state moves to `RUNNING`, and staged work is considered present.

If the user asks to stop while ingestion is running, the cancellation flag is set and the state moves to `STOPPING`. This tells future UI code that cancellation has been requested but cooperative cancellation has not finished yet. A repeated stop request while already `STOPPING` is treated as an idempotent no-op and returns the current state.

When cancellation finishes, the caller reports whether staged work remains. If work remains, the state moves to `PAUSED` and keeps the same attempt ID so the same attempt can resume later. If no work remains, the state moves back to `IDLE` and the temporary workspace is removed.

Resuming a paused attempt first verifies that the same attempt ID still has its temporary workspace, clears the previous cancellation request, then moves `PAUSED` back to `RUNNING` with that same attempt ID. Completing a running attempt with the current attempt ID moves the state to `COMPLETE`, clears the cancellation flag, removes the temporary workspace, and allows the UI to distinguish successful completion from a never-started idle state.

## Inputs

Ingestion Attempt State receives caller intent to start, stop, resume, finish cancellation, or complete an attempt. Cancellation and completion calls must include the attempt ID they belong to. Cancellation completion also receives a boolean staged-work signal so it can choose between `PAUSED` and `IDLE`. Stop requests also coordinate with Ingestion Attempt Cancellation so downstream work can see that Pause was requested.

It does not receive source file paths, source text, parser output, chunks, hashes, provider responses, database connections, or UI request objects.

## Outputs

The system returns immutable in-memory attempt state objects containing:

- The current attempt status.
- The current attempt ID, when an attempt exists.
- Whether staged work remains available for resume.
- The current temporary workspace when looked up by the current attempt ID.

It does not produce database rows, files, committed source metadata, chunks, provider calls, HTTP responses, or visible UI directly.

## Saved State And Resume Behavior

Attempt state is in memory only. It is intended to represent the currently running app process, not crash recovery or durable saved progress.

`PAUSED` means cancellation finished while staged work still exists and the same attempt can resume with its existing temporary workspace. `IDLE` means no current attempt is resumable. `COMPLETE` means an attempt finished successfully, its temporary workspace has been cleaned, and the completed state can be shown separately from `IDLE` until a new attempt starts.

## Retry, Pause, And Abort Behavior

This model supports cooperative cancellation state, but it does not interrupt running work itself. The future ingestion runner must request a stop, check the cancellation flag between work-launch boundaries, finish its own cancellation work, and then report whether staged work remains.

Fresh starts from `IDLE` or `COMPLETE` create new attempt IDs, new temporary workspaces, and fresh cancellation flags. Resume from `PAUSED` keeps the existing attempt ID and workspace while clearing the previous cancellation request. Terminal cancellation and successful completion remove the temporary workspace and clear the cancellation flag. Late completion or cancellation results for older attempt IDs are rejected and leave the current state unchanged.

## Failure Behavior

Invalid transitions are logged at `WARNING` and rejected without changing state. Examples include stopping while idle, resuming while not paused, starting while already running, or completing an attempt while it is not running. Repeated stop requests while already `STOPPING` are logged at `WARNING` and return the current state.

If the cancellation flag cannot be set for a valid stop request, the failure is logged at `ERROR`, the attempt remains `RUNNING`, and the caller receives a cancellation error.

Stale attempt results are logged at `WARNING` and rejected without changing state. Workspace creation failures and unexpected state-model failures are logged at `ERROR` and raised so callers do not continue with an unknown lifecycle state.

Logs must not include raw source paths, full temporary workspace paths, source text, local machine details, provider output, or user data.

## System Interactions

Ingestion Attempt State currently interacts with:

- Future ingestion orchestration, which will use it before and after cooperative cancellation, resume, and completion.
- Ingestion Attempt Cancellation, which stores the attempt-scoped cancellation signal used by future orchestration and commit guards.
- Temporary Ingestion Workspace, which provides current-attempt scratch storage for Start and Resume attempts.
- Temporary Source Staging State, whose remaining staged work determines whether cancellation ends in `PAUSED` or `IDLE`.
- Future one-button UI state, which can map the backend lifecycle to start, stopping, resume, and completion feedback.
- The central logger, which records transition summaries and rejected transitions without source data.

It must stay separate from parser internals, source preflight checks, committed source storage, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- The initial state is `IDLE` with no attempt ID.
- Starting from `IDLE` creates a new attempt ID.
- Starting from `COMPLETE` creates a new attempt ID.
- Starting creates a temporary workspace before the state becomes `RUNNING`.
- Starting from `RUNNING`, `STOPPING`, or `PAUSED` is rejected.
- Stopping is allowed only from `RUNNING`.
- Repeated stopping while already `STOPPING` returns the current state and logs a warning.
- Stop requests set the current attempt's cancellation flag before the state moves to `STOPPING`.
- Cancellation completion is accepted only from `STOPPING` and only for the current attempt ID.
- Cancellation with staged work moves to `PAUSED`.
- Cancellation without staged work moves to `IDLE`, clears the cancellation flag, and cleans the temporary workspace.
- Resume is allowed only from `PAUSED` with staged work remaining and the existing temporary workspace available, then clears the cancellation flag.
- Completion is accepted only from `RUNNING` and only for the current attempt ID, then clears the cancellation flag and cleans the temporary workspace.
- `COMPLETE` and `IDLE` remain distinct statuses.
- Stale attempt IDs cannot complete or cancel a newer attempt.

Cross-system edge cases:

- Future ingestion orchestration must pass the current attempt ID into completion and cancellation-finished calls.
- Future ingestion orchestration must use the current attempt ID when asking for a temporary workspace.
- Future cancellation code must report whether staged work remains instead of guessing from status alone.
- Future orchestration must stop launching new work after the cancellation flag is requested.
- Future resume code must not create a new workspace for the paused attempt.
- Future cleanup code must preserve `PAUSED` workspaces during the same process and clean only terminal attempt workspaces.
- Future UI code must treat `STOPPING` as an in-progress cancellation state, not as already paused.
- Future UI code must treat `PAUSED` as resumable work and `IDLE` as ready for a fresh start.
- Future source commit work must not infer that attempt state has committed, parsed, copied, hashed, or chunked any source.
- Future source commit work must not treat temporary workspace files as committed source files.
- Attempt state must not create or migrate app-global or per-world database tables.

## Invariants

- Attempt state must remain in memory for this system.
- Only one active attempt may exist in the registry.
- `IDLE` must not have an attempt ID or staged work remaining.
- `PAUSED` must mean staged work remains.
- `COMPLETE` must stay distinct from `IDLE`.
- Fresh starts must create new attempt IDs.
- Fresh starts must initialize a not-requested cancellation flag.
- Resume must keep the paused attempt ID.
- Resume must clear the previous cancellation request.
- Fresh starts must create new temporary workspaces.
- Resume must keep the paused attempt's existing temporary workspace.
- Completion and terminal cancellation must clean the attempt workspace without changing the meaning of `COMPLETE`, `IDLE`, or `PAUSED`.
- Terminal completion and terminal cancellation must clear the attempt cancellation flag.
- Repeated stop requests while `STOPPING` must not change state or create a new attempt.
- Stale attempt results must never mutate current state.
- Invalid transitions must leave current state unchanged.
- The system must not parse, hash, copy, commit, persist, or assign book numbers for sources.
- No database migration is required for ingestion attempt state.

## Implementation Landmarks

- `app/ingestion/attempt_state.py` owns the in-memory attempt state model, registry, transitions, stale-result rejection, terminal workspace cleanup coordination, and logging.
- `app/ingestion/attempt_cancellation.py` owns the in-memory cancellation flag used when Pause is requested.
- `app/ingestion/attempt_workspace.py` owns temporary workspace creation, lookup, current-attempt scoping, and cleanup.
- `app/ingestion/__init__.py` exports the public attempt-state and workspace API for backend callers.
- `tests/test_ingestion_attempt_state.py` covers lifecycle transitions, workspace creation and reuse, stale attempt rejection, invalid transition logging, unexpected failure logging, and database non-persistence.

## What AI/Coders Must Check Before Changing This System

Before editing Ingestion Attempt State, check:

- Whether the change belongs in attempt state or in ingestion orchestration, source staging, parser routing, commit logic, routes, or UI behavior.
- Whether `IDLE`, `PAUSED`, and `COMPLETE` remain semantically distinct.
- Whether stale attempt IDs still cannot mutate current state.
- Whether cancellation completion still chooses `PAUSED` only when staged work remains.
- Whether valid Pause requests still set the cancellation flag before entering `STOPPING`.
- Whether repeated Pause requests while `STOPPING` remain idempotent.
- Whether cancellation to `IDLE` and successful completion still clean the temporary workspace.
- Whether terminal cleanup and Resume clear cancellation flag state at the right time.
- Whether Start and Resume still preserve the Temporary Ingestion Workspace contract.
- Whether logs avoid source paths, full temporary workspace paths, source text, provider output, local machine details, and user data.
- Whether attempt state remains independent of database schema, source commits, parser work, chunk storage, embeddings, graph extraction, and durable failed statuses.
