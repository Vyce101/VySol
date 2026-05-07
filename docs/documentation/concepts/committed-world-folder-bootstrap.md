# Committed World Folder Bootstrap

Committed World Folder Bootstrap is VySol's backend contract for creating and resolving the on-disk folder for a committed world. It stores committed world folders under `user/worlds/<world_id>/`, using the UUID world ID as the folder name, and creates a `sources/` folder inside each committed world folder.

This page is for developers, power users, and AI coding agents that need to understand the committed-world folder boundary before changing world creation, ingestion setup, source storage, per-world databases, or path handling.

## Why It Exists

Committed worlds need a stable storage location that does not change when a user renames a world. Display names are user-facing metadata, while world IDs are stable storage identifiers. Keeping folder paths based on UUID world IDs lets future systems add source files, per-world databases, chunks, and graph state without coupling stored files to mutable display names.

The folder bootstrap is intentionally small. It creates only the committed world's root folder and its `sources/` child folder so world-scoped systems can build on a stable boundary without making folder bootstrap responsible for their content.

## Ownership Boundary

Committed World Folder Bootstrap owns:

- Resolving the `user/worlds/` storage root.
- Resolving a committed world folder from a UUID `world_id`.
- Resolving the `sources/` folder inside a committed world folder.
- Creating the committed world folder and `sources/` folder.
- Rejecting non-UUID folder IDs before path resolution or folder creation.
- Logging committed world folder creation at `INFO`.
- Logging folder creation failures at `ERROR` without local absolute paths or display names.

Committed World Folder Bootstrap does not own:

- Draft world folders or draft world persistence.
- Committed world index records.
- Display names, descriptions, asset selections, or `last_used_at` timestamps.
- `world.sqlite` creation.
- Source file copies, source records, chunks, embeddings, graph records, or ingestion state.
- UI, World Hub behavior, Customize behavior, or chat instance behavior.

## Normal Flow

Backend code receives a committed world ID from an existing committed-world record or another trusted committed-world flow. The folder helper validates that the ID is a UUID string before using it as a path segment.

After validation, the helper resolves the committed world folder as `user/worlds/<world_id>/` and the sources folder as `user/worlds/<world_id>/sources/`. Folder creation is idempotent: existing folders are accepted, and missing parent folders are created as needed.

Successful creation logs the committed world folder bootstrap at `INFO` using the world ID only. If the filesystem rejects creation, the failure is logged at `ERROR` and re-raised so the caller can fail the wider operation instead of assuming storage exists.

## Inputs

Committed World Folder Bootstrap receives a `world_id` string. It does not receive display names, draft IDs, source files, database rows, asset metadata, provider responses, or user-facing path text.

## Outputs

The system returns `Path` objects for the committed world folder and its `sources/` folder. The creation helper creates folders on disk under ignored user-owned storage. It does not create database rows, source files, per-world databases, UI state, chunks, embeddings, graph records, or manifests.

## System Interactions

Committed World Folder Bootstrap currently interacts with:

- Global App Storage path helpers, which define the repo-local `user/` storage root.
- Committed World Index Storage, which creates and stores UUID world IDs that can be used by folder helpers.
- World Database Bootstrap, which uses committed world folders as the location for `world.sqlite`.
- Draft World Splitter Settings, which must remain in-memory and must not create committed world folders.
- The central logger, which records successful folder creation and filesystem failures.

Ingestion, source storage, per-world database, graph, and retrieval systems may use these helpers to find world-scoped storage, but they should keep their own file and database responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Non-UUID world IDs are rejected before any folder path is resolved or created.
- Display names are rejected by the same UUID validation because they are not valid storage identifiers.
- Existing committed world folders and `sources/` folders are accepted during creation.
- Missing parent directories under `user/` are created as needed.
- Filesystem creation failures are logged at `ERROR` and re-raised.
- Logs use sanitized wording and world IDs instead of full local paths.

Cross-system edge cases:

- Draft world creation must not create `user/worlds/`.
- Committed World Index Storage owns world record creation; this system only uses world IDs.
- Future rename flows must update display-name metadata without moving folders.
- Source-copy and ingestion flows must use `sources/` without creating `world.sqlite`, chunks, graph records, or other per-world state as part of folder bootstrap.
- Future code must not pass user-provided display names into path helpers.

## Invariants

- Committed world folders must live under `user/worlds/<world_id>/`.
- The folder name must be the UUID world ID, never the display name.
- The `sources/` folder must live directly inside the committed world folder.
- Path helpers must accept `world_id` only.
- Invalid UUID values must fail before folder creation.
- Draft worlds must not create committed world folders.
- Folder logs must avoid local absolute paths and user-provided display names.
- This system must not create `world.sqlite`, source copies, chunks, graph records, UI state, or committed world index rows.

## Implementation Landmarks

- `app/storage/paths.py` owns the shared `user/worlds/` root helper.
- `app/storage/world_folders.py` owns committed world folder resolution, UUID validation, and folder creation.
- `tests/test_world_folder_bootstrap.py` covers the folder bootstrap contract.

## What AI/Coders Must Check Before Changing This System

Before editing Committed World Folder Bootstrap, check:

- Whether the change still belongs to folder bootstrap or has become source storage, ingestion, per-world database, graph, or UI behavior.
- Whether any new path helper still uses UUID world IDs instead of display names.
- Whether invalid IDs fail before filesystem writes.
- Whether draft-world code remains separate from committed folder creation.
- Whether logs avoid full local paths and display names.
- Whether tests prove folder resolution, `sources/` creation, invalid-ID rejection, filesystem failure logging, and draft-world separation.
