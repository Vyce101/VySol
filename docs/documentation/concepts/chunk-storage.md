# Chunk Storage

Chunk Storage is VySol's per-world storage contract for final splitter output. It stores chunk records in each committed world's `world.sqlite` database with separate book numbers, chunk numbers, overlap text, and optional character offsets.

This page is for developers, power users, and AI coding agents that need to understand the chunk storage boundary before changing world database migrations, ingestion commit behavior, splitter integration, embeddings, graph extraction, retrieval, or provenance handling.

## Why It Exists

Future ingestion systems need a durable place to save the final chunks that downstream embedding, graph, retrieval, and provenance systems can reference. Chunk Storage keeps that saved state world-scoped so each committed world can carry its own source-derived content without writing chunk data to the global app database.

The storage boundary is intentionally narrow. It records caller-prepared final splitter output only. It does not parse source files, extract text, generate chunks, assign book numbers, calculate overlap, calculate offsets, create embeddings, or inspect chunks through UI.

## Ownership Boundary

Chunk Storage owns:

- Storing final chunk records in `world.sqlite`.
- Preserving caller-provided chunk IDs, source IDs, book numbers, chunk numbers, chunk text, overlap text, and optional character offsets.
- Keeping `book_number` and `chunk_number` as separate values.
- Keeping `overlap_text` separate from `chunk_text`.
- Rejecting blank required IDs and blank chunk text before insert.
- Rejecting invalid book numbers, chunk numbers, overlap text, and character offsets before insert.
- Rejecting duplicate chunk IDs and duplicate book/chunk positions.
- Listing chunk records in stable book and chunk order.
- Logging successful batch insert summaries at `INFO`.
- Logging counts and IDs only at `DEBUG`.
- Logging SQLite insert and read failures at `ERROR`.

Chunk Storage does not own:

- Parser output, source text extraction, or full parsed source text storage.
- Splitter execution, chunk generation, overlap calculation, or offset calculation.
- Combined labels such as `B1/C1`.
- Source file copying, source hashing, source metadata creation, or book-number assignment.
- Embeddings, vector storage, graph extraction, graph storage, retrieval, chunk inspection UI, or user-facing ingestion controls.
- Deleting, replacing, reordering, repairing, or re-splitting stored chunks.
- Global app database storage.

## Normal Flow

World Database Bootstrap opens a committed world's `world.sqlite` and applies the migration that creates the `chunks` table.

After a future splitter or ingestion system has already produced final chunk records, backend code passes those records into Chunk Storage. The repository validates the batch, checks for duplicate chunk IDs and duplicate book/chunk positions, inserts the batch in one transaction, commits the insert, logs a count-level summary, and returns the stored chunk records.

Later backend systems can list chunks from the same world database connection. Results are ordered by `book_number`, then `chunk_number`, then `chunk_id` so downstream systems can process story content in a stable order without relying on combined labels.

## Inputs

Chunk Storage receives an open `sqlite3.Connection` for a world database and caller-prepared final chunk records: chunk ID, source ID, book number, chunk number, chunk text, overlap text, and optional character start/end offsets.

Book and chunk numbers must be positive integers. Chunk text must be non-empty text. Overlap text must be text and may be empty. Character offsets may be missing, but any supplied offset must be a whole number at or above `0`; when both offsets are supplied, the end offset must not come before the start offset.

## Outputs

The system writes chunk rows to the `chunks` table inside `world.sqlite` and returns immutable stored chunk objects to backend callers. It can return the stored chunk list in stable story order.

It does not produce source files, parser output, splitter output, embeddings, graph records, retrieval results, manifests, HTTP responses, app-global rows, or user-facing UI state.

## Failure Behavior

Invalid chunk metadata and duplicate chunk identity or book/chunk positions are rejected before insert, logged at `WARNING`, and raised as chunk validation errors.

SQLite duplicate checks, inserts, and reads are logged at `ERROR` and re-raised when they fail. Failed batch inserts roll back before the SQLite error leaves the repository, so callers do not get partially stored chunk batches.

Logs must never include `chunk_text`, `overlap_text`, full parsed source text, or extracted source text.

## System Interactions

Chunk Storage currently interacts with:

- World Database Bootstrap, which opens `world.sqlite` and applies the chunk table migration.
- Committed Source Storage, whose source IDs and book numbers can be referenced by future ingestion code before chunks are stored.
- Future parser and splitter systems, which must prepare final chunk records before this repository saves them.
- Future embedding, graph, retrieval, provenance, and inspection systems, which can read chunk records but must keep their own storage responsibilities separate.
- The central logger, which records chunk batch summaries, validation rejections, and database failures.

It must stay separate from Global App Storage and Committed World Index Storage. The global app database can identify a committed world, but chunk content belongs in that world's database.

## Current Edge Cases

Internal edge cases:

- Blank chunk IDs and source IDs are rejected before insert.
- Non-integer book numbers, non-integer chunk numbers, and values below `1` are rejected before insert.
- Blank chunk text is rejected before insert.
- Empty overlap text is accepted.
- Missing character offsets are accepted.
- Negative offsets and non-integer offsets are rejected before insert.
- End offsets before start offsets are rejected when both are supplied.
- Duplicate chunk IDs are rejected before insert.
- Duplicate book/chunk positions are rejected before insert.
- Listing an empty chunk table returns an empty list.
- Failed batch inserts roll back before the error leaves the repository.
- Chunk text and overlap text are stored but never logged.

Cross-system edge cases:

- Parser and splitter systems must not pass full source text as a substitute for chunk text.
- Splitter systems must provide separate overlap text instead of merging overlap into a combined label or source-text record.
- Book-number assignment must happen before chunk insert; this system only validates positive book numbers and position uniqueness.
- Character offset calculation must happen before chunk insert; this system only stores supplied offsets when available.
- Downstream systems must use separate book and chunk numbers instead of expecting combined labels such as `B1/C1`.
- Source metadata must remain world-scoped and chunk rows must not be written to `app.sqlite`.

## Invariants

- Chunk records must live in the relevant world's `world.sqlite`.
- Chunk IDs must be unique within a world.
- The combination of `book_number` and `chunk_number` must be unique within a world.
- Book numbers and chunk numbers must be positive integers.
- Chunk text and overlap text must stay in separate fields.
- Full parsed or extracted source text must not be stored by this system.
- Combined book/chunk labels must not be stored by this system.
- The repository must not calculate IDs, source IDs, book numbers, chunk numbers, overlap text, or offsets.
- Listing must be stable in book and chunk order.
- Logs must not include chunk text, overlap text, parsed source text, or extracted source text.

## Implementation Landmarks

- `app/storage/world_migrations.py` owns the chunk table migration.
- `app/storage/chunks.py` owns chunk validation, batch append, duplicate checks, row mapping, and ordered listing.
- `tests/test_chunk_storage.py` covers the chunk storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Chunk Storage, check:

- Whether the change belongs to storage or to parser, splitter, ingestion, embedding, graph, retrieval, or UI behavior.
- Whether schema changes need a handwritten world database migration and `PRAGMA user_version` advance.
- Whether the repository is still preserving caller-provided values instead of calculating them.
- Whether batch insert rollback behavior remains intact.
- Whether book numbers and chunk numbers remain separate.
- Whether overlap text remains separate from chunk text.
- Whether full parsed or extracted source text is still excluded from this storage boundary.
- Whether logs avoid chunk text, overlap text, source text, and sensitive local path detail.
- Whether tests cover insert, listing order, validation rejection, duplicate rejection, rollback, read failure, and logging boundaries.
