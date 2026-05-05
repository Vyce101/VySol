# Global App Storage

Global App Storage is VySol's app-wide SQLite storage foundation. It creates and opens the repo-local `user/data/app.sqlite` database, applies handwritten migrations, and exposes a reusable global database connection for backend code.

This page is for developers, power users, and AI coding agents that need to understand the storage boundary before changing startup, migrations, database helpers, or future app-wide data.

## Why It Exists

VySol needs a small global database for app-level state before world-specific storage exists. The global database gives startup a known place to create, open, version, and migrate app-wide data without mixing that data into future per-world databases.

This boundary matters because later worlds should be easier to export, inspect, recover, and ingest independently. Future world records, graph extraction data, chunks, nodes, edges, and assets should not be added to `app.sqlite` just because a SQLite connection already exists.

## Ownership Boundary

Global App Storage owns:

- Creating `user/data/app.sqlite` when it is missing.
- Opening the global SQLite database with Python standard-library `sqlite3`.
- Reading and writing schema version through `PRAGMA user_version`.
- Applying ordered handwritten migrations.
- Returning a usable global database connection.
- Closing the global connection during backend shutdown.

Global App Storage does not own:

- World records or per-world databases.
- Asset records, chunk storage, graph nodes, graph edges, or graph manifestation.
- Ingestion, parsing, embeddings, provider keys, retrieval, or chat.
- User interface state.
- Launcher logs or documentation build output.

## Normal Flow

On backend startup, the FastAPI lifespan calls the global database bootstrap. The bootstrap ensures the `user/data/` folder exists, opens or creates `app.sqlite`, reads the current schema version, applies any pending migrations in order, and stores the resulting connection as the global connection.

Each migration runs inside an explicit transaction. After a migration succeeds, the database `user_version` is advanced to that migration version. If a migration fails, the transaction is rolled back and startup fails instead of serving the app with a partially migrated database.

On backend shutdown, the global connection is closed.

## System Interactions

Global App Storage currently interacts with:

- Backend startup, which initializes storage before the app is considered ready.
- The health endpoint indirectly, because startup must complete before the backend can serve normally.
- The launcher, which starts the backend and waits for its health check.
- Future global app systems, such as settings, hub metadata, or world indexes.

It must stay separate from future per-world storage. The global database may eventually point to worlds or store app-level metadata about them, but it should not become the storage location for world content itself.

## Current Edge Cases

Internal edge cases:

- Missing `user/data/` folders are created before opening the database.
- Missing `app.sqlite` is created by SQLite when opened.
- Existing databases are opened and migrated instead of recreated.
- Already-applied migrations are skipped by comparing against `PRAGMA user_version`.
- Failed SQLite setup or migration work is logged and re-raised.
- Failed migrations roll back their transaction before the error leaves the migration runner.

Cross-system edge cases:

- Backend startup treats unrecoverable database bootstrap failure as a startup failure.
- The launcher can report backend readiness only after database bootstrap succeeds.
- Future world storage must not silently reuse the global database for per-world content.

## Invariants

- `app.sqlite` is the global app database, not a world database.
- Schema version must come from `PRAGMA user_version`.
- Migrations must be ordered, handwritten, and idempotent when rerun against an already-migrated database.
- A migration must not advance `user_version` unless its schema changes completed successfully.
- Startup must not continue after an unrecoverable database bootstrap failure.
- Feature modules must use the central database helper instead of opening their own global app connection ad hoc.
- New world, asset, ingestion, parser, chunk, node, or edge storage must not be added to the global database without a new accepted storage decision.

## Implementation Landmarks

- `app/storage/paths.py` defines repo-local storage paths.
- `app/storage/database.py` owns global database bootstrap and connection management.
- `app/storage/migrations.py` owns migration ordering and `PRAGMA user_version`.
- `app/main.py` initializes storage during backend lifespan startup.

## What AI/Coders Must Check Before Changing This System

Before editing Global App Storage, check:

- Whether the change belongs in global app storage or future per-world storage.
- Whether a new migration is needed and whether it advances `PRAGMA user_version`.
- Whether startup still fails loudly on unrecoverable database setup problems.
- Whether tests cover missing database creation, schema versioning, migration ordering, and usable connections.
- Whether the change preserves the ADR decision for SQLite and handwritten migrations.
