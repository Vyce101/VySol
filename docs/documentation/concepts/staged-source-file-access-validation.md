# Staged Source File Access Validation

Staged Source File Access Validation is VySol's backend preflight for proving selected source file references still point to readable files before future ingestion startup work begins.

This page is for developers, power users, and AI coding agents that need to understand how staged file access is checked before changing source staging, parser routing, source copy behavior, book numbering, chunk generation, commit orchestration, or logging.

## Why It Exists

VySol's staging state stores selected file paths as references. It does not copy source files when the user selects them, so a file can be moved, deleted, replaced by a folder, or become unreadable before a future Start or Resume action tries to ingest it.

This validation layer gives future ingestion startup code one reusable gate that can fail the whole staged batch before parser, hash, copy, numbering, chunk, or commit work starts.

## Ownership Boundary

Staged Source File Access Validation owns:

- Accepting already-staged temporary source entries.
- Checking each staged `source_file_path` with `pathlib`.
- Rejecting the whole batch if any staged path is missing.
- Rejecting the whole batch if any staged path is not a regular file.
- Rejecting the whole batch if any staged file cannot be opened for binary reading.
- Returning the original staged entries unchanged when every staged file is available.
- Logging expected missing or unreadable staged files at `WARNING` without raw local paths.
- Logging unexpected file access failures at `ERROR` without raw local paths.

Staged Source File Access Validation does not own:

- Selecting files, classifying source types, or deciding whether the staging list is empty.
- Parsing TXT, EPUB, or PDF content.
- Hashing, copying, moving, deleting, or committing source files.
- Assigning source IDs, book numbers, chunk numbers, or stored paths.
- Creating world folders, database rows, chunks, embeddings, graph records, manifests, routes, UI state, or progress state.

## Normal Flow

A future Start or Resume ingestion flow can read temporary staging entries and call this validator before doing any work that reads content, copies files, assigns permanent ordering, or writes world data.

The validator converts each staged path through `pathlib.Path`, checks that it exists, checks that it is a regular file, then opens it in binary read mode and reads only a tiny probe. The probe proves the app can open the file without treating the bytes as source content.

If every staged file passes, the validator returns the same staged entries in the same order. If any staged file fails, the validator logs a safe batch summary and raises a staged source file access error.

## Inputs

The validator receives a sequence of temporary source staging entries. Each entry already contains the temporary staging entry ID, selected path reference, source file type summary, validity state, and any source-type error message created by Temporary Source Staging State and Source Type Selection Filter.

It does not receive database connections, parser output, splitter settings, provider responses, saved manifests, or user-facing request objects.

## Outputs

On success, the validator returns a tuple containing the original staged entries unchanged. This keeps it usable as a future Start or Resume preflight without converting entries into committed metadata.

On failure, it raises a staged source file access error for expected missing or unreadable staged files. Unexpected file access failures are raised as runtime failures after a path-safe error log.

It does not create parsed text, file copies, hashes, source metadata, chunks, world folders, database rows, UI state, or progress events.

## Failure Behavior

Expected access failures are batch-blocking failures. Missing paths, non-file paths, and files that cannot be opened for reading are collected and logged at `WARNING` as safe metadata: count, staging entry ID, source type, and reason.

Unexpected access failures are logged at `ERROR` with safe metadata and the exception type. Logs must not include raw local paths, source text, parsed text, file bytes, usernames, or local machine details.

## System Interactions

Staged Source File Access Validation currently interacts with:

- Temporary Source Staging State, which owns temporary entries and selected path references.
- Source Type Selection Filter, which marks unsupported source types before this validator is useful for ingestion startup.
- Staged Source Hash Preflight, which can hash staged source contents after file access has already been validated.
- Source Parser Router, which should only receive staged sources after type validity and file access preflight pass.
- Future Start and Resume ingestion orchestration, which can call this gate before hashing, parsing, copying, numbering, chunking, or committing.
- The central logger, which records path-safe access failure summaries.

It must stay separate from parser internals, storage repositories, route handlers, source copy behavior, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty input returns an empty tuple; Source Type Selection Filter owns the policy that an empty staged list cannot start ingestion.
- Missing paths are reported as missing staged files.
- Directories and other non-file paths are reported as non-file staged entries.
- Permission or open failures are reported as unreadable staged files.
- Multiple expected failures are collected before the batch is rejected.
- Successful validation preserves the caller's staged entry objects and order.

Cross-system edge cases:

- Staging state may contain path references that were valid at selection time but no longer exist at Start or Resume time.
- Unsupported source types should still be blocked by Source Type Selection Filter before parser routing.
- Parser Router may still reject malformed content later; this validator only proves file availability, not parseability.
- Future hash, copy, book-number, chunk, and commit systems must run only after this validator succeeds.
- Logs must remain safe for public repositories and local machines by avoiding full selected paths.

## Invariants

- Validation must happen before future parsing, copying, source hashing, book-number assignment, chunk generation, and source commit work.
- Expected missing or unreadable staged files must block the whole batch.
- Successful validation must not mutate staged entries or source files.
- The validator must not parse, hash, copy, commit, persist, or assign permanent identity.
- File access checking must use `pathlib` rather than ad hoc string path handling.
- Readability probing must not load or retain source content.
- Logs must not include raw local paths or source text.

## Implementation Landmarks

- `app/ingestion/staging/source_file_access.py` owns staged source file access validation.
- `app/ingestion/staging/__init__.py` exports the validator and error for future ingestion callers.
- `tests/test_staged_source_file_access.py` covers success, missing paths, non-file paths, unreadable files, unexpected access failures, empty input, batch rejection, and path-safe logging.

## What AI/Coders Must Check Before Changing This System

Before editing Staged Source File Access Validation, check:

- Whether the change belongs in file access preflight or in source type filtering, parser routing, file copy, hashing, commit orchestration, chunk generation, or UI behavior.
- Whether every expected file access failure still blocks the whole staged batch.
- Whether validation still runs without assigning source IDs, book numbers, hashes, stored paths, chunks, or database rows.
- Whether the validator still returns staged entries unchanged on success.
- Whether unexpected error logs avoid exception text that may contain raw paths.
- Whether tests cover both expected failures and log safety.
