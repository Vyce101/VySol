# Asset Deletion

Asset Deletion is VySol's backend storage system for deleting uploaded asset files that no committed world uses. It removes the uploaded asset metadata row from `app.sqlite` and deletes the stored file from user asset storage when deletion is allowed.

This page is for developers, power users, and AI coding agents that need to understand the asset deletion contract before changing asset storage, committed world asset references, upload cleanup, logging, or future asset picker behavior.

## Why It Exists

Uploaded assets can become unused when no committed world selects them as a background or font. VySol needs a safe backend cleanup boundary that can remove those unused uploads without breaking committed worlds or touching built-in defaults.

This system keeps deletion separate from upload storage and asset metadata creation. Safe Asset File Storage owns copying and resolving uploaded files. Asset Metadata Storage owns asset records and built-in policy. Asset Deletion coordinates those systems only when an uploaded asset is safe to remove.

## Ownership Boundary

Asset Deletion owns:

- Checking whether an asset exists before deletion.
- Rejecting built-in asset deletion.
- Checking whether any committed world references the asset as a background or font.
- Deleting unused uploaded asset metadata rows.
- Deleting the stored uploaded file through a safe resolved path.
- Logging successful unused uploaded asset deletion at `INFO`.
- Logging attempted built-in deletion at `WARNING`.
- Logging file and database deletion failures at `ERROR` without raw full paths.

Asset Deletion does not own:

- Creating asset metadata.
- Copying uploaded asset files into storage.
- Validating uploaded image or font content.
- Detecting duplicate uploads by file hash.
- Rewriting committed world records to fallback assets.
- Deleting used uploaded assets.
- Deleting built-in default assets.
- Rendering asset picker UI, confirmation UI, or user-facing deletion flows.

## Normal Flow

A backend caller asks to delete an asset by asset ID. Asset Deletion reads asset metadata from the shared app database. Missing asset IDs return no deletion result.

If the asset is built in, deletion is rejected and logged as a warning. If the asset is user-uploaded, Asset Deletion checks the committed world index for any world whose background or font asset ID matches the candidate asset. Used uploaded assets return no deletion result and are left unchanged.

For an unused uploaded asset, Asset Deletion resolves the stored file path through Safe Asset File Storage's existing path safety checks. If the path is safe, the system deletes the asset metadata row, deletes the stored file with Python `pathlib`, commits the database change, logs the successful deletion, and returns a deletion result.

## Inputs

Asset Deletion receives:

- An asset ID.
- An optional SQLite connection for tests or callers that already control the database connection.

The asset ID is treated as the lookup key only. Stored paths come from asset metadata and must pass safe resolution before any file deletion happens.

## Outputs

Asset Deletion produces:

- A boolean deletion result for backend callers.
- A removed uploaded asset metadata row when deletion succeeds.
- A deleted uploaded file when deletion succeeds.
- Log events for successful deletion, protected built-in deletion attempts, and deletion failures.

It does not produce UI state, fallback asset choices, world updates, HTTP responses, or new asset metadata.

## Failure Behavior

Unsafe stored paths return no deletion result after the resolver rejects the path and logs the unsafe path without exposing raw path text. Database deletion failures are rolled back, logged at `ERROR`, and re-raised. File deletion failures roll back the staged metadata deletion, log at `ERROR`, and re-raise so callers do not mistake a partial failure for a successful cleanup.

Used uploaded assets are not treated as failures. They return no deletion result because preserving committed world references is the expected behavior.

## System Interactions

Asset Deletion currently interacts with:

- Asset Metadata Storage, by reading asset records and deleting the metadata row for an allowed unused upload.
- Safe Asset File Storage, by reusing stored asset path resolution before deleting a file.
- Committed World Index Storage, by checking whether any committed world background or font references the asset ID.
- Global App Storage, by using the shared app database connection.
- The central logger, by recording deletion success, protected deletion attempts, and deletion failures without raw full paths.

Future asset picker or confirmation UI can call this backend system, but UI should keep confirmation, button state, and user messaging outside this storage boundary.

## Current Edge Cases

Internal edge cases:

- Missing asset IDs return no deletion result.
- Built-in assets are rejected before any file or database deletion.
- Unsafe stored paths return no deletion result.
- File deletion failures roll back the staged metadata deletion.
- Database deletion failures roll back the database transaction and re-raise.
- Logs must not include raw full paths.

Cross-system edge cases:

- Uploaded assets referenced by committed worlds must not be deleted.
- The committed world index must not be updated to fallback defaults during deletion.
- Built-in default asset references may point outside user asset storage and must remain protected.
- Stored paths are metadata and must be resolved safely before file deletion.
- Asset deletion must not perform upload validation, duplicate detection, or world cleanup work.

## Invariants

- Built-in assets are never deletable.
- Only uploaded assets with no committed world references may be deleted.
- Background and font references in committed worlds must remain unchanged.
- Stored asset files must be deleted through safe resolved paths, not raw metadata strings.
- Deletion logs must avoid raw full paths and local user-owned path details.
- Asset deletion must use the central database helper when a caller does not provide a connection.
- Upload storage, metadata creation, deduplication, and UI confirmation must remain separate responsibilities.

## Implementation Landmarks

- `app/storage/asset_deletion.py` owns the deletion flow.
- `app/storage/worlds.py` owns the committed world asset reference lookup.
- `app/storage/asset_files.py` owns stored asset path resolution.
- `app/storage/assets.py` owns asset metadata reads and built-in policy fields.
- `tests/test_asset_deletion.py` covers the deletion contract.

## What AI/Coders Must Check Before Changing This System

Before editing Asset Deletion, check:

- Whether the requested change should stay in deletion or belongs in upload storage, metadata creation, deduplication, committed world updates, or UI.
- Whether built-in assets remain protected before file or metadata deletion.
- Whether committed world background and font references are checked before deleting uploaded assets.
- Whether used uploaded assets remain unchanged.
- Whether unsafe stored paths are rejected before file deletion.
- Whether file and database failures are logged at `ERROR` and re-raised.
- Whether logs avoid raw full paths and other local user-owned details.
- Whether tests cover built-in rejection, used asset preservation, unused upload deletion, unsafe path rejection, and file/database failures.
