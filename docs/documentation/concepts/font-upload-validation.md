# Font Upload Validation

Font Upload Validation is VySol's backend gate for deciding whether a candidate uploaded font is safe enough to enter the global asset library. It checks the original filename suffix, the file size, and whether fontTools can open the file as a supported font before Safe Asset File Storage copies the file or creates asset metadata.

This page is for developers, power users, and AI coding agents that need to understand the font upload validation contract before changing font uploads, asset file storage, asset metadata, logging, or future font UI.

## Why It Exists

Uploaded font files are user-controlled inputs. A filename can claim to be a font while the file is unsupported, too large, corrupted, or not a font at all. VySol needs validation before storage so rejected uploads do not create files under user asset storage and do not create records in `app.sqlite`.

Font Upload Validation keeps font acceptance rules separate from physical file copying, metadata persistence, hash deduplication, font-name extraction, CSS rendering, and picker UI. That boundary lets upload-facing code reuse the same validation contract without turning file storage into a broader font-processing system.

## Ownership Boundary

Font Upload Validation owns:

- Allowing uploaded font filenames with `.ttf`, `.otf`, `.woff`, or `.woff2` suffixes.
- Rejecting unsupported font suffixes before content verification.
- Enforcing the current maximum font upload size before fontTools opens the file.
- Using fontTools to verify that the file can be opened as a supported font.
- Logging expected validation rejections at `WARNING`.
- Logging unexpected file-size, dependency, or fontTools validation failures at `ERROR`.
- Logging accepted font uploads at `INFO` without logging font contents.

Font Upload Validation does not own:

- Accepting files from HTTP requests or UI controls.
- Copying accepted files into `user/assets/fonts/`.
- Creating, reading, updating, or deleting asset metadata.
- Calculating file hashes or checking duplicate hashes.
- Extracting final display font names from font files.
- Rendering CSS font faces or font picker UI.
- Rewriting built-in font asset references.

## Normal Flow

A backend caller hands Safe Asset File Storage a candidate font path and the original filename supplied by the upload boundary. Before any hash, copy, or metadata write happens, Safe Asset File Storage calls Font Upload Validation.

The validator derives the final filename component from the original filename, checks that its suffix is one of the supported font suffixes, checks the file size, and then asks fontTools to open and load the font. If validation succeeds, control returns to Safe Asset File Storage so the accepted font can be copied and recorded.

## Inputs

Font Upload Validation receives:

- A local source file path for the candidate font upload.
- The original filename supplied by the upload boundary.

The original filename is used only to derive the expected file type. It is not trusted as proof of content and does not control the stored asset filename.

## Outputs

Successful validation returns no value and allows the caller to continue the storage flow. Expected validation failures raise a font upload validation error before storage. Unexpected file, dependency, or fontTools failures are logged and re-raised so callers can fail the upload explicitly.

This system does not write files, write database rows, mutate metadata, extract font names, produce UI state, or return HTTP responses.

## Failure Behavior

Unsupported suffixes, oversized files, and invalid font bytes are expected validation failures. They are logged at `WARNING` without logging font contents or full local paths, then rejected before storage.

Unexpected failures while checking file size, loading fontTools, or running fontTools verification are logged at `ERROR` and re-raised. The validator does not create fallback acceptances when verification fails.

## System Interactions

Font Upload Validation currently interacts with:

- Safe Asset File Storage, which calls validation before hashing, copying, and metadata creation for font uploads.
- Asset Metadata Storage, indirectly, by preventing rejected fonts from becoming asset metadata rows.
- Asset Hash Deduplication, indirectly, by ensuring rejected fonts are not hashed as accepted uploads.
- The central logger, by recording validation acceptance, rejections, and unexpected validation failures without exposing font contents.

Future upload UI, font picker UI, CSS rendering, or font-name extraction systems may call into or build on the same storage path while keeping their own responsibilities separate.

## Current Edge Cases

Internal edge cases:

- Uppercase or mixed-case allowed suffixes are accepted through case-insensitive suffix handling.
- Original filenames with path separators use only the final filename component for suffix decisions.
- Supported suffixes with non-font content are rejected.
- Oversized files are rejected before fontTools opens them.
- Missing or unreadable files log an `ERROR` and re-raise the original file error.
- Missing fontTools or WOFF2 support logs an `ERROR` and fails explicitly instead of accepting the upload.

Cross-system edge cases:

- Rejected fonts must not be copied into user asset storage.
- Rejected fonts must not create uploaded asset metadata rows in `app.sqlite`.
- Validation must happen before hashing so invalid fonts are not treated as accepted asset candidates.
- Safe Asset File Storage may still sanitize filenames for storage, but validation must not depend on the stored filename.
- Font validation must not populate `full_font_name`; font-name extraction is a separate concern.

## Invariants

- Font validation must run before font hash calculation, file copy, or metadata creation.
- The validator must not rely only on file extension.
- The accepted font suffixes must stay aligned with the upload contract: `.ttf`, `.otf`, `.woff`, and `.woff2`.
- The maximum accepted font size is 3 MiB.
- Expected validation failures must log at `WARNING`.
- Unexpected file, dependency, or fontTools failures must log at `ERROR`.
- Accepted font uploads must log at `INFO`.
- Logs must not include font contents or full local paths.
- Validation must not copy, delete, move, transcode, render, extract display names, or write metadata.

## Implementation Landmarks

- `app/storage/font_upload_validation.py` owns the font upload validation rules.
- `app/storage/asset_files.py` calls the validator before storing font uploads.
- `requirements.txt` pins fontTools and WOFF2 support.
- `tests/test_font_upload_validation.py` covers the validator contract.
- `tests/test_asset_file_storage.py` covers the storage boundary behavior when validation rejects a font.

## What AI/Coders Must Check Before Changing This System

Before editing Font Upload Validation, check:

- Whether the requested change belongs in validation, Safe Asset File Storage, asset metadata, deduplication, font-name extraction, upload UI, picker UI, or CSS rendering.
- Whether validation still runs before hash, copy, and metadata creation.
- Whether expected rejections still prevent both file storage and metadata writes.
- Whether allowed suffixes and fontTools verification stay consistent with the upload contract.
- Whether oversized files are rejected before fontTools opens them.
- Whether WOFF2 support remains available through pinned dependencies.
- Whether logs avoid font contents and full local user paths.
- Whether tests cover valid fonts, unsupported suffixes, fake fonts, oversized files, dependency failures, unexpected failures, and storage rejection behavior.
