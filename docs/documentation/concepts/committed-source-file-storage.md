# Committed Source File Storage

Committed Source File Storage is VySol's commit-time file copy contract for accepted source files. It prepares safe internal filenames, preserves the original filename as metadata, and coordinates source file copies with the commit rollback helper so copied files are only exposed after the wider commit succeeds.

This page is for developers, power users, and AI coding agents that need to understand committed source file copying before changing source commit orchestration, path handling, committed source metadata, chunk storage, or rollback behavior.

## Why It Exists

User-selected filenames are useful metadata, but they are not safe durable storage keys. VySol needs committed source copies to live under the committed world's `sources/` folder with internal filenames that do not depend on local paths, display names, or user-controlled folder structures.

The file-copy boundary also has to stay tied to commit success. A failed copy must block database writes, and a later database or promotion failure must not leave files visible as committed sources.

## Ownership Boundary

Committed Source File Storage owns:

- Preparing source IDs for accepted staged sources.
- Building safe stored source filenames from generated IDs and conservative suffixes.
- Preserving the original filename as metadata only.
- Preparing `sources/<internal-filename>` stored path strings for future metadata writes.
- Preparing file copy pairs for the commit rollback helper.
- Running source file copies through the rollback-aware commit wrapper.
- Logging copy preparation and successful copy summaries at `INFO`.
- Logging copy failures at `ERROR` without raw paths or filenames.
- Logging unsafe filename or storage path attempts at `WARNING`.

Committed Source File Storage does not own:

- Selecting files, validating source types, validating file access, parsing source text, hashing file contents, or duplicate source checks.
- Assigning book numbers, chunk numbers, commit timestamps, or chunk IDs.
- Writing committed source rows, chunk rows, graph records, embeddings, route responses, or UI state.
- Deleting user-selected source files.

## Normal Flow

Earlier ingestion preparation accepts a staged source batch by validating file type, file access, hash, duplicate status, parsing, and chunk preparation. Commit orchestration then passes the target world ID and the already-hashed accepted sources into Committed Source File Storage.

For each accepted source, this system generates a source ID, reads only the final filename component from the current source path for original-filename metadata, derives a conservative suffix, and prepares a final destination inside the world's `sources/` folder. It returns prepared source file objects containing source ID, original filename, stored path, source type, source hash, and the file copy pair.

When commit orchestration is ready to write durable records, it can pass those prepared objects and a database-write callback into the rollback-aware wrapper. The wrapper delegates temporary copying, transaction control, final promotion, rollback, and cleanup to Commit Rollback and Cleanup Helper.

## Inputs

Committed Source File Storage receives a committed world ID and accepted hashed staged sources. Each hashed source contains the current source file path, staged source file type, staging entry metadata, and source hash.

The wrapper receives an open world database connection, prepared committed source file objects, and a caller-owned database callback.

## Outputs

The preparation step returns immutable prepared source file objects and does not write files or database records.

The commit wrapper copies source files into the committed world's `sources/` folder only when the rollback helper reaches final file promotion. It returns the caller callback result after the helper commits the database transaction.

## Failure Behavior

Invalid world IDs fail through the committed-world folder boundary before source destinations are prepared. Unsupported filename suffixes are ignored after a path-safe warning, allowing storage to continue with the generated ID alone.

Copy failures are logged at `ERROR`, abort the whole commit, and prevent the database callback from running. Database callback failures, file promotion failures, and commit failures are rolled back by the commit helper, which removes temporary files and any helper-promoted final files.

Logs must not include raw selected paths, source filenames, source text, file bytes, local machine details, or user data.

## System Interactions

Committed Source File Storage currently interacts with:

- Temporary Source Staging State, Staged Source Hash Preflight, and duplicate preflight, which prepare accepted source inputs before copy preparation.
- Committed World Folder Bootstrap, which resolves the target world's `sources/` folder.
- Commit Rollback and Cleanup Helper, which performs temporary copying, promotion, transaction control, rollback, and cleanup.
- Committed Source Storage, which can receive the prepared source ID, original filename, stored path, file type, and hash during the same wider commit.
- Chunk Storage, which can be written by the same wider commit after source IDs and book numbers are known.
- The central logger, which records safe copy preparation, copy success, unsafe filename attempts, and copy failures.

It must stay separate from parser internals, splitter internals, staging mutation, committed source metadata validation, graph extraction, embeddings, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty accepted batches return an empty prepared-source tuple and can run through the wrapper with no file copies.
- Original filenames are preserved only as metadata and never used as the stored filename.
- Uppercase safe suffixes are normalized to lowercase for stored filenames.
- Unsupported suffixes are omitted from the stored filename after a warning.
- Final destinations are checked to stay inside the world `sources/` folder.
- Duplicate final destinations and existing final files are rejected by the rollback helper before copying.

Cross-system edge cases:

- Copy preparation must run after source acceptance checks, not at selection time.
- A copied file must not be treated as committed until the rollback helper returns successfully.
- Committed source metadata and chunk rows must not be written when any source copy fails.
- Future source metadata writes must use the prepared original filename and stored path instead of recalculating them from user paths.
- Commit orchestration callbacks must not call self-committing storage helpers inside the rollback helper transaction.

## Invariants

- Stored source copies must live under the committed world's `sources/` folder.
- Stored filenames must use generated source IDs, not original filenames.
- Original filenames must remain metadata only.
- File copying must happen during commit work, not at source selection time.
- File copy failure must abort the whole commit.
- Partial copies must not be exposed as committed source files.
- The system must not parse files, assign book numbers, or write committed database records by itself.
- Logs must avoid raw paths, filenames, source text, file bytes, and local machine details.

## Implementation Landmarks

- `app/storage/committed_source_files.py` owns committed source file copy preparation and the rollback-aware source copy wrapper.
- `app/ingestion/commit_cleanup.py` owns temporary copy, promotion, rollback, and cleanup mechanics.
- `app/storage/world_folders.py` owns committed world source folder resolution.
- `tests/test_committed_source_file_storage.py` covers committed source file storage behavior.

## What AI/Coders Must Check Before Changing This System

Before editing Committed Source File Storage, check:

- Whether the change belongs in file copy preparation instead of staging, parsing, hashing, duplicate checks, book-number assignment, committed source metadata, chunk storage, graph extraction, retrieval, or UI.
- Whether copied files still remain invisible as committed sources until the wider commit succeeds.
- Whether source IDs remain the stored filename basis.
- Whether original filenames remain metadata only.
- Whether callback code still leaves transaction control to the rollback helper.
- Whether logs avoid raw paths, filenames, source text, file bytes, and local machine details.
