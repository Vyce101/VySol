# World Detail Customize UI

World Detail Customize UI is VySol's frontend-only Customize tab surface for world identity and visual style presentation in World Detail. It shows editable local fields for the world name and Description, plus read-only previews of the selected background and world-title font.

This page is for developers, power users, and AI coding agents that need to understand the Customize tab boundary before changing World Detail layout, draft defaults, committed-world detail presentation, or future customization persistence.

## Why It Exists

World Detail needs a visible Customize surface before persistence, pickers, uploads, and save/discard behavior exist. The UI gives draft and committed worlds the same basic identity-editing shape while keeping all edits local to the frontend for now.

The boundary matters because this tab is presentation and draft-local editing only. It must not imply that changing fields saves committed metadata, changes draft storage, uploads assets, deletes assets, starts ingestion, or refreshes committed-world recent-use state.

## Ownership Boundary

World Detail Customize UI owns:

- Rendering the Customize tab content inside World Detail.
- Showing editable local World Name and Description fields.
- Showing the current world title outside the field boxes with the selected title font applied.
- Showing read-only background and font previews for the current local selection.
- Initializing committed-world fields from Committed World Detail API data.
- Initializing draft fields from frontend-local defaults.
- Keeping the two Customize panels equal width on desktop and contained in the left half of the viewport.
- Keeping normal Customize text selectable while leaving app chrome behavior unchanged.
- Showing quiet loading, idle, and error states without console logging.

World Detail Customize UI does not own:

- Saving or discarding Customize changes.
- Persisting draft world identity or visual style.
- Updating committed world metadata or `last_used_at`.
- Marking draft customization dirty state.
- Background or font picker selection behavior.
- Asset upload, validation, deduplication, deletion, or replacement.
- Ingestion controls, source staging, parsing, splitting, committing, retrieval, graph behavior, or chat.
- World Hub cards or World Hub hero behavior.
- Backend routes, storage migrations, or app logging.

## Normal Flow

World Detail renders the Customize tab by passing the current draft or committed load state into the Customize UI. Draft routes use local frontend defaults: `Untitled World`, an empty Description, the main built-in background, and the default Inter font. Committed routes use the loaded committed detail response for display name, optional description, background image URL, font asset ID, and font file URL.

When a user edits World Name or Description, the fields update local React state only. The visible title updates immediately from the local World Name field. Font preview applies only to title-style text, matching the current app rule that world fonts affect world titles rather than every UI label.

## Inputs

The UI receives frontend load state from World Detail. In committed mode, loaded state includes committed world identity, selected background URL, selected font URL, and asset IDs. In draft mode, the UI receives draft route state but uses local defaults because draft identity persistence does not exist yet.

## Outputs

The UI produces visible frontend state only: field values, title preview, background preview, font preview, and loading/error surfaces. It does not write backend state, create files, call persistence endpoints, mutate asset records, or emit app logs.

## User-Facing Behavior

Users see a left-side Customize work area with a title above two equal-width glass panels. The left panel owns world identity fields. The right panel owns visual style previews. On desktop, the right edge of the visual panel should land at roughly the viewport midpoint so the right half of the screen remains available for the background image. On narrow screens, the panels stack vertically to avoid cramped controls.

Committed worlds show saved values after committed detail loads. Draft worlds show `Untitled World` and an empty Description by default. If committed detail cannot load, the tab shows a quiet error state instead of falling back to draft defaults.

## System Interactions

World Detail Customize UI interacts with:

- World Detail Page Shell, which hosts the tab, top-level route state, and parent navigation.
- Committed World Detail API, which supplies committed-world identity and visual-style values.
- Draft World Detail API, which supplies draft route state but not draft identity fields.
- Asset File Delivery, which serves committed background images and font files through browser-safe URLs.
- Built-in frontend assets, which provide draft defaults for the main background and default font.

It must stay separate from asset storage, committed-world index updates, draft-world persistence, ingestion orchestration, source staging, graph systems, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- Draft routes without loaded draft detail still show safe local draft defaults.
- Committed routes without loaded detail show a committed-values-not-loaded state rather than draft defaults.
- Empty Description stays empty instead of inventing placeholder copy.
- Empty World Name edits keep the preview area stable by falling back to the draft default title for preview text.
- Long names wrap inside the title and font preview instead of forcing the layout wider.
- Mobile layouts stack the panels and allow vertical page scroll.

Cross-system edge cases:

- Local edits must not call draft dirty-state routes because Save/Discard persistence is not part of the current Customize UI contract.
- Committed detail loading must remain read-only and must not refresh `last_used_at`.
- Background and font previews must use browser-safe URLs or app-owned source imports, not local filesystem paths.
- Customize UI failures must stay visible and quiet without browser console noise.
- The UI must not make drafts visible in World Hub or create committed world rows.

## Invariants

- Draft defaults remain frontend-local until a future persistence contract exists.
- Committed values must come from the committed detail response, not from World Hub card state.
- Field edits are local-only and must not persist, save, discard, upload, delete, or mark used.
- Background and font previews are references only until picker behavior exists.
- World fonts affect title-style text only.
- The Customize tab must remain separate from Ingestion behavior.
- The layout must preserve right-side background visibility on desktop and avoid clipped controls on narrow screens.
- No local machine paths, secrets, user file paths, or uploaded file paths may be exposed in the UI.

## Implementation Landmarks

- `frontend/src/world-detail-customize-tab.tsx` owns the Customize tab composition and local form state.
- `frontend/src/world-detail-page.tsx` passes draft and committed load state into the tab.
- `frontend/src/styles.css` owns the current glass-panel Customize layout and responsive behavior.

## What AI/Coders Must Check Before Changing This System

Before editing World Detail Customize UI, check:

- Whether the change would cross into persistence, Save/Discard, picker behavior, upload/delete behavior, or committed-world updates.
- Whether committed-world reads still use Committed World Detail API and remain read-only.
- Whether draft behavior still avoids pretending durable draft identity storage exists.
- Whether normal text remains selectable where expected and controls avoid overlap on narrow screens.
- Whether visual previews still avoid raw local paths and backend-owned stored paths.
