# Committed Source Storage

Committed Source Storage is VySol's per-world metadata record for source files that have been committed into a world. It stores committed source metadata in the world's `world.sqlite` database so later ingestion, chunking, graph, and retrieval systems can identify the immutable source set without depending on draft state or app-global storage.

This page is for developers, power users, and AI coding agents that need to understand the committed source metadata contract before changing source commit behavior, world database migrations, file-copy behavior, parser setup, chunk creation, or book ordering.

## Why It Exists

Committed worlds need a durable list of the sources that belong to that world. The list must be stable after commit so later systems can refer to source IDs, stored paths, hashes, and permanent book numbers without recalculating or reordering them.

The storage boundary is intentionally narrow. It records caller-prepared metadata only. It does not copy files, calculate hashes, assign book numbers, parse source text, or create chunks.

## Ownership Boundary

Committed Source Storage owns:

- Storing committed source metadata rows in `world.sqlite`.
- Preserving caller-provided source IDs, original filenames, stored path strings, file types, hashes, book numbers, and commit timestamps.
- Rejecting blank required metadata before insert.
- Rejecting duplicate source IDs and duplicate book numbers.
- Listing committed source records in stable book order.
- Logging successful appends at `INFO`.
- Logging duplicate or invalid metadata rejection at `WARNING`.
- Logging SQLite failures at `ERROR`.

Committed Source Storage does not own:

- Copying source files into the world `sources/` folder.
- Calculating source hashes, file types, source IDs, book numbers, or commit timestamps.
- Assigning or reassigning book numbers.
- Deleting, replacing, reordering, or re-splitting committed sources.
- Parser logic, source text extraction, chunk creation, embeddings, graph records, retrieval, or UI state.
- Committed world index records or global app database storage.

## Normal Flow

World Database Bootstrap opens the committed world's `world.sqlite` and applies the migration that creates the committed source table.

After separate commit-time systems have copied files, calculated hashes, assigned book numbers, and chosen one batch commit timestamp, backend code can pass the final metadata into the committed source repository. The repository validates required fields, checks for duplicate source IDs or book numbers, inserts the row, commits the transaction, logs the append, and returns the stored record.

Later backend code can list committed sources from the same world database connection. Results are ordered by permanent `book_number`, with `source_id` as a stable tie-breaker.

## Inputs

Committed Source Storage receives an open `sqlite3.Connection` for a world database and caller-prepared source metadata: source ID, original filename, stored path string, source file type, source hash, permanent book number, and committed timestamp.

The committed timestamp must be supplied by the caller in UTC ISO format, `YYYY-MM-DD HH:MM:SS`, so every source in the same commit batch can share the same value.

## Outputs

The system writes committed source metadata rows to `world.sqlite` and returns immutable committed source objects to backend callers. It can return the committed source list in book order.

It does not produce source files, source text, chunks, embeddings, graph records, manifests, app-global rows, HTTP responses, or user-facing state.

## Failure Behavior

Invalid metadata and duplicate source identity or book order are rejected before insert, logged at `WARNING`, and raised as committed source validation errors.

SQLite duplicate checks, inserts, and reads are logged at `ERROR` and re-raised when they fail. Failed inserts roll back before the SQLite error leaves the repository. Logs must never include full source text.

## System Interactions

Committed Source Storage currently interacts with:

- World Database Bootstrap, which opens `world.sqlite` and applies the committed source table migration.
- Committed Source File Storage, which prepares safe stored source paths and copies accepted files into the world `sources/` folder during the wider commit.
- Committed World Folder Bootstrap, whose `sources/` folder is where committed source file copies are stored.
- Book Number Assignment, which reads existing committed source rows before future commit orchestration saves new source metadata.
- Commit-time hashing and file-type detection systems, which prepare metadata before this repository saves it.
- Future ingestion, chunk, graph, and retrieval systems, which can read committed source metadata but must keep their own storage responsibilities separate.
- The central logger, which records source metadata append, rejection, and database failure events.

It must stay separate from Global App Storage and Committed World Index Storage. The global app database can identify a committed world, but source metadata belongs in that world's database.

## Current Edge Cases

Internal edge cases:

- Blank source IDs are rejected before insert.
- Blank original filenames, stored paths, file types, hashes, and timestamps are rejected before insert.
- Non-integer book numbers and book numbers below `1` are rejected before insert.
- Duplicate source IDs are rejected before insert.
- Duplicate book numbers are rejected before insert.
- Listing an empty source table returns an empty list.
- Failed inserts roll back before the error leaves the repository.
- Source text is never accepted by the repository and must not be logged.

Cross-system edge cases:

- File-copy behavior may store files under the world `sources/` folder, but this system stores only the path string it receives.
- Book-number assignment must happen before append; this system only enforces uniqueness.
- Hash calculation and file-type detection must happen before append; this system only stores the supplied values.
- Parser and chunk systems must not infer that a committed source row means source text has already been parsed or chunked.
- Committed world renames must not affect stored source paths or book numbers.
- Source metadata must remain world-scoped and must not be written to `app.sqlite`.

## Invariants

- Committed source metadata must live in the relevant world's `world.sqlite`.
- Source rows are append-only for this storage contract.
- Source IDs must be unique within a world.
- Book numbers must be positive integers and unique within a world.
- The repository must not calculate IDs, hashes, file types, paths, timestamps, or book numbers.
- The repository must not check physical file existence.
- Listing must be stable in `book_number` order.
- Logs must not include full source text.

## Implementation Landmarks

- `app/storage/world_migrations.py` owns the committed source table migration.
- `app/storage/committed_sources.py` owns committed source metadata validation, append, duplicate checks, and book-order listing.
- `tests/test_committed_source_storage.py` covers the committed source storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Committed Source Storage, check:

- Whether the change belongs to metadata storage or to file copy, hashing, parser, chunk, graph, retrieval, or UI behavior.
- Whether schema changes need a handwritten world database migration and `PRAGMA user_version` advance.
- Whether the repository is still preserving caller-provided values instead of calculating them.
- Whether append-only behavior remains intact.
- Whether duplicate source IDs and book numbers are still rejected before insert.
- Whether source metadata remains world-scoped instead of app-global.
- Whether logs avoid source text and sensitive local path detail.
- Whether tests cover append, listing order, validation rejection, duplicate rejection, rollback, and SQLite failure behavior.
