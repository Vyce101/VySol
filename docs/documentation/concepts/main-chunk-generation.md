# Main Chunk Generation

Main Chunk Generation is VySol's in-memory ingestion splitting layer for turning already-parsed text into ordered main chunks with separate previous-context overlap. It repeatedly uses Split Point Search to choose boundaries, slices the parsed text at those boundaries, and returns or streams chunk objects for backend callers.

This page is for developers, power users, and AI coding agents that need to understand the main chunk contract before changing ingestion splitting, parser integration, chunk storage integration, or later graph extraction work.

## Why It Exists

VySol needs a deterministic layer between parsed source text and future persisted chunk records. Split Point Search chooses one boundary at a time, but ingestion callers need a complete ordered list of main chunks with source-local overlap before later systems add source metadata, embeddings, graph extraction, or storage.

Keeping Main Chunk Generation separate from parsing and storage makes the splitter easier to test. It lets backend code prove that parsed text is divided without losing, duplicating, trimming, normalizing, or rewriting valid text, while still giving graph extraction a previous-context field that does not change the main chunk text.

## Ownership Boundary

Main Chunk Generation owns:

- Producing ordered in-memory main chunks from already-parsed text.
- Calling Split Point Search repeatedly until all parsed text has been consumed.
- Preserving chunk text exactly as Python string slices from the parsed input.
- Calculating previous-context overlap from already-consumed text in the same parsed input.
- Keeping overlap text separate from `chunk_text`.
- Assigning in-memory chunk numbers starting at `1` in source text order.
- Calculating character start and end offsets from the parsed input.
- Skipping only exact empty string chunks.
- Preserving whitespace-only chunks when they are produced by valid slicing.
- Logging generated chunk counts at `DEBUG`.
- Logging unexpected splitter failures at `ERROR` without source or chunk text.

Main Chunk Generation does not own:

- Parsing files or extracting text from source documents.
- Cleaning, trimming, normalizing, deduplicating, or rewriting text.
- Retrieval overlap, graph extraction, or deciding how overlap affects downstream context.
- Creating source records, book numbers, source IDs, chunk IDs, or saved chunk records.
- Writing to SQLite or any other storage.
- Creating embeddings, graph records, retrieval records, manifests, HTTP responses, or UI state.
- Adding FastAPI routes or user-facing ingestion controls.

## Normal Flow

Backend ingestion code passes already-parsed text and validated splitter settings into the main chunk helper. The helper starts with the full parsed text as the remaining text.

For each loop, it asks Split Point Search for the next split index using the configured chunk size and max lookback size. It slices the current remaining text from the start through that split index, calculates offsets from the number of parsed characters already consumed, calculates previous-context overlap from the same parsed input, appends a main chunk when the slice is not exactly empty, and then continues with the unsliced remainder.

The returned or streamed chunks preserve source order. Joining all returned `chunk_text` values should reconstruct the parsed input for normal non-empty input, including leading whitespace, trailing whitespace, delimiter characters, and whitespace-only content. Overlap is never merged into `chunk_text`. Chunk offsets are Python string character indexes into that same parsed input, and `character_end_offset` is exclusive.

## Inputs

Main Chunk Generation receives:

- Already-parsed text as a plain Python string.
- Splitter settings in the shared splitter settings shape.

It assumes splitter settings have already been validated by the splitter settings system. The helper uses chunk size, max lookback size, and overlap size. Splitter version is carried by the settings object for shared configuration consistency, but this system does not use it to branch behavior.

It does not receive source files, file paths, database connections, provider responses, saved manifests, source metadata, or user-facing request objects.

## Outputs

The system returns or streams main chunk objects. Each object contains an ordered chunk number, exact chunk text, separate overlap text, character start offset, and exclusive character end offset.

It does not create source records, final storage chunk records, chunk IDs, book numbers, database rows, files, embeddings, graph records, HTTP responses, UI state, or saved progress.

## Failure Behavior

If Split Point Search raises unexpectedly, Main Chunk Generation logs an `ERROR` and raises a main chunk generation error. The log message must not include parsed text, source text, chunk text, or overlap text.

If Split Point Search returns a split index that cannot make progress or falls outside the remaining text, Main Chunk Generation logs an `ERROR` with counts and lengths only, then raises a main chunk generation error. This prevents infinite loops and prevents invalid boundaries from silently losing or duplicating text.

Routine chunk generation logs only count summaries at `DEBUG`.

## System Interactions

Main Chunk Generation currently interacts with:

- Split Point Search, which chooses each next boundary.
- Draft World Splitter Settings, whose validated setting shape supplies chunk size and max lookback size before committed ingestion work exists.
- World Splitter Settings Storage, whose committed settings can later supply chunk size, max lookback size, and overlap size for world ingestion.
- Future parser systems, which should pass already-extracted text into this helper rather than making it read files.
- Temporary Split Chunk Outputs, which can stream generated chunks into an attempt-local SQLite file without first collecting every chunk in a list.
- Chunk Storage, which can later receive caller-prepared final chunk records after source metadata, IDs, and book numbers are handled outside this helper.
- The central logger, which records count summaries and unexpected splitter failures without text content.

It must stay separate from parser logic, storage repositories, route handlers, embeddings, graph extraction, retrieval, and UI systems.

## Current Edge Cases

Internal edge cases:

- Empty parsed text returns an empty list.
- Parsed text shorter than or equal to chunk size returns one exact chunk.
- Hard split boundaries from Split Point Search are used when no preferred delimiter is found.
- Delimiter-inclusive split indexes keep selected delimiters in the left chunk.
- Leading whitespace, trailing whitespace, and in-between whitespace are preserved.
- Whitespace-only parsed text is preserved as content when produced by slicing.
- Exact empty slices are skipped.
- Chunk numbers start at `1` and increment in returned order.
- Character start and end offsets stay contiguous across returned chunks.
- The first returned chunk has empty overlap text.
- Overlap size `0` produces empty overlap text for every chunk.
- Overlap can be larger than chunk size and can include text from multiple previous chunks.
- Non-progressing split indexes are rejected.
- Out-of-range split indexes are rejected.

Cross-system edge cases:

- Parser systems must pass parsed text rather than source files or path data.
- Caller code must validate splitter settings before using this helper.
- Callers must invoke this helper per source or book boundary so previous-context overlap never crosses source boundaries.
- Storage code must not treat in-memory main chunks as final database records without adding source IDs, book numbers, and chunk IDs through the appropriate caller-owned flow.
- Logs must not include parsed text, source text, chunk text, overlap text, or local path details.

## Invariants

- Main chunks are ordered by source text order.
- Main chunk text must be exact slices of the parsed input.
- Overlap text must stay separate from main chunk text.
- Overlap text must only come from earlier text in the same parsed input.
- Valid text must not be trimmed, normalized, cleaned, rewritten, lost, or duplicated.
- Whitespace-only chunks are valid when produced by slicing.
- Only exact empty strings are skipped.
- Chunk numbers are in-memory ordering values, not persisted database identities.
- Character offsets are Python string indexes into parsed text, not byte or token offsets.
- Character end offsets are exclusive.
- Split indexes are character indexes, not token counts or byte counts.
- This system must remain pure backend string logic with no parser, database, route, UI, provider, embedding, graph, retrieval, or manifest responsibilities.
- Logs must never include source text, chunk text, or overlap text.

## Implementation Landmarks

- `app/ingestion/splitting` owns Split Point Search and Main Chunk Generation.
- `tests/test_main_chunk_generation.py` covers ordering, exact text preservation, empty input, whitespace preservation, hard splits, delimiter-based splits, chunk numbering, character offsets, previous-context overlap, and defensive splitter failures.

## What AI/Coders Must Check Before Changing This System

Before editing Main Chunk Generation, check:

- Whether the change belongs to main chunk generation or to parsing, storage, routing, embeddings, graph extraction, retrieval, or UI behavior.
- Whether returned chunk text still reconstructs the parsed input when joined.
- Whether overlap remains separate from chunk text and only uses earlier text from the same parsed input.
- Whether returned offsets still identify each chunk's exact position in the parsed input.
- Whether whitespace-only content is still preserved.
- Whether exact empty chunks are the only skipped chunks.
- Whether Split Point Search remains the only boundary chooser.
- Whether splitter settings validation remains outside this helper.
- Whether defensive splitter failures still prevent infinite loops and avoid text logging.
- Whether tests cover text preservation, ordering, numbering, whitespace, hard splits, delimiter splits, overlap boundaries, and failure logs.
