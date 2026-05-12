# Temporary Parsed Source Outputs

Temporary Parsed Source Outputs is VySol's backend ingestion boundary for turning a staged batch into per-source parsed text that is still temporary. It ties parser work to the current temporary ingestion workspace, parses staged sources one at a time, and returns in-memory parsed outputs that later ingestion systems can use only after every source has parsed successfully.

This page is for developers, power users, and AI coding agents that need to understand the parsed-output preparation contract before changing ingestion orchestration, parser routing, temporary workspace handling, source commit behavior, chunk generation, or logging.

## Why It Exists

VySol needs a clear stop point between "the user staged these source files" and "the app is allowed to commit world data." A staged source can have a supported extension and still fail when the parser reads the current file contents.

This boundary lets ingestion prepare parsed text for every staged source before any source records, book numbers, chunks, copied files, or committed storage are created. If one source cannot parse into usable text, the whole attempt stops while all parsed text remains temporary.

## Ownership Boundary

Temporary Parsed Source Outputs owns:

- Accepting a current temporary ingestion workspace and already-staged source entries.
- Parsing staged sources one at a time in caller-provided order.
- Calling Source Parser Router for TXT, EPUB, and PDF parser dispatch.
- Rejecting the whole attempt when any source parser rejects a staged source.
- Rejecting parsed outputs that do not contain usable text.
- Returning temporary in-memory parsed outputs with attempt ID, staging entry ID, normalized source type, and parsed text.
- Logging per-source parse preparation success at `INFO` with safe counts and IDs only.
- Logging parser rejection summaries at `WARNING` without parsed text or raw paths.
- Logging unexpected preparation failures at `ERROR` without parsed text or raw paths.

Temporary Parsed Source Outputs does not own:

- Selecting files, detecting source types, or deciding whether staged entries are valid enough to start.
- Implementing TXT, EPUB, or PDF parser internals.
- Copying staged source files into temporary or final storage.
- Saving parsed text permanently or writing parsed text into the temporary workspace.
- Hashing sources, duplicate checking, assigning source IDs, assigning book numbers, generating chunks, or creating committed source records.
- Creating database rows, migrations, manifests, embeddings, graph records, routes, UI state, or progress events.

## Normal Flow

A future Start or Resume ingestion flow obtains the current temporary ingestion workspace for the active attempt and reads the temporary staged source entries that are ready for ingestion.

The preparation helper receives the workspace and staged entries. For each staged entry, it builds a parser-router staged source from the current source file path and staged source type, then asks Source Parser Router to parse the current file. The helper validates that the parser returned usable text, logs a safe success summary, and appends a temporary parsed output to the in-memory result tuple.

If every source succeeds, the caller receives parsed outputs in the same order as the staged entries. If any source fails, parsing stops at that source, the failure is raised, and downstream commit work must not continue.

## Inputs

Temporary Parsed Source Outputs receives:

- A temporary ingestion workspace for the active attempt.
- Temporary source staging entries containing staging entry IDs, current path references, and staged source types.

It does not receive database connections, splitter settings, source hashes, committed source metadata, provider responses, saved manifests, or user-facing request objects.

## Outputs

On success, the system returns temporary parsed source output objects containing:

- The attempt ID.
- The temporary staging entry ID.
- The normalized source file type returned by parser routing.
- The parsed text in memory.

It does not create files, database rows, committed source metadata, chunks, source IDs, book numbers, stored paths, embeddings, graph records, HTTP responses, UI state, or saved progress.

## Failure Behavior

Expected parser rejections are logged at `WARNING` with safe attempt and staging metadata, then raised so the whole attempt stops before commit work. This includes unsupported source types that reach the router, unreadable files, malformed EPUBs, broken PDFs, undecodable TXT files, and sources that do not produce usable text.

Unexpected preparation failures are logged at `ERROR` with safe metadata and raised as preparation failures. Logs must not include parsed source text, raw source paths, filenames, file bytes, local machine details, or user data.

## System Interactions

Temporary Parsed Source Outputs currently interacts with:

- Temporary Ingestion Workspace, which supplies the active attempt ID and temporary workspace boundary.
- Temporary Source Staging State, which supplies staged source entries and their temporary IDs.
- Source Parser Router, which dispatches each source to the matching TXT, EPUB, or PDF parser.
- Future ingestion orchestration, which can call this boundary before source hashing, duplicate checks, chunking, source copy, book-number assignment, or committed source storage.
- Main Chunk Generation, which can later receive parsed text only after every source in the staged batch has prepared successfully.
- The central logger, which records safe parse preparation summaries and failures.

It must stay separate from parser internals, source-type selection, file access validation, hash preflight, duplicate preflight, committed source storage, chunk storage, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- Empty input returns an empty tuple without creating commit policy.
- Input order is preserved in the returned parsed outputs.
- Sources are parsed one at a time instead of pre-routing the whole batch through the router's batch helper.
- The first parser rejection stops later staged sources from parsing.
- Parser-returned source types are normalized through Source Parser Router before output.
- Empty, whitespace-only, or non-string parsed output is rejected as unusable.
- Successful preparation does not write parsed text into the temporary workspace.
- Success logs include character counts only, not parsed text.

Cross-system edge cases:

- Unsupported source types should normally be blocked by Source Type Selection Filter before this boundary, but parser routing still rejects one if it reaches preparation.
- Staged source paths remain current file references; parser routing reads whatever file exists at parse time.
- Staged Source File Access Validation can prove a file is readable before this boundary, but parser preparation still owns parseability and usable-text failure.
- Future source hashing and duplicate checks must not treat parsed output preparation as committed source metadata.
- Future book-number assignment, chunk generation, source copy, and committed storage must run only after all staged sources parse successfully.
- Paused or resumed ingestion must use the current attempt workspace so prepared outputs stay tied to the active attempt.

## Invariants

- Parsed text must remain temporary and in memory for this system.
- The system must not save full parsed text permanently.
- The system must not write parsed text into the temporary workspace.
- Any source that cannot parse into usable text must block the whole attempt.
- Parsing must happen per source in staged order.
- Later sources must not parse after an earlier source fails.
- Returned outputs must not contain source IDs, book numbers, chunk numbers, stored paths, hashes, or committed metadata.
- Logs must never include parsed source text, raw source paths, filenames, file bytes, or full local paths.
- No database migration is required for temporary parsed source outputs.

## Implementation Landmarks

- `app/ingestion/parsed_source_outputs.py` owns temporary parsed output preparation.
- `app/ingestion/parsing` owns parser routing and parser internals.
- `app/ingestion/__init__.py` exports the public parsed output preparation API for future ingestion callers.
- `tests/test_parsed_source_outputs.py` covers ordering, failure blocking, output shape, temporary workspace non-writes, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Temporary Parsed Source Outputs, check:

- Whether the change belongs in parsed output preparation or in parser internals, source staging, file access validation, hashing, duplicate checks, chunk generation, source copy, committed storage, or UI behavior.
- Whether parser failures still block the whole staged batch before commit work.
- Whether parsed text still stays out of logs and out of persistent storage.
- Whether parsed outputs still avoid source IDs, book numbers, chunk numbers, stored paths, and hashes.
- Whether later sources still remain unparsed after the first failure.
- Whether the helper remains tied to the active temporary ingestion workspace without writing parsed text there.
