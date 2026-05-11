# Safe Asset File Storage

Safe Asset File Storage is VySol's backend system for copying accepted uploaded image and font files into repo-local user storage without trusting user-provided filenames for the stored filename. It stores uploaded images under `user/assets/images/`, uploaded fonts under `user/assets/fonts/`, creates matching asset metadata, and resolves stored files later by asset ID.

This page is for developers, power users, and AI coding agents that need to understand the uploaded asset file storage contract before changing uploads, asset metadata, path handling, logging, or future asset UI.

## Why It Exists

Uploaded asset filenames can contain display-friendly names, but they are not safe stable storage keys. VySol needs uploaded assets to have stable internal filenames that cannot collide through duplicate display names, cannot depend on local user paths, and can be resolved later from metadata.

Safe Asset File Storage keeps this responsibility separate from asset metadata, hash deduplication, media validation rules, font extraction, deletion, and UI. That boundary lets upload-facing code store a file safely without turning file storage into a broader asset-processing system.

## Ownership Boundary

Safe Asset File Storage owns:

- Copying uploaded image files into `user/assets/images/`.
- Copying uploaded font files into `user/assets/fonts/`.
- Generating asset IDs before copy so internal filenames can use `{asset_id}{suffix}`.
- Preserving the original filename only as asset metadata.
- Using the original filename stem as the default display name.
- Allowing duplicate display names for different files.
- Calculating the file hash required by uploaded asset metadata.
- Creating the uploaded asset metadata record after the copy succeeds.
- Resolving a stored asset file path by asset ID.
- Logging successful storage at `INFO`, unsafe path rejection and copy failure at `ERROR`, and unsupported filename patterns at `WARNING`.

Safe Asset File Storage does not own:

- Defining image or font validation rules.
- Detecting or reusing duplicate hashes.
- Extracting font names from font files.
- Deleting asset files or metadata.
- Rendering upload controls or asset pickers.
- Rewriting built-in asset references.

## Normal Flow

A backend caller passes an asset type, a local source file path, and the original filename to the storage helper. The helper chooses the correct user asset directory from the asset type, calls Image Upload Validation before storing image uploads, and calls Font Upload Validation before storing font uploads.

After validation succeeds, the helper generates a new asset ID, derives a safe optional suffix from the original filename, and builds a destination filename from the asset ID. Before copying, it confirms the destination path stays inside the intended asset storage directory. It calculates a SHA-256 file hash for metadata, copies the source file with Python stdlib file tools, creates the asset metadata record, logs the successful storage event, and returns the saved asset metadata.

Later, a backend caller can resolve an asset ID. The resolver reads asset metadata, treats the stored path as repo-relative metadata, rejects absolute paths or parent-directory traversal, and returns the resolved local file path when the metadata is safe.

## Inputs

Safe Asset File Storage receives:

- An asset type, currently image or font.
- A local source file path for the candidate upload.
- The original filename supplied by the upload boundary.
- An optional SQLite connection for tests or callers that already control the database connection.

The original filename may influence the display name and safe suffix, but it must not control the internal stored filename.

## Outputs

Safe Asset File Storage produces:

- A copied asset file under the correct `user/assets/` child directory.
- An asset metadata row with asset type, display name, stored path, file hash, upload policy, and original filename.
- A returned asset metadata object for backend callers.
- A resolved local file path when an asset ID points to safe stored metadata.

It does not produce UI state, extracted font names, validation policy, duplicate decisions, or deletion results.

## Failure Behavior

Unsupported asset types are rejected before a copy. Image and font validation rejections happen before hash calculation, copy, or metadata creation. Unsafe destination or resolver paths are logged at `ERROR` and rejected without logging raw user paths. Copy failures are logged at `ERROR` and re-raised so callers can fail the upload flow explicitly.

Unsupported original filename path patterns, unusable display names, or unsupported suffixes are logged at `WARNING`. The helper still stores the file when it can choose a safe internal filename and display-name fallback.

## System Interactions

Safe Asset File Storage currently interacts with:

- Asset Metadata Storage, by creating uploaded asset metadata and resolving metadata by asset ID.
- Asset Hash Deduplication, by reusing its SHA-256 hash calculation helper without performing duplicate lookup.
- Image Upload Validation, by calling it before storing image uploads.
- Font Upload Validation, by calling it before storing font uploads.
- Global App Storage, by relying on the app database connection path and migrations used by asset metadata.
- User-owned storage paths, by writing files under the repo-local `user/assets/` area.
- The central logger, by recording storage success, unsafe path rejection, copy failures, and unsupported filename patterns without exposing raw local paths.

Future deletion and UI systems may call or wrap this system while keeping their own responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Images and fonts are routed to different storage directories.
- Invalid image uploads are rejected before copy or metadata creation.
- Invalid font uploads are rejected before copy or metadata creation.
- Duplicate display names are allowed because the stored filename uses the asset ID.
- Original filenames with path separators keep only the final filename component for display and suffix decisions.
- Unsupported suffix patterns are ignored instead of becoming part of the stored filename.
- Missing or unusable display names fall back to a generic uploaded asset display name.
- Copy failures do not create asset metadata.
- Missing asset IDs return no resolved path.
- Unsafe stored paths return no resolved path.

Cross-system edge cases:

- Uploaded asset metadata requires a file hash, so storage must calculate one before metadata creation.
- Image validation must run before hash calculation so rejected images are not treated as accepted asset candidates.
- Font validation must run before hash calculation so rejected fonts are not treated as accepted asset candidates.
- Safe storage must not call duplicate lookup because hash deduplication is a separate decision point.
- Stored paths are metadata and must stay repo-relative so resolvers can reject absolute paths and traversal.
- Built-in asset references can remain outside `user/assets/` because this system owns uploaded files only.
- Logs must avoid raw user paths because source paths and filenames may contain local user-owned details.

## Invariants

- Uploaded image files must be stored under `user/assets/images/`.
- Uploaded font files must be stored under `user/assets/fonts/`.
- Stored filenames must use the asset ID, not the original filename.
- Original filenames may be preserved only as metadata.
- Display names must not be treated as unique file identifiers.
- Stored paths must be repo-relative metadata.
- Resolver logic must reject absolute paths and parent-directory traversal.
- Image validation must happen before image hash calculation, file copy, or metadata creation.
- Font validation must happen before font hash calculation, file copy, or metadata creation.
- File copy must happen before metadata creation.
- Image validation rules, font validation rules, hash deduplication, font-name extraction, deletion, and UI must remain separate responsibilities.

## Implementation Landmarks

- `app/storage/asset_files.py` owns uploaded file copying and asset ID path resolution.
- `app/storage/image_upload_validation.py` owns image upload validation rules.
- `app/storage/font_upload_validation.py` owns font upload validation rules.
- `app/storage/assets.py` owns asset metadata creation, validation, read, and list behavior.
- `app/storage/asset_deduplication.py` owns file hash calculation and exact duplicate lookup.
- `app/storage/paths.py` owns repo-local user asset directory helpers.
- `tests/test_asset_file_storage.py` covers the safe file storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Safe Asset File Storage, check:

- Whether the requested change belongs in file storage or in validation, deduplication, deletion, font extraction, metadata-only storage, or UI.
- Whether image validation still happens before hash calculation, file copy, and metadata creation.
- Whether font validation still happens before hash calculation, file copy, and metadata creation.
- Whether the stored filename still avoids user-provided filename control.
- Whether copied files remain under the correct `user/assets/` child directory.
- Whether metadata creation still happens only after a successful copy.
- Whether asset ID resolution still rejects unsafe stored paths.
- Whether logs avoid raw user paths and local user-owned details.
- Whether duplicate display names remain allowed.
- Whether tests cover copy success, validation rejection, path resolution, unsafe paths, copy failures, and unsupported filename patterns.
