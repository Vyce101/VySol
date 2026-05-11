# Asset Metadata Storage

Asset Metadata Storage is VySol's app-level record system for known image and font assets. It stores metadata in `user/data/app.sqlite` so backend systems can seed built-in defaults, create uploaded asset metadata, read asset references by ID, and list asset records without taking ownership of physical file copying, file validation, deletion, or UI picker behavior.

This page is for developers, power users, and AI coding agents that need to understand the asset metadata contract before changing storage, migrations, asset registration, upload handling, font handling, or future asset UI.

## Why It Exists

VySol needs a small, durable place to remember which assets the app knows about. Built-in assets and uploaded assets both need stable IDs, display names, type information, stored paths, optional original filenames, and optional font metadata so other systems can refer to them without coupling themselves to every detail of file storage.

This system keeps the metadata layer separate. Safe Asset File Storage can create uploaded metadata after it copies a file, while other systems can decide file validation, font-name extraction, and user-facing picker behavior without changing the core metadata contract.

## Ownership Boundary

Asset Metadata Storage owns:

- Seeding known built-in default image and font asset references.
- Creating asset metadata records for image and font assets.
- Reading one asset metadata record by asset ID.
- Reading the main default background and font asset references by their stable built-in IDs.
- Listing asset metadata records in a stable order.
- Generating UUID asset IDs for regular created metadata records when a caller does not provide one.
- Accepting caller-provided asset IDs when another storage system must align metadata with a physical stored filename.
- Preserving stable app-defined IDs for known built-in defaults.
- Validating metadata required by the current storage contract.
- Treating built-in assets as non-user-uploaded and non-deletable through policy derived from `is_built_in`.
- Preserving the original uploaded filename as optional metadata.
- Logging metadata creation, default seeding, default lookup results, invalid metadata, and database failures without exposing full stored paths.

Asset Metadata Storage does not own:

- Copying uploaded files into local storage.
- Validating uploaded file types.
- Calculating file hashes or checking whether a file hash already belongs to another asset record.
- Deleting asset records or physical files.
- Extracting font names from font files.
- Rendering asset pickers or other user interface flows.
- Deciding where uploaded assets are physically stored.

## Normal Flow

During global database bootstrap, Asset Metadata Storage seeds the known built-in image and font references after migrations complete. Built-in defaults use stable app-defined IDs and an idempotent upsert, so repeated startup refreshes the same rows instead of creating duplicates.

Backend code can also build a new asset metadata request with an asset type, display name, stored path, built-in/uploaded flag, optional file hash, optional original filename, optional full font name, and optional caller-provided asset ID. Asset Metadata Storage validates that request before writing anything to SQLite.

If validation succeeds, the storage layer uses the caller-provided asset ID or generates a UUID asset ID, inserts the record into the `assets` table, commits the transaction, logs the creation at `INFO`, and returns the saved record. Read and list operations query the same table and map SQLite rows back into backend asset metadata objects.

Backend code can look up the main default background and main default font through dedicated storage helpers. Successful default lookups are logged at `INFO`. Missing built-in default references are logged at `ERROR` and return no record.

## Inputs

Asset Metadata Storage receives backend-created metadata values and built-in default definitions owned by the app. Current valid asset types are image and font. The stored path is metadata; Safe Asset File Storage produces stored paths for uploaded files, while built-in defaults use app-owned asset paths.

Uploaded assets must include a file hash. Built-in assets may omit the file hash. Original filename and full font name are optional and are stored exactly as provided, because filename interpretation and font extraction are outside this system.

## Outputs

The system writes asset metadata rows into `app.sqlite` and returns asset metadata objects to backend callers. Returned metadata exposes user-uploaded and deletable policy as derived values from `is_built_in`. It does not produce files, UI state, copied-file results, extracted font names, or HTTP responses.

## System Interactions

Asset Metadata Storage currently interacts with:

- Asset Hash Deduplication, which can calculate an exact file hash and look for an existing asset ID before callers decide whether to create new metadata.
- Safe Asset File Storage, which copies uploaded files and creates matching uploaded asset metadata.
- Global App Storage, which opens `app.sqlite`, applies migrations, and triggers default asset seeding.
- Backend storage modules that need to create, read, or list asset metadata.
- The central logger, which records creation, default seeding, default lookup, validation, and database failure events.

Font extraction and picker UI systems may call this system after they produce valid metadata, but those systems should keep their own responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Unknown asset types are rejected before a database write.
- Empty display names are rejected before a database write.
- Empty stored paths are rejected before a database write.
- Uploaded assets without a file hash are rejected before a database write.
- Caller-provided asset IDs must not be empty.
- Built-in assets without a file hash are allowed.
- Known built-in defaults are seeded idempotently by stable asset ID.
- Built-in asset metadata returns `is_user_uploaded` and `is_deletable` as false through derived policy.
- Missing asset IDs return no record instead of creating one.
- Missing main default background or font references return no record and log an `ERROR`.
- SQLite failures are rolled back, logged at `ERROR`, and re-raised.

Cross-system edge cases:

- Stored paths must not be logged in full, because uploaded asset storage may produce local user-owned paths.
- The metadata layer must not assume the physical file already exists.
- The metadata layer must not treat duplicate display names as duplicate files; exact file hash lookup belongs to Asset Hash Deduplication and copy decisions belong to Safe Asset File Storage.
- Font metadata must not pretend extraction happened; `full_font_name` is optional until a font extraction system provides it.
- Global App Storage must seed built-in defaults only after the assets table migration has been applied.

## Invariants

- Regular created metadata records must receive UUID asset IDs unless a caller supplies a stable asset ID for a coordinated storage operation.
- Known built-in defaults must keep stable app-defined asset IDs so other backend systems can refer to them predictably.
- `asset_type` must be either image or font.
- `display_name` and `stored_path` must not be empty.
- Uploaded asset metadata must include a non-empty file hash.
- Built-in asset metadata may omit the file hash.
- `original_filename` must remain optional metadata, not the stored filename.
- `is_built_in` is the stored source of truth for whether an asset is user-uploaded or deletable.
- `full_font_name` must remain optional and caller-provided until font extraction exists.
- Exact file deduplication must stay separate from metadata creation.
- Asset metadata code must use the central database helper instead of opening a separate app database connection ad hoc.
- Logs must not include full stored paths.

## Implementation Landmarks

- `app/storage/asset_deduplication.py` owns exact file hash calculation and duplicate asset lookup.
- `app/storage/migrations.py` owns the `assets` table migration.
- `app/storage/assets.py` owns asset metadata validation and create/read/list behavior.
- `app/storage/asset_files.py` owns uploaded file copying and uploaded asset path resolution.
- `app/storage/default_assets.py` owns known built-in default definitions, seeding, and main default lookup helpers.
- `tests/test_asset_metadata_storage.py` covers the current storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Asset Metadata Storage, check:

- Whether the requested change belongs in metadata storage or in file storage, validation, deletion, font extraction, or UI.
- Whether schema changes need a new handwritten migration and `PRAGMA user_version` advance.
- Whether a built-in default needs a stable app-defined ID instead of a generated UUID.
- Whether a caller-provided asset ID is needed to coordinate metadata with a physical stored filename.
- Whether invalid metadata is rejected before database writes.
- Whether duplicate asset checks belong in Asset Hash Deduplication instead of metadata creation.
- Whether default seeding remains idempotent.
- Whether database failures are logged and re-raised without swallowing the original error.
- Whether logs avoid full stored paths and other local user-owned details.
- Whether built-in asset policy continues to derive from `is_built_in`.
- Whether tests cover both built-in and uploaded asset metadata.
