# TXT Parser

TXT Parser is VySol's backend ingestion parser for turning supported `.txt` source files into clean in-memory Unicode text. It chooses a safe standard-library decoder, reads the source strictly, and returns a Python string for later splitting.

This page is for developers, power users, and AI coding agents that need to understand the TXT parsing contract before changing source ingestion, parser selection, chunk generation, committed source records, or logging.

## Why It Exists

VySol needs a small, deterministic parser boundary before text reaches Main Chunk Generation. TXT files can arrive with different Unicode byte markers, and ingestion must reject unreadable files instead of silently replacing undecodable bytes with corruption markers.

Keeping TXT parsing separate from chunking and storage lets future commit-time ingestion prove that clean text exists before source metadata, chunks, embeddings, graph extraction, or persistent records are created.

## Ownership Boundary

TXT Parser owns:

- Reading a TXT source file into an in-memory Python string.
- Choosing a supported decoder from the file's byte-order mark when one is present.
- Falling back to strict UTF-8 when no supported byte-order mark is present.
- Supporting UTF-8, UTF-8 with BOM, UTF-16 with BOM, and obvious UTF-32 BOM-based text.
- Preserving decoded text structure without trimming, normalizing, or rewriting it.
- Rejecting undecodable text before downstream ingestion commits any source work.
- Logging successful parse summaries at `INFO` without parsed text.
- Logging unsupported or unreadable decoding at `WARNING`.
- Logging unexpected file read failures at `ERROR`.

TXT Parser does not own:

- Charset detection libraries or guessing encodings without a clear supported path.
- Saving full parsed text to files, databases, manifests, or logs.
- Splitting chunks, calculating overlap, assigning source IDs, book numbers, chunk IDs, or hashes.
- Creating committed source metadata or chunk records.
- Creating embeddings, graph records, retrieval records, HTTP responses, UI state, or user-facing upload controls.

## Normal Flow

Backend ingestion code passes a TXT file path to the parser. The parser reads a small byte prefix to identify a supported Unicode byte-order mark. If it finds one, it uses the matching strict Python standard-library decoder. If no supported marker is present, it reads the file as strict UTF-8.

The returned string is the only successful output. The parser does not trim whitespace, normalize line endings, remove decoded characters, or save the source text. Later ingestion systems can pass the returned string into Main Chunk Generation only after this parse succeeds.

## Inputs

TXT Parser receives one source file path for a TXT file. It reads the file bytes through Python's standard file APIs and does not receive database connections, splitter settings, source metadata, provider responses, saved manifests, or user-facing request objects.

## Outputs

The system returns an in-memory Python string containing the decoded TXT content. It also emits safe logs that can include the decoder label and character count, but must not include parsed text or sensitive local path detail.

It does not create saved source text, final chunk objects, database rows, files, embeddings, graph records, HTTP responses, UI state, or saved progress.

## Failure Behavior

If a supported decoder cannot produce clean text, TXT Parser logs a `WARNING` and raises a TXT parse error. This blocks later source commit work from treating corrupted text as usable input.

If the file cannot be read because of an unexpected filesystem failure, TXT Parser logs an `ERROR` and lets that failure leave the parser. Logs must never include parsed text.

## System Interactions

TXT Parser currently interacts with:

- Main Chunk Generation, which can receive parsed TXT strings after this parser succeeds.
- Split Point Search, indirectly through Main Chunk Generation after parsing.
- Future source commit orchestration, which should parse successfully before committing source metadata or chunks.
- Committed Source Storage and Chunk Storage, which should receive caller-prepared records only after parsing and chunk preparation happen outside those repositories.
- The central logger, which records parse summaries and failures without source text.

It must stay separate from storage repositories, splitter internals, route handlers, embeddings, graph extraction, retrieval, and UI systems.

## Current Edge Cases

Internal edge cases:

- Plain UTF-8 TXT files decode through strict UTF-8.
- UTF-8 BOM files decode without exposing the BOM as parsed content.
- UTF-16 files with a byte-order mark decode through the standard UTF-16 codec.
- Obvious UTF-32 BOM files decode through the standard UTF-32 codec.
- Invalid byte sequences are rejected instead of being replaced or ignored.
- Original decoded whitespace and line endings are preserved as much as the decoder provides them.
- Empty files can return an empty string; later systems decide whether empty parsed text is useful.

Cross-system edge cases:

- Future source commit work must parse before saving source metadata or chunks.
- Main Chunk Generation must receive parsed text, not file paths or raw bytes.
- Chunk Storage must not infer that a parser success has already assigned chunk IDs, book numbers, source IDs, or storage records.
- Logs must stay safe for public repositories and local machines by avoiding parsed text and full local paths.

## Invariants

- TXT parsing must use Python standard file decoding tools only unless a later ticket adds charset detection.
- Decoding must use strict errors, never silent replacement or ignored bytes.
- Valid decoded text must not be trimmed, normalized, cleaned, deduplicated, rewritten, saved, or logged.
- Parser success means clean in-memory text was produced, not that source commit or chunk storage has happened.
- Parser failure must block downstream commit-time ingestion for that source.
- Supported encodings are explicit backend behavior, not user-editable settings in this system.
- This system must remain parser-only with no splitter, storage, route, UI, provider, embedding, graph, retrieval, or manifest responsibilities.

## Implementation Landmarks

- `app/ingestion/parsing` owns TXT parsing.
- `tests/test_txt_parser.py` covers supported Unicode decoding, strict decode failures, file read failures, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing TXT Parser, check:

- Whether the change belongs in TXT parsing or in future source commit orchestration, chunk generation, storage, routing, embeddings, graph extraction, retrieval, or UI behavior.
- Whether all decoding still uses strict errors and avoids `replace` or `ignore`.
- Whether supported encodings remain explicit and standard-library based.
- Whether successful parsing still returns only in-memory text.
- Whether logs avoid parsed text and sensitive local path detail.
- Whether parser failures still block downstream source commit work.
- Whether tests cover BOM handling, strict rejection, text preservation, and log safety.
