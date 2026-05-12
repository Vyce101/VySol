# Source Parser Router

Source Parser Router is VySol's backend ingestion boundary for sending already-staged source files to the parser that matches their staged source type. It accepts staged source records, supports TXT, EPUB, and PDF source types, and returns parsed in-memory text only after the matching parser succeeds.

This page is for developers, power users, and AI coding agents that need to understand the parser routing contract before changing source staging, parser integration, source commit orchestration, chunk generation, committed source records, or logging.

## Why It Exists

VySol needs staged source batches to fail before commit work if a source type is unsupported or if the selected parser cannot open the file. The router gives future source commit orchestration one small place to prove that a staged source type maps to a known parser before any metadata, chunks, or database records are saved.

Keeping routing separate from parser logic and storage lets TXT, EPUB, and PDF parsing stay focused on content extraction while future ingestion code can call one stable routing boundary for staged source batches.

## Ownership Boundary

Source Parser Router owns:

- Accepting staged source records with a source file path and staged source type.
- Normalizing staged source types case-insensitively.
- Supporting only TXT, EPUB, and PDF source types.
- Routing TXT sources to TXT Parser.
- Routing EPUB sources to EPUB Parser.
- Routing PDF sources to PDF Parser.
- Validating every staged source type in a batch before parsing any file in that batch.
- Rejecting unsupported or blank staged source types before downstream commit work.
- Returning parsed in-memory text after the selected parser succeeds.
- Calling parsers against the current file at the staged path instead of an earlier selected file version.
- Logging parser routing at `DEBUG` without source text.
- Logging unsupported source type rejection at `WARNING`.
- Logging unexpected router failures at `ERROR`.

Source Parser Router does not own:

- Detecting source types from filenames, suffixes, MIME types, or file contents.
- Implementing TXT, EPUB, or PDF parsing behavior.
- Source staging UI, upload controls, file copy behavior, source hashing, or book-number assignment.
- Splitting parsed text, generating chunks, creating committed source metadata, or saving database rows.
- Embeddings, graph records, retrieval records, manifests, HTTP responses, or user-facing progress state.

## Normal Flow

Backend ingestion code passes one staged source or a staged source batch into the router. Each staged source contains a source file path and a staged source type string supplied by the staging layer.

For a single source, the router normalizes the staged type, looks up the matching parser, logs the routing decision, calls that parser with the source file path, and returns the normalized source type with the parsed text. The parser reads whatever file currently exists at that path. Parsers remain responsible for rejecting fake extensions, malformed files, unavailable files, and unreadable files. Temporary Parsed Source Outputs performs the batch-level usable-text check before later commit work.

For a batch, the router first routes every staged source type before parsing any file. If any source type is unsupported, the batch is rejected before parser calls begin. If all source types are supported, the router parses sources in the batch order and lets parser failures stop the batch before future commit orchestration can continue.

## Inputs

Source Parser Router receives staged source records containing:

- A source file path for the staged source file.
- A staged source type string such as `txt`, `epub`, or `pdf`.

The router does not receive database connections, splitter settings, source metadata records, provider responses, saved manifests, or user-facing request objects.

## Outputs

The router returns parsed staged source records containing:

- The original source file path.
- The normalized source type.
- The parsed in-memory text returned by the selected parser.

It does not save parsed text, final chunk objects, database rows, files, embeddings, graph records, HTTP responses, UI state, or progress state.

## Failure Behavior

Unsupported or blank staged source types are logged at `WARNING` and rejected before parser calls. This lets a future staged batch fail before any commit-time save behavior starts.

Expected parser failures leave the router unchanged and propagate from the selected parser. This preserves each parser's existing failure contract for malformed EPUBs, broken PDFs, undecodable TXT files, fake extensions, unavailable files, unreadable files, and parser-owned no-usable-text rejection.

Unexpected router failures are logged at `ERROR` and raised as router failures. Logs must not include parsed text, source text, or sensitive local path detail.

## System Interactions

Source Parser Router currently interacts with:

- TXT Parser, which decodes supported TXT files into in-memory text.
- EPUB Parser, which extracts readable text from EPUB spine documents.
- PDF Parser, which extracts text from text-based PDF files.
- Source Type Selection Filter, which can supply valid staged source types derived from selected file suffixes.
- Temporary Parsed Source Outputs, which calls the router per staged source before later commit work can continue.
- Future source staging UI, which can display invalid selections before the router is called.
- Future source commit orchestration, which can use Temporary Parsed Source Outputs to call the router before saving source metadata or chunks.
- Main Chunk Generation, which can receive parsed text only after routing and parsing succeed.
- The central logger, which records routing and rejection summaries without source text.

It must stay separate from parser internals, storage repositories, route handlers, embeddings, graph extraction, retrieval, and UI systems.

## Current Edge Cases

Internal edge cases:

- `txt`, `epub`, and `pdf` are the only supported normalized source types.
- Uppercase and mixed-case staged source types are accepted after normalization.
- Leading and trailing whitespace around a staged source type is ignored during normalization.
- Blank source types are rejected as unsupported.
- Unsupported source types are rejected before any parser runs.
- Batch routing validates every source type before parsing the first file.
- TXT batches read current file contents at parse time and preserve source order.
- Parser failures propagate without being converted into successful routed results.

Cross-system edge cases:

- Source type detection remains a Source Type Selection Filter responsibility, not a router responsibility.
- Invalid source selections should be blocked before parser routing rather than passed into the router as normal work.
- Fake extensions are rejected by parser/open behavior when the staged source type selects a parser but the file content is invalid.
- Staged source paths remain references; parser routing must not preserve the exact file version selected earlier.
- Missing, replaced, or unreadable current files fail through the selected parser before downstream commit work.
- Temporary Parsed Source Outputs may reject parser-returned text that is empty or whitespace-only before future chunk or commit work.
- Future commit orchestration must not save source metadata or chunks until the router and selected parser have succeeded.
- Main Chunk Generation must receive parsed text, not staged source records or file paths.
- Logs must stay safe for public repositories and local machines by avoiding parsed text and full local paths.

## Invariants

- Supported source types must remain explicit and limited to TXT, EPUB, and PDF until a later source type is intentionally added.
- Batch routing must reject unsupported staged source types before parsing any file in that batch.
- Parser success means in-memory parsed text was produced, not that source commit or chunk storage has happened.
- Parser failure must block downstream commit-time ingestion for that source.
- Parser routing must keep staged sources path-based and must not snapshot or copy source files.
- The router must not infer source type from filename or file content.
- The router must not implement parser logic, chunking, storage, UI, provider, embedding, graph, retrieval, or manifest behavior.
- Logs must never include parsed source text.

## Implementation Landmarks

- `app/ingestion/parsing` owns parser routing and individual parser modules.
- `tests/test_source_parser_router.py` covers parser selection, source type normalization, unsupported type rejection, batch prevalidation, current-file parsing, parser failure propagation, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Source Parser Router, check:

- Whether the change belongs in routing, an individual parser, source staging, source commit orchestration, chunk generation, storage, or UI behavior.
- Whether all supported source types still map to exactly one parser.
- Whether unsupported source types still fail before batch parsing begins.
- Whether parser failures still propagate and block future commit work.
- Whether no source type is inferred from a filename, suffix, MIME type, or content inside the router.
- Whether source type inference from selected file suffixes remains owned by Source Type Selection Filter.
- Whether successful routing still returns only in-memory parsed text.
- Whether logs avoid parsed text and sensitive local path detail.
- Whether tests cover routing, normalization, batch rejection, parser failure propagation, and log safety.
