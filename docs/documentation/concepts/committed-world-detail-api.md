# Committed World Detail API

Committed World Detail API is VySol's backend HTTP contract for opening a committed world into World Detail without treating that read as recent use. It combines app-level world metadata from `app.sqlite` with source and splitter records from the selected world's `world.sqlite`.

This page is for developers, power users, and AI coding agents that need to understand committed World Detail loading before changing World Hub navigation, World Detail route state, committed-world metadata reads, source summaries, or splitter settings storage.

## Why It Exists

World Hub can list committed worlds from global app storage, but World Detail needs more than card data. It needs the saved customization metadata, committed source summaries, and locked splitter settings for one world.

The boundary matters because opening Manage World is a read operation. It must not refresh `last_used_at`, create missing world folders, create replacement databases, expose stored source paths, or imply that chat, retrieval, graph, deletion, replacement, or re-ingestion behavior exists in this flow.

## Ownership Boundary

Committed World Detail API owns:

- Validating that the committed world exists in `app.sqlite` before opening world-scoped storage.
- Reading committed world metadata from global app storage.
- Opening the existing selected world's `world.sqlite`.
- Reading locked splitter settings for the committed world.
- Reading committed source summaries in book order.
- Returning browser-safe asset URLs for saved background and font asset IDs.
- Failing detail load when required committed detail state is missing or invalid.
- Logging backend detail-load failures at `ERROR`.

Committed World Detail API does not own:

- Updating `last_used_at` for read-only detail loads.
- Creating committed worlds, draft worlds, world folders, or replacement `world.sqlite` files.
- Saving customization changes.
- Adding, deleting, replacing, or re-ingesting committed sources.
- Reading source text, chunk text, graph records, retrieval data, or chat state.
- Exposing stored file paths, hashes, source text, or local filesystem paths.
- Rendering Customize controls in the frontend.

## Normal Flow

World Hub routes to committed World Detail with a committed world ID when the user activates Manage World. The World Detail page requests committed detail for that world ID.

The backend first reads the committed world record from `app.sqlite`. If the world is missing, the request fails before any world-scoped database path is opened. If the world exists, the backend opens that world's existing `world.sqlite`, reads locked splitter settings, reads committed source summaries in book order, resolves browser-safe asset URLs, and returns a detail response.

The load is intentionally read-only. It preserves `last_used_at`; that timestamp is only for real use signals such as saved committed-world customization changes or successful source commits.

## Inputs

Committed World Detail API receives a committed world ID from frontend route state. It reads committed metadata from `app.sqlite`, world-scoped settings and source rows from `world.sqlite`, and asset URL data from Asset File Delivery.

## Outputs

The API returns committed detail state for World Detail:

- World identity and saved display metadata.
- Background and font asset IDs plus browser-safe delivery URLs.
- Current `last_used_at` as stored in global app storage.
- Locked splitter settings.
- Committed source summaries with source identity, original filename, source type, book number, and commit time.

It may also return a load failure for missing worlds, missing world databases, invalid splitter settings, or source/settings read failures. It does not write app state as part of a successful read.

## Failure Behavior

Detail load failures are operation failures for the requested world and are logged at `ERROR`. Missing committed worlds must fail before opening world-scoped storage so a bad request cannot create a folder or empty database. Missing, unlocked, or invalid splitter settings fail the detail load because a committed world detail view must reflect committed splitter state.

## User-Facing Behavior

World Detail can show loading, loaded, or error state for committed detail. The initial committed view defaults to the Customize tab. Current UI output is intentionally minimal: it proves the saved data is loaded into frontend state without building full Customize controls.

## System Interactions

Committed World Detail API interacts with:

- World Hub Page, which creates committed World Detail route state when Manage World is activated.
- World Detail Page Shell, which calls this API in committed mode and displays loading or error state.
- Committed World Index Storage, which owns global committed metadata and `last_used_at`.
- World Database Bootstrap, which provides guarded access to an existing world-scoped database.
- World Splitter Settings Storage, which owns locked splitter settings.
- Committed Source Storage, which owns committed source summaries.
- Asset File Delivery, which turns saved asset IDs into browser-safe URLs.

## Current Edge Cases

Internal edge cases:

- Missing committed world IDs fail before world-scoped storage is opened.
- Missing `world.sqlite` is a load failure, not a bootstrap signal.
- Missing splitter settings fail the load.
- Unlocked splitter settings fail the load because committed detail requires committed settings.
- Invalid splitter values fail the load through storage validation.
- Source summary read failures fail the load instead of returning partial committed detail.

Cross-system edge cases:

- Detail reads must preserve `last_used_at`; recent-use updates belong to saved customization changes and successful source commits.
- Detail responses must not expose stored paths, hashes, source text, or local filesystem paths from committed source storage.
- The frontend must surface load errors in UI state without console spam.
- Opening committed detail must not create draft state, staging state, ingestion attempts, graph data, retrieval state, or chat state.

## Invariants

- A committed detail load must validate the world exists in `app.sqlite` before opening `world.sqlite`.
- A committed detail load must not create missing world folders or databases.
- A committed detail load must not update `last_used_at`.
- A committed detail response must include locked splitter settings or fail.
- Committed source summaries must stay summaries; they must not expose persisted file paths, hashes, source text, or local filesystem paths.
- Backend load failures must log at `ERROR`.

## Implementation Landmarks

- `app/committed_worlds` owns the committed detail HTTP route.
- `app/storage/world_databases.py` owns existing-world database opening.
- `app/storage/world_splitter_settings.py` owns splitter settings reads and lock state.
- `app/storage/committed_sources.py` owns committed source summary reads.
- `frontend/src/committed-world-api.ts` owns the frontend request helper and response types.
- `frontend/src/world-detail-page.tsx` owns committed-mode loading, error state, and minimal display state.

## What AI/Coders Must Check Before Changing This System

Before editing Committed World Detail API, check:

- Whether the change could update `last_used_at` from a read-only detail load.
- Whether a missing committed world or missing `world.sqlite` could accidentally create storage.
- Whether source summaries expose paths, hashes, source text, or local filesystem paths.
- Whether splitter settings are still required to be locked for committed detail.
- Whether frontend error handling remains visible to users without console logging.
- Whether the change crosses into chat, retrieval, graph, source deletion, source replacement, or re-ingestion behavior.
