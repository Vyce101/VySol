# New World Batch Commit

New World Batch Commit is VySol's backend orchestration contract for turning the first accepted staged source batch into a visible committed world. It creates the UUID world folder and `world.sqlite`, writes locked splitter settings, committed source metadata, chunk records, and promoted source copies, then inserts the app-level world index row last.

This page is for developers, power users, and AI coding agents that need to understand the durable commit boundary before changing ingestion orchestration, world creation, source copying, chunk storage, app index visibility, or rollback behavior.

## Why It Exists

Creating a new world crosses multiple durable systems: a world folder, a per-world SQLite database, copied source files, source metadata, chunk records, splitter settings, and the global app index used by World Hub.

If the app index row is written too early, World Hub can show a world whose source files, chunks, or world database are incomplete. New World Batch Commit exists to keep that visibility boundary atomic: the world becomes visible only after its first accepted source batch has been committed successfully.

## Ownership Boundary

New World Batch Commit owns:

- Rejecting empty accepted source batches before creating a world folder, world database, source copy, or app index row.
- Rejecting cancellation-requested attempts before creating a world folder, world database, source copy, or app index row.
- Generating one UUID world ID for the new committed world.
- Bootstrapping the new world folder and `world.sqlite`.
- Validating the accepted batch against duplicate source hashes in the new world database.
- Preparing committed source file copies.
- Assigning first-batch book numbers.
- Reading temporary split chunk rows from the active ingestion attempt workspace.
- Writing locked splitter settings, committed source records, and chunk records inside one world database transaction.
- Promoting source file copies through the rollback-aware file promotion helper.
- Adding the committed world row to `app.sqlite` only after world data and source files are valid.
- Cleaning up the new world folder if any commit step fails before World Hub visibility is established.
- Logging successful commits at `INFO`, rollback and cleanup activity at `WARNING`, commit failures at `ERROR`, and unrecoverable consistency failures at `CRITICAL`.

New World Batch Commit does not own:

- File selection, source type filtering, file access validation, parsing, splitting, hash calculation, or temporary staging state.
- User-facing progress, World Hub rendering, route responses, or UI state.
- Retrying failed batches, preserving failed-source slots, or committing an empty world at this commit boundary.
- Embeddings, graph extraction, retrieval records, chat state, provenance manifests, or future post-commit enrichment work.
- Deleting user-selected source files.

## Normal Flow

Earlier ingestion systems validate the selected files, parse them, split them, hash them, and store temporary split chunk rows in the active attempt workspace. New World Batch Commit receives the already-accepted first batch, validated draft splitter settings, the active temporary ingestion workspace, and the new world metadata.

The orchestrator rejects a cancellation-requested attempt or empty batch before durable world storage begins. For a non-empty, non-cancelled batch, it generates a UUID world ID, bootstraps the world database, validates duplicate hashes, prepares source copy destinations, assigns book numbers starting at `1`, and builds chunk records from temporary split output.

The source file promotion helper then copies source files to temporary paths and opens the world database transaction. Inside that transaction, the orchestrator writes locked splitter settings, committed source rows, and chunk rows without calling storage functions that perform their own commits. The helper promotes source files and commits the transaction only after the callback succeeds.

After the world folder, world database, source records, chunks, locked settings, and source copies are valid, the orchestrator inserts the app index row into `app.sqlite`. That insert is the point where the new world can appear in World Hub.

## Inputs

New World Batch Commit receives:

- New committed world metadata.
- Validated draft splitter settings.
- The active temporary ingestion workspace.
- Accepted hashed staged sources for the first batch.
- An optional app database connection for tests.

The accepted sources are expected to have passed parser, splitter, hash, file access, and preflight work before reaching this boundary.

## Outputs

On success, New World Batch Commit returns the committed world, committed source records, stored chunks, source count, and chunk count. It also leaves durable state in the UUID world folder, the new `world.sqlite`, copied source files, and the global app index.

On failure, it raises the original commit error after rollback and cleanup have been attempted. It must not return partial commit state as if the world were committed.

## Failure Behavior

Cancellation-requested attempts and empty accepted batches are rejected before folder, database, file, or app index creation.

Failures during duplicate validation, source copy preparation, book-number assignment, locked settings writes, source metadata writes, chunk writes, source file copying, file promotion, or world database commit keep the world hidden from World Hub. The orchestrator closes the world database connection, removes the new UUID world folder, logs the failure at `ERROR`, and logs cleanup activity at `WARNING`.

If the final app index insert fails after world data has committed, the orchestrator rolls back the app index transaction, removes the new world folder, logs the failure at `ERROR`, and keeps the world hidden. If cleanup cannot restore filesystem and database consistency, it logs the unrecoverable state at `CRITICAL`.

Logs must not include chunk text, overlap text, raw selected paths, raw local storage paths, filenames, full source text, or local machine details.

## System Interactions

New World Batch Commit interacts with:

- Temporary Ingestion Workspace and Temporary Split Chunk Outputs, which provide attempt-local chunk rows.
- Ingestion Attempt Cancellation, which prevents final commit after Pause has been requested for the attempt.
- Staged Source Hash Preflight and Staged Source Duplicate Preflight, which prepare and validate source hashes.
- Book Number Assignment, which supplies first-batch book numbers.
- Committed World Folder Bootstrap and World Database Bootstrap, which create the UUID storage boundary.
- World Splitter Settings Storage, Committed Source Storage, Chunk Storage, and Committed Source File Storage, which define the durable data contracts written during commit.
- Commit Rollback and Cleanup Helper, which coordinates source file promotion with the world database transaction.
- Committed World Index Storage and Global App Storage, which make the committed world visible through `app.sqlite`.
- The central logger, which records commit, rollback, cleanup, and unrecoverable consistency events without user-owned content.

It must stay separate from parser internals, splitter algorithms, UI progress, World Hub rendering, embeddings, graph extraction, retrieval, chat behavior, and provider systems.

## Current Edge Cases

Internal edge cases:

- Empty accepted batches fail before durable world storage is created.
- Cancellation-requested attempts fail before durable world storage is created.
- A batch that produces no chunks fails before app index visibility.
- Every committed source in the batch must have at least one temporary split chunk.
- Temporary split chunk rows must reference staged source IDs that belong to the accepted batch.
- Duplicate source IDs, duplicate source hashes, duplicate book numbers, duplicate chunk IDs, and duplicate book/chunk positions are rejected before or during the world transaction.
- Source file copy failures prevent world database writes from being committed.
- File promotion and world database commit failures trigger rollback and source file cleanup.
- Cleanup handles already-missing world folders as already cleaned.

Cross-system edge cases:

- World Hub visibility depends on the app index row, so the app index insert must remain last.
- Pause requests must prevent the attempt from reaching final durable commit after cancellation is requested.
- Existing self-committing storage functions must not be called inside the rollback helper transaction.
- Temporary split chunk output can contain chunk text, but commit logs must never include that text.
- Source copy preparation preserves original filenames as metadata, but logs and stored filenames must not expose raw selected paths.
- The new world folder must be removed if final app index insertion fails.
- Failure cleanup must not delete user-selected source files.

## Invariants

- A new world must not appear in World Hub until its world folder, `world.sqlite`, locked splitter settings, committed source records, chunk records, source copies, and app index row are all valid.
- The world ID must be a UUID and must be used consistently for the folder, world database, copied source paths, and app index row.
- Empty worlds must not be committed at this boundary.
- Cancelled attempts must not be committed at this boundary.
- Source file promotion and world database writes must share one rollback-aware commit boundary.
- The app index insert must happen after the world data transaction and source file promotion succeed.
- Cleanup must remove the new world folder when commit fails before visibility or when app index insertion fails after world data commit.
- Logs must not contain chunk text, overlap text, source text, raw local paths, filenames, or user data.

## Implementation Landmarks

- `app/ingestion/new_world_commit.py` owns the orchestration, transaction-safe write helpers, app index insertion, and new-world cleanup behavior.
- `app/storage/committed_source_files.py` prepares source copy pairs and preserves staging entry IDs for chunk/source mapping.
- `app/ingestion/commit_cleanup.py` owns temporary source copy promotion and rollback mechanics.
- `app/storage/worlds.py` owns app index validation rules used by the final visibility insert.
- `tests/test_new_world_commit.py` covers success, rollback, cleanup, app index failure, unrecoverable cleanup logging, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing New World Batch Commit, check:

- Whether the change belongs in final commit orchestration instead of parser, splitter, staging, file validation, storage repository, UI, graph, embedding, retrieval, or chat behavior.
- Whether empty accepted batches are still rejected before any durable world storage is created.
- Whether cancellation-requested attempts are still rejected before any durable world storage is created.
- Whether the app index row is still inserted last.
- Whether source file promotion and world database writes still share the rollback helper boundary.
- Whether transaction-safe helpers still avoid storage functions that call `commit()` internally.
- Whether cleanup still removes the new world folder after world data failure or final app index failure.
- Whether cleanup can fail loudly enough to expose unrecoverable database/filesystem inconsistency.
- Whether logs still avoid chunk text, overlap text, source text, raw local paths, filenames, and user data.
