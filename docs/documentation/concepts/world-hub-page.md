# World Hub Page

World Hub Page is VySol's default frontend landing surface for committed worlds and the current Create World entrypoint. It renders the cinematic app frame, loads committed-world data in recent-use order, uses the latest committed world for the hero area when one exists, displays each committed world as a stable image card, and offers a dedicated Create World card at the start of the card row.

This page is for developers, power users, and AI coding agents that need to understand the World Hub contract before changing committed-world visibility, card layout, asset delivery, launcher startup, or the Create World entrypoint.

## Why It Exists

VySol needs a recognizable first screen that can show committed worlds and provide the first action for opening a new draft world without making the frontend responsible for ingestion, commit, or durable world storage. The hub is the user-facing bridge between committed-world index records, the visual world list, and backend-owned draft opening.

The boundary matters because the hub sits near several systems that should remain separate: committed-world storage, asset delivery, draft-world opening, recent-world ordering, and World Detail routing.

## Ownership Boundary

World Hub Page owns:

- Rendering the default frontend landing page frame.
- Showing the VySol logo mark and wordmark as non-clickable branding.
- Showing a centered `Worlds` navbar with no search or settings controls.
- Showing the default `Create World` hero area when there are no committed worlds.
- Loading committed-world records from the backend in most-recent-use order.
- Using the latest committed world's saved name, optional description, background, and font for the hero area.
- Rendering the dedicated Create World card as the first card-row item.
- Showing the current committed-world count on the Create World card.
- Initiating backend-owned draft creation when the Create World card is clicked.
- Rendering each committed world as a cinematic card with its background image and display name.
- Keeping card dimensions stable without horizontal hover expansion.
- Truncating long committed-world card titles with an ellipsis.
- Applying the selected/default world font only to the hero title and description.
- Keeping card text on the normal app font even when a world has a selected font.
- Keeping the hero, navbar, and cards responsive without creating vertical page scroll on narrow browser heights.
- Surfacing committed-world load failure in the UI without adding browser console noise.

World Hub Page does not own:

- Creating draft setup state directly or inventing frontend-only draft IDs.
- Creating committed worlds.
- Running ingestion, parsing, splitting, or commit orchestration.
- Uploading, selecting, deleting, or editing assets.
- Marking committed worlds as used.
- Showing chunk counts, chronicle counts, chat stats, graph stats, last-used text, card actions, search, filters, or settings.
- Switching the hero title, hero description, hero font, or page background from hovered or manually selected cards.
- Customize, Ingestion, chat, retrieval, graph extraction, or provider behavior.
- App logging or console diagnostics.

## Normal Flow

The frontend entrypoint renders World Hub as the default page when no world-detail route query is present. The page imports the app's built-in logo, default background image, default font, Create World card image, local tab primitives, committed-world API client, and draft-world creation flow helper.

On mount, the page requests committed-world records from the backend. The backend reads committed worlds from `app.sqlite`, sorts them by `last_used_at` with the most recent world first, and returns browser-safe background and font asset URLs. Empty results leave the Create World card as the only card-row item and keep the default Create World hero.

The Create World card always renders before committed-world cards. It uses the app's default background behavior for the page, but its own card image is the dedicated Create World artwork. Clicking the card calls the draft-world flow helper, which creates a backend draft and updates browser history to the draft World Detail route without a full document reload.

When committed worlds exist, the first returned world controls the hero background, title, description, and hero font. Committed-world cards render in the same backend order using their background image and saved world name only. Committed-world cards do not change the hero through hover, navigate, expose actions, or display stats.

## Inputs

World Hub Page receives imported frontend defaults, the Create World card image, browser click actions, and backend committed-world responses. Responses include committed-world identity, display name, optional description, background asset identity and URL, font asset identity and URL, and `last_used_at`.

It does not receive raw local file paths, source text, chunk records, graph state, chat state, provider responses, draft IDs, uploaded file handles, or draft-world metadata.

## Outputs

The system produces visible frontend UI state: brand, navbar, hero presentation, Create World card, committed-world cards, empty-list state, and load-failure state. On Create World click it asks the Draft World Detail API to create a draft and then updates browser history to World Detail. It does not write files, create database rows directly, create committed worlds, mutate committed-world metadata, persist UI state, or emit app logs.

## User-Facing Behavior

Users see a cinematic World Hub with VySol branding, one content-sized `Worlds` nav item, a hero area, and a row that starts with the Create World card.

If at least one committed world exists, the most recently used world appears first and supplies the hero background, name, optional description, and hero font. If the description is missing, the description space remains blank instead of falling back to default copy. If no committed world exists, users see the default Create World hero with the default background and font.

The Create World card shows its dedicated image, `Create World`, and the current committed-world count such as `5 Worlds`. Each committed-world card shows the selected/default background image and world name only. Current committed-world cards do not show descriptions, counts, stats, timestamps, actions, or navigation behavior. Hero title, hero description, and long committed-world card titles clamp inside their reserved areas instead of expanding the layout.

If committed-world loading fails, the card row shows a quiet `Unable to load worlds.` surface while the browser console stays free of repeated frontend error spam.

## System Interactions

World Hub Page currently interacts with:

- Committed World Card API, which lists committed worlds for card rendering.
- Draft World Detail API, which creates backend-owned draft setup when the Create World card is clicked.
- World Detail Page Shell, which renders after the frontend route changes to draft mode.
- Asset File Delivery, which serves card background images and hero fonts by asset ID.
- Committed World Index Storage, which owns the committed-world metadata behind the card API.
- Asset Metadata Storage and Safe Asset File Storage indirectly through backend asset resolution.
- Built-in default assets, which provide the logo, page background image, and default font.
- The local tab wrapper, which provides the static navbar structure.
- The frontend and backend launcher services used during normal startup.

It must stay separate from draft-world registry internals, source staging internals, ingestion attempts, parser systems, graph systems, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- Empty committed-world lists render the Create World card without fake committed-world cards.
- Failed card loading shows a quiet row-level message without adding noisy console logs.
- The latest committed world controls the hero only after the committed-world list loads successfully.
- Missing world descriptions render as blank hero descriptions, not default Create World descriptions.
- Hero title text is constrained to avoid resizing the overall page layout.
- Hero description text is constrained to avoid resizing the overall page layout.
- Long committed-world card titles truncate with an ellipsis instead of wrapping or resizing cards.
- The Create World card count is always visible and does not depend on hover or focus.
- The Create World card uses its dedicated image while the page background remains driven by default or latest committed-world hero behavior.
- Card layout uses fixed dimensions and does not depend on hover expansion.
- Card text uses the default app font even when the committed world has a selected font asset.
- Hero title and description use the latest committed world's selected/default font when committed worlds exist.
- Narrow browser layouts keep the app surface locked to the viewport so cards do not create vertical page scroll.
- The hero and navbar text remain visible and non-selectable.
- The brand area is not an anchor or button, so clicking it does not navigate.

Cross-system edge cases:

- Rendering the hub must not create drafts or committed worlds.
- Clicking Create World must create a backend-owned draft, not a frontend-only draft record.
- Create World navigation must update the frontend route without forcing a full document reload.
- Rendering the hub must not mark committed worlds as used.
- Card image URLs and hero font URLs must come from backend asset delivery instead of hardcoded local filesystem paths.
- Stored asset paths must remain backend-owned so unsafe or missing assets are rejected before file serving.
- Recent-use ordering must come from committed-world storage rather than client-side draft or display-name sorting.

## Invariants

- World Hub must remain the default frontend page when no world-detail route query is present.
- The VySol brand must remain visible, top-left, and non-clickable.
- The navbar must contain only `Worlds` for the current hub.
- The navbar must use the shared content-sized app nav behavior: width follows its contents, height stays fixed, and tab text size matches other app nav tabs.
- Search and settings must not appear in the current hub.
- The default empty-list hero copy must remain `Create World` and `Build a living setting for roleplay and simulation.` until that default copy is intentionally changed.
- The Create World card must remain the first card-row item.
- The Create World card must call backend draft creation before routing to World Detail.
- When committed worlds exist, the hero must use the most recently used committed world's saved metadata.
- Card rendering must use committed-world backend data, not mock frontend-only worlds.
- Committed-world cards must show background image and name only for the current card behavior.
- Draft and uncommitted worlds must not appear in the Hub.
- The hub must not hardcode local machine paths, user data, secrets, or uploaded file paths.

## Implementation Landmarks

- `frontend/src/world-hub-page.tsx` owns the World Hub composition, card loading state, and card rendering.
- `frontend/src/world-hub-page.css` owns World Hub-specific layout, viewport locking, and card styling.
- `frontend/src/committed-world-api.ts` owns the frontend card-list request.
- `frontend/src/draft-world-api.ts` owns the Create World draft-opening helper.
- `frontend/src/main.tsx` owns the current route switch between Hub and World Detail.
- `app/committed_worlds` owns the committed-world card listing route.
- `app/storage/worlds.py` owns recent-use ordering for committed-world records.
- `app/asset_files` owns safe browser-facing asset file delivery.
- `frontend/vite.config.ts` proxies the frontend card and asset requests during dev startup.

## What AI/Coders Must Check Before Changing This System

Before editing World Hub Page, check:

- Whether the change belongs in card rendering instead of world creation, ingestion, asset upload, search, settings, storage, or navigation work.
- Whether the page still renders when the backend returns no committed worlds.
- Whether rendering the hub still avoids creating drafts, committed-world rows, source state, or ingestion state.
- Whether clicking Create World still creates draft state through the Draft World Detail API.
- Whether committed worlds still arrive in most-recent-use order.
- Whether draft or uncommitted worlds remain excluded.
- Whether card images and hero fonts still load through safe backend asset delivery.
- Whether narrow browser layouts remain non-scrollable while preserving the card row.
- Whether hero text constraints prevent long names or descriptions from resizing the layout unexpectedly.
- Whether generated frontend build output stays ignored and source assets remain the tracked source of truth.
