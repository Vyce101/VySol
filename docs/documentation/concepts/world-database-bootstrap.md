# World Database Bootstrap

World Database Bootstrap is VySol's per-world SQLite storage foundation. It creates and opens `world.sqlite` inside `user/worlds/<world_id>/`, applies handwritten migrations with `PRAGMA user_version`, and returns a usable SQLite connection for world-scoped storage.

This page is for developers, power users, and AI coding agents that need to understand the per-world database boundary before changing world storage, ingestion setup, source processing, graph state, or migration behavior.

## Why It Exists

Committed worlds need durable storage that belongs to one world at a time. Keeping world data in `world.sqlite` inside the UUID world folder makes each world easier to inspect, export, migrate, and recover independently from the global app database.

The bootstrap is intentionally narrow. It establishes the database file, schema versioning, migration runner, and baseline metadata table so world-scoped storage systems can add their own tables through explicit world database migrations.

## Ownership Boundary

World Database Bootstrap owns:

- Resolving `world.sqlite` through the committed world UUID folder.
- Creating or opening `user/worlds/<world_id>/world.sqlite`.
- Opening world databases with Python standard-library `sqlite3`.
- Returning SQLite connections configured with row access by column name.
- Reading and writing per-world schema version through `PRAGMA user_version`.
- Applying ordered handwritten world database migrations.
- Creating the world metadata bootstrap schema.
- Logging world database creation, opening, migrations, failed opens, failed migrations, and corrupted database opens.

World Database Bootstrap does not own:

- Creating committed world index records.
- Looking up worlds by display name.
- Draft world persistence.
- Owning splitter settings, source, chunk, embedding, graph, parser, or ingestion table behavior.
- Copying source files into `sources/`.
- Global app database migrations or default app data seeding.
- UI, World Hub behavior, Customize behavior, retrieval, or chat behavior.

## Normal Flow

Backend code calls the world database helper with a committed world UUID. The helper validates the UUID through the committed world folder boundary, creates the committed world folder and `sources/` folder if needed, and then opens `world.sqlite` inside that UUID folder.

After opening the database, the helper reads the current world schema version with `PRAGMA user_version`, applies any pending world database migrations in order, and returns the open SQLite connection. Existing databases are opened and migrated in place; already-applied migrations are skipped.

Each migration runs inside an explicit transaction. A migration advances `user_version` only after its schema changes complete successfully.

## Inputs

World Database Bootstrap receives a `world_id` string. It does not receive display names, draft IDs, source files, parser output, chunk data, provider responses, graph records, or user-facing path text.

## Outputs

The system creates or opens `world.sqlite` under ignored user-owned storage and returns a `sqlite3.Connection`. World migrations may create tables owned by separate world-scoped storage systems; the bootstrap itself does not create source records, chunks, embeddings, graph records, manifests, or UI state.

## Failure Behavior

Filesystem, open, and migration failures are logged and re-raised so callers do not continue with an unsafe or partially migrated world database. Recoverable open and migration failures are logged at `ERROR`; corrupted database opens are logged at `CRITICAL`; world IDs and schema versions stay at `DEBUG`.

## System Interactions

World Database Bootstrap currently interacts with:

- Committed World Folder Bootstrap, which validates UUID world IDs and resolves committed world folders.
- Global App Storage by following the same SQLite and handwritten migration strategy while keeping world content out of `app.sqlite`.
- Committed World Index Storage, which produces stable committed world IDs that callers can pass into world database helpers.
- Committed Source Storage, which owns the committed source metadata table created by a world database migration.
- World Splitter Settings Storage, which owns the splitter settings table created by a world database migration.
- The central logger, which records world database lifecycle and failure events.

Committed source, future ingestion, graph, retrieval, and chat systems may use this bootstrap to reach their world-scoped storage, but each system should own its table behavior and add schema through world database migrations instead of mixing world content into the global app database.

## Current Edge Cases

Internal edge cases:

- Non-UUID world IDs are rejected before database path resolution or database creation.
- Display names are rejected by UUID validation and must not be used for storage paths.
- Missing world folders are created before opening `world.sqlite`.
- Missing `world.sqlite` files are created by SQLite when opened.
- Existing world databases are opened and migrated instead of recreated.
- Already-applied migrations are skipped by comparing against `PRAGMA user_version`.
- World-scoped feature tables can be added by ordered world migrations without moving their repository behavior into the bootstrap module.
- Failed world migrations roll back before the error leaves the migration runner.
- Corrupted world database opens are treated as unrecoverable and logged at `CRITICAL`.

Cross-system edge cases:

- The global database must not receive world content tables just because it already has SQLite helpers.
- Committed world renames must not move or rename the UUID folder or `world.sqlite`.
- Source file storage may use the sibling `sources/` folder, but source metadata rows belong to Committed Source Storage rather than the bootstrap.
- World Splitter Settings Storage may use a world migration for its table, but the bootstrap must not own settings creation, reading, or locking.
- Committed Source Storage may use a world migration for its table, but the bootstrap must not own source metadata validation, append, listing, file copy, or source text processing.
- Future ingestion and graph systems must keep their tables inside the relevant world database, not in `app.sqlite`.
- Logs must avoid local absolute paths and display names.

## Invariants

- World databases must live at `user/worlds/<world_id>/world.sqlite`.
- The folder segment must be the UUID world ID, never the display name.
- World database helpers must accept `world_id` only.
- World database migrations must be separate from global app database migrations.
- Schema version must come from `PRAGMA user_version`.
- A migration must not advance `user_version` unless its schema changes completed successfully.
- World-scoped feature tables must be added through accepted feature work and explicit world migrations.
- World content must remain outside `app.sqlite`.

## Implementation Landmarks

- `app/storage/world_databases.py` owns world database path resolution, opening, bootstrap, and corruption handling.
- `app/storage/world_migrations.py` owns world database migration ordering and `PRAGMA user_version`.
- `app/storage/world_folders.py` owns UUID folder validation and committed world folder creation.
- `tests/test_world_database_bootstrap.py` covers the world database bootstrap contract.

## What AI/Coders Must Check Before Changing This System

Before editing World Database Bootstrap, check:

- Whether the change belongs in world database bootstrap or in committed source, ingestion, graph, retrieval, or UI behavior.
- Whether new world schema needs a handwritten world database migration.
- Whether invalid IDs still fail before filesystem or database writes.
- Whether display names remain out of path resolution and logging.
- Whether migration failures still roll back and re-raise.
- Whether corrupted database opens remain visibly unrecoverable.
- Whether tests prove UUID path resolution, database creation/opening, migration versioning, usable connections, failure logging, and corrupted database behavior.
