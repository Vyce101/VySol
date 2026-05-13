# Existing World Batch Commit

Existing World Batch Commit is VySol's backend orchestration contract for appending a staged source batch to a committed world. It opens the existing world's `world.sqlite`, appends source metadata and chunk rows after the current highest book number, promotes copied source files into the world's `sources/` folder, and refreshes the app index `last_used_at` after the core commit succeeds.

This page is for developers, power users, and AI coding agents that need to understand the durable append boundary before changing existing-world source ingestion, file promotion, chunk storage, book numbering, rollback behavior, or recent-use updates.

## Why It Exists

Adding sources to an existing world crosses the same durable systems as new-world commit work: the per-world database, copied source files, permanent book numbers, and chunk storage.

Existing worlds also already contain committed source and chunk data that must remain untouched. Existing World Batch Commit exists to make add-source work append-only and atomic: new rows and files appear only after the whole batch succeeds, while failed commits leave the existing world data as it was before the attempt.

## Ownership Boundary

Existing World Batch Commit owns:

- Rejecting empty accepted source batches before opening or mutating world storage.
- Rejecting cancellation-requested attempts before opening or mutating world storage.
- Verifying the target world exists in the app-level committed world index before opening `world.sqlite`.
- Opening the existing world database.
- Validating staged source hashes against both the batch and existing committed sources.
- Preparing committed source file copies for the target world.
- Assigning append-only book numbers after the highest existing committed source book number.
- Reading temporary split chunk rows from the active ingestion attempt workspace.
- Writing new committed source rows and new chunk rows inside one world database transaction.
- Promoting new source file copies through the rollback-aware file promotion helper.
- Refreshing the committed world's `last_used_at` after the source/chunk/file commit succeeds.
- Logging successful commits at `INFO`, rollback and cleanup activity at `WARNING`, commit failures at `ERROR`, and unrecoverable cleanup inconsistency at `CRITICAL`.

Existing World Batch Commit does not own:

- Creating new committed worlds or app index rows.
- Creating, deleting, replacing, reordering, or re-splitting existing committed sources or chunks.
- Writing or changing world splitter settings.
- File selection, source type filtering, file access validation, parsing, splitting, hashing, or temporary staging state.
- User-facing progress, route responses, World Hub rendering, or UI state.
- Embeddings, graph extraction, retrieval records, chat state, provenance manifests, or future post-commit enrichment work.
- Retrying failed batches, preserving failed-source slots, or deleting user-selected source files.

## Normal Flow

Earlier ingestion systems validate selected files, parse them, split them, hash them, and store temporary split chunk rows in the active attempt workspace. Existing World Batch Commit receives the target world ID, the active temporary ingestion workspace, and the already-accepted hashed staged sources.

The orchestrator first rejects cancellation-requested attempts, then confirms the target world exists in the global committed-world index. That check prevents a random UUID from silently creating a new world folder through the world database bootstrap path. For a non-empty, non-cancelled batch, it opens the existing world database, validates duplicate hashes, prepares source copy destinations, assigns book numbers after the highest existing committed source, and builds chunk records from temporary split output.

The source file promotion helper then copies source files to temporary paths and opens the world database transaction. Inside that transaction, the orchestrator writes only new committed source rows and new chunk rows. The helper promotes source files and commits the transaction only after the database callback succeeds.

After the world database and source file commit succeeds, the orchestrator refreshes `last_used_at` in the app-level committed world index. That timestamp refresh is a non-fatal side effect: if it fails, the source commit still returns success because the core world append already completed.

## Inputs

Existing World Batch Commit receives:

- A committed world ID.
- The active temporary ingestion workspace.
- Accepted hashed staged sources for the add-source batch.
- An optional app database connection for tests.

The accepted sources are expected to have passed parser, splitter, hash, file access, and preflight work before reaching this boundary.

## Outputs

On success, Existing World Batch Commit returns committed source records, stored chunk records, source count, chunk count, and whether `last_used_at` was refreshed. It also leaves new durable state in the existing world database and copied source files under the existing world's `sources/` folder.

On failure before the core world commit succeeds, it raises the original commit error after rollback and cleanup have been attempted. It must not return partial commit state as if the source batch was committed.

## Failure Behavior

Cancellation-requested attempts, empty accepted batches, and missing committed-world index records are rejected before world storage is mutated.

Failures during duplicate validation, source copy preparation, book-number assignment, source metadata writes, chunk writes, source file copying, file promotion, or world database commit leave existing committed data unchanged. Rollback removes only helper-created temporary files and newly promoted source files from the failed batch. It does not delete existing world files, existing source rows, existing chunk rows, or user-selected source files.

If the post-commit `last_used_at` refresh fails, the orchestrator logs the timestamp failure at `ERROR`, returns source-commit success, and does not ask callers to retry the source commit. Raising at that stage would make a successful source append look like a failed commit and could cause duplicate retry attempts.

Logs must not include chunk text, overlap text, raw selected paths, raw local storage paths, filenames, full source text, or local machine details.

## System Interactions

Existing World Batch Commit interacts with:

- Committed World Index Storage, which proves the target world exists before mutation and receives the best-effort `last_used_at` refresh after commit.
- Ingestion Attempt Cancellation, which prevents final commit after Pause has been requested for the attempt.
- World Database Bootstrap, which opens and migrates the target world database.
- Temporary Ingestion Workspace and Temporary Split Chunk Outputs, which provide attempt-local chunk rows.
- Staged Source Hash Preflight and Staged Source Duplicate Preflight, which prepare and validate source hashes.
- Book Number Assignment, which appends new source numbers after existing committed sources.
- Committed Source File Storage, which prepares source copy pairs and safe stored source paths.
- Shared world batch record writing, which writes transaction-safe committed source and chunk rows.
- Commit Rollback and Cleanup Helper, which coordinates source file promotion with the world database transaction.
- Committed Source Storage and Chunk Storage, which define the durable row contracts written during commit.
- The central logger, which records commit, rollback, cleanup, and timestamp refresh failures without user-owned content.

It must stay separate from parser internals, splitter algorithms, UI progress, World Hub rendering, embeddings, graph extraction, retrieval, chat behavior, and provider systems.

## Current Edge Cases

Internal edge cases:

- Empty accepted batches fail before world database writes or source copy promotion.
- Cancellation-requested attempts fail before world database writes, source copy promotion, or recent-use refresh.
- Missing committed-world index records fail before world database creation or mutation.
- A batch that produces no chunks fails before source files are promoted.
- Every committed source in the batch must have at least one temporary split chunk.
- Temporary split chunk rows must reference staged source IDs that belong to the accepted batch.
- Duplicate source IDs, duplicate source hashes, duplicate book numbers, duplicate chunk IDs, and duplicate book/chunk positions are rejected before or during the world transaction.
- Source file copy failures prevent world database writes from being committed.
- File promotion and world database commit failures trigger rollback and source file cleanup.
- `last_used_at` refresh failures are logged without changing the successful source commit result.

Cross-system edge cases:

- Existing committed source and chunk rows must remain append-only and must not be altered by add-source work.
- Pause requests must prevent the attempt from appending final durable source data after cancellation is requested.
- Old book-number gaps are preserved; new sources append after the highest existing book number.
- Existing self-committing storage functions must not be called inside the rollback helper transaction.
- Temporary split chunk output can contain chunk text, but commit logs must never include that text.
- Source copy preparation preserves original filenames as metadata, but logs and stored filenames must not expose raw selected paths.
- Failure cleanup must not delete existing committed source files or user-selected source files.
- A successful source append with a failed recent-use refresh must not be reported as a failed source commit.

## Invariants

- Existing worlds can receive new source batches only when the target world already exists in the committed-world index.
- Cancelled attempts must not append source batches to existing worlds.
- New committed source rows must append after the highest existing committed source book number.
- Existing committed source rows, chunk rows, source files, and splitter settings must remain unchanged.
- Source file promotion and world database writes must share one rollback-aware commit boundary.
- The `last_used_at` refresh must happen after the source/chunk/file commit succeeds and must remain non-fatal.
- Cleanup must remove only files created or promoted for the failed batch.
- Logs must not contain chunk text, overlap text, source text, raw local paths, filenames, or user data.

## Implementation Landmarks

- `app/ingestion/existing_world_commit.py` owns the existing-world orchestration, app-index existence check, post-commit recent-use refresh, and commit-level logging.
- `app/ingestion/world_batch_records.py` owns shared transaction-safe source and chunk row construction used by source batch commit flows.
- `app/storage/committed_source_files.py` prepares source copy pairs and delegates promotion to the rollback helper.
- `app/ingestion/commit_cleanup.py` owns temporary source copy promotion and rollback mechanics.
- `tests/test_existing_world_commit.py` covers append success, rollback, cleanup, non-fatal timestamp refresh failure, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Existing World Batch Commit, check:

- Whether the change belongs in final commit orchestration instead of parser, splitter, staging, file validation, storage repositories, UI, graph, embedding, retrieval, or chat behavior.
- Whether the target world is still verified through the app-level committed-world index before world storage is opened or mutated.
- Whether cancellation-requested attempts are still rejected before world storage is opened or mutated.
- Whether existing committed source and chunk records remain untouched.
- Whether new book numbers still append after the highest existing committed source.
- Whether source file promotion and world database writes still share the rollback helper boundary.
- Whether transaction-safe helpers still avoid storage functions that call `commit()` internally.
- Whether post-commit `last_used_at` refresh failures still log at `ERROR` without raising.
- Whether cleanup can fail loudly enough to expose unrecoverable database/filesystem inconsistency.
- Whether logs still avoid chunk text, overlap text, source text, raw local paths, filenames, and user data.
