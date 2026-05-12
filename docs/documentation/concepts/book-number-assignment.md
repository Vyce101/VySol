# Book Number Assignment

Book Number Assignment is VySol's backend commit-preparation contract for assigning permanent source book numbers to a staged batch after the batch has already been proven ingestible. It reads committed source records from the target world's `world.sqlite` database, finds the highest existing book number, and returns append-only assignments for the staged sources in their current order.

This page is for developers, power users, and AI coding agents that need to understand book numbering before changing source commit orchestration, committed source storage, chunk storage, staging order, or ingestion logging.

## Why It Exists

Book numbers are permanent story-order identity. They must not be assigned while a source is only staged, because parsing, hashing, duplicate checks, splitting, or later commit preparation can still fail.

Keeping assignment in final commit preparation lets VySol preserve the user's staged order without mutating existing committed source order. It also keeps numbering append-only: existing gaps are left alone, and new sources start after the highest committed book number already stored for that world.

## Ownership Boundary

Book Number Assignment owns:

- Reading the highest existing committed source book number from `world.sqlite`.
- Assigning book numbers to a staged batch only after earlier ingestibility checks have succeeded.
- Starting at `1` when a world has no committed sources.
- Appending after the highest existing book number for worlds with committed sources.
- Preserving the caller-provided staged source order.
- Rejecting duplicate staged source IDs before assignment.
- Rejecting assignment ranges that conflict with committed source book numbers.
- Logging assigned ranges at `INFO` or `DEBUG` without source text or paths.
- Logging numbering conflicts and invalid assignment input at `ERROR`.

Book Number Assignment does not own:

- Creating, deleting, reordering, or updating committed source rows.
- Copying source files into world storage.
- Parsing source text, hashing files, duplicate hash preflight, or split chunk preparation.
- Creating permanent source IDs, chunk IDs, stored paths, timestamps, chunks, embeddings, graph records, retrieval state, routes, or UI labels.
- Filling old numbering gaps.
- Displaying `B#` labels in the UI.

## Normal Flow

Earlier ingestion preparation validates source type, source file access, source hashes, duplicate source content, parsed source text, and temporary split chunk output. Once that staged batch is known to be ingestible, future commit orchestration passes the target world database connection and the ordered staged source IDs into Book Number Assignment.

The assignment helper queries `committed_sources` for the highest committed `book_number`. If no committed rows exist, the first staged source receives book number `1`. Otherwise, the first staged source receives the next number after the highest committed book number. Each following staged source receives the next integer in the same staged order.

The helper returns assignment objects to the caller. It does not write them to `world.sqlite`; future commit orchestration is responsible for combining those assignments with source IDs, hashes, stored paths, timestamps, and chunk records during the final atomic commit.

## Inputs

Book Number Assignment receives:

- An open world `sqlite3.Connection`.
- Ordered staged source IDs from the caller's already-validated staged batch.
- Existing committed source book numbers from the world's `committed_sources` table.

It does not receive source paths, filenames, source text, parsed text, chunk text, provider output, user-facing request objects, or final committed source metadata.

## Outputs

The system returns immutable assignment objects containing each staged source ID and its assigned permanent book number.

It does not create database rows, source files, chunks, app-global records, HTTP responses, UI state, or restart-persistent progress.

## Failure Behavior

If staged source IDs are blank or duplicated, assignment fails before any numbers are returned and logs an `ERROR`.

If the committed source table cannot be read, SQLite errors are logged at `ERROR` and re-raised. If the proposed assignment range overlaps existing committed book numbers, assignment fails and logs an `ERROR`. Logs must not include source text, filenames, local paths, or user data.

## System Interactions

Book Number Assignment currently interacts with:

- Temporary Source Staging State, which preserves the staged order that later assignment must use.
- Staged Source Hash Preflight and Staged Source Duplicate Preflight, which should complete before book numbers are assigned.
- Temporary Parsed Source Outputs and Temporary Split Chunk Outputs, which should prove source text and chunks are usable before permanent numbering.
- Committed Source Storage, whose `committed_sources` table is the source of truth for existing book numbers.
- Chunk Storage, whose final chunk rows must use the same book numbers assigned to their source.
- Future commit orchestration, which can combine these assignments with final source and chunk records.
- The central logger, which records assignment ranges and conflicts without source content.

It must stay separate from Global App Storage, parser internals, splitter internals, source file copying, committed source writes, chunk writes, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty staged batches return no assignments.
- New worlds assign the first staged source as book number `1`.
- Existing worlds append after the highest existing committed book number.
- Old gaps are not filled.
- Staged order is preserved exactly.
- Blank staged source IDs are rejected.
- Duplicate staged source IDs are rejected.
- Assignment logs include only the assigned range and count.

Cross-system edge cases:

- Existing committed source order must not change when new staged sources are assigned.
- Book numbers must be assigned after ingestibility checks, not during staging, parsing, hashing, or temporary splitting.
- Future commit orchestration must treat returned assignments as uncommitted until all final database writes and file work succeed.
- Committed Source Storage still enforces unique book numbers when final rows are written.
- Chunk Storage must receive chunk rows that use the same book number assigned to the source.
- Logs must stay safe even if staged source IDs are derived from user-selected paths.

## Invariants

- Committed source rows in `world.sqlite` are the source of truth for existing book numbers.
- Book numbers are positive integers.
- Book numbers are append-only for a world.
- New assignments must start after the highest committed book number.
- Old gaps must not be filled.
- Staged source order must be preserved.
- Assignment must not write committed source records, chunk records, source files, or UI state.
- Logs must not include source text, filenames, raw paths, or local machine details.

## Implementation Landmarks

- `app/ingestion/book_number_assignment.py` owns assignment validation, highest-number lookup, conflict checks, and assignment logging.
- `app/ingestion/__init__.py` exports the public assignment API for future ingestion callers.
- `tests/test_book_number_assignment.py` covers new-world numbering, existing-world append behavior, gap preservation, staged order, conflicts, SQLite failures, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Book Number Assignment, check:

- Whether the change belongs in assignment preparation or in staging, parsing, hashing, split output, source copy, committed source storage, chunk storage, or UI behavior.
- Whether assignment still happens after ingestibility checks and before final committed source/chunk writes.
- Whether committed source records remain the source of truth for existing numbers.
- Whether old gaps are still preserved instead of reused.
- Whether staged order is still preserved exactly.
- Whether the helper remains read-only against `world.sqlite`.
- Whether logs avoid source text, filenames, local paths, and user data.
