# Split Point Search

Split Point Search is VySol's ingestion helper for choosing the next character index where source text should split. It chooses one boundary only. It does not build the final chunk list, calculate overlap, parse source files, or save chunk records.

This page is for developers, power users, and AI coding agents that need to understand the split-point contract before changing ingestion splitting, splitter settings, future parser integration, or chunk storage integration.

## Why It Exists

VySol needs a deterministic boundary chooser beneath ingestion splitting. The helper lets chunk generation code ask, "Where should this one chunk boundary land?" using plain Python string operations and character-based settings.

Keeping this small matters because choosing one boundary is easier to test and reason about than complete chunk generation. Main Chunk Generation can use this boundary choice while parser and storage systems still own parsing, source metadata, and database writes.

## Ownership Boundary

Split Point Search owns:

- Choosing one next split index from text and character-based settings.
- Searching backward from the maximum chunk boundary within the configured lookback window.
- Applying the fixed internal priority of double newline, single newline, sentence punctuation, then space.
- Returning a Python slice end index that keeps the chosen separator in the left slice.
- Falling back to a hard split at the maximum chunk size when no preferred split point is found.

Split Point Search does not own:

- Generating full chunk lists.
- Calculating overlap text.
- Parsing source files or language-aware sentence splitting.
- Creating source records, chunk records, embeddings, graph records, or database writes.
- Exposing split priority as a user-editable setting.
- Logging source text or routine split decisions.

## Normal Flow

Future ingestion code passes source text, a maximum chunk size, and a maximum lookback size into the split-point helper. If the remaining text already fits within the maximum chunk size, the helper returns the text length.

For longer text, the helper searches the character window ending at the maximum chunk boundary. It checks split markers in fixed priority order: double newline, single newline, sentence punctuation, and then space. Within a priority, it uses the last matching marker in the window so the candidate chunk is as large as that priority allows.

The returned value is an integer slice boundary. Callers can use `text[:split_index]` and keep the selected separator on the left side of the split. If the helper finds no allowed marker inside the lookback window, it returns the maximum chunk size.

## Inputs

Split Point Search receives plain text plus character-based `chunk_size` and `max_lookback_size` values. It assumes callers have already validated the settings before using them for ingestion work.

It does not receive source files, parsed documents, world database connections, provider responses, user-facing settings metadata, or saved manifests.

## Outputs

The system returns one integer split index. It produces no files, database rows, final chunk objects, overlap text, embeddings, graph records, HTTP responses, UI state, logs, or saved progress.

## System Interactions

Split Point Search currently interacts with:

- Draft World Splitter Settings, which defines in-memory splitter settings before future ingestion starts.
- World Splitter Settings Storage, which persists committed-world splitter settings that future ingestion code can validate and pass to this helper.
- Main Chunk Generation, which repeatedly calls this helper after text extraction, then adds chunk offsets and previous-context overlap before final chunk records are prepared.
- Future parser and ingestion systems, which can pass extracted text into main chunk generation rather than calling this helper for complete chunk lists.
- Chunk Storage, which should receive final caller-prepared chunk records after a future chunking system uses split boundaries.

It must stay separate from storage repositories and parser logic. This helper can inform future chunk generation, but it does not persist or inspect chunk records itself.

## Current Edge Cases

Internal edge cases:

- Text shorter than the maximum chunk size returns the text length.
- Text exactly equal to the maximum chunk size returns the text length.
- Double newlines are preferred over later lower-priority markers inside the same lookback window.
- Single newlines are preferred when no double newline is available.
- Sentence punctuation is preferred over spaces.
- Spaces are used only when higher-priority markers are unavailable.
- Markers before the lookback window are ignored.
- The latest marker within the selected priority is used.
- Missing markers inside the lookback window cause a hard split at the maximum chunk size.
- The selected marker remains in `text[:split_index]`.

Cross-system edge cases:

- Callers must validate splitter settings before passing them into the helper.
- Main Chunk Generation must not treat this helper as proof that offsets, overlap, source metadata, or storage records have already been calculated.
- Future parser work must pass extracted text into this helper rather than making this helper read files.
- Future storage work must save final chunk records through Chunk Storage rather than adding database behavior here.
- Logs must never include source text if defensive error handling is added later.

## Invariants

- Split indexes are character indexes, not token counts or byte counts.
- Split priority is fixed inside backend code and must not become user-editable in this system.
- `text[:split_index]` must include the chosen separator.
- Search must stay inside the lookback window for preferred split points.
- The hard split fallback must stay at the maximum chunk size.
- This system must remain pure string logic with no database, parser, overlap, route, UI, provider, embedding, or graph responsibilities.
- Routine split-point decisions must not be logged.

## Implementation Landmarks

- `app/ingestion/splitting` owns split-point search helpers.
- `tests/test_split_point_search.py` covers split priority, lookback behavior, delimiter-inclusive indexes, and hard split fallback.

## What AI/Coders Must Check Before Changing This System

Before editing Split Point Search, check:

- Whether the change still chooses one split index or belongs in future chunk generation.
- Whether the change accidentally adds parser, overlap, storage, route, UI, provider, embedding, or graph behavior.
- Whether the returned index still works as a Python slice end index that keeps the separator on the left.
- Whether priority remains fixed and internal.
- Whether settings validation remains outside this helper.
- Whether tests cover priority order, lookback boundaries, same-priority latest match behavior, and hard split fallback.
- Whether logs still avoid source text.
