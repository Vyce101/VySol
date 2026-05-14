# World Detail Page Shell

World Detail Page Shell is VySol's first frontend layout contract for a single world screen. It provides the visual frame that future Customize and Ingestion features will fill without making the shell responsible for those feature behaviors, and it can be reached from the Hub's draft Create World flow through client-side route state.

This page is for developers, power users, and AI coding agents that need to understand the World Detail shell before changing frontend layout, route state, world-mode presentation, default visual assets, or future Customize and Ingestion tab work.

## Why It Exists

VySol needs a stable world-level surface before the full Customize and Ingestion workflows exist. The shell gives draft worlds and committed worlds the same recognizable place in the app: cinematic background, VySol branding, and two top-level tabs.

The boundary matters because a layout shell should not accidentally become storage, ingestion, settings, upload, or source-management logic. Future tickets can add real controls inside the tab panes while keeping the outer frame consistent.

## Ownership Boundary

World Detail Page Shell owns:

- Rendering the World Detail page frame in the frontend.
- Showing the VySol logo mark and wordmark as non-clickable branding.
- Showing the centered `Customize` and `Ingestion` tabs.
- Switching between draft-safe Customize and Ingestion shell panes.
- Supporting draft and committed display modes through frontend route/query state.
- Reading backend draft detail when draft route state includes a draft ID.
- Using the app's true default world image and default font assets for the temporary visual shell.
- Keeping the cinematic glass styling and responsive layout stable across desktop and narrow viewports.

World Detail Page Shell does not own:

- Customize fields, validation, saving, or asset picking.
- Ingestion controls, source staging, start, pause, retry, progress, or provider behavior.
- Backend draft creation, draft storage, or API contracts.
- The World Hub Create World card or draft-opening click behavior.
- Draft-world persistence or committed-world storage.
- File uploads, source file handling, parsing, chunking, embeddings, graph extraction, or retrieval.
- App logging or console diagnostics.
- User task documentation for customizing or ingesting worlds.

## Normal Flow

The frontend route switch renders the World Detail shell when route/query state indicates a world-detail mode or draft ID. If the mode is `draft` and a draft ID is present, the shell asks the backend for draft detail so the visible state reflects backend-owned splitter defaults and staged-source setup. If draft mode has no draft ID, the shell keeps a draft-safe visual fallback for direct development loading without creating a frontend-only committed draft.

If the mode is `committed`, the same shell renders committed-world placeholder pane labels. Committed world data loading remains outside this shell contract until a later ticket connects it.

The page always renders the same top-level frame: background image, dark cinematic overlays, non-clickable VySol branding, and the centered tab control. The user can switch between `Customize` and `Ingestion`, but each tab currently shows only minimal shell state because feature controls belong to later tickets.

## Inputs

World Detail Page Shell currently receives frontend route/query state for display mode and optional draft ID. That route state may come from direct URL loading, browser Back/Forward, or the Hub's client-side Create World navigation. In backend-backed draft mode, it also receives draft detail from the Draft World Detail API. It imports app-owned built-in assets for the visual default background, font, and logo mark.

It does not receive committed world records, raw source paths, ingestion attempts, database rows, provider responses, or uploaded assets.

## Outputs

The system produces visible frontend UI state only. It renders the page shell, active tab state, draft loading/error state, and minimal pane copy.

It may read backend draft detail when a draft ID is present. It does not write files, create database rows, create drafts by rendering, persist draft data, start ingestion, save settings, or emit app logs.

## User-Facing Behavior

Users see a full-screen world detail frame with VySol branding in the top-left and two centered tabs. The brand is informational only and must not navigate or refresh the page when clicked.

The `Customize` and `Ingestion` tabs are visible in both draft and committed modes. Draft panes may show minimal read-only backend state, such as loaded splitter defaults or staged-source count. The panes intentionally avoid real controls until the related feature tickets add them.

## System Interactions

World Detail Page Shell currently interacts with:

- Built-in default assets, which provide the true default world image and default font used by the shell.
- Draft World Detail API, which provides backend-owned draft splitter settings and staged-source summaries when a draft ID is present.
- World Hub Page, which can create a draft and route into this shell through browser history.
- The frontend launcher service, which can start the Vite development server when the frontend service is enabled.
- Future Customize UI, which can place world identity and visual controls inside the Customize pane.
- Future Ingestion UI, which can place source and ingestion controls inside the Ingestion pane.

It must stay separate from backend storage, draft-world registries, committed-world indexes, source staging mutation, ingestion attempt state, parsing, chunking, graph systems, and retrieval.

## Current Edge Cases

Internal edge cases:

- Missing or unknown mode values fall back to draft display mode.
- Draft mode without a draft ID stays a visual shell fallback and does not create frontend-only draft state.
- Client-side navigation from the Hub can render this shell without a full document reload.
- Browser Back/Forward can return between Hub and World Detail through route state.
- The brand area is not an anchor or button, so clicking it does not navigate.
- The tab shell must fit without clipped tab labels on narrow viewports.
- The active tab underline must remain tied to the selected tab.
- The shell uses source built-in assets, while generated frontend build output remains reproducible and ignored.

Cross-system edge cases:

- The shell must use the true default world image and font rather than choosing any built-in asset at random.
- Backend draft IDs must be read from route state and rehydrated from the backend rather than invented by the frontend.
- Missing or failed draft rehydration must stay draft-safe and must not create committed storage.
- Route changes must not create draft state by rendering the shell; draft creation belongs to the Hub entrypoint and Draft World Detail API.
- Draft mode must not create committed-world records or durable folders.
- Committed mode must not mark a world as used simply because this static shell rendered.
- Future Customize and Ingestion work must add behavior inside the tab panes without turning the shell into storage or orchestration logic.
- Logs must remain absent unless a future UI logging standard is introduced.

## Invariants

- The World Detail shell must render both `Customize` and `Ingestion` tabs in draft and committed modes.
- The VySol brand must remain visible, top-left, and non-clickable.
- The shell must not implement Customize fields or Ingestion controls by itself.
- The shell must not persist draft state, committed-world state, source state, or ingestion state.
- Rendering the shell must not create a draft; draft creation belongs to the Hub Create World entrypoint calling the backend API.
- The shell must not hardcode local machine paths, user data, secrets, or uploaded file paths.
- Frontend build output must remain reproducible from source assets and package metadata.

## Implementation Landmarks

- `frontend/src/world-detail-page.tsx` owns the shell composition, mode handling, branding, and tab panes.
- `frontend/src/draft-world-api.ts` owns draft detail API calls and the Create World navigation helper.
- `frontend/src/main.tsx` owns the current route switch between Hub and World Detail.
- `frontend/src/styles.css` owns the cinematic glass visual treatment, responsive layout, and default font face.
- `frontend/src/components/ui/tabs.tsx` owns the local Radix Tabs wrapper used by the shell.
- `scripts/launcher/launcher.config.json` contains the frontend service configuration for the Vite dev server.

## What AI/Coders Must Check Before Changing This System

Before editing World Detail Page Shell, check:

- Whether the change belongs in the shell instead of a future Customize, Ingestion, storage, or backend route system.
- Whether both draft and committed modes still render the same shell structure.
- Whether backend-backed draft route state still rehydrates from Draft World Detail API.
- Whether the VySol brand remains non-clickable.
- Whether the tab labels, active state, and responsive layout remain visible without clipping.
- Whether true default assets are still used when no real world data is connected.
- Whether generated build output stays ignored and source assets remain the tracked source of truth.
