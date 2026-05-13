# World Hub Page

World Hub Page is VySol's default frontend landing surface for committed worlds. It renders the cinematic app frame, keeps the current static Create World hero area, loads committed-world card data, and displays each committed world as a stable image card.

This page is for developers, power users, and AI coding agents that need to understand the World Hub contract before changing committed-world visibility, card layout, asset delivery, launcher startup, or future Create World entrypoints.

## Why It Exists

VySol needs a recognizable first screen that can show committed worlds without making the frontend responsible for creating, ingesting, or mutating world storage. The hub is the user-facing bridge between committed-world index records and the visual world list.

The boundary matters because the hub sits near several systems that should remain separate: committed-world storage, asset delivery, future Create World flows, recent-world ordering, and future World Detail navigation.

## Ownership Boundary

World Hub Page owns:

- Rendering the default frontend landing page frame.
- Showing the VySol logo mark and wordmark as non-clickable branding.
- Showing a centered `Worlds` navbar with no search or settings controls.
- Showing the static `Create World` hero title.
- Showing the static `Build a living setting for roleplay and simulation.` hero description.
- Loading committed-world card records from the backend.
- Rendering each committed world as a cinematic card with its background image and display name.
- Keeping card dimensions stable without horizontal hover expansion.
- Keeping the static hero area and page background independent from card selection.
- Keeping the hero, navbar, and cards responsive without creating vertical page scroll on narrow browser heights.

World Hub Page does not own:

- Creating draft worlds or committed worlds.
- Running ingestion, parsing, splitting, or commit orchestration.
- Uploading, selecting, deleting, or editing assets.
- Marking committed worlds as used.
- Showing chunk counts, chronicle counts, chat stats, graph stats, last-used text, card actions, search, filters, or settings.
- Switching the hero title, hero description, hero font, or page background from hovered or selected cards.
- Customize, Ingestion, chat, retrieval, graph extraction, or provider behavior.
- App logging or console diagnostics.

## Normal Flow

The frontend entrypoint renders World Hub as the default page. The page imports the app's built-in logo, default background image, default font, local tab primitives, and committed-world API client.

On mount, the page requests committed-world card records from the backend. Empty results leave the row as an empty glass footprint. Non-empty results render one card per committed world using the card background asset URL returned by the backend and the committed-world display name.

The hero remains static regardless of the committed worlds returned. A card can show the world's image and name, but it does not change the hero, navigate, expose actions, or display stats.

## Inputs

World Hub Page receives imported frontend assets and backend committed-world card responses. Card responses include committed-world identity, display name, optional description, background asset identity, and the safe background image URL used by the browser.

It does not receive raw local file paths, source text, chunk records, graph state, chat state, provider responses, draft IDs, or uploaded file handles.

## Outputs

The system produces visible frontend UI state only: brand, navbar, static hero copy, and committed-world cards. It does not write files, create database rows, create drafts, mutate committed-world metadata, persist UI state, or emit app logs.

## User-Facing Behavior

Users see a cinematic World Hub with VySol branding, one compact `Worlds` nav item, the static Create World hero area, and a row of committed-world cards when committed worlds exist.

Each committed-world card shows the selected background image and world name only. Current cards do not show counts, stats, timestamps, actions, or navigation behavior.

## System Interactions

World Hub Page currently interacts with:

- Committed World Card API, which lists committed worlds for card rendering.
- Asset File Delivery, which serves card background images by asset ID.
- Committed World Index Storage, which owns the committed-world metadata behind the card API.
- Asset Metadata Storage and Safe Asset File Storage indirectly through backend asset resolution.
- Built-in default assets, which provide the logo, page background image, and default font.
- The local tab wrapper, which provides the static navbar structure.
- The frontend and backend launcher services used during normal startup.

It must stay separate from draft-world registries, source staging, ingestion attempts, parser systems, graph systems, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- Empty committed-world lists render an empty card-row footprint instead of fake world cards.
- Failed card loading leaves the row empty without adding noisy console logs.
- Card layout uses fixed dimensions and does not depend on hover expansion.
- Card text uses the default app font even when the committed world has a selected font asset.
- Narrow browser layouts keep the app surface locked to the viewport so cards do not create vertical page scroll.
- The hero and navbar text remain visible and non-selectable.
- The brand area is not an anchor or button, so clicking it does not navigate.

Cross-system edge cases:

- Rendering the hub must not create drafts or committed worlds.
- Rendering the hub must not mark committed worlds as used.
- Card image URLs must come from backend asset delivery instead of hardcoded local filesystem paths.
- Stored asset paths must remain backend-owned so unsafe or missing assets are rejected before file serving.
- Future Create World behavior should call backend-owned draft or commit flows instead of inventing frontend-only world records.
- Future hero switching should remain a separate behavior from card rendering.

## Invariants

- World Hub must remain the default frontend page until routing changes are introduced intentionally.
- The VySol brand must remain visible, top-left, and non-clickable.
- The navbar must contain only `Worlds` for the current hub.
- Search and settings must not appear in the current hub.
- The hero copy must remain `Create World` and `Build a living setting for roleplay and simulation.` until a later ticket changes that copy.
- Card rendering must use committed-world backend data, not mock frontend-only worlds.
- Cards must show background image and name only for the current card behavior.
- The hub must not hardcode local machine paths, user data, secrets, or uploaded file paths.

## Implementation Landmarks

- `frontend/src/world-hub-page.tsx` owns the World Hub composition, card loading state, and card rendering.
- `frontend/src/world-hub-page.css` owns World Hub-specific layout, viewport locking, and card styling.
- `frontend/src/committed-world-api.ts` owns the frontend card-list request.
- `app/committed_worlds` owns the committed-world card listing route.
- `app/asset_files` owns safe browser-facing asset file delivery.
- `frontend/vite.config.ts` proxies the frontend card and asset requests during dev startup.

## What AI/Coders Must Check Before Changing This System

Before editing World Hub Page, check:

- Whether the change belongs in card rendering instead of world creation, ingestion, asset upload, search, settings, storage, or navigation work.
- Whether the page still renders when the backend returns no committed worlds.
- Whether the hub still avoids creating drafts, committed-world rows, source state, or ingestion state.
- Whether card images still load through safe backend asset delivery.
- Whether narrow browser layouts remain non-scrollable while preserving the card row.
- Whether the hero remains static unless a later hero-switching ticket changes that behavior.
- Whether generated frontend build output stays ignored and source assets remain the tracked source of truth.
