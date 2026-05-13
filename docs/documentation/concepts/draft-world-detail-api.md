# Draft World Detail API

Draft World Detail API is VySol's backend HTTP contract for opening an uncommitted draft world in World Detail. It creates backend-owned draft setup state, exposes the draft's splitter defaults and staged-source summary, and keeps the draft outside committed world storage.

This page is for developers, power users, and AI coding agents that need to understand draft opening behavior before changing Create World entrypoints, World Detail route state, draft splitter defaults, source staging setup, or committed-world visibility.

## Why It Exists

VySol needs a Create World flow that can open World Detail before a world is committed. The frontend must not invent draft identity or splitter defaults on its own, because draft setup state belongs to the backend and later ingestion work needs the same draft ID.

The boundary matters because opening a draft is not the same as committing a world. A draft can be visible in World Detail, refreshed by draft ID, and prepared for future source staging without appearing in World Hub or creating durable world storage.

## Ownership Boundary

Draft World Detail API owns:

- Creating a new in-memory draft world through the draft-world registry.
- Creating or replacing a temporary source staging context keyed by the draft ID.
- Returning draft splitter settings from backend draft state.
- Returning a safe staged-source summary without raw selected file paths.
- Returning `404` for missing draft IDs.
- Keeping draft opening separate from committed world storage, source parsing, ingestion attempts, and world folders.

Draft World Detail API does not own:

- World Hub rendering, Create World buttons, or entry screens.
- Customize controls, validation, saving, or asset picking.
- Source selection UI, file pickers, drag/drop behavior, parsing, splitting, hashing, or duplicate checks.
- Committing worlds, creating world folders, creating `world.sqlite`, copying sources, or writing `app.sqlite` world rows.
- Persisting draft state across app restarts.
- App logging beyond the lower-level draft and staging systems it calls.

## Normal Flow

A future Create World entrypoint calls the draft creation endpoint. The backend creates a draft world in memory, creates an empty temporary source staging context with the same draft ID, and returns a draft detail response. The frontend then navigates to World Detail with draft route state containing that draft ID.

When World Detail loads with a draft ID, it calls the read endpoint. The backend reads the existing draft world and matching temporary staging context from memory, then returns splitter settings and staged-source summaries. Refreshing the same URL reuses the backend draft as long as the app process still owns that in-memory state.

## Inputs

Draft World Detail API receives draft creation requests and draft IDs from frontend route or service code. It reads in-memory draft-world and temporary source staging state.

It does not receive display names, selected source file paths, parser output, source text, chunk rows, database connections, provider responses, or committed world metadata.

## Outputs

The API returns draft detail responses containing:

- A draft ID.
- Splitter settings with character-count defaults and splitter version metadata.
- Staged-source summaries containing temporary staging entry IDs, source type, validity state, and safe error text.

It produces backend in-memory state only. It does not write files, create database rows, create durable world folders, start ingestion, parse sources, copy sources, create chunks, call providers, or emit UI state directly.

## User-Facing Behavior

Users can land in a draft World Detail shell that has `Customize` and `Ingestion` tabs before the world is committed. The Customize pane can show that backend splitter defaults loaded, and the Ingestion pane can show the current staged-source count, but actual controls belong to later tickets.

Missing or expired draft IDs should keep the UI in a draft-safe error state rather than creating a committed world or silently inventing a frontend-only draft.

## Failure Behavior

Missing draft IDs return `404`. Lower-level draft default initialization failures or staging-state validation failures are allowed to fail the request instead of creating partial draft setup state.

The API must not recover by creating a committed world, writing fallback database rows, creating a world folder, or replacing missing backend state with frontend-only draft state.

## System Interactions

Draft World Detail API interacts with:

- Draft World Splitter Settings, which creates and stores draft splitter defaults in memory.
- Temporary Source Staging State, which owns the empty staged-source context and future staged source summaries.
- World Detail Page Shell, which reads backend draft detail for draft route state.
- Committed World Index Storage and Committed World Folder Bootstrap only as systems it must avoid during draft opening.

It must stay separate from ingestion start orchestration, parser routing, chunk storage, new-world commit orchestration, asset storage, graph extraction, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- Creating a draft returns backend defaults and an empty staged-source list.
- Creating a draft creates a matching temporary staging context keyed by draft ID.
- Reading an existing draft returns the same in-memory draft setup state.
- Reading a missing draft returns `404`.
- Missing staging state for an existing draft is represented as an empty staged-source list rather than committed source data.

Cross-system edge cases:

- Draft opening must not write committed world rows into `app.sqlite`.
- Draft opening must not create committed world folders or `world.sqlite`.
- Draft opening must not parse, hash, split, copy, or commit staged sources.
- World Hub must not show drafts because World Hub visibility depends on committed world index rows.
- Refresh behavior depends on the running backend process; app restart recovery remains outside this in-memory draft contract.
- Staged-source summaries must not expose raw local file paths.

## Invariants

- The backend draft registry is the source of truth for draft IDs and splitter defaults.
- The draft ID must be shared by the draft world and temporary source staging context.
- Draft detail responses must stay safe to show in UI without exposing raw local paths.
- Opening a draft must not create committed storage or committed world visibility.
- Draft state must remain temporary and outside `app/storage` migrations.
- The API must not start ingestion or treat splitter settings as proof that splitting has run.
- Future commit code must remain the first boundary that can make a new world visible in World Hub.

## Implementation Landmarks

- `app/draft_worlds/routes.py` owns the draft detail HTTP routes and response shaping.
- `app/draft_worlds/registry.py` owns in-memory draft creation and reads.
- `app/ingestion/staging/source_staging_state.py` owns temporary staged-source state.
- `frontend/src/draft-world-api.ts` owns frontend calls and future Create World navigation helper behavior.
- `frontend/src/world-detail-page.tsx` owns draft route rehydration in the shell.
- `tests/test_draft_world_routes.py` covers the route contract.

## What AI/Coders Must Check Before Changing This System

Before editing Draft World Detail API, check:

- Whether the change still belongs to draft opening rather than World Hub, Customize controls, Ingestion controls, or new-world commit orchestration.
- Whether draft creation still creates matching draft and staging state without committed storage.
- Whether missing draft IDs fail clearly instead of creating hidden state.
- Whether response data avoids raw local paths, source text, secrets, and user-owned file contents.
- Whether frontend refresh behavior still rehydrates from the backend draft ID.
- Whether tests prove no committed world rows, world folders, `world.sqlite`, parsing, chunking, or source copies are created.
