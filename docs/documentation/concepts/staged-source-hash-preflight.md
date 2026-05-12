# Staged Source Hash Preflight

Staged Source Hash Preflight is VySol's backend ingestion preflight for calculating temporary content hashes for staged source files before later duplicate checks, book-number assignment, or committed source metadata creation.

This page is for developers, power users, and AI coding agents that need to understand how staged source hashes are produced before changing source staging, duplicate checks, source commit orchestration, file copy behavior, book numbering, or logging.

## Why It Exists

VySol needs future ingestion startup code to identify exact source-file duplicates before assigning permanent book numbers or creating committed source records. A stable content hash lets later duplicate checks and commit logic compare file contents without parsing source text, copying files, or writing database rows during preflight.

This preflight keeps hashing separate from storage and duplicate-blocking policy. It calculates temporary `sha256:<hex>` values and returns them in memory so future orchestration can decide how to use those hashes.

## Ownership Boundary

Staged Source Hash Preflight owns:

- Accepting already-staged temporary source entries.
- Reading each staged source file as bytes in fixed-size chunks.
- Calculating SHA-256 content hashes in `sha256:<hex>` format.
- Returning temporary in-memory hashed staged source objects.
- Preserving the caller's staged source order.
- Logging hash completion summaries without raw local paths or file contents.
- Logging hash or read failures at `ERROR` without raw local paths or file contents.

Staged Source Hash Preflight does not own:

- Selecting files, classifying source types, or deciding whether ingestion can start.
- Proving selected paths exist before hashing.
- Parsing TXT, EPUB, or PDF content.
- Blocking duplicates or deciding duplicate policy.
- Copying, moving, deleting, or storing source files.
- Assigning source IDs, book numbers, chunk numbers, or stored paths.
- Creating committed source records, chunks, embeddings, graph records, manifests, routes, UI state, or progress state.
- Asset hash deduplication for images or fonts.

## Normal Flow

A future Start or Resume ingestion flow can call Staged Source File Access Validation first to prove selected source paths still point to readable files. After access validation succeeds, the same staged entries can be passed into this hash preflight.

The preflight reads each staged source file in binary chunks, updates a SHA-256 hasher, and returns a hashed staged source object containing the original temporary staging entry plus the temporary source hash. Results preserve the input order so later duplicate checks and commit logic can keep using the user's staged order before book numbers are assigned.

## Inputs

The preflight receives a sequence of temporary source staging entries. Each entry already contains the temporary staging entry ID, selected path reference, source file type summary, validity state, and any source-type error message created by earlier staging systems.

It does not receive database connections, parser output, splitter settings, committed source metadata, provider responses, saved manifests, or user-facing request objects.

## Outputs

On success, the preflight returns a tuple of temporary hashed staged source objects. Each object contains:

- The original temporary source staging entry.
- A `source_hash` value formatted as `sha256:<hex>`.

It does not create parsed text, file copies, duplicate decisions, source metadata, chunks, world folders, database rows, UI state, or progress events.

## Failure Behavior

Hashing requires reading the staged file contents as bytes. Missing, unreadable, or otherwise unopenable files log an `ERROR` with safe metadata and re-raise the file read failure so future ingestion startup can stop before duplicate checks or commit logic continue.

Unexpected hash failures are logged at `ERROR` with safe metadata and raised as runtime failures. Logs must not include raw local paths, source text, parsed text, file bytes, usernames, or local machine details.

## System Interactions

Staged Source Hash Preflight currently interacts with:

- Temporary Source Staging State, which owns temporary entries and selected path references.
- Staged Source File Access Validation, which should prove files are readable before this preflight hashes their contents.
- Future duplicate checks, which can compare temporary source hashes before deciding whether a staged source may continue.
- Future source commit orchestration, which can pass the temporary hashes into committed metadata creation after separate source IDs, stored paths, timestamps, and book numbers are prepared.
- The central logger, which records path-safe hash summaries and failures.

It must stay separate from parser internals, storage repositories, route handlers, source copy behavior, asset deduplication, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty input returns an empty tuple.
- Input order is preserved in the hashed output.
- Files are read in chunks instead of being loaded fully into memory.
- Missing or unreadable files log an `ERROR` and raise instead of producing fallback hashes.
- Hash completion logs include counts only, not source contents or full paths.

Cross-system edge cases:

- Access validation should run before hashing so missing or unreadable staged files are blocked consistently.
- Unsupported source types should still be blocked by Source Type Selection Filter before future ingestion startup continues.
- Duplicate checks may use the temporary hashes later, but duplicate-blocking policy is outside this preflight.
- Committed Source Storage may later receive a source hash from commit orchestration, but it must not infer that this preflight created committed metadata.
- Asset hash deduplication remains separate and must not be reused as source ingestion policy.

## Invariants

- Hash values must use the `sha256:<hex>` format expected by source metadata.
- Hashes must stay temporary until future commit orchestration creates committed source records.
- The preflight must not mutate staged entries or source files.
- The preflight must not parse, copy, commit, persist, deduplicate, or assign permanent identity.
- Hashing must read bytes in chunks rather than retaining full source files in memory.
- Logs must not include raw local paths, source text, parsed text, or file contents.

## Implementation Landmarks

- `app/ingestion/staging/source_hash_preflight.py` owns temporary staged source hash calculation.
- `app/ingestion/staging/__init__.py` exports the hash preflight result and function for future ingestion callers.
- `tests/test_staged_source_hash_preflight.py` covers successful hashing, order preservation, empty input, read failures, hash format, and path-safe logging.

## What AI/Coders Must Check Before Changing This System

Before editing Staged Source Hash Preflight, check:

- Whether the change belongs in hashing or in file access validation, source type filtering, parser routing, duplicate checks, file copy, commit orchestration, chunk generation, or UI behavior.
- Whether hashing still produces temporary in-memory results instead of committed metadata.
- Whether hash failures still stop downstream duplicate checks and commit work.
- Whether staged source order is still preserved for future book-number assignment.
- Whether logs avoid source contents and sensitive local path detail.
- Whether tests cover successful hashing, failure behavior, and log safety.
