# Ingestion Attempt State

Ingestion Attempt State is VySol's in-memory backend contract for representing one active source-ingestion attempt. It gives backend callers a truthful state model for whether ingestion has not started, is running, is stopping, is paused with resumable staged work, or has completed successfully, and which ingestion phase the current attempt has reached.

This page is for developers, power users, and AI coding agents that need to understand ingestion attempt state before changing ingestion orchestration, cancellation handling, source staging integration, future route handlers, one-button UI behavior, or logging.

## Why It Exists

VySol's future ingestion UI is expected to use one primary control for start, pause or stop, resume, and complete feedback. That control needs backend state that does not pretend cancellation is instant and does not confuse a never-started flow with a successful finish.

The attempt state model keeps that lifecycle separate from parsing, chunking, source commits, and UI rendering. It also carries attempt IDs so late results from an older attempt or a cancelled current attempt can be rejected instead of mutating lifecycle state or cleaning live Deep Pause work.

The phase model exists because some decisions need more detail than `RUNNING`. Draft leave safety, for example, must know whether the attempt is still before durable text commit or has already reached the point where source text and chunks are safely stored.

## Ownership Boundary

Ingestion Attempt State owns:

- Representing the single active backend ingestion attempt in process memory.
- Distinguishing `IDLE`, `RUNNING`, `STOPPING`, `PAUSED`, and `COMPLETE` attempt statuses.
- Distinguishing attempt phases: `not_started`, `preflight`, `parsing`, `splitting`, `atomic_text_commit`, and `text_committed`.
- Creating a new attempt ID when a fresh attempt starts from `IDLE` or `COMPLETE`.
- Coordinating fresh attempt workspace creation before entering `RUNNING`.
- Letting backend callers update the phase for the current running attempt by attempt ID.
- Coordinating attempt cancellation flag setup, pause requests, resume clearing, and terminal cleanup.
- Cancelling active or pausable attempts during app shutdown without treating shutdown as a successful completion.
- Preserving the same attempt ID while a paused attempt resumes.
- Verifying that a paused attempt still has its temporary workspace before resume.
- Coordinating temporary workspace cleanup after successful completion and terminal cancellation to `IDLE`.
- Abandoning the active temporary workspace record during app-close cancellation so startup cleanup owns filesystem removal.
- Rejecting stale completion or cancellation results from old attempt IDs.
- Rejecting late completion results from the cancelled current attempt while it is `STOPPING` or `PAUSED`.
- Representing whether staged work remains when cooperative cancellation finishes.
- Logging cancellation completion at `INFO`.
- Logging valid state transitions at `INFO`.
- Logging invalid transitions and stale attempt results at `WARNING`.
- Logging unexpected state-model failures at `ERROR`.

Ingestion Attempt State does not own:

- Rendering the one-button UI or choosing button labels.
- Creating or managing temporary workspace directories beyond coordinating with Temporary Ingestion Workspace.
- Running parsers, source access checks, source hashing, duplicate checks, chunk generation, provider calls, or source commits beyond tracking the phase reported by orchestration and rejecting lifecycle results that no longer match the current state.
- Persisting attempt state to `app.sqlite`, `world.sqlite`, files, manifests, or saved-world data.
- Creating durable failed source, failed world, or failed attempt statuses.
- Managing external job queues, worker processes, or background task scheduling.

## Normal Flow

Before ingestion starts, the registry reports `IDLE` with no attempt ID, no staged work remaining, and phase `not_started`. When a caller starts a fresh attempt, a new attempt ID is generated, Temporary Ingestion Workspace creates scratch storage for that ID, the state moves to `RUNNING`, staged work is considered present, and phase starts at `preflight`.

While the attempt is running, future ingestion orchestration can move the same attempt through `preflight`, `parsing`, `splitting`, `atomic_text_commit`, and `text_committed`. Phase updates are accepted only for the current running attempt ID. Stale attempt IDs and non-running states are rejected without changing the current state.

If the user asks to stop while ingestion is running, the cancellation flag is set and the state moves to `STOPPING`. This tells future UI code that cancellation has been requested but cooperative cancellation has not finished yet. A repeated stop request while already `STOPPING` is treated as an idempotent no-op and returns the current state.

When cancellation finishes, the caller reports whether staged work remains. This is the only point where `PAUSED` can be exposed. If work remains, the state moves to `PAUSED` and keeps the same attempt ID and temporary workspace so the same attempt can resume later without discarding already prepared temporary work. If no work remains, the state moves back to `IDLE` and the temporary workspace is removed.

Resuming a paused attempt first verifies that the same attempt ID still has its temporary workspace, clears the previous cancellation request, then moves `PAUSED` back to `RUNNING` with that same attempt ID and preserved phase. Completing a running attempt with the current attempt ID moves the state to `COMPLETE`, resets phase to `not_started`, clears the cancellation flag, removes the temporary workspace, and allows the UI to distinguish successful completion from a never-started idle state.

If a completion result arrives for the same attempt after cancellation has moved it to `STOPPING` or `PAUSED`, the result is rejected. The attempt state, cancellation flag, and temporary workspace remain unchanged so a cancelled attempt cannot accidentally complete or delete resumable Deep Pause data.

When the app is closing, the shutdown boundary cancels any current `RUNNING`, `STOPPING`, or `PAUSED` attempt. It leaves the cancellation flag requested, preserves the current phase, records the lifecycle as stopping, and abandons the temporary workspace record instead of deleting the workspace during shutdown. App-close cancellation is not a successful commit and is not a resumable pause; it exists so late completion and commit guards reject the attempt while backend startup remains responsible for removing abandoned temporary workspace folders.

## Inputs

Ingestion Attempt State receives caller intent to start, stop, resume, finish cancellation, complete an attempt, or update the phase of the current running attempt. Cancellation, completion, and phase update calls must include the attempt ID they belong to. Cancellation completion also receives a boolean staged-work signal so it can choose between `PAUSED` and `IDLE`. Stop requests also coordinate with Ingestion Attempt Cancellation so downstream work can see that Pause was requested.

On FastAPI shutdown, the app-close cancellation boundary can ask this system to cancel the current active or pausable attempt without preserving it for restart resume.

It does not receive source file paths, source text, parser output, chunks, hashes, provider responses, database connections, or UI request objects.

## Outputs

The system returns immutable in-memory attempt state objects containing:

- The current attempt status.
- The current attempt phase.
- The current attempt ID, when an attempt exists.
- Whether staged work remains available for resume.
- The current temporary workspace when looked up by the current attempt ID.

It does not produce database rows, files, committed source metadata, chunks, provider calls, HTTP responses, or visible UI directly.

## Saved State And Resume Behavior

Attempt state is in memory only. It is intended to represent the currently running app process, not crash recovery or durable saved progress.

`PAUSED` means cancellation finished while staged work still exists and the same attempt can resume with its existing temporary workspace and preserved phase. That workspace may contain intermediate parsed or split data needed for a true Deep Pause continuation. `IDLE` means no current attempt is resumable and phase is `not_started`. `COMPLETE` means an attempt finished successfully, its temporary workspace has been cleaned, phase is reset to `not_started`, and the completed state can be shown separately from `IDLE` until a new attempt starts.

App-close cancellation discards the same-process resume boundary. A paused attempt that exists only because the app is still open must not be persisted across restart, and shutdown must not convert paused work into a committed or resumable attempt.

## Retry, Pause, And Abort Behavior

This model supports cooperative cancellation state, but it does not interrupt running work itself. The future ingestion runner must request a stop, check the cancellation flag between work-launch boundaries, finish its own cancellation work, and then report whether staged work remains.

Fresh starts from `IDLE` or `COMPLETE` create new attempt IDs, new temporary workspaces, fresh cancellation flags, and phase `preflight`. Resume from `PAUSED` keeps the existing attempt ID, phase, and workspace while clearing the previous cancellation request. Terminal cancellation and successful completion remove the temporary workspace, reset phase to `not_started`, and clear the cancellation flag. Late completion or cancellation results for older attempt IDs are rejected and leave the current state unchanged. Late completion for the cancelled current attempt is also rejected while `STOPPING` or `PAUSED`.

App-close cancellation is stricter than same-process Pause. It handles `RUNNING`, `STOPPING`, and `PAUSED` as discard-on-close states, keeps the cancellation signal requested, and does not expose a restart resume path.

## Failure Behavior

Invalid transitions are logged at `WARNING` and rejected without changing state. Examples include stopping while idle, resuming while not paused, starting while already running, updating phase while not running, or completing an attempt while it is not running. Repeated stop requests while already `STOPPING` are logged at `WARNING` and return the current state.

If the cancellation flag cannot be set for a valid stop request, the failure is logged at `ERROR`, the attempt remains `RUNNING`, and the caller receives a cancellation error.

Stale attempt results are logged at `WARNING` and rejected without changing state. Late completion results from a cancelled current attempt are also logged at `WARNING`, rejected without changing state, and must not clean the paused workspace. Workspace creation failures and unexpected state-model failures are logged at `ERROR` and raised so callers do not continue with an unknown lifecycle state.

App-close cancellation is logged at `INFO`. It must not commit staged work, must not clear the cancellation flag in a way that permits a late commit, and must leave temporary workspace folder removal to the next startup cleanup boundary.

Logs must not include raw source paths, full temporary workspace paths, source text, local machine details, provider output, or user data.

## System Interactions

Ingestion Attempt State currently interacts with:

- Future ingestion orchestration, which will use it before and after cooperative cancellation, resume, and completion.
- Ingestion Attempt Cancellation, which stores the attempt-scoped cancellation signal used by future orchestration and commit guards.
- Temporary Ingestion Workspace, which provides current-attempt scratch storage for Start and Resume attempts.
- Temporary Source Staging State, whose remaining staged work determines whether cancellation ends in `PAUSED` or `IDLE`.
- App-close cancellation, which discards draft or staged source state and uses attempt state to reject late completion.
- Draft World Leave Safety, which reads the current phase to decide whether leaving a draft is safe after durable text commit.
- Future one-button UI state, which can map the backend lifecycle to start, stopping, resume, and completion feedback.
- The central logger, which records transition summaries and rejected transitions without source data.

It must stay separate from parser internals, source preflight checks, committed source storage, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- The initial state is `IDLE` with no attempt ID.
- The initial phase is `not_started`.
- Starting from `IDLE` creates a new attempt ID and enters `preflight`.
- Starting from `COMPLETE` creates a new attempt ID and enters `preflight`.
- Starting creates a temporary workspace before the state becomes `RUNNING`.
- Starting from `RUNNING`, `STOPPING`, or `PAUSED` is rejected.
- Phase updates are accepted only for the current `RUNNING` attempt.
- Stale phase updates are rejected without changing state.
- Non-running phase updates are rejected without changing state.
- Stopping is allowed only from `RUNNING`.
- Repeated stopping while already `STOPPING` returns the current state and logs a warning.
- Stop requests set the current attempt's cancellation flag before the state moves to `STOPPING`.
- Stop requests preserve the current phase.
- Cancellation completion is accepted only from `STOPPING` and only for the current attempt ID.
- Cancellation with staged work moves to `PAUSED`, logs cancellation completion, and preserves the existing attempt ID, phase, and temporary workspace.
- Cancellation without staged work moves to `IDLE`, resets phase to `not_started`, clears the cancellation flag, and cleans the temporary workspace.
- Resume is allowed only from `PAUSED` with staged work remaining and the existing temporary workspace available, then clears the cancellation flag and preserves phase.
- Completion is accepted only from `RUNNING` and only for the current attempt ID, then resets phase to `not_started`, clears the cancellation flag, and cleans the temporary workspace.
- `COMPLETE` and `IDLE` remain distinct statuses.
- Stale attempt IDs cannot complete or cancel a newer attempt.
- Late completion from the current attempt while `STOPPING` or `PAUSED` is rejected without changing state or cleaning the workspace.
- App-close cancellation accepts `RUNNING`, `STOPPING`, and `PAUSED` attempts as discard-on-close states.
- App-close cancellation keeps the cancellation signal requested so late completion and commit work are rejected.
- App-close cancellation preserves phase for late-guard visibility while marking the attempt as stopping.
- App-close cancellation abandons workspace registry ownership instead of deleting the temporary workspace folder during shutdown.

Cross-system edge cases:

- Future ingestion orchestration must pass the current attempt ID into completion and cancellation-finished calls.
- Future ingestion orchestration must use the current attempt ID when asking for a temporary workspace.
- Future cancellation code must report whether staged work remains instead of guessing from status alone.
- Future orchestration must stop launching new work after the cancellation flag is requested.
- Future orchestration must report cancellation completion before the backend exposes `PAUSED`.
- Future orchestration must treat completion results that arrive after cancellation as rejected late results.
- Future resume code must not create a new workspace for the paused attempt.
- Future cleanup code must preserve `PAUSED` workspaces during the same process and clean only terminal attempt workspaces.
- Future UI code must treat `STOPPING` as an in-progress cancellation state, not as already paused.
- Future UI code must treat `PAUSED` as resumable work and `IDLE` as ready for a fresh start.
- Future source commit work must not infer that attempt state has committed, parsed, copied, hashed, or chunked any source.
- Future source commit work must set `text_committed` only after source text and chunks are durably committed to SQLite.
- Draft leave safety must not treat `RUNNING` alone as safe; it must read the phase.
- Future source commit work must not treat temporary workspace files as committed source files.
- FastAPI shutdown must run app-close cancellation before closing the global database connection so draft and staging cleanup can still use app-owned registries.
- App-close cancellation must not preserve `PAUSED` state for restart resume.
- Attempt state must not create or migrate app-global or per-world database tables.

## Invariants

- Attempt state must remain in memory for this system.
- Only one active attempt may exist in the registry.
- `IDLE` must not have an attempt ID or staged work remaining.
- `IDLE` and `COMPLETE` must use phase `not_started`.
- `PAUSED` must mean staged work remains.
- `COMPLETE` must stay distinct from `IDLE`.
- Fresh starts must create new attempt IDs.
- Fresh starts must enter phase `preflight`.
- Phase updates must be scoped to the current running attempt ID.
- Fresh starts must initialize a not-requested cancellation flag.
- Resume must keep the paused attempt ID.
- Resume must preserve the paused attempt phase.
- Resume must clear the previous cancellation request.
- Fresh starts must create new temporary workspaces.
- Resume must keep the paused attempt's existing temporary workspace.
- `PAUSED` must only be exposed after cancellation completion is reported.
- Completion and terminal cancellation must clean the attempt workspace without changing the meaning of `COMPLETE`, `IDLE`, or `PAUSED`.
- Completion and terminal cancellation must reset phase to `not_started`.
- Terminal completion and terminal cancellation must clear the attempt cancellation flag.
- Repeated stop requests while `STOPPING` must not change state or create a new attempt.
- App close must never be treated as successful completion.
- App close must not preserve paused staged work across restart.
- Stale attempt results must never mutate current state.
- Stale phase updates must never mutate current state.
- Late completion results from a cancelled current attempt must never mutate current state or clean Deep Pause workspace data.
- Invalid transitions must leave current state unchanged.
- The system must not parse, hash, copy, commit, persist, or assign book numbers for sources.
- No database migration is required for ingestion attempt state.

## Implementation Landmarks

- `app/ingestion/attempt_state.py` owns the in-memory attempt state and phase model, registry, transitions, stale-result rejection, terminal workspace cleanup coordination, and logging.
- `app/ingestion/app_close_cancellation.py` coordinates app-close discard behavior across attempt state, active staged-batch metadata, draft worlds, source staging, and temporary workspace ownership.
- `app/ingestion/attempt_cancellation.py` owns the in-memory cancellation flag used when Pause is requested.
- `app/ingestion/attempt_workspace.py` owns temporary workspace creation, lookup, current-attempt scoping, and cleanup.
- `app/ingestion/__init__.py` exports the public attempt-state and workspace API for backend callers.
- `tests/test_ingestion_attempt_state.py` covers lifecycle transitions, phase updates, workspace creation and reuse, stale attempt rejection, invalid transition logging, unexpected failure logging, and database non-persistence.

## What AI/Coders Must Check Before Changing This System

Before editing Ingestion Attempt State, check:

- Whether the change belongs in attempt state or in ingestion orchestration, source staging, parser routing, commit logic, routes, or UI behavior.
- Whether `IDLE`, `PAUSED`, and `COMPLETE` remain semantically distinct.
- Whether phase updates remain scoped to the current running attempt.
- Whether `text_committed` still means source text and chunks have been durably committed.
- Whether stale attempt IDs still cannot mutate current state.
- Whether cancellation completion still chooses `PAUSED` only when staged work remains.
- Whether `PAUSED` is exposed only after cancellation completion, never directly from Pause request.
- Whether valid Pause requests still set the cancellation flag before entering `STOPPING`.
- Whether repeated Pause requests while `STOPPING` remain idempotent.
- Whether late completion after cancellation is still rejected without deleting paused workspace data.
- Whether app-close cancellation still discards `RUNNING`, `STOPPING`, and `PAUSED` attempts without creating restart-resumable work.
- Whether cancellation to `IDLE` and successful completion still clean the temporary workspace.
- Whether terminal cleanup and Resume clear cancellation flag state at the right time.
- Whether Start and Resume still preserve the Temporary Ingestion Workspace contract.
- Whether logs avoid source paths, full temporary workspace paths, source text, provider output, local machine details, and user data.
- Whether attempt state remains independent of database schema, source commits, parser work, chunk storage, embeddings, graph extraction, and durable failed statuses.
