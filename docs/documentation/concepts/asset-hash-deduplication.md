# Asset Hash Deduplication

Asset Hash Deduplication is VySol's backend helper for detecting whether an uploaded image or font file is already known by exact file hash. It takes a file path, calculates a SHA-256 hash with Python's standard `hashlib` module, checks the global `assets` table for that hash, and returns an existing asset ID when a match exists.

This page is for developers, power users, and AI coding agents that need to understand the deduplication contract before changing asset upload handling, file storage, metadata creation, or future asset picker behavior.

## Why It Exists

VySol needs a small, reusable way to recognize exact duplicate asset files before future upload storage creates new physical files or new metadata records. The helper keeps hash calculation and duplicate lookup separate from upload validation, file copying, and metadata creation, so those future systems can call it without inheriting extra responsibilities.

This system only compares exact file contents through a cryptographic hash. It does not compare display names, visual similarity, font metadata, or world ownership.

## Ownership Boundary

Asset Hash Deduplication owns:

- Reading a candidate asset file in chunks.
- Calculating a SHA-256 file hash in the existing `sha256:<hex>` format.
- Searching the app-level `assets.file_hash` value for a matching record.
- Returning the existing asset ID when an exact hash match exists.
- Returning no asset ID when no matching hash exists.
- Logging deduplication hits and hash or lookup failures without logging file contents.

Asset Hash Deduplication does not own:

- Accepting uploaded files from users or HTTP requests.
- Validating image or font file types.
- Copying files into user-owned asset storage.
- Creating, updating, or deleting asset metadata records.
- Preventing duplicate display names.
- Comparing perceptual image similarity.
- Extracting font names from font files.
- Choosing whether a caller should reuse, reject, or continue processing a duplicate file.

## Normal Flow

A future upload or storage system passes a candidate file path to the deduplication helper before final asset acceptance. The helper reads the file in fixed-size chunks, updates a SHA-256 hasher, and formats the result with the `sha256:` prefix used by asset metadata.

After hashing succeeds, the helper queries the global `assets` table for a row whose `file_hash` exactly matches the calculated value. If a row exists, the helper logs a deduplication hit at `INFO`, logs the matched asset ID and a short hash prefix at `DEBUG`, and returns the asset ID. If no row exists, it returns `None` so the caller can continue its own storage and metadata flow.

## Inputs

Asset Hash Deduplication receives:

- A local file path for the candidate asset file.
- An optional SQLite connection for tests or callers that already control the database connection.

The helper treats the file contents as bytes and does not inspect file extensions, MIME types, image dimensions, font metadata, display names, or world context.

## Outputs

Asset Hash Deduplication returns:

- An existing asset ID string when the calculated hash matches an existing asset record.
- `None` when no existing asset record has the same file hash.

The helper does not write files, write database rows, mutate metadata, or produce UI state.

## Failure Behavior

File read or hash failures are logged at `ERROR` and re-raised so the caller can decide how upload acceptance should fail. SQLite lookup failures are also logged at `ERROR` and re-raised. The helper does not swallow failures, create fallback hashes, or assume that a failed hash means the file is unique.

## System Interactions

Asset Hash Deduplication currently interacts with:

- Asset Metadata Storage, by reading `assets.file_hash` values and returning existing asset IDs.
- Global App Storage, by using the global database connection when a caller does not provide one.
- The central logger, by recording deduplication hits and failures without exposing full file contents.

Future upload validation and safe asset file storage systems may call this helper before copying files or creating metadata records.

## Current Edge Cases

Internal edge cases:

- Large files are read in chunks instead of loading the full file into memory.
- Missing or unreadable files log an `ERROR` and re-raise the original `OSError`.
- Files with different contents but the same display name do not match, because display names are not part of deduplication.
- Files with the same contents but different names or future world context do match, because deduplication is global and hash-based.

Cross-system edge cases:

- Existing built-in assets with no stored file hash are ignored by the lookup until a future system stores hashes for them.
- Future upload systems must call this helper before creating duplicate files or metadata records if they want deduplication behavior.
- Future metadata creation must still provide a non-empty file hash for uploaded assets, because this helper does not create metadata rows.

## Invariants

- Deduplication must remain global, not per world.
- Deduplication must use exact file contents, not display names or perceptual similarity.
- Hash values must use the `sha256:<hex>` format stored by asset metadata.
- The helper must return only an existing asset ID or `None`.
- The helper must not create, update, delete, copy, or move asset files or metadata records.
- Logs must never include full file contents.
- Hash or database failures must be logged and re-raised.

## Implementation Landmarks

- `app/storage/asset_deduplication.py` owns hash calculation and duplicate asset lookup.
- `app/storage/assets.py` owns asset metadata creation, validation, read, and list behavior.
- `tests/test_asset_deduplication.py` covers the current deduplication helper contract.

## What AI/Coders Must Check Before Changing This System

Before editing Asset Hash Deduplication, check:

- Whether the requested change belongs in deduplication or in upload validation, safe file storage, metadata creation, font extraction, or UI.
- Whether the change preserves global hash-based deduplication.
- Whether the helper still avoids writing files or metadata records.
- Whether hash and database failures are logged and re-raised.
- Whether logs avoid file contents and local user-owned path details.
- Whether tests cover both dedupe hits and no-match results.
