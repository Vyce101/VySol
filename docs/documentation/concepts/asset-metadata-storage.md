# Asset Metadata Storage

Asset Metadata Storage is VySol's app-level record system for known image and font assets. It stores metadata in `user/data/app.sqlite` so backend systems can seed built-in defaults, create uploaded asset metadata, read asset references by ID, and list asset records without needing physical file upload, file copying, file validation, or UI picker behavior to exist first.

This page is for developers, power users, and AI coding agents that need to understand the asset metadata contract before changing storage, migrations, asset registration, upload handling, font handling, or future asset UI.

## Why It Exists

VySol needs a small, durable place to remember which assets the app knows about. Built-in assets and later uploaded assets both need stable IDs, display names, type information, stored paths, and optional font metadata so future systems can refer to them without coupling themselves to the file upload flow.

This system creates the metadata layer first. Later tickets can decide how uploaded files are copied into repo-local storage, how file types are validated, how font names are extracted, and how users pick assets in the interface.

## Ownership Boundary

Asset Metadata Storage owns:

- Seeding known built-in default image and font asset references.
- Creating asset metadata records for image and font assets.
- Reading one asset metadata record by asset ID.
- Reading the main default background and font asset references by their stable built-in IDs.
- Listing asset metadata records in a stable order.
- Generating UUID asset IDs for regular created metadata records.
- Preserving stable app-defined IDs for known built-in defaults.
- Validating metadata required by the current storage contract.
- Treating built-in assets as non-user-uploaded and non-deletable through policy derived from `is_built_in`.
- Logging metadata creation, default seeding, default lookup results, invalid metadata, and database failures without exposing full stored paths.

Asset Metadata Storage does not own:

- Copying uploaded files into local storage.
- Validating uploaded file types.
- Calculating file hashes or checking whether a file hash already belongs to another asset record.
- Deleting asset records or physical files.
- Extracting font names from font files.
- Rendering asset pickers or other user interface flows.
- Deciding where future uploaded assets are physically stored.

## Normal Flow

During global database bootstrap, Asset Metadata Storage seeds the known built-in image and font references after migrations complete. Built-in defaults use stable app-defined IDs and an idempotent upsert, so repeated startup refreshes the same rows instead of creating duplicates.

Backend code can also build a new asset metadata request with an asset type, display name, stored path, built-in/uploaded flag, optional file hash, and optional full font name. Asset Metadata Storage validates that request before writing anything to SQLite.

If validation succeeds, the storage layer generates a UUID asset ID, inserts the record into the `assets` table, commits the transaction, logs the creation at `INFO`, and returns the saved record. Read and list operations query the same table and map SQLite rows back into backend asset metadata objects.

Backend code can look up the main default background and main default font through dedicated storage helpers. Successful default lookups are logged at `INFO`. Missing built-in default references are logged at `ERROR` and return no record.

## Inputs

Asset Metadata Storage receives backend-created metadata values and built-in default definitions owned by the app. Current valid asset types are image and font. The stored path is only metadata at this stage; later upload work will decide how files are copied and which stored paths are produced for uploads.

Uploaded assets must include a file hash. Built-in assets may omit the file hash. Full font name is optional and is stored exactly as provided, because font extraction is outside the current system.

## Outputs

The system writes asset metadata rows into `app.sqlite` and returns asset metadata objects to backend callers. Returned metadata exposes user-uploaded and deletable policy as derived values from `is_built_in`. It does not produce files, UI state, upload results, extracted font names, or HTTP responses.

## System Interactions

Asset Metadata Storage currently interacts with:

- Asset Hash Deduplication, which can calculate an exact file hash and look for an existing asset ID before future upload storage creates new metadata.
- Global App Storage, which opens `app.sqlite`, applies migrations, and triggers default asset seeding.
- Backend storage modules that need to create, read, or list asset metadata.
- The central logger, which records creation, default seeding, default lookup, validation, and database failure events.

Future upload, font extraction, and picker UI systems may call this system after they produce valid metadata, but those systems should keep their own responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Unknown asset types are rejected before a database write.
- Empty display names are rejected before a database write.
- Empty stored paths are rejected before a database write.
- Uploaded assets without a file hash are rejected before a database write.
- Built-in assets without a file hash are allowed.
- Known built-in defaults are seeded idempotently by stable asset ID.
- Built-in asset metadata returns `is_user_uploaded` and `is_deletable` as false through derived policy.
- Missing asset IDs return no record instead of creating one.
- Missing main default background or font references return no record and log an `ERROR`.
- SQLite failures are rolled back, logged at `ERROR`, and re-raised.

Cross-system edge cases:

- Stored paths must not be logged in full, because future upload work may produce local user-owned paths.
- The metadata layer must not assume the physical file already exists.
- The metadata layer must not treat duplicate display names as duplicate files; exact file hash lookup belongs to Asset Hash Deduplication.
- Font metadata must not pretend extraction happened; `full_font_name` is optional until a font extraction system provides it.
- Global App Storage must seed built-in defaults only after the assets table migration has been applied.

## Invariants

- Regular created metadata records must receive UUID asset IDs generated by the storage layer.
- Known built-in defaults must keep stable app-defined asset IDs so other backend systems can refer to them predictably.
- `asset_type` must be either image or font.
- `display_name` and `stored_path` must not be empty.
- Uploaded asset metadata must include a non-empty file hash.
- Built-in asset metadata may omit the file hash.
- `is_built_in` is the stored source of truth for whether an asset is user-uploaded or deletable.
- `full_font_name` must remain optional and caller-provided until font extraction exists.
- Exact file deduplication must be performed by the dedicated deduplication helper before callers create metadata.
- Asset metadata code must use the central database helper instead of opening a separate app database connection ad hoc.
- Logs must not include full stored paths.

## Implementation Landmarks

- `app/storage/asset_deduplication.py` owns exact file hash calculation and duplicate asset lookup.
- `app/storage/migrations.py` owns the `assets` table migration.
- `app/storage/assets.py` owns asset metadata validation and create/read/list behavior.
- `app/storage/default_assets.py` owns known built-in default definitions, seeding, and main default lookup helpers.
- `tests/test_asset_metadata_storage.py` covers the current storage contract.

## What AI/Coders Must Check Before Changing This System

Before editing Asset Metadata Storage, check:

- Whether the requested change belongs in metadata storage or in a future upload, validation, deletion, font extraction, or UI system.
- Whether schema changes need a new handwritten migration and `PRAGMA user_version` advance.
- Whether a built-in default needs a stable app-defined ID instead of a generated UUID.
- Whether invalid metadata is rejected before database writes.
- Whether duplicate asset checks belong in Asset Hash Deduplication instead of metadata creation.
- Whether default seeding remains idempotent.
- Whether database failures are logged and re-raised without swallowing the original error.
- Whether logs avoid full stored paths and other local user-owned details.
- Whether built-in asset policy continues to derive from `is_built_in`.
- Whether tests cover both built-in and uploaded asset metadata.
