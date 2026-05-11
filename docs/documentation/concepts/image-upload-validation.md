# Image Upload Validation

Image Upload Validation is VySol's backend gate for deciding whether a candidate uploaded background image is safe enough to enter the global asset library. It checks the original filename suffix, the file size, and the actual image content before Safe Asset File Storage copies the file or creates asset metadata.

This page is for developers, power users, and AI coding agents that need to understand the upload validation contract before changing image uploads, asset file storage, asset metadata, logging, or future upload UI.

## Why It Exists

Uploaded image files are user-controlled inputs. A filename can claim to be an image while the file is actually unsupported, too large, corrupted, or not an image at all. VySol needs validation before storage so rejected uploads do not create files under user asset storage and do not create records in `app.sqlite`.

Image Upload Validation keeps media acceptance rules separate from physical file copying, metadata persistence, hash deduplication, asset deletion, and image editing. That boundary lets future upload callers reuse the same validation contract without turning storage helpers into a general media-processing system.

## Ownership Boundary

Image Upload Validation owns:

- Allowing uploaded image filenames with `.png`, `.jpg`, `.jpeg`, or `.webp` suffixes.
- Rejecting unsupported image suffixes before content verification.
- Enforcing the current maximum image upload size before Pillow opens the file.
- Using Pillow to verify that the file can be opened and verified as the expected image format.
- Rejecting files whose actual image format does not match the allowed format implied by the suffix.
- Logging expected validation rejections at `WARNING`.
- Logging unexpected file-size or Pillow validation failures at `ERROR`.

Image Upload Validation does not own:

- Accepting files from HTTP requests or UI controls.
- Copying accepted files into `user/assets/images/`.
- Creating, reading, updating, or deleting asset metadata.
- Calculating file hashes or checking duplicate hashes.
- Validating fonts.
- Editing, cropping, resizing, or transcoding images.
- Choosing future asset picker behavior.

## Normal Flow

A backend caller hands Safe Asset File Storage a candidate image path and the original filename supplied by the upload boundary. Before any hash, copy, or metadata write happens, Safe Asset File Storage calls Image Upload Validation.

The validator derives the final filename component from the original filename, checks that its suffix maps to an allowed image format, checks the file size, and then asks Pillow to open the file using only the expected format. Pillow verification must succeed for the upload to continue. If validation succeeds, control returns to Safe Asset File Storage so the accepted image can be copied and recorded.

## Inputs

Image Upload Validation receives:

- A local source file path for the candidate image upload.
- The original filename supplied by the upload boundary.

The original filename is used only to derive the expected image type. It is not trusted as proof of content and does not control the stored asset filename.

## Outputs

Successful validation returns no value and allows the caller to continue the storage flow. Expected validation failures raise an image upload validation error before storage. Unexpected file or Pillow failures are logged and re-raised so callers can fail the upload explicitly.

This system does not write files, write database rows, mutate metadata, produce UI state, or return HTTP responses.

## Failure Behavior

Unsupported suffixes, oversized files, invalid image bytes, and suffix/content mismatches are expected validation failures. They are logged at `WARNING` without logging image contents or full local paths, then rejected before storage.

Unexpected failures while checking file size or running Pillow verification are logged at `ERROR` and re-raised. The validator does not create fallback acceptances when verification fails.

## System Interactions

Image Upload Validation currently interacts with:

- Safe Asset File Storage, which calls validation before hashing, copying, and metadata creation for image uploads.
- Asset Metadata Storage, indirectly, by preventing rejected images from becoming asset metadata rows.
- Asset Hash Deduplication, indirectly, by ensuring rejected images are not hashed as accepted uploads.
- The central logger, by recording validation rejections and unexpected validation failures without exposing image contents.

Future upload UI or API systems may call into the same storage path while keeping their own request and response responsibilities separate.

## Current Edge Cases

Internal edge cases:

- `.jpg` and `.jpeg` both map to JPEG validation.
- Uppercase or mixed-case allowed suffixes are accepted through case-insensitive suffix handling.
- Supported suffixes with non-image content are rejected.
- Supported suffixes with a different real image format are rejected.
- Oversized files are rejected before Pillow opens the file.
- Missing or unreadable files log an `ERROR` and re-raise the original file error.

Cross-system edge cases:

- Rejected images must not be copied into user asset storage.
- Rejected images must not create uploaded asset metadata rows in `app.sqlite`.
- Validation must happen before hashing so invalid images are not treated as accepted asset candidates.
- Safe Asset File Storage may still sanitize filenames for storage, but validation must not depend on the stored filename.
- Font uploads remain outside this validation contract.

## Invariants

- Image validation must run before image hash calculation, file copy, or metadata creation.
- The validator must not rely only on file extension.
- The accepted image formats must stay aligned with the upload contract: PNG, JPEG, and WEBP.
- The maximum accepted image size is 3 MiB.
- Expected validation failures must log at `WARNING`.
- Unexpected file or Pillow failures must log at `ERROR`.
- Logs must not include image contents.
- Validation must not copy, delete, move, transcode, resize, crop, or write metadata.

## Implementation Landmarks

- `app/storage/image_upload_validation.py` owns the image upload validation rules.
- `app/storage/asset_files.py` calls the validator before storing image uploads.
- `tests/test_image_upload_validation.py` covers the validator contract.
- `tests/test_asset_file_storage.py` covers the storage boundary behavior when validation rejects an image.

## What AI/Coders Must Check Before Changing This System

Before editing Image Upload Validation, check:

- Whether the requested change belongs in validation, Safe Asset File Storage, asset metadata, deduplication, upload UI, or image editing.
- Whether validation still runs before hash, copy, and metadata creation.
- Whether expected rejections still prevent both file storage and metadata writes.
- Whether allowed formats, suffix mapping, and Pillow verification stay consistent.
- Whether oversized files are rejected before Pillow opens them.
- Whether logs avoid image contents and full local user paths.
- Whether tests cover valid images, unsupported suffixes, fake images, suffix/content mismatches, oversized files, and unexpected failures.
