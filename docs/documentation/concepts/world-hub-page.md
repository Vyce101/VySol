# World Hub Page

World Hub Page is VySol's default frontend landing surface for committed worlds. It renders the cinematic app frame, loads committed-world data in recent-use order, uses the latest committed world for the hero area when one exists, and displays each committed world as a stable image card.

This page is for developers, power users, and AI coding agents that need to understand the World Hub contract before changing committed-world visibility, card layout, asset delivery, launcher startup, or future Create World entrypoints.

## Why It Exists

VySol needs a recognizable first screen that can show committed worlds without making the frontend responsible for creating, ingesting, or mutating world storage. The hub is the user-facing bridge between committed-world index records and the visual world list.

The boundary matters because the hub sits near several systems that should remain separate: committed-world storage, asset delivery, future Create World flows, recent-world ordering, and future World Detail navigation.

## Ownership Boundary

World Hub Page owns:

- Rendering the default frontend landing page frame.
- Showing the VySol logo mark and wordmark as non-clickable branding.
- Showing a centered `Worlds` navbar with no search or settings controls.
- Showing the default `Create World` hero area when there are no committed worlds.
- Loading committed-world records from the backend in most-recent-use order.
- Using the latest committed world's saved name, optional description, background, and font for the hero area.
- Rendering each committed world as a cinematic card with its background image and display name.
- Keeping card dimensions stable without horizontal hover expansion.
- Applying the selected/default world font only to the hero title and description.
- Keeping card text on the normal app font even when a world has a selected font.
- Keeping the hero, navbar, and cards responsive without creating vertical page scroll on narrow browser heights.
- Surfacing committed-world load failure in the UI without adding browser console noise.

World Hub Page does not own:

- Creating draft worlds or committed worlds.
- Running ingestion, parsing, splitting, or commit orchestration.
- Uploading, selecting, deleting, or editing assets.
- Marking committed worlds as used.
- Showing chunk counts, chronicle counts, chat stats, graph stats, last-used text, card actions, search, filters, or settings.
- Switching the hero title, hero description, hero font, or page background from hovered or manually selected cards.
- Customize, Ingestion, chat, retrieval, graph extraction, or provider behavior.
- App logging or console diagnostics.

## Normal Flow

The frontend entrypoint renders World Hub as the default page. The page imports the app's built-in logo, default background image, default font, local tab primitives, and committed-world API client.

On mount, the page requests committed-world records from the backend. The backend reads committed worlds from `app.sqlite`, sorts them by `last_used_at` with the most recent world first, and returns browser-safe background and font asset URLs. Empty results leave the row as an empty glass footprint and keep the default Create World hero.

When committed worlds exist, the first returned world controls the hero background, title, description, and hero font. Cards render in the same backend order using their background image and saved world name only. Cards do not change the hero through hover, navigate, expose actions, or display stats.

## Inputs

World Hub Page receives imported frontend defaults and backend committed-world responses. Responses include committed-world identity, display name, optional description, background asset identity and URL, font asset identity and URL, and `last_used_at`.

It does not receive raw local file paths, source text, chunk records, graph state, chat state, provider responses, draft IDs, uploaded file handles, or draft-world metadata.

## Outputs

The system produces visible frontend UI state only: brand, navbar, hero presentation, committed-world cards, empty-list state, and load-failure state. It does not write files, create database rows, create drafts, mutate committed-world metadata, persist UI state, or emit app logs.

## User-Facing Behavior

Users see a cinematic World Hub with VySol branding, one compact `Worlds` nav item, a hero area, and a row of committed-world cards when committed worlds exist.

If at least one committed world exists, the most recently used world appears first and supplies the hero background, name, optional description, and hero font. If the description is missing, the description space remains blank instead of falling back to default copy. If no committed world exists, users see the default Create World hero with the default background and font.

Each committed-world card shows the selected/default background image and world name only. Current cards do not show descriptions, counts, stats, timestamps, actions, or navigation behavior. Hero title and description text clamp inside their reserved area instead of expanding the layout.

If committed-world loading fails, the card row shows a quiet `Unable to load worlds.` surface while the browser console stays free of repeated frontend error spam.

## System Interactions

World Hub Page currently interacts with:

- Committed World Card API, which lists committed worlds for card rendering.
- Asset File Delivery, which serves card background images and hero fonts by asset ID.
- Committed World Index Storage, which owns the committed-world metadata behind the card API.
- Asset Metadata Storage and Safe Asset File Storage indirectly through backend asset resolution.
- Built-in default assets, which provide the logo, page background image, and default font.
- The local tab wrapper, which provides the static navbar structure.
- The frontend and backend launcher services used during normal startup.

It must stay separate from draft-world registries, source staging, ingestion attempts, parser systems, graph systems, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- Empty committed-world lists render an empty card-row footprint instead of fake world cards.
- Failed card loading shows a quiet row-level message without adding noisy console logs.
- The latest committed world controls the hero only after the committed-world list loads successfully.
- Missing world descriptions render as blank hero descriptions, not default Create World descriptions.
- Hero title text is constrained to avoid resizing the overall page layout.
- Hero description text is constrained to avoid resizing the overall page layout.
- Card layout uses fixed dimensions and does not depend on hover expansion.
- Card text uses the default app font even when the committed world has a selected font asset.
- Hero title and description use the latest committed world's selected/default font when committed worlds exist.
- Narrow browser layouts keep the app surface locked to the viewport so cards do not create vertical page scroll.
- The hero and navbar text remain visible and non-selectable.
- The brand area is not an anchor or button, so clicking it does not navigate.

Cross-system edge cases:

- Rendering the hub must not create drafts or committed worlds.
- Rendering the hub must not mark committed worlds as used.
- Card image URLs and hero font URLs must come from backend asset delivery instead of hardcoded local filesystem paths.
- Stored asset paths must remain backend-owned so unsafe or missing assets are rejected before file serving.
- Future Create World behavior should call backend-owned draft or commit flows instead of inventing frontend-only world records.
- Recent-use ordering must come from committed-world storage rather than client-side draft or display-name sorting.

## Invariants

- World Hub must remain the default frontend page until routing changes are introduced intentionally.
- The VySol brand must remain visible, top-left, and non-clickable.
- The navbar must contain only `Worlds` for the current hub.
- Search and settings must not appear in the current hub.
- The default empty-list hero copy must remain `Create World` and `Build a living setting for roleplay and simulation.` until that default copy is intentionally changed.
- When committed worlds exist, the hero must use the most recently used committed world's saved metadata.
- Card rendering must use committed-world backend data, not mock frontend-only worlds.
- Cards must show background image and name only for the current card behavior.
- Draft and uncommitted worlds must not appear in the Hub.
- The hub must not hardcode local machine paths, user data, secrets, or uploaded file paths.

## Implementation Landmarks

- `frontend/src/world-hub-page.tsx` owns the World Hub composition, card loading state, and card rendering.
- `frontend/src/world-hub-page.css` owns World Hub-specific layout, viewport locking, and card styling.
- `frontend/src/committed-world-api.ts` owns the frontend card-list request.
- `app/committed_worlds` owns the committed-world card listing route.
- `app/storage/worlds.py` owns recent-use ordering for committed-world records.
- `app/asset_files` owns safe browser-facing asset file delivery.
- `frontend/vite.config.ts` proxies the frontend card and asset requests during dev startup.

## What AI/Coders Must Check Before Changing This System

Before editing World Hub Page, check:

- Whether the change belongs in card rendering instead of world creation, ingestion, asset upload, search, settings, storage, or navigation work.
- Whether the page still renders when the backend returns no committed worlds.
- Whether the hub still avoids creating drafts, committed-world rows, source state, or ingestion state.
- Whether committed worlds still arrive in most-recent-use order.
- Whether draft or uncommitted worlds remain excluded.
- Whether card images and hero fonts still load through safe backend asset delivery.
- Whether narrow browser layouts remain non-scrollable while preserving the card row.
- Whether hero text constraints prevent long names or descriptions from resizing the layout unexpectedly.
- Whether generated frontend build output stays ignored and source assets remain the tracked source of truth.
