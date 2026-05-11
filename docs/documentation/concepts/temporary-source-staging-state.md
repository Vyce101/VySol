# Temporary Source Staging State

Temporary Source Staging State is VySol's in-memory backend contract for holding selected source file references while a user is preparing draft-world or existing-world add-source work. It keeps source entries visible and editable before any future commit flow decides what should become durable world data.

This page is for developers, power users, and AI coding agents that need to understand temporary source staging before changing draft setup, existing-world add-source behavior, source selection, commit orchestration, file storage, or logging.

## Why It Exists

VySol needs users to select multiple source files, inspect the order, remove mistakes, and reorder the batch before later ingestion work commits anything to a world. The staging state gives backend callers a temporary place to hold those file references without treating them as committed sources.

The boundary matters because selected file paths are local UI/app state. They must not become `world.sqlite` rows, copied files, hashes, permanent book numbers, chunks, embeddings, graph records, or app-global records just because the user has selected them.

## Ownership Boundary

Temporary Source Staging State owns:

- Creating caller-keyed staging contexts for draft-world and existing-world add-source flows.
- Holding ordered temporary source entries in process memory.
- Adding selected file paths as staging entries.
- Reusing Source Type Selection Filter for extension-based file type and validity state.
- Removing staged entries by temporary staging entry ID.
- Reordering staged entries by an explicit list of existing staging entry IDs.
- Replacing or discarding a staging context when the caller's flow no longer needs it.
- Logging add and remove summaries at `DEBUG` without raw local paths.
- Logging staging state failures at `ERROR` without raw local paths.

Temporary Source Staging State does not own:

- Persisting staged sources to `app.sqlite` or `world.sqlite`.
- Copying selected files into app or world storage.
- Parsing source text, checking file existence, hashing files, assigning book numbers, committing source metadata, creating chunks, embeddings, graph records, manifests, or provider calls.
- UI rendering, file picker behavior, HTTP route design, or committed source ordering after commit.

## Normal Flow

A caller creates a staging context with an ID owned by the draft-world or existing-world add-source flow. When the user selects files, the caller adds selected paths to that context. Each selected path becomes a temporary entry with a generated staging entry ID, the original path object, the source type summary from Source Type Selection Filter, validity state, and any invalid-type error message.

The caller can remove individual entries by staging entry ID. The caller can reorder entries by passing the complete ordered list of existing staging entry IDs. Reorder requests must match the current entries exactly so accidental drops, duplicates, or unknown entry IDs are rejected instead of silently changing the batch.

When the user leaves before commit, cancels, or finishes a later successful commit flow, the caller discards the staging context. Discarding removes the in-memory staging entries and does not touch any database or file storage.

## Inputs

Temporary Source Staging State receives staging context IDs from callers, selected source file paths, staging entry IDs for removal, and ordered staging entry IDs for reorder. It does not receive database connections, source file contents, parser output, splitter output, hashes, book numbers, provider responses, or committed source metadata.

## Outputs

The system returns in-memory source staging state objects containing ordered temporary entries. Each entry contains:

- A temporary staging entry ID.
- The selected source file path.
- The source file type summary.
- A validity state.
- An error message for invalid source types.

It does not create database rows, copy files, parse text, create chunks, call providers, or assign permanent source identity.

## Failure Behavior

Missing staging contexts return no staging state instead of creating hidden persistent state. Invalid staging context IDs, duplicate replacement entry IDs, and reorder requests that do not match the current entries are logged at `ERROR` and rejected as staging state failures.

Unexpected add failures are logged at `ERROR` and raised as temporary source staging failures. Logs must not include raw selected source paths, source text, local machine details, or user data.

## System Interactions

Temporary Source Staging State currently interacts with:

- Source Type Selection Filter, which classifies selected paths and marks unsupported file types as invalid staging items.
- Future draft-world and existing-world add-source flows, which can create, edit, and discard staging contexts.
- Future commit orchestration, which can read temporary state before separate systems parse, copy, hash, assign book numbers, and commit sources.
- The central logger, which records path-safe staging summaries and failures.

It must stay separate from Global App Storage, World Database Bootstrap, Committed Source Storage, parser internals, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Missing contexts return no state for read, add, remove, reorder, and discard operations.
- Adding paths preserves existing entries and appends new entries in selection order.
- Unsupported or extensionless paths remain visible as invalid entries through Source Type Selection Filter.
- Removing a missing entry from an existing context leaves the other entries unchanged.
- Reorder requests must include every current staging entry ID exactly once.
- Replacing a context rejects duplicate staging entry IDs.
- Staging entries do not include or assign `book_number`.

Cross-system edge cases:

- Draft-world and existing-world add-source flows must discard staging contexts when the user leaves before commit.
- Staged paths are references only; later commit work must still decide whether and how to parse, copy, hash, order, and persist sources.
- Future commit code must not infer that staging state has already produced committed source IDs, stored paths, source hashes, permanent book numbers, chunks, or database rows.
- Staging state must not create or migrate app-global or per-world database tables.
- Logs must avoid full source paths and local machine details.

## Invariants

- Temporary source staging state must remain in memory.
- Staged entries must preserve caller-visible order until explicitly reordered.
- Reorder operations must not add, drop, or duplicate entries.
- Removing entries must not delete, move, or modify files.
- Source type classification must stay delegated to Source Type Selection Filter.
- The system must not parse, hash, copy, commit, persist, or assign book numbers for staged sources.
- No database migration is required for temporary source staging state.

## Implementation Landmarks

- `app/ingestion/staging/source_staging_state.py` owns temporary staging contexts, entries, add/remove/reorder/discard behavior, and path-safe staging logs.
- `app/ingestion/staging/source_type_filter.py` owns extension-based source type classification and invalid source type messages.
- `tests/test_source_staging_state.py` covers temporary state lifecycle, ordering, removal, discard behavior, database non-persistence, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Temporary Source Staging State, check:

- Whether the change still belongs to temporary staging state or belongs in parser routing, commit orchestration, file copy, committed source storage, chunk storage, UI, or route handling.
- Whether selected paths remain references instead of copied files.
- Whether staged entries still avoid permanent source IDs, hashes, stored paths, book numbers, and database rows.
- Whether reorder behavior still requires the complete current entry set.
- Whether callers can discard staging state when a draft or add-source flow ends before commit.
- Whether logs avoid raw source paths, source text, local machine details, and user data.
