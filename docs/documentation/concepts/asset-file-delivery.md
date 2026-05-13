# Asset File Delivery

Asset File Delivery is VySol's backend route boundary for serving known asset files to the browser by asset ID. It lets frontend surfaces such as World Hub load card background images without exposing local filesystem paths or trusting frontend-provided stored paths.

This page is for developers, power users, and AI coding agents that need to understand browser-facing asset delivery before changing card images, asset storage, path resolution, or future asset preview UI.

## Why It Exists

Asset metadata stores repo-relative paths, and committed worlds store asset IDs. The browser needs an HTTP URL for an image, but the frontend must not construct local file paths or know where built-in and uploaded assets physically live.

Asset File Delivery keeps that HTTP serving boundary small. It resolves an asset ID through existing storage policy, rejects unsafe or missing paths, and returns the file only when the resolved path is readable.

## Ownership Boundary

Asset File Delivery owns:

- Exposing an HTTP file URL for a known asset ID.
- Resolving the asset ID through backend asset file storage.
- Returning not-found responses for missing, unsafe, or unreadable asset files.
- Keeping local stored paths out of frontend API responses.

Asset File Delivery does not own:

- Creating asset metadata.
- Copying uploaded files into user asset storage.
- Validating uploaded image or font bytes.
- Calculating asset hashes or deduplicating uploads.
- Deleting assets or applying fallback replacements.
- Choosing which asset a committed world should use.
- Rendering frontend card or picker UI.

## Normal Flow

A frontend surface receives an asset file URL from a backend response, then requests that URL from the app backend. Asset File Delivery receives the asset ID, asks Safe Asset File Storage to resolve it, checks that the resolved path is a readable file, and returns a file response.

If the asset ID is unknown, resolves to an unsafe path, or points to a missing file, the route returns not found instead of leaking path details.

## Inputs

Asset File Delivery receives an asset ID in the route path. It reads asset metadata and resolved file state through backend storage helpers.

It does not receive raw stored paths, uploaded file handles, source files, world records, or user-selected local paths from the browser.

## Outputs

On success, the system returns a browser-readable file response. On failure, it returns a not-found HTTP response. It does not write files, create database rows, mutate asset metadata, or emit frontend state.

## Failure Behavior

Missing asset IDs, unsafe stored path metadata, and missing physical files all produce the same not-found response. This keeps local storage details out of browser-facing errors.

Unexpected storage failures still follow normal backend exception handling; the delivery route does not mask storage-layer consistency problems as successful file responses.

## System Interactions

Asset File Delivery currently interacts with:

- Safe Asset File Storage, which resolves asset IDs into safe repo-local paths.
- Asset Metadata Storage, which stores the asset record and stored path metadata used by resolution.
- World Hub Page, which uses delivered image files for committed-world cards.
- Committed World Card API, which returns asset delivery URLs to the frontend.

It must stay separate from upload validation, asset deletion, committed-world metadata storage, and frontend layout behavior.

## Current Edge Cases

Internal edge cases:

- Missing asset IDs return not found.
- Stored paths with absolute or parent-directory traversal are rejected by storage resolution before delivery.
- Resolved paths that are not files return not found.
- File serving does not expose the underlying stored path in the URL.

Cross-system edge cases:

- Built-in assets and uploaded assets can both be served as long as their metadata resolves safely.
- World Hub cards depend on this route for background images, so the card API must return asset delivery URLs rather than raw stored paths.
- Asset deletion and fallback behavior must update metadata references before delivery is expected to succeed for deleted uploaded assets.

## Invariants

- Browser-facing asset URLs must use asset IDs, not local filesystem paths.
- Asset path safety must be enforced by backend storage resolution.
- Unsafe or missing assets must not produce file responses.
- Delivery must not create, copy, validate, delete, or mutate assets.
- Logs and errors must avoid exposing raw local user paths.

## Implementation Landmarks

- `app/asset_files` owns the HTTP route for asset file delivery.
- `app/storage/asset_files.py` owns safe asset path resolution.
- `app/storage/assets.py` owns asset metadata lookup.
- Frontend dev proxy configuration forwards `/assets` requests to the backend.

## What AI/Coders Must Check Before Changing This System

Before editing Asset File Delivery, check:

- Whether the change belongs in delivery instead of upload storage, validation, metadata, deletion, or UI.
- Whether delivery still resolves asset IDs through the safe storage helper.
- Whether unsafe paths and missing files still return not found without leaking local paths.
- Whether built-in and uploaded asset references still share the same delivery path.
- Whether frontend code still receives asset URLs rather than constructing local paths.
