# Draft World Splitter Settings

Draft World Splitter Settings is VySol's in-memory backend contract for the splitter settings attached to a new uncommitted draft world. It gives future ingestion setup code a stable place to read and update splitter settings before the world is successfully committed.

This page is for developers, power users, and AI coding agents that need to understand draft-world setup state before changing ingestion defaults, draft lifecycle behavior, committed-world storage, or future splitter integration.

## Why It Exists

VySol needs draft worlds to start with agreed splitter settings before the recursive text splitter, Ingestion tab, and full commit flow exist. The settings are available to backend code as character counts, but they do not validate user choices, run splitting, or persist anything to the global database.

The boundary matters because uncommitted draft worlds are temporary setup state. They must not become committed worlds, app-wide settings, migrations, source records, chunk records, or hidden database rows just because the backend needs a place to hold defaults.

## Ownership Boundary

Draft World Splitter Settings owns:

- Creating default splitter settings for a new draft world.
- Treating splitter values as character counts.
- Holding draft splitter settings in process memory.
- Reading an in-memory draft world by draft ID.
- Updating in-memory draft splitter settings without validation.
- Discarding an in-memory draft world when future commit or discard flows no longer need it.
- Logging default initialization failure at `ERROR`.

Draft World Splitter Settings does not own:

- HTTP routes or UI behavior.
- Recursive text splitting.
- Ingestion source records, chunk records, embeddings, graph records, or provider calls.
- Validation, locking, normalization, or range enforcement for splitter settings.
- Persisting draft worlds or committed splitter settings.
- Creating committed world index records.
- Database migrations or schema changes.

## Normal Flow

Backend code creates a new draft world through the draft-world registry. The registry creates default splitter settings, generates a draft ID, stores the draft world in memory, and returns it to the caller.

The default settings are `chunk_size` `4000`, `max_lookback_size` `1000`, and `overlap_size` `400`. These values are plain integer character counts. No byte counting, token counting, source parsing, or splitter execution happens in this system.

Before a future successful commit, backend code may replace the draft splitter settings in memory. Because this system intentionally does not validate settings, the updated values are stored exactly as provided. After a future commit or discard action, the draft-world registry can remove the draft so the temporary settings are no longer available.

## Inputs

Draft World Splitter Settings receives draft-world creation requests, draft IDs for read/update/discard operations, and replacement splitter settings from backend callers. It does not receive source files, committed world IDs, provider responses, or database state.

## Outputs

The system returns in-memory draft-world objects and splitter-setting objects to backend callers. It produces no database rows, files, migrations, source records, chunk records, embeddings, graph records, HTTP responses, or user-facing UI state.

## System Interactions

Draft World Splitter Settings currently interacts with:

- The central logger, which records only default initialization failures for this system.
- Future Ingestion tab or ingestion setup code, which can read the draft settings once an HTTP or UI surface exists.
- Future commit or discard flow, which should remove draft state after it no longer represents an uncommitted world.

It must stay separate from Global App Storage and Committed World Index Storage. Draft settings may inform a future commit flow, but this system does not write committed-world records or app database state.

## Current Edge Cases

Internal edge cases:

- Missing draft IDs return no draft world instead of creating one.
- Updating a missing draft ID returns no draft world.
- Discarding a missing draft ID returns no draft world.
- Replacement splitter settings are stored without validation or correction.
- Default initialization failures are logged at `ERROR` and re-raised.
- Failed default initialization must not leave a partial draft world in memory.

Cross-system edge cases:

- Draft worlds must not be written to `app.sqlite`.
- Creating draft-world defaults must not require the recursive text splitter to exist.
- Future Ingestion tab code must treat these settings as setup state, not as proof that splitting has run.
- Future commit code must remove the draft only after a successful commit, not before.
- Future validation or locking must be added outside this default-setting contract unless that feature explicitly expands the system.

## Invariants

- New draft worlds must start with the agreed splitter defaults.
- Splitter values must be treated as character counts.
- Draft-world state must remain in memory and outside `app/storage`.
- No database migration is required for uncommitted draft splitter settings.
- The system must not run the splitter.
- The system must not validate, lock, or persist committed splitter settings.
- Routine create, read, update, and discard behavior must not log success messages.
- Default initialization failure must be logged at `ERROR`.

## Implementation Landmarks

- `app/draft_worlds/splitter_settings.py` owns the splitter-setting value object and defaults.
- `app/draft_worlds/world.py` owns the in-memory draft-world object.
- `app/draft_worlds/registry.py` owns draft creation, read, update, and discard behavior.
- `tests/test_draft_world_splitter_defaults.py` covers the current contract.

## What AI/Coders Must Check Before Changing This System

Before editing Draft World Splitter Settings, check:

- Whether the change is still temporary draft setup state or has become committed-world persistence.
- Whether the recursive splitter is being accidentally introduced into a defaults-only ticket.
- Whether new validation, locking, normalization, or persistence belongs in a separate feature.
- Whether any database migration or `app/storage` change would violate the in-memory draft boundary.
- Whether future commit or discard code removes drafts only after the intended lifecycle event.
- Whether logs avoid routine success noise and local user details.
- Whether tests prove defaults, in-memory updates, discard behavior, no database schema change, and default initialization failure logging.
