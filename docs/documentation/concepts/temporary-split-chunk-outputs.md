# Temporary Split Chunk Outputs

Temporary Split Chunk Outputs is VySol's backend ingestion boundary for turning temporary parsed source outputs into attempt-local split chunk rows. It runs the main chunk splitter for each parsed staged source, writes the chunk output to a SQLite file inside the current temporary ingestion workspace, and keeps that output temporary until future atomic commit code decides whether the whole attempt can be saved.

This page is for developers, power users, and AI coding agents that need to understand the split-output preparation contract before changing ingestion orchestration, temporary workspace handling, splitter integration, source commit behavior, chunk storage, or logging.

## Why It Exists

Parsed source text can be large, and future commit code needs a stable handoff point between "all staged sources parsed successfully" and "the app is allowed to write permanent world data." Holding every generated chunk only in memory would make large source batches fragile and would force later commit work to rerun splitting.

This boundary materializes split results in the attempt workspace while keeping them outside committed world storage. If any source cannot be split or written safely, the whole preparation fails before source records, book numbers, copied files, or permanent chunk rows are created.

## Ownership Boundary

Temporary Split Chunk Outputs owns:

- Accepting a current temporary ingestion workspace, prepared parsed source outputs, and validated splitter settings.
- Validating splitter settings before split output is created.
- Recreating the attempt-local split chunk SQLite file for the current preparation run.
- Splitting parsed outputs in caller-provided staged order.
- Writing one temporary SQLite row per generated chunk.
- Preserving attempt ID, staging entry ID, source type, chunk number, chunk text, overlap text, character offsets, and splitter version in temporary rows.
- Returning lightweight preparation summaries that do not contain chunk text or overlap text.
- Providing a streaming reader for future atomic commit code.
- Failing the whole preparation if splitting or SQLite writes cannot complete safely.
- Logging split completion summaries at `INFO`, counts and offsets at `DEBUG`, and preparation failures at `ERROR`.

Temporary Split Chunk Outputs does not own:

- Selecting source files, validating source types, reading source file paths, parsing source text, or proving file access.
- Choosing split points or calculating chunk overlap itself.
- Assigning permanent source IDs, chunk IDs, book numbers, stored paths, source hashes, or commit timestamps.
- Copying source files into final storage.
- Writing committed source records or permanent chunk rows to `world.sqlite`.
- Creating embeddings, graph records, retrieval records, manifests, routes, UI state, progress events, or chunk inspection UI.
- Making temporary ingestion workspaces durable across app restarts.

## Normal Flow

A future ingestion flow prepares temporary parsed source outputs first. After every staged source parses successfully, the caller passes those parsed outputs, the active temporary ingestion workspace, and splitter settings into split-output preparation.

The preparation helper validates the splitter settings, deletes any previous attempt-local split output database for that workspace, creates a fresh `split_chunks.sqlite` file, and opens one SQLite transaction. It processes parsed outputs in order. For each source, it asks Main Chunk Generation for chunks, writes each chunk row immediately, records a source-level summary, and continues to the next parsed source.

If every source succeeds, the SQLite transaction commits and the caller receives a summary containing the attempt ID, output database path, source count, total chunk count, and per-source chunk counts. Future atomic commit code can stream rows back from the same temporary database in source order and chunk order without loading every chunk into memory.

## Inputs

Temporary Split Chunk Outputs receives:

- A temporary ingestion workspace for the active attempt.
- Temporary parsed source outputs containing attempt ID, staging entry ID, normalized source type, and parsed text.
- Splitter settings containing chunk size, max lookback size, overlap size, and splitter version.

It does not receive source files, raw path references, world database connections, committed source metadata, source hashes, provider responses, saved manifests, user-facing request objects, or final chunk IDs.

## Outputs

On success, the system creates `split_chunks.sqlite` inside the active temporary ingestion workspace. The database contains temporary split chunk rows with attempt and staging identity, source type, chunk number, chunk text, overlap text, character offsets, and splitter version.

The preparation call returns a lightweight summary only. The streaming reader returns temporary split chunk row objects in source order and chunk order for future commit code.

It does not create committed source records, final chunk records, book numbers, source copies, embeddings, graph records, HTTP responses, UI state, or saved progress outside the temporary workspace.

## Saved State And Resume Behavior

Split chunk output is saved only inside the current attempt's temporary workspace. That makes the current running process able to pause and resume ingestion work without keeping all chunks in memory.

The workspace itself remains transient. If the app closes, uncommitted attempts and their temporary split output are discarded with the temporary workspace. This system does not add restart-persistent resume behavior.

## Failure Behavior

If splitter settings are invalid, splitting fails, SQLite setup fails, or any row cannot be written, preparation rolls back the active transaction, removes the incomplete split output database, logs an `ERROR` with safe metadata, and raises a split-output preparation error. Downstream commit work must not continue after that error.

If a reader cannot find or read the temporary split output database, it logs an `ERROR` with the attempt ID and raises a read error.

Logs must never include chunk text, overlap text, parsed source text, raw source paths, filenames, full temporary paths, provider output, local machine details, or user data.

## System Interactions

Temporary Split Chunk Outputs currently interacts with:

- Temporary Ingestion Workspace, which supplies the active attempt ID and attempt-local folder.
- Temporary Parsed Source Outputs, which supplies parsed text only after every staged source parses successfully.
- Draft World Splitter Settings and World Splitter Settings Storage, which supply the splitter settings shape and splitter version metadata.
- Main Chunk Generation, which performs the actual chunk slicing, overlap calculation, numbering, and offset calculation.
- Future atomic commit orchestration, which can stream temporary split rows before assigning permanent source IDs, book numbers, chunk IDs, and storage records.
- Chunk Storage, which can later receive final caller-prepared chunk records after commit orchestration adds permanent identity.
- The central logger, which records safe split summaries and failures.

It must stay separate from source staging, parser internals, hash preflight, duplicate preflight, committed source storage, source file copy, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty parsed-output input creates an empty valid temporary split database and returns an empty summary.
- Parsed source order is preserved by storing a source order value with each row.
- Chunk rows are read in stable source order and chunk number order.
- The temporary database is recreated for each preparation run in the same workspace.
- Splitter settings are validated before output is created.
- Splitter failures remove incomplete temporary output.
- SQLite write failures roll back and remove incomplete temporary output.
- Completion summaries omit chunk text and overlap text.
- Debug logs include counts, offsets, and splitter version only.

Cross-system edge cases:

- Parsed output preparation must complete for every staged source before this system runs.
- Main Chunk Generation owns text preservation, overlap calculation, chunk numbering, and offsets; this system only persists those temporary results.
- Future atomic commit code must treat temporary rows as uncommitted data until source IDs, chunk IDs, book numbers, source copies, and permanent database writes all succeed.
- Future chunk storage must not read this temporary database directly as if it were `world.sqlite`.
- App-close behavior discards uncommitted temporary split output because the workspace is not restart-persistent.
- Logs must stay safe even though temporary rows contain chunk text and overlap text.

## Invariants

- Split chunk outputs must remain temporary until future atomic commit succeeds.
- The system must write only inside the active temporary ingestion workspace.
- The system must not write permanent records to `world.sqlite`.
- The system must not copy source files or assign final book numbers, source IDs, chunk IDs, stored paths, hashes, or timestamps.
- Splitting must happen per parsed source in staged order.
- Any unsafe split or SQLite write failure must block the whole preparation.
- Partial split output must not remain after preparation failure.
- Chunk text and overlap text must stay separate.
- Splitter version must be stored as backend-controlled metadata, not as a user setting.
- Streaming reads must not require loading every temporary chunk into memory.
- Logs must never include chunk text, overlap text, parsed source text, raw paths, filenames, or full local paths.

## Implementation Landmarks

- `app/ingestion/split_chunk_outputs.py` owns temporary split chunk output preparation, temporary schema creation, rollback cleanup, and streaming reads.
- `app/ingestion/splitting` owns Main Chunk Generation and Split Point Search.
- `app/ingestion/__init__.py` exports the public split-output preparation API for future ingestion callers.
- `tests/test_split_chunk_outputs.py` covers materialization, ordering, summaries, streaming reads, rollback cleanup, non-persistence, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Temporary Split Chunk Outputs, check:

- Whether the change belongs in temporary split output preparation or in parsing, splitter internals, source staging, hashing, duplicate checks, source copy, committed source storage, chunk storage, or UI behavior.
- Whether temporary split output still lives only inside the active attempt workspace.
- Whether failures still roll back and remove incomplete temporary output before commit work can continue.
- Whether the reader still streams rows in source and chunk order.
- Whether chunk text and overlap text remain stored but never logged.
- Whether permanent identity assignment remains outside this system.
- Whether app-close behavior still discards uncommitted split output with the temporary workspace.
