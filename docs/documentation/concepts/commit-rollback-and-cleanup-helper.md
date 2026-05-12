# Commit Rollback and Cleanup Helper

Commit Rollback and Cleanup Helper is VySol's backend safety contract for future source commit work that must keep copied files and SQLite records in sync. It copies source files to temporary locations first, runs caller-owned database writes inside one transaction, promotes files to their final paths, and cleans up helper-created files when a failure blocks the commit.

This page is for developers, power users, and AI coding agents that need to understand the commit safety boundary before changing ingestion orchestration, committed source file storage, committed source metadata, chunk storage, or rollback logging.

## Why It Exists

Source commit work crosses two storage systems: the filesystem and `world.sqlite`. A failed file copy must not create database rows, and a failed database commit must not leave copied files behind as if the source was committed.

The helper exists to make that failure boundary reusable before full source commit flows are built. It gives future ingestion orchestration one place to coordinate temporary file copies, SQLite transactions, rollback, and idempotent cleanup without mixing those concerns into parser, staging, or storage repositories.

## Ownership Boundary

Commit Rollback and Cleanup Helper owns:

- Receiving caller-prepared file copy pairs and a caller-provided database write callback.
- Rejecting duplicate final destinations and already-existing final destination files before copying.
- Copying files to temporary paths in their destination folders before database writes start.
- Opening the SQLite transaction only after temporary file copies succeed.
- Promoting temporary files to final paths before the database transaction commits.
- Rolling back the active SQLite transaction when commit work fails.
- Cleaning temporary files and helper-promoted final files after failure.
- Keeping cleanup idempotent so retrying cleanup is safe.
- Logging rollback start and completion at `WARNING`.
- Logging cleanup failures at `ERROR` and unrecoverable cleanup inconsistencies at `CRITICAL` without raw local paths.

Commit Rollback and Cleanup Helper does not own:

- Selecting source files, validating source types, reading source text, parsing, splitting, hashing, duplicate preflight, or book-number assignment.
- Creating source IDs, chunk IDs, stored path strings, commit timestamps, manifests, embeddings, graph records, retrieval records, routes, UI state, or user-facing progress.
- Deciding which committed source or chunk records should be written.
- Calling existing storage functions that commit their own transactions from inside its transaction.
- Crash-recovery sweeping for abandoned temporary files after process exit.

## Normal Flow

A future commit orchestrator prepares final file copy pairs and a database write callback. The helper validates the final destinations, creates temporary files beside their intended destinations, and copies the source file bytes into those temporary paths.

After every temporary copy succeeds, the helper starts a SQLite transaction and calls the database write callback. The callback writes records through the provided connection but leaves `commit()` and `rollback()` to the helper.

If the callback succeeds, the helper promotes each temporary file to its final destination and then commits the database transaction. If any step fails, the helper rolls back the transaction when one is active, removes temporary files, removes any final files it promoted, logs the rollback, and re-raises the original failure to the caller.

## Inputs

Commit Rollback and Cleanup Helper receives:

- File copy pairs containing source `Path` objects and final destination `Path` objects.
- An open `sqlite3.Connection`.
- A database write callback that receives that connection.

It does not receive source text, parsed text, chunk text, user-facing request objects, provider responses, or permanent source metadata decisions.

## Outputs

On success, the helper leaves final copied files at their destination paths, commits the caller's SQLite writes, and returns the callback result.

On failure, the helper raises the original error after attempting rollback and cleanup. It does not return partial commit state, create UI state, create manifests, or create retry records.

## Failure Behavior

If validation or file copy fails before the transaction starts, the helper does not call the database write callback and removes any temporary files it created.

If database writes, final file promotion, or database commit fail after the transaction starts, the helper rolls back the transaction when possible and cleans tracked files. Cleanup treats missing files as already cleaned. If cleanup cannot remove a tracked file, the helper logs the cleanup failure at `ERROR`; if any tracked file remains after cleanup, it logs the inconsistency at `CRITICAL`.

Logs must not include raw source paths, final paths, filenames, source text, chunk text, local machine details, or user data.

## System Interactions

Commit Rollback and Cleanup Helper currently interacts with:

- Temporary Split Chunk Outputs, whose temporary rows can later feed commit orchestration.
- Temporary Source Staging State, Source Type Selection Filter, staged source file access validation, staged source hash preflight, and duplicate preflight, which prepare inputs before commit work reaches this helper.
- Committed Source Storage and Chunk Storage, which can later receive caller-prepared records when future transaction-safe write paths are available.
- World Database Bootstrap, which supplies the world database connection.
- Committed World Folder Bootstrap, whose source folder can become the final file destination area.
- The central logger, which records rollback and cleanup failures without local path details.

It must stay separate from parser internals, splitter internals, source staging state, committed source repositories that self-commit, graph extraction, embeddings, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Duplicate final destination paths are rejected before file copies.
- Existing final destination files are rejected before file copies.
- Missing source files fail before database writes.
- File copy failure prevents database writes.
- Database write failure rolls back the transaction and removes temporary copies.
- File promotion failure rolls back the transaction and removes temporary copies.
- Database commit failure rolls back when possible and removes helper-promoted final files.
- Cleanup can be called repeatedly without failing on already-missing tracked files.
- Cleanup failures and remaining tracked files are logged without raw local paths.

Cross-system edge cases:

- Future commit orchestration must complete parser, splitter, hash, duplicate, and book-order decisions before calling this helper.
- Future database write callbacks must not call self-committing storage functions inside the helper transaction.
- Future source commit code must treat temporary files as uncommitted until the helper returns successfully.
- Future chunk or source rows must not be written when file copies fail.
- Future cleanup callers must only track files created or promoted by this helper, not user-selected source files.
- Logs must stay safe even though file paths may point into user-owned storage.

## Invariants

- Database writes must not start until every temporary file copy succeeds.
- Final file promotion must not happen before the database write callback succeeds.
- The helper owns the transaction commit and rollback for its callback.
- File cleanup must be idempotent.
- The helper must not delete source files selected by the user.
- The helper must not create parser output, chunk output, source IDs, chunk IDs, hashes, book numbers, timestamps, embeddings, graph records, retrieval records, routes, or UI state.
- Logs must avoid raw local paths, filenames, source text, chunk text, and user data.

## Implementation Landmarks

- `app/ingestion/commit_cleanup.py` owns the helper dataclasses, transaction wrapper, file preparation, file promotion, rollback, and cleanup behavior.
- `app/ingestion/__init__.py` exports the public helper API for future ingestion callers.
- `tests/test_commit_cleanup.py` covers success, copy failure, write failure, promotion failure, commit failure, idempotent cleanup, cleanup logging, path-safe logging, duplicate destination rejection, and existing destination rejection.

## What AI/Coders Must Check Before Changing This System

Before editing Commit Rollback and Cleanup Helper, check:

- Whether the change belongs in rollback coordination or in parser, splitter, staging, hashing, duplicate checks, committed source storage, chunk storage, graph extraction, retrieval, routes, or UI.
- Whether database writes still start only after temporary file copies succeed.
- Whether cleanup still removes temporary copies and helper-promoted final files after failure.
- Whether cleanup remains safe to retry.
- Whether callbacks are still expected to avoid their own `commit()` and `rollback()` calls.
- Whether logs still avoid raw paths, filenames, source text, chunk text, and local machine details.
