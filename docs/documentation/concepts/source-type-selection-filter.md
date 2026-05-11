# Source Type Selection Filter

Source Type Selection Filter is VySol's backend staging boundary for classifying selected source files before ingestion can start. It takes selected file paths, keeps every selected file in the staging list, and marks each entry as valid or invalid based only on its filename extension.

This page is for developers, power users, and AI coding agents that need to understand the source selection contract before changing staging behavior, parser routing, source ingestion startup, UI source lists, or logging.

## Why It Exists

VySol needs selected source files to become visible staging entries even when a file type is unsupported. The filter gives the future UI enough state to show which selected files can proceed and which files block ingestion, without silently dropping user selections or parsing file contents too early.

Keeping this filter separate from parsing and commit work lets source selection stay cheap and predictable. Parser systems can focus on reading supported files later, while the staging layer owns extension-based eligibility.

## Ownership Boundary

Source Type Selection Filter owns:

- Accepting selected source file paths in the order they were provided.
- Detecting source type from the `pathlib` suffix only.
- Supporting `.txt`, `.epub`, and `.pdf` selections.
- Returning every selected file as a staging item.
- Marking supported selections with `is_valid=True`.
- Marking unsupported or extensionless selections with `is_valid=False`.
- Returning a clear error message for invalid staging items.
- Blocking ingestion startup when the staging list is empty or any staging item is invalid.
- Logging unsupported source types at `WARNING` without full source paths.
- Logging unexpected filter failures at `ERROR`.

Source Type Selection Filter does not own:

- Source file parsing, content validation, hashing, copying, committing, or database writes.
- Detecting MIME types, checking file existence, or validating file contents.
- Source staging UI controls, FastAPI endpoints, upload dialogs, or user-facing list rendering.
- Parser selection after a source has already been staged as valid.
- Chunk generation, embeddings, graph records, retrieval records, manifests, or provider calls.

## Normal Flow

Future source selection code passes selected source file paths into the filter. The filter reads each path's suffix with `pathlib`, normalizes that suffix case-insensitively, and creates one staging item for each selected file.

Supported `.txt`, `.epub`, and `.pdf` files become valid staging items with normalized source types of `txt`, `epub`, and `pdf`. Unsupported or missing extensions stay in the list as invalid staging items with a source type summary such as `docx` or `missing` and a UI-facing error message.

Before future ingestion starts, callers can ask whether the staging list can begin ingestion. Ingestion can start only when the list is not empty and every staged source is valid.

## Inputs

Source Type Selection Filter receives selected source file paths. It does not require database connections, file handles, parser output, splitter settings, provider responses, saved manifests, or user-facing request objects.

## Outputs

The filter returns staging items containing:

- The selected source file path.
- The normalized source file type.
- The validity state.
- An error message for invalid selections.

It also returns a boolean ingestion-start decision for a staging list. It does not save files, parse text, create database rows, generate chunks, call providers, create embeddings, or produce UI state directly.

## Failure Behavior

Unsupported source types are not raised as errors. They stay in the returned staging list, are marked invalid, and are logged at `WARNING` without full source paths.

Unexpected filter failures are logged at `ERROR` and raised as source type filter failures. Logs must not include selected source paths, source text, or local machine details.

## System Interactions

Source Type Selection Filter currently interacts with:

- Source Parser Router, which can later receive only valid staged source types.
- Future source staging UI, which can display validity and error message state.
- Future Start Ingestion behavior, which should remain blocked while the staging list is empty or contains invalid items.
- The central logger, which records unsupported type summaries and unexpected failures without full source paths.

It must stay separate from parser internals, storage repositories, route handlers, source file copy behavior, embeddings, graph extraction, retrieval, and UI rendering.

## Current Edge Cases

Internal edge cases:

- `.txt`, `.epub`, and `.pdf` are the only supported suffixes.
- Uppercase and mixed-case supported suffixes are accepted after normalization.
- Unsupported suffixes are preserved as invalid staging items.
- Files without suffixes are preserved as invalid staging items with `missing` as the source type summary.
- Mixed valid and invalid selections preserve their original order.
- An empty staging list cannot start ingestion.
- Any invalid staging item blocks ingestion startup.

Cross-system edge cases:

- Invalid staging items must remain visible to future UI code instead of being silently rejected.
- Parser Router should receive source types from valid staging items rather than infer them from filenames.
- Future ingestion startup must check staging validity before parsing, copying, hashing, committing, or creating chunks.
- Logs must stay safe for public repositories and local machines by avoiding full selected paths.

## Invariants

- All selected files must enter the staging list.
- Source type selection must use `pathlib` suffix handling, not content inspection or ad hoc string parsing.
- Unsupported source types must be represented as invalid staging items instead of being silently dropped.
- Invalid staging items must include an error message that future UI code can display.
- Ingestion must not start from an empty staging list or a staging list containing invalid items.
- This filter must not parse, copy, hash, validate contents, commit sources, create chunks, or write database state.

## Implementation Landmarks

- `app/ingestion/staging` owns source type selection filtering.
- `tests/test_source_type_selection_filter.py` covers supported source types, invalid staging entries, ingestion blocking, order preservation, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing Source Type Selection Filter, check:

- Whether the change belongs in source selection, parser routing, source commit orchestration, UI, or storage.
- Whether all selected files still appear in the returned staging list.
- Whether unsupported types still produce invalid staging items with a UI-facing error message.
- Whether ingestion remains blocked when the staging list is empty or contains invalid items.
- Whether parser work still happens later and only for valid staged sources.
- Whether logs avoid full source paths, source text, and local machine details.
