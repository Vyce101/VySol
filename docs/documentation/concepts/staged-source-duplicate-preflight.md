# Staged Source Duplicate Preflight

Staged Source Duplicate Preflight is VySol's backend ingestion guard for rejecting exact duplicate staged source content within one committed world before future commit orchestration assigns book numbers.

This page is for developers, power users, and AI coding agents that need to understand source duplicate blocking before changing staged hashing, source commit orchestration, committed source storage, book numbering, or ingestion logging.

## Why It Exists

VySol needs each committed world to avoid storing the same source content twice by accident. Users may select the same file twice, select two files with different names but identical contents, or add a source that already exists in the current world.

The duplicate preflight catches those cases while the sources are still temporary. Blocking at this point keeps future orchestration from assigning new book numbers, copying files, or creating committed source metadata for a batch that cannot be accepted.

## Ownership Boundary

Staged Source Duplicate Preflight owns:

- Accepting already-hashed staged source objects.
- Comparing staged source hashes against committed source hashes in the supplied world database connection.
- Comparing staged source hashes against each other in the same staged batch.
- Rejecting the whole staged batch when duplicate source content is found.
- Returning the original hashed staged source order unchanged when no duplicate exists.
- Logging duplicate-source rejection at `WARNING`.
- Logging duplicate-check SQLite failures at `ERROR`.
- Logging only staged entry IDs, committed source IDs, and hash prefixes at `DEBUG`.

Staged Source Duplicate Preflight does not own:

- Calculating source hashes or reading source files.
- Selecting files, validating file access, classifying source types, or parsing source text.
- Comparing filenames, display names, stored paths, or asset hashes.
- Checking for duplicate source content across different world database connections.
- Assigning source IDs, book numbers, chunk numbers, stored paths, or timestamps.
- Copying, moving, deleting, or storing files.
- Creating committed source records, chunks, embeddings, graph records, manifests, routes, UI state, or progress state.

## Normal Flow

A future ingestion commit flow should validate staged file access, calculate staged source hashes, then pass the hashed staged sources and the target world's open database connection into this duplicate preflight.

The preflight first checks for duplicate hashes inside the staged batch. If the staged batch is internally unique, it queries the same world database's `committed_sources` table for matching `source_hash` values. If no duplicates are found, it returns the hashed staged source tuple unchanged so later orchestration can preserve staged order while assigning book numbers.

## Inputs

The preflight receives an open SQLite connection for one world database and a sequence of hashed staged source objects. Each hashed staged source contains the original temporary staging entry and its temporary `sha256:<hex>` source hash.

It does not receive raw source text, source file bytes, parser output, file-copy results, splitter settings, source metadata drafts, app-global database connections, provider responses, or user-facing request objects.

## Outputs

On success, the preflight returns the original hashed staged source objects as a tuple in the same order the caller provided.

On duplicate detection, it raises a duplicate staged source error before downstream commit work can continue. It does not create files, database rows, source IDs, book numbers, chunks, embeddings, graph records, manifests, UI state, or progress events.

## Failure Behavior

Duplicate content found inside the staged batch or inside the same world database is logged at `WARNING` and raises a duplicate staged source error. The batch is rejected as a whole.

SQLite failures during committed source hash lookup are logged at `ERROR` with exception details and re-raised so the caller can stop ingestion startup. Logs must not include raw local paths, filenames, source text, file bytes, or full source hashes.

## System Interactions

Staged Source Duplicate Preflight currently interacts with:

- Staged Source Hash Preflight, which calculates the temporary source hashes this preflight compares.
- Temporary Source Staging State, whose staged entry IDs may appear in safe debug logs.
- Committed Source Storage, whose per-world `committed_sources.source_hash` values define already-accepted source content for that world.
- Future source commit orchestration, which should call this preflight after hashing and before assigning book numbers.
- The central logger, which records safe duplicate rejection and database failure details.

It must stay separate from parser internals, file-copy behavior, route handlers, asset deduplication, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty input returns an empty tuple and does not require a committed-source lookup.
- Input order is preserved on success.
- Duplicate hashes inside the same staged batch are rejected before committed source lookup.
- Duplicate logs include safe identifiers and hash prefixes only.

Cross-system edge cases:

- Same filenames with different content are allowed because this system compares content hashes, not filenames.
- Same source content in different worlds is allowed because the lookup uses only the supplied world database connection.
- Asset duplicates are not checked here and must remain governed by asset-specific deduplication behavior.
- Book-number assignment must happen only after this preflight succeeds.
- Committed Source Storage may still enforce source ID and book-number uniqueness later, but source hash duplicate policy belongs here.

## Invariants

- Duplicate source content is scoped to one world database connection.
- Matching staged source hashes inside one batch must reject the whole batch.
- Matching staged and committed source hashes in the same world must reject the whole batch.
- The preflight must not assign book numbers or any other permanent identity.
- The preflight must not mutate staged entries, source files, or database rows.
- Logs must not include raw local paths, filenames, source text, file bytes, or full source hashes.

## Implementation Landmarks

- `app/ingestion/staging/source_duplicate_preflight.py` owns duplicate staged source hash validation.
- `app/ingestion/staging/__init__.py` exports the duplicate preflight error and helper for future ingestion callers.
- `tests/test_staged_source_duplicate_preflight.py` covers same-world committed duplicates, same-batch duplicates, cross-world allowance, empty batches, ordering, database failures, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Staged Source Duplicate Preflight, check:

- Whether the change belongs in duplicate policy instead of hashing, staging state, parser routing, file copy, committed source storage, chunk generation, or UI behavior.
- Whether duplicate checks still happen before future book-number assignment.
- Whether duplicate policy remains world-scoped and does not query app-global storage or other world databases.
- Whether same filenames with different content and same content in different worlds remain allowed.
- Whether asset duplicate behavior remains separate.
- Whether logs avoid source contents, full hashes, filenames, and sensitive local path detail.
