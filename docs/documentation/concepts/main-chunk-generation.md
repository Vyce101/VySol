# Main Chunk Generation

Main Chunk Generation is VySol's in-memory ingestion splitting layer for turning already-parsed text into ordered main chunks. It repeatedly uses Split Point Search to choose boundaries, slices the parsed text at those boundaries, and returns chunk objects for backend callers.

This page is for developers, power users, and AI coding agents that need to understand the main chunk contract before changing ingestion splitting, parser integration, chunk storage integration, or future overlap generation.

## Why It Exists

VySol needs a deterministic layer between parsed source text and future persisted chunk records. Split Point Search chooses one boundary at a time, but ingestion callers need a complete ordered list of main chunks before later systems can add overlap, source metadata, offsets, embeddings, graph extraction, or storage.

Keeping Main Chunk Generation separate from parsing and storage makes the splitter easier to test. It lets backend code prove that parsed text is divided without losing, duplicating, trimming, normalizing, or rewriting valid text before any database or downstream ingestion behavior is added.

## Ownership Boundary

Main Chunk Generation owns:

- Producing an ordered in-memory list of main chunks from already-parsed text.
- Calling Split Point Search repeatedly until all parsed text has been consumed.
- Preserving chunk text exactly as Python string slices from the parsed input.
- Assigning in-memory chunk numbers starting at `1` in source text order.
- Skipping only exact empty string chunks.
- Preserving whitespace-only chunks when they are produced by valid slicing.
- Logging generated chunk counts at `DEBUG`.
- Logging unexpected splitter failures at `ERROR` without source or chunk text.

Main Chunk Generation does not own:

- Parsing files or extracting text from source documents.
- Cleaning, trimming, normalizing, deduplicating, or rewriting text.
- Calculating overlap text.
- Creating source records, book numbers, source IDs, chunk IDs, offsets, or saved chunk records.
- Writing to SQLite or any other storage.
- Creating embeddings, graph records, retrieval records, manifests, HTTP responses, or UI state.
- Adding FastAPI routes or user-facing ingestion controls.

## Normal Flow

Backend ingestion code passes already-parsed text and validated splitter settings into the main chunk helper. The helper starts with the full parsed text as the remaining text.

For each loop, it asks Split Point Search for the next split index using the configured chunk size and max lookback size. It slices the current remaining text from the start through that split index, appends a main chunk when the slice is not exactly empty, and then continues with the unsliced remainder.

The returned list preserves source order. Joining all returned `chunk_text` values should reconstruct the parsed input for normal non-empty input, including leading whitespace, trailing whitespace, delimiter characters, and whitespace-only content.

## Inputs

Main Chunk Generation receives:

- Already-parsed text as a plain Python string.
- Splitter settings in the shared splitter settings shape.

It assumes splitter settings have already been validated by the splitter settings system. The helper uses only chunk size and max lookback size. Overlap size and splitter version are carried by the settings object for shared configuration consistency, but this system does not use them to generate overlap or versioned output.

It does not receive source files, file paths, database connections, provider responses, saved manifests, source metadata, or user-facing request objects.

## Outputs

The system returns an in-memory list of main chunk objects. Each object contains an ordered chunk number and exact chunk text.

It does not create source records, final storage chunk records, overlap text, chunk IDs, book numbers, character offsets, database rows, files, embeddings, graph records, HTTP responses, UI state, or saved progress.

## Failure Behavior

If Split Point Search raises unexpectedly, Main Chunk Generation logs an `ERROR` and raises a main chunk generation error. The log message must not include parsed text, source text, or chunk text.

If Split Point Search returns a split index that cannot make progress or falls outside the remaining text, Main Chunk Generation logs an `ERROR` with counts and lengths only, then raises a main chunk generation error. This prevents infinite loops and prevents invalid boundaries from silently losing or duplicating text.

Routine chunk generation logs only count summaries at `DEBUG`.

## System Interactions

Main Chunk Generation currently interacts with:

- Split Point Search, which chooses each next boundary.
- Draft World Splitter Settings, whose validated setting shape supplies chunk size and max lookback size before committed ingestion work exists.
- World Splitter Settings Storage, whose committed settings can later supply the same values for world ingestion.
- Future parser systems, which should pass already-extracted text into this helper rather than making it read files.
- Chunk Storage, which can later receive caller-prepared final chunk records after source metadata, IDs, offsets, and overlap are handled outside this helper.
- The central logger, which records count summaries and unexpected splitter failures without text content.

It must stay separate from parser logic, storage repositories, overlap generation, route handlers, embeddings, graph extraction, retrieval, and UI systems.

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
- Non-progressing split indexes are rejected.
- Out-of-range split indexes are rejected.

Cross-system edge cases:

- Parser systems must pass parsed text rather than source files or path data.
- Caller code must validate splitter settings before using this helper.
- Overlap generation must remain outside this helper so main chunk text stays clean.
- Storage code must not treat in-memory main chunks as final database records without adding source IDs, book numbers, chunk IDs, overlap text, and offsets through the appropriate caller-owned flow.
- Logs must not include parsed text, source text, chunk text, overlap text, or local path details.

## Invariants

- Main chunks are ordered by source text order.
- Main chunk text must be exact slices of the parsed input.
- Valid text must not be trimmed, normalized, cleaned, rewritten, lost, or duplicated.
- Whitespace-only chunks are valid when produced by slicing.
- Only exact empty strings are skipped.
- Chunk numbers are in-memory ordering values, not persisted database identities.
- Split indexes are character indexes, not token counts or byte counts.
- This system must remain pure backend string logic with no parser, overlap, database, route, UI, provider, embedding, graph, retrieval, or manifest responsibilities.
- Logs must never include source text or chunk text.

## Implementation Landmarks

- `app/ingestion/splitting` owns Split Point Search and Main Chunk Generation.
- `tests/test_main_chunk_generation.py` covers ordering, exact text preservation, empty input, whitespace preservation, hard splits, delimiter-based splits, chunk numbering, and defensive splitter failures.

## What AI/Coders Must Check Before Changing This System

Before editing Main Chunk Generation, check:

- Whether the change belongs to main chunk generation or to parsing, overlap, storage, routing, embeddings, graph extraction, retrieval, or UI behavior.
- Whether returned chunk text still reconstructs the parsed input when joined.
- Whether whitespace-only content is still preserved.
- Whether exact empty chunks are the only skipped chunks.
- Whether Split Point Search remains the only boundary chooser.
- Whether splitter settings validation remains outside this helper.
- Whether defensive splitter failures still prevent infinite loops and avoid text logging.
- Whether tests cover text preservation, ordering, numbering, whitespace, hard splits, delimiter splits, and failure logs.
