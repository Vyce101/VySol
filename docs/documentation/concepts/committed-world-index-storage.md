# Committed World Index Storage

Committed World Index Storage is VySol's app-level record system for worlds that have been committed by the backend. It stores world index metadata in `user/data/app.sqlite` so backend systems can create, read, update, mark as used, and list committed worlds without owning world folders, per-world databases, source records, chunk records, graph records, or UI state.

This page is for developers, power users, and AI coding agents that need to understand the committed-world index contract before changing world creation, storage migrations, asset selection, future World Hub behavior, or per-world storage boundaries.

## Why It Exists

VySol needs a durable app-level index of committed worlds before deeper world storage exists. The index lets the backend remember which worlds exist, what display name users chose, optional descriptive text, which background and font asset references belong to the world card or future hub view, and when each committed world was last used.

The index is intentionally separate from per-world storage. It can point to a committed world and preserve user-facing metadata, but it must not become the place where world content, source text, chunks, graph nodes, graph edges, or ingestion state are stored.

## Ownership Boundary

Committed World Index Storage owns:

- Creating committed world index records.
- Reading one committed world index record by world ID.
- Updating a committed world index record by world ID.
- Listing committed world index records in stable display order.
- Listing committed world index records by most recent use.
- Refreshing `last_used_at` when a committed world is created, edited, or explicitly marked as used.
- Generating UUID world IDs with Python standard-library `uuid`.
- Preserving display names exactly as entered.
- Rejecting case-insensitive duplicate display names.
- Storing optional descriptions.
- Storing selected background and font asset references as asset ID strings.
- Storing `last_used_at` timestamps in UTC ISO `YYYY-MM-DD HH:MM:SS` format.
- Logging committed world creation, update, last-used updates, duplicate-name rejection, missing world IDs, and database failures.

Committed World Index Storage does not own:

- Draft world persistence.
- World folder creation or path resolution.
- Per-world databases.
- Source records, chunk records, graph records, or ingestion state.
- Asset metadata creation, upload handling, file copying, or physical asset validation.
- World Hub UI or other user interface flows.
- Customize, Ingestion, chat instance, analytics, or usage-history behavior.

## Normal Flow

Global App Storage applies the migration that creates the `worlds` table. Backend code can then create a committed world request with a display name, optional description, background asset ID, and font asset ID.

Before writing, the storage layer validates that the display name and asset references are non-empty. It stores the display name exactly as entered and also stores an internal normalized display-name key using Python `casefold()` so names like `Naruto`, `naruto`, and `NARUTO` conflict with each other.

If validation and duplicate checks pass, the storage layer generates a UUID world ID, sets `last_used_at`, inserts the row, commits the transaction, logs creation at `INFO`, and returns the saved record. Read and list operations query the same table and map SQLite rows back into committed world objects.

Update operations replace the mutable index fields for an existing world ID and refresh `last_used_at` because metadata edits count as world use. Explicit last-used updates are handled by a dedicated repository function so future world-scoped systems can refresh the timestamp at their real interaction boundaries without owning the timestamp format or SQL update. Missing world IDs return no record; explicit last-used misses are logged at `ERROR`.

## Inputs

Committed World Index Storage receives backend-created committed world metadata: display name, optional description, selected background asset ID, selected font asset ID, and world IDs for later read, update, or mark-used calls. The asset IDs are references to records owned by Asset Metadata Storage; this system does not validate physical files or create asset records.

## Outputs

The system writes committed world index rows into `app.sqlite` and returns committed world objects to backend callers. It can return worlds in stable display order or most-recent-use order. It does not produce folders, per-world databases, UI state, source records, chunk records, graph records, usage-history records, or draft-world records.

## System Interactions

Committed World Index Storage currently interacts with:

- Asset Deletion by exposing whether any committed world uses a candidate asset ID before uploaded asset cleanup.
- Global App Storage, which opens `app.sqlite`, applies migrations, and provides the shared database connection.
- Asset Metadata Storage by storing background and font asset IDs that refer to known asset records.
- Committed World Folder Bootstrap by producing UUID world IDs that can be used for committed world folder paths.
- World Database Bootstrap by producing UUID world IDs that callers can use to open per-world databases.
- Committed World Detail API by serving the global metadata part of a read-only detail load without refreshing `last_used_at`.
- The central logger, which records committed world creation, update, last-used updates, duplicate rejection, missing world IDs, and database failures.

Future World Hub, Customize, Ingestion, chat instance, and graph systems may use committed world IDs as stable references. Systems that represent real world use should call the explicit mark-used repository behavior at their own interaction boundary, but they should keep their own storage responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Empty display names are rejected before a database write.
- Empty background asset references are rejected before a database write.
- Empty font asset references are rejected before a database write.
- Display names are stored exactly as entered, including casing.
- Case-insensitive duplicate display names are rejected before insert or update.
- Created committed worlds receive a `last_used_at` timestamp before insert.
- Committed world metadata updates refresh `last_used_at`.
- Explicit mark-used calls update only `last_used_at`.
- Read-only detail loads return the stored `last_used_at` without changing it.
- Recent-use listing sorts UTC ISO timestamps by natural SQLite text order.
- Missing world IDs return no record instead of creating one.
- Updating a missing world ID returns no record before duplicate-name checks.
- Marking a missing world ID as used returns no record and logs an error.
- SQLite write failures are rolled back, logged at `ERROR`, and re-raised.
- SQLite read failures are logged at `ERROR` and re-raised.

Cross-system edge cases:

- Draft worlds must not be written to the committed world index.
- Asset references are stored as IDs only; this system must not assume a physical asset file exists.
- Committed world folder paths must be handled by Committed World Folder Bootstrap, not by display-name logic in this system.
- Logs must not include sensitive local paths.
- Last-used logs must keep world IDs and timestamps at `DEBUG` when those details are useful.
- Future Customize, Ingestion, and chat instance flows should use the shared mark-used behavior instead of duplicating timestamp SQL.
- The global database must store only the committed world index, not per-world content.

## Invariants

- Committed world IDs must be generated as UUID strings by the storage layer.
- Display names must be preserved exactly as entered.
- Display-name uniqueness must be enforced case-insensitively through the normalized key.
- `description` must remain optional.
- Background and font asset references must be non-empty asset ID strings.
- `last_used_at` must be stored as a zero-padded UTC ISO `YYYY-MM-DD HH:MM:SS` string.
- Recent-use ordering must sort by the natural text order of the UTC ISO timestamp.
- Draft worlds must remain outside this storage system.
- Per-world content must remain outside `app.sqlite`.
- Feature modules must use the central database helper instead of opening separate app database connections ad hoc.

## Implementation Landmarks

- `app/storage/migrations.py` owns the `worlds` table migrations.
- `app/storage/worlds.py` owns committed world validation, create/read/update/list, recent-use listing, and mark-used behavior.
- `tests/test_committed_world_storage.py` covers the current storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Committed World Index Storage, check:

- Whether the change belongs in committed world index metadata or per-world storage.
- Whether schema changes need a new handwritten migration and `PRAGMA user_version` advance.
- Whether draft-world behavior is being accidentally persisted here.
- Whether display-name uniqueness still matches the case-insensitive committed-world rule.
- Whether `last_used_at` is refreshed only for committed-world use signals and not for unrelated storage reads.
- Whether committed detail loads preserve `last_used_at` while still returning the stored value.
- Whether recent-use sorting still relies on UTC ISO timestamp text order correctly.
- Whether logs avoid sensitive local paths and other user-owned details.
- Whether database failures are logged and re-raised without swallowing the original error.
- Whether tests cover create, read, update, list, mark-used behavior, recent-use ordering, duplicate rejection, migration backfill, and database failure behavior.
