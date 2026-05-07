# World Splitter Settings Storage

World Splitter Settings Storage is VySol's committed-world storage contract for the splitter settings saved inside each world's `world.sqlite`. It stores the chunk size, max lookback size, overlap size, splitter version, and lock state that future ingestion code can use after a world is committed.

This page is for developers, power users, and AI coding agents that need to understand how committed splitter settings are persisted before changing world storage, ingestion commit behavior, splitter defaults, or per-world database migrations.

## Why It Exists

Splitter settings affect how source text is expected to be divided into chunks. Once ingestion commits successfully for a world, later systems need a durable record of the settings that shaped that world's stored content.

The storage boundary keeps that record in the world database instead of the global app database. This lets each committed world carry its own splitter settings alongside future world-scoped source, chunk, embedding, graph, and ingestion state.

The lock state exists so future ingestion commit code can mark the settings as fixed after the first successful ingestion commit. This ticket provides the storage contract and lock method only; it does not create the ingestion flow that decides when to call it.

## Ownership Boundary

World Splitter Settings Storage owns:

- Creating the committed-world splitter settings row in `world.sqlite`.
- Reading the persisted splitter settings row.
- Marking splitter settings as locked.
- Storing chunk size, max lookback size, overlap size, splitter version, and lock state.
- Treating splitter sizes as integer character counts.
- Preserving the splitter version as string metadata.
- Logging settings creation and lock at `INFO`.
- Logging numeric settings and splitter version only at `DEBUG`.
- Logging missing or invalid persisted settings state at `ERROR`.
- Rolling back failed write operations before re-raising SQLite failures.

World Splitter Settings Storage does not own:

- Draft world persistence.
- Draft splitter setting updates.
- Settings UI or user-facing controls.
- Splitter execution or recursive text splitting.
- Ingestion source records, chunk records, embeddings, graph records, or provider calls.
- Deciding when the first successful ingestion commit happened.
- Re-ingestion, unlocking, editing locked settings, or settings migration between worlds.
- Global app database storage.

## Normal Flow

World Database Bootstrap creates or opens the committed world's `world.sqlite` and applies the migration that creates the `world_splitter_settings` table.

When future commit code is ready to persist splitter settings for a committed world, backend code creates the default world splitter settings row through the repository. The repository uses the same defaults currently used by Draft World Splitter Settings: `chunk_size` `4000`, `max_lookback_size` `1000`, `overlap_size` `400`, and `splitter_version` `"1"`. The persisted row starts unlocked.

Backend code can read the settings row later from the same world database connection. The repository maps the SQLite row into a storage object with boolean lock state, while the database stores lock state as `0` or `1`.

After future ingestion code completes the first successful ingestion commit, it can call the lock method. Locking updates only the lock state and preserves the stored numeric settings and splitter version.

## Inputs

World Splitter Settings Storage receives an open `sqlite3.Connection` for a world database. It does not receive world display names, draft IDs, source files, parsed text, chunks, embeddings, graph records, provider responses, or UI state.

The create method reads the current default splitter settings from the draft splitter settings module so defaults stay consistent between draft setup and committed storage.

## Outputs

The system writes one settings row to `world_splitter_settings` inside `world.sqlite` and returns stored splitter settings objects to backend callers. It can return no settings when the persisted state is missing or invalid.

It does not produce source files, chunks, embeddings, graph records, manifests, HTTP responses, user-facing state, or app-global database rows.

## Failure Behavior

SQLite read failures are logged at `ERROR` and re-raised so callers do not continue with an unknown settings state.

SQLite create and lock failures are rolled back, logged at `ERROR`, and re-raised. Missing or invalid persisted settings state is logged at `ERROR` and returned as no settings so callers can block unsafe use instead of inventing settings.

Routine creation and lock success are logged at `INFO`. Numeric settings and splitter version are kept at `DEBUG`.

## System Interactions

World Splitter Settings Storage currently interacts with:

- World Database Bootstrap, which opens `world.sqlite` and applies the migration that creates the settings table.
- Draft World Splitter Settings, which owns the default splitter values and version used to seed committed storage.
- Future ingestion commit code, which should call the lock method only after the first successful ingestion commit.
- The central logger, which records settings creation, lock, invalid state, and SQLite failures.

It must stay separate from Global App Storage and Committed World Index Storage. The global app database may identify a committed world, but the splitter settings for that world belong in the world database.

## Current Edge Cases

Internal edge cases:

- Missing settings rows return no settings and log an error.
- Invalid persisted settings rows return no settings and log an error.
- The database schema enforces a singleton settings row with `settings_id` `1`.
- The database schema accepts only `0` or `1` lock state.
- Locking preserves chunk size, max lookback size, overlap size, and splitter version.
- Failed create operations roll back before the SQLite error leaves the repository.
- Failed lock operations roll back before the SQLite error leaves the repository.
- Numeric settings and splitter version are logged only at `DEBUG`.

Cross-system edge cases:

- Draft splitter settings remain in memory and must not be mistaken for committed storage.
- Future ingestion code must lock settings only after a successful first ingestion commit.
- Future ingestion code must not rely on missing settings by silently recreating or guessing them during chunk work.
- Future re-ingestion, unlocking, or settings editing must be added through explicit feature work rather than hidden behavior in this repository.
- World database migrations must remain separate from global app migrations.
- Logs must avoid local absolute paths and display names.

## Invariants

- Committed-world splitter settings must live in the relevant `world.sqlite`.
- The settings table must contain at most one current settings row.
- The lock is one-way for this storage contract.
- Locking must not modify numeric settings or splitter version.
- Splitter size values are integer character counts.
- Splitter version must remain string metadata.
- Missing or invalid persisted settings must not be treated as valid defaults.
- This system must not run the splitter or create ingestion content.
- This system must not write splitter settings to `app.sqlite`.

## Implementation Landmarks

- `app/storage/world_splitter_settings.py` owns committed-world splitter settings create, read, and lock behavior.
- `app/storage/world_migrations.py` owns the migration that creates the settings table.
- `app/draft_worlds/splitter_settings.py` owns the shared default values and splitter version.
- `tests/test_world_splitter_settings_storage.py` covers the committed settings storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing World Splitter Settings Storage, check:

- Whether the change belongs to committed storage or draft setup state.
- Whether new schema changes need a handwritten world database migration.
- Whether settings remain world-scoped instead of app-global.
- Whether missing or invalid persisted settings still fail visibly.
- Whether lock behavior remains one-way.
- Whether logs keep numeric settings and splitter version at `DEBUG`.
- Whether future ingestion code calls lock only after a successful first ingestion commit.
- Whether tests prove creation, reading, locking, missing state, invalid state, rollback behavior, and logging levels.
