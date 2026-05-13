# World Hub Page Shell

World Hub Page Shell is VySol's frontend landing surface for the world list area. It provides the static visual frame that future committed-world listing and Create World entrypoints can fill without making the shell responsible for world storage, draft creation, or navigation behavior.

This page is for developers, power users, and AI coding agents that need to understand the World Hub shell before changing frontend layout, launcher startup, default visual assets, or future world-card behavior.

## Why It Exists

VySol needs a recognizable first screen before real World Hub data and actions are connected. The shell gives the app a stable landing frame with VySol branding, a compact `Worlds` navbar, Create World hero copy, and a reserved card-row area.

The boundary matters because the hub will eventually sit near several important systems: committed-world visibility, draft creation, Create World cards, recent-world ordering, and World Detail navigation. The shell must make room for those systems without pretending to own them early.

## Ownership Boundary

World Hub Page Shell owns:

- Rendering the default frontend landing page frame.
- Showing the VySol logo mark and wordmark as non-clickable branding.
- Showing a centered `Worlds`-only navbar with no search or settings controls.
- Showing the static `Create World` hero title.
- Showing the static `Build a living setting for roleplay and simulation.` hero description.
- Reserving the card-row layout area without rendering real world cards.
- Keeping the hero and navbar text non-selectable.
- Keeping the cinematic glass styling responsive across desktop and narrow viewports.
- Using launcher wiring that opens the frontend app when `run.bat` starts VySol.

World Hub Page Shell does not own:

- Loading committed worlds from storage.
- Showing real world cards, counts, thumbnails, last-used state, or hover actions.
- Creating draft worlds or committed worlds.
- Search, settings, filters, sort controls, or navigation actions.
- Marking committed worlds as used.
- Customize, Ingestion, chat, retrieval, graph extraction, or provider behavior.
- App logging or console diagnostics.

## Normal Flow

The frontend entrypoint renders World Hub as the default page. The shell imports the app's built-in logo, default background image, default font, and local tab primitives, then renders a full-screen cinematic frame.

The top-left brand is informational only. The centered navbar contains a single active `Worlds` item and does not navigate. The hero area displays static Create World copy, and the reserved card-row area shows layout space for future cards without creating cards or binding actions.

When launched through `run.bat`, the launcher starts both backend and frontend services, waits for their health checks, and opens the frontend URL.

## Inputs

World Hub Page Shell currently receives only imported frontend assets and CSS. It does not receive committed world records, draft IDs, route state, user queries, saved settings, provider responses, database rows, raw file paths, or uploaded assets.

## Outputs

The system produces visible frontend UI state only: brand, single-item navbar, hero copy, and a reserved card-row area. It does not write files, create database rows, create drafts, call backend APIs, persist UI state, or emit app logs.

## User-Facing Behavior

Users see a cinematic World Hub landing shell with VySol branding, one compact `Worlds` nav item, the Create World hero area, and an empty card-row frame. There is no search box, settings control, separate `Worlds` heading above the row, real card data, hover behavior, or navigation action in the current shell.

## System Interactions

World Hub Page Shell currently interacts with:

- Built-in default assets, which provide the logo, background image, and font used by the shell.
- The local tab wrapper, which provides the static navbar structure.
- The frontend launcher service, which starts the Vite development server.
- The backend launcher service, which is started alongside the frontend for normal app startup.
- Future Draft World Detail API use, which a later Create World entrypoint may call before opening World Detail.
- Future Committed World Index Storage use, which later card loading can read after committed worlds exist.

It must stay separate from committed-world storage, draft-world registries, source staging, ingestion attempts, parser systems, graph systems, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- The navbar has one active item and must stay compact instead of inheriting multi-tab spacing.
- The hero and navbar text are visible but not text-selectable.
- The reserved card-row area must be visible without rendering fake cards or skeleton cards.
- The brand area is not an anchor or button, so clicking it does not navigate.
- The shell must fit on narrow viewports without clipping the brand, nav label, hero copy, or row frame.
- Generated frontend build output remains reproducible and ignored.

Cross-system edge cases:

- Rendering the hub must not create drafts or committed worlds.
- Rendering the hub must not read or mark committed worlds as used.
- Future Create World behavior should call backend-owned draft creation instead of inventing frontend-only draft IDs.
- Future world-card loading should depend on committed-world visibility rules rather than draft state.
- Launcher startup must open the frontend URL while still starting the backend service needed by future hub actions.
- Logs must remain absent unless a future UI logging standard is introduced.

## Invariants

- World Hub must remain the default frontend page until routing changes are introduced intentionally.
- The VySol brand must remain visible, top-left, and non-clickable.
- The navbar must contain only `Worlds` in the current shell.
- Search and settings must not appear in this shell.
- The hero copy must remain exactly `Create World` and `Build a living setting for roleplay and simulation.` until a later ticket changes the copy.
- The shell must not load real worlds, create cards, implement hover behavior, or navigate.
- The shell must not hardcode local machine paths, user data, secrets, or uploaded file paths.

## Implementation Landmarks

- `frontend/src/world-hub-page.tsx` owns the shell composition, branding, static navbar, hero copy, and reserved row.
- `frontend/src/world-hub-page.css` owns World Hub-specific layout and visual styling.
- `frontend/src/main.tsx` chooses World Hub as the default frontend page.
- `frontend/vite.config.ts` allows Vite dev mode to serve repo-owned frontend assets imported by the app.
- `scripts/launcher/launcher.config.json` wires normal startup to backend plus frontend services.
- `scripts/launcher/Run-App.ps1` owns launcher startup, readiness, and app-owned process cleanup.

## What AI/Coders Must Check Before Changing This System

Before editing World Hub Page Shell, check:

- Whether the change belongs in the static shell instead of future Create World, card loading, search, settings, storage, or navigation work.
- Whether the page still renders without backend data.
- Whether the hub still avoids creating drafts, committed-world rows, source state, or ingestion state.
- Whether the navbar remains compact and usable on narrow viewports.
- Whether the hero and navbar text remain non-selectable unless a later interaction ticket changes that behavior.
- Whether launcher changes still start both frontend and backend and open the frontend app.
- Whether generated build output stays ignored and source assets remain the tracked source of truth.
