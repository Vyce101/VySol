# Draft World Splitter Settings

Draft World Splitter Settings is VySol's in-memory backend contract for the splitter settings attached to a new uncommitted draft world. It gives future ingestion setup code a stable place to read, update, and validate splitter settings before ingestion work is allowed to use them.

This page is for developers, power users, and AI coding agents that need to understand draft-world setup state before changing ingestion defaults, draft lifecycle behavior, committed-world storage, or future splitter integration.

## Why It Exists

VySol needs draft worlds to start with agreed splitter settings before the recursive text splitter, Ingestion tab, and full commit flow exist. The settings are available to backend code as character counts, and validation gives future Start or Resume flows a backend-owned gate before parsing, splitting, source copying, or commit work begins.

The boundary matters because uncommitted draft worlds are temporary setup state. They must not become committed worlds, app-wide settings, migrations, source records, chunk records, or hidden database rows just because the backend needs a place to hold defaults. Committed-world splitter settings are handled by a separate world database storage contract.

## Ownership Boundary

Draft World Splitter Settings owns:

- Creating default splitter settings for a new draft world.
- Treating splitter values as character counts.
- Attaching the current splitter version metadata to default splitter settings.
- Holding draft splitter settings in process memory.
- Reading an in-memory draft world by draft ID.
- Updating in-memory draft splitter settings without forcing validation at update time.
- Validating splitter settings when backend callers need to prove settings are safe to use.
- Discarding an in-memory draft world when future commit or discard flows no longer need it.
- Logging default initialization failures, invalid validation rejections, validation diagnostics, and unexpected validation failures at the agreed levels.

Draft World Splitter Settings does not own:

- HTTP routes or UI behavior.
- Recursive text splitting.
- Ingestion source records, chunk records, embeddings, graph records, or provider calls.
- Locking, normalizing, correcting, or persisting draft splitter settings.
- Persisting draft worlds or owning committed splitter settings storage.
- Creating committed world index records.
- Database migrations or schema changes.

## Normal Flow

Backend code creates a new draft world through the draft-world registry. The registry creates default splitter settings, generates a draft ID, stores the draft world in memory, and returns it to the caller.

The default settings are `chunk_size` `4000`, `max_lookback_size` `1000`, `overlap_size` `400`, and `splitter_version` `"1"`. The size values are plain integer character counts. The splitter version is string metadata that can also seed committed-world splitter settings storage. No byte counting, token counting, source parsing, or splitter execution happens in this system.

Before a future successful commit, backend code may replace the draft splitter settings in memory. Updates still store replacement values exactly as provided so draft editing can stay separate from use-time validation. When a future Start or Resume flow is ready to process staged ingestion work, it should validate the current settings first and reject invalid settings before any parsing, splitting, source copying, or commit work begins.

Validation accepts whole-number character counts only. `chunk_size` must be at least `1`, `max_lookback_size` must be at least `0` and less than `chunk_size`, and `overlap_size` must be at least `0`. `splitter_version` must be a non-empty string. Overlap can be larger than chunk size because future splitting behavior may use it independently from the fixed chunk priority.

After a future commit or discard action, the draft-world registry can remove the draft so the temporary settings are no longer available. Persisting and locking committed-world splitter settings happens outside this draft registry boundary.

## Inputs

Draft World Splitter Settings receives draft-world creation requests, draft IDs for read/update/discard operations, replacement splitter settings, and validation requests from backend callers. It does not receive source files, committed world IDs, provider responses, or database state.

## Outputs

The system returns in-memory draft-world objects and splitter-setting objects to backend callers. Validation returns the original splitter settings when they are valid, or raises a validation error when they are not. It produces no database rows, files, migrations, source records, chunk records, embeddings, graph records, HTTP responses, or user-facing UI state.

## System Interactions

Draft World Splitter Settings currently interacts with:

- The central logger, which records default initialization failures, validation rejections, validation diagnostics, and unexpected validation failures.
- World Splitter Settings Storage, which can reuse the default splitter values when committed settings are created in `world.sqlite`.
- Future Ingestion tab or ingestion setup code, which can read and update the draft settings once an HTTP or UI surface exists.
- Future Start or Resume ingestion code, which should validate settings before it processes staged batches.
- Future commit or discard flow, which should remove draft state after it no longer represents an uncommitted world.

It must stay separate from Global App Storage and Committed World Index Storage. Draft settings may inform a future commit flow, but this system does not write committed-world records, committed splitter settings, or app database state.

## Current Edge Cases

Internal edge cases:

- Missing draft IDs return no draft world instead of creating one.
- Updating a missing draft ID returns no draft world.
- Discarding a missing draft ID returns no draft world.
- Replacement splitter settings are stored without correction.
- Validation rejects non-integer, boolean, negative, too-small, and incompatible lookback settings.
- Validation rejects missing, empty, or non-string splitter versions.
- Validation allows overlap to be larger than chunk size.
- Expected validation rejections are logged at `WARNING`, with setting values and splitter version logged only at `DEBUG`.
- Unexpected validation failures are logged at `ERROR` and re-raised.
- Default initialization failures are logged at `ERROR` and re-raised.
- Failed default initialization must not leave a partial draft world in memory.

Cross-system edge cases:

- Draft worlds must not be written to `app.sqlite`.
- Creating draft-world defaults must not require the recursive text splitter to exist.
- Future Ingestion tab code must treat these settings as setup state, not as proof that splitting has run.
- Future Start or Resume code must call validation before using settings for staged ingestion work.
- Future commit code must remove the draft only after a successful commit, not before.
- Committed-world locking and persistence must stay in World Splitter Settings Storage unless a later feature explicitly changes the boundary.

## Invariants

- New draft worlds must start with the agreed splitter defaults.
- Splitter values must be treated as character counts.
- The splitter version must remain string metadata, not a numeric setting.
- Draft-world state must remain in memory and outside `app/storage`.
- No database migration is required for uncommitted draft splitter settings.
- The system must not run the splitter.
- Committed settings locking and persistence must remain outside this draft system.
- Validation must reject invalid settings without correcting or normalizing them.
- Validation must keep overlap independent enough to allow values larger than chunk size.
- Routine create, read, update, and discard behavior must not log success messages.
- Default initialization failure and unexpected validation failure must be logged at `ERROR`.

## Implementation Landmarks

- `app/draft_worlds/splitter_settings.py` owns the splitter-setting value object, defaults, validation error, and validation function.
- `app/draft_worlds/world.py` owns the in-memory draft-world object.
- `app/draft_worlds/registry.py` owns draft creation, read, update, and discard behavior.
- `tests/test_draft_world_splitter_defaults.py` covers the current draft and validation contract.

## What AI/Coders Must Check Before Changing This System

Before editing Draft World Splitter Settings, check:

- Whether the change is still temporary draft setup state or belongs in World Splitter Settings Storage.
- Whether the recursive splitter is being accidentally introduced into a defaults-only ticket.
- Whether new locking, normalization, correction, or persistence belongs in a separate feature or committed storage boundary.
- Whether any database migration or `app/storage` change would violate the in-memory draft boundary.
- Whether future ingestion code validates settings before using them for staged batch processing.
- Whether future commit or discard code removes drafts only after the intended lifecycle event.
- Whether logs avoid routine success noise and local user details.
- Whether tests prove defaults, in-memory updates, validation rules, validation logging, discard behavior, no database schema change, and default initialization failure logging.
