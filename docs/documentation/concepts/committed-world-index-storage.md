# Committed World Index Storage

Committed World Index Storage is VySol's app-level record system for worlds that have been committed by the backend. It stores world index metadata in `user/data/app.sqlite` so backend systems can create, read, update, and list committed worlds without creating world folders, per-world databases, source records, chunk records, graph records, or UI state.

This page is for developers, power users, and AI coding agents that need to understand the committed-world index contract before changing world creation, storage migrations, asset selection, future World Hub behavior, or per-world storage boundaries.

## Why It Exists

VySol needs a durable app-level index of committed worlds before deeper world storage exists. The index lets the backend remember which worlds exist, what display name users chose, optional descriptive text, and which background and font asset references belong to the world card or future hub view.

The index is intentionally separate from future per-world storage. It can point to a committed world and preserve user-facing metadata, but it must not become the place where world content, source text, chunks, graph nodes, graph edges, or ingestion state are stored.

## Ownership Boundary

Committed World Index Storage owns:

- Creating committed world index records.
- Reading one committed world index record by world ID.
- Updating a committed world index record by world ID.
- Listing committed world index records in stable display order.
- Generating UUID world IDs with Python standard-library `uuid`.
- Preserving display names exactly as entered.
- Rejecting case-insensitive duplicate display names.
- Storing optional descriptions.
- Storing selected background and font asset references as asset ID strings.
- Logging committed world creation, update, duplicate-name rejection, and database failures.

Committed World Index Storage does not own:

- Draft world persistence.
- World folders.
- Per-world databases.
- Source records, chunk records, graph records, or ingestion state.
- Asset metadata creation, upload handling, file copying, or physical asset validation.
- World Hub UI or other user interface flows.

## Normal Flow

Global App Storage applies the migration that creates the `worlds` table. Backend code can then create a committed world request with a display name, optional description, background asset ID, and font asset ID.

Before writing, the storage layer validates that the display name and asset references are non-empty. It stores the display name exactly as entered and also stores an internal normalized display-name key using Python `casefold()` so names like `Naruto`, `naruto`, and `NARUTO` conflict with each other.

If validation and duplicate checks pass, the storage layer generates a UUID world ID, inserts the row, commits the transaction, logs creation at `INFO`, and returns the saved record. Read and list operations query the same table and map SQLite rows back into committed world objects. Update operations replace the mutable index fields for an existing world ID and return no record when the world ID is missing.

## Inputs

Committed World Index Storage receives backend-created committed world metadata: display name, optional description, selected background asset ID, and selected font asset ID. The asset IDs are references to records owned by Asset Metadata Storage; this system does not validate physical files or create asset records.

## Outputs

The system writes committed world index rows into `app.sqlite` and returns committed world objects to backend callers. It does not produce folders, per-world databases, UI state, source records, chunk records, graph records, or draft-world records.

## System Interactions

Committed World Index Storage currently interacts with:

- Global App Storage, which opens `app.sqlite`, applies migrations, and provides the shared database connection.
- Asset Metadata Storage by storing background and font asset IDs that refer to known asset records.
- The central logger, which records committed world creation, update, duplicate rejection, and database failures.

Future World Hub, world folder, per-world database, ingestion, and graph systems may use committed world IDs as stable references, but those systems should keep their own storage responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Empty display names are rejected before a database write.
- Empty background asset references are rejected before a database write.
- Empty font asset references are rejected before a database write.
- Display names are stored exactly as entered, including casing.
- Case-insensitive duplicate display names are rejected before insert or update.
- Missing world IDs return no record instead of creating one.
- Updating a missing world ID returns no record before duplicate-name checks.
- SQLite write failures are rolled back, logged at `ERROR`, and re-raised.
- SQLite read failures are logged at `ERROR` and re-raised.

Cross-system edge cases:

- Draft worlds must not be written to the committed world index.
- Asset references are stored as IDs only; this system must not assume a physical asset file exists.
- Logs must not include sensitive local paths.
- The global database must store only the committed world index, not per-world content.

## Invariants

- Committed world IDs must be generated as UUID strings by the storage layer.
- Display names must be preserved exactly as entered.
- Display-name uniqueness must be enforced case-insensitively through the normalized key.
- `description` must remain optional.
- Background and font asset references must be non-empty asset ID strings.
- Draft worlds must remain outside this storage system.
- Per-world content must remain outside `app.sqlite`.
- Feature modules must use the central database helper instead of opening separate app database connections ad hoc.

## Implementation Landmarks

- `app/storage/migrations.py` owns the `worlds` table migration.
- `app/storage/worlds.py` owns committed world validation and create/read/update/list behavior.
- `tests/test_committed_world_storage.py` covers the current storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Committed World Index Storage, check:

- Whether the change belongs in committed world index metadata or future per-world storage.
- Whether schema changes need a new handwritten migration and `PRAGMA user_version` advance.
- Whether draft-world behavior is being accidentally persisted here.
- Whether display-name uniqueness still matches the case-insensitive committed-world rule.
- Whether logs avoid sensitive local paths and other user-owned details.
- Whether database failures are logged and re-raised without swallowing the original error.
- Whether tests cover create, read, update, list, duplicate rejection, and database failure behavior.
