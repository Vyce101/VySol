# Asset Deletion

Asset Deletion is VySol's backend storage system for removing uploaded asset records and stored uploaded files. It supports direct deletion for unused uploaded assets and confirmed fallback deletion for uploaded assets that committed worlds currently use.

This page is for developers, power users, and AI coding agents that need to understand the asset deletion contract before changing asset storage, committed world asset references, upload cleanup, logging, or future asset picker behavior.

## Why It Exists

Uploaded assets can become unused, or they can be selected by committed worlds as background images or fonts. VySol needs a safe backend boundary that can delete uploaded assets without breaking committed worlds, touching built-in defaults, or letting stale confirmation data rewrite worlds the caller did not review.

This system keeps deletion separate from upload storage, asset metadata creation, and UI confirmation. Safe Asset File Storage owns copying and resolving uploaded files. Asset Metadata Storage owns asset records and built-in policy. Committed World Index Storage owns world records. Asset Deletion coordinates those systems only at the deletion boundary.

## Ownership Boundary

Asset Deletion owns:

- Checking whether an asset exists before deletion.
- Rejecting built-in asset deletion.
- Looking up committed worlds affected by an uploaded asset deletion.
- Returning affected committed world IDs and display names before used uploaded assets are deleted.
- Requiring confirmed affected world IDs before fallback deletion.
- Updating affected committed worlds to the main default image or font during confirmed fallback deletion.
- Deleting uploaded asset metadata rows.
- Deleting stored uploaded files through safe resolved paths.
- Keeping fallback world updates and uploaded asset metadata deletion inside one SQLite transaction.
- Logging affected-world lookup and confirmed fallback updates at `INFO`.
- Logging attempted built-in deletion at `WARNING`.
- Logging file and database deletion failures at `ERROR` without raw full paths.

Asset Deletion does not own:

- Creating asset metadata.
- Copying uploaded asset files into storage.
- Validating uploaded image or font content.
- Detecting duplicate uploads by file hash.
- Choosing custom replacement assets.
- Deleting built-in default assets.
- Rendering asset picker UI, confirmation UI, or user-facing deletion flows.

## Normal Flow

A backend caller asks for deletion impact by asset ID. Asset Deletion reads asset metadata from the shared app database. Missing asset IDs return no impact. Built-in assets are rejected and logged as a warning. Uploaded assets return a deletion impact object containing the asset ID, asset type, and committed world references whose background or font asset ID matches the uploaded asset.

If the uploaded asset is unused, a backend caller can still use the direct unused deletion flow. Asset Deletion resolves the stored file path through Safe Asset File Storage's path safety checks, deletes the uploaded asset metadata row, deletes the stored file with Python `pathlib`, commits the database change, logs the deletion, and returns a deletion result.

If committed worlds use the uploaded asset, the caller must pass confirmed affected world IDs back to the confirmed fallback deletion flow. Asset Deletion re-reads the current affected worlds inside the delete path. If the current affected world IDs do not exactly match the confirmed IDs, deletion is refused so stale confirmation data cannot update worlds the caller did not show.

When confirmation matches, Asset Deletion chooses the main default image for uploaded image deletion or the main default font for uploaded font deletion. It starts a SQLite transaction, updates the affected committed world asset column, deletes the uploaded asset metadata row, deletes the stored file, commits the transaction, logs the fallback update and deletion, and returns a deletion result.

## Inputs

Asset Deletion receives:

- An asset ID.
- Confirmed affected committed world IDs for used uploaded asset deletion.
- An optional SQLite connection for tests or callers that already control the database connection.

The asset ID is treated as the lookup key only. Stored paths come from asset metadata and must pass safe resolution before any file deletion happens.

## Outputs

Asset Deletion produces:

- A deletion impact object containing affected committed world IDs and display names.
- A boolean deletion result for backend callers.
- Updated committed world asset references when confirmed fallback deletion succeeds.
- A removed uploaded asset metadata row when deletion succeeds.
- A deleted uploaded file when deletion succeeds.
- Log events for affected-world lookup, confirmed fallback updates, successful deletion, protected built-in deletion attempts, and deletion failures.

It does not produce UI state, HTTP responses, uploaded asset metadata, custom fallback choices, or user-facing confirmation messages.

## Failure Behavior

Unsafe stored paths return no deletion result after the resolver rejects the path and logs the unsafe path without exposing raw path text. Database failures are rolled back, logged at `ERROR`, and re-raised. File deletion failures roll back staged fallback updates and metadata deletion, log at `ERROR`, and re-raise so callers do not mistake a partial failure for successful cleanup.

Stale confirmation data is not treated as a system failure. If the confirmed world IDs do not match the current affected world IDs, Asset Deletion returns no deletion result and leaves the asset, file, and committed world references unchanged.

## System Interactions

Asset Deletion currently interacts with:

- Asset Metadata Storage, by reading asset records and deleting uploaded metadata rows when deletion succeeds.
- Safe Asset File Storage, by reusing stored asset path resolution before deleting a file.
- Committed World Index Storage, by listing affected worlds and replacing affected background or font references during confirmed fallback deletion.
- Global App Storage, by using the shared app database connection.
- Default Asset references, by using the main default image or font as the fallback target.
- The central logger, by recording deletion impact lookup, fallback updates, deletion success, protected deletion attempts, and deletion failures without raw full paths.

Future asset picker or confirmation UI can call this backend system, but UI should keep confirmation display, button state, and user messaging outside this storage boundary.

## Current Edge Cases

Internal edge cases:

- Missing asset IDs return no deletion impact or deletion result.
- Built-in assets are rejected before any file or database deletion.
- Unsafe stored paths return no deletion result.
- Stale confirmed world IDs refuse deletion without changing metadata, files, or world references.
- File deletion failures roll back staged fallback updates and metadata deletion.
- Database failures roll back the database transaction and re-raise.
- Logs must not include raw full paths.

Cross-system edge cases:

- Uploaded assets referenced by committed worlds can be deleted only after affected world IDs are known and confirmed.
- Confirmed fallback deletion must update only the matching asset column for the deleted asset type.
- Image deletion must not alter font selections, and font deletion must not alter background selections.
- Built-in default asset references may point outside user asset storage and must remain protected.
- Stored paths are metadata and must be resolved safely before file deletion.
- Asset deletion must not perform upload validation, duplicate detection, or custom replacement selection.

## Invariants

- Built-in assets are never deletable.
- Uploaded asset deletion must not happen before affected committed worlds can be identified.
- Used uploaded assets require matching confirmed world IDs before fallback deletion.
- Confirmed fallback deletion must use the main default image for image assets and the main default font for font assets.
- Confirmed fallback world updates and uploaded asset metadata deletion must stay inside one SQLite transaction.
- Stored asset files must be deleted through safe resolved paths, not raw metadata strings.
- Deletion logs must avoid raw full paths and local user-owned path details.
- Asset deletion must use the central database helper when a caller does not provide a connection.
- Upload storage, metadata creation, deduplication, custom fallback choice, and UI confirmation must remain separate responsibilities.

## Implementation Landmarks

- `app/storage/asset_deletion.py` owns deletion impact lookup, unused deletion, and confirmed fallback deletion.
- `app/storage/worlds.py` owns committed world asset reference lookup and transaction-friendly fallback updates.
- `app/storage/asset_files.py` owns stored asset path resolution.
- `app/storage/assets.py` owns asset metadata reads and built-in policy fields.
- `app/storage/default_assets.py` owns the stable main default image and font references.
- `tests/test_asset_deletion.py` covers the deletion contract.

## What AI/Coders Must Check Before Changing This System

Before editing Asset Deletion, check:

- Whether the requested change should stay in deletion or belongs in upload storage, metadata creation, deduplication, committed world updates, or UI.
- Whether built-in assets remain protected before file or metadata deletion.
- Whether affected committed world names and IDs are available before used uploaded assets can be deleted.
- Whether confirmed deletion rejects stale affected-world confirmation data.
- Whether fallback updates change only the asset column that matches the deleted asset type.
- Whether fallback updates and metadata deletion remain transactionally tied together.
- Whether unsafe stored paths are rejected before file deletion.
- Whether file and database failures are logged at `ERROR` and re-raised.
- Whether logs avoid raw full paths and other local user-owned details.
- Whether tests cover built-in rejection, impact lookup, unused upload deletion, confirmed fallback deletion, stale confirmation rejection, unsafe path rejection, and file/database failures.
