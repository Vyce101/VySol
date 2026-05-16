# Draft Abandon Confirmation UI

Draft Abandon Confirmation UI is VySol's frontend guard for intentional in-app navigation away from an uncommitted draft world when the backend says leaving is unsafe. It shows a destructive confirmation dialog before temporary draft setup is discarded.

This page is for developers, power users, and AI coding agents that need to understand the visible draft-abandon contract before changing World Detail navigation, draft leave checks, confirmation dialog behavior, or route transitions back to World Hub.

## Why It Exists

New-world drafts can hold temporary identity choices, customization state, and staged sources before a successful commit makes the world visible in World Hub. Without a confirmation step, the visible `Worlds` navigation could discard that setup too easily.

The UI exists to put a human confirmation boundary in front of intentional in-app abandonment while preserving refresh and tab-close behavior for the draft rehydration contract.

## Ownership Boundary

Draft Abandon Confirmation UI owns:

- Intercepting the World Detail `Worlds` parent navigation when the current route is a draft with a draft ID.
- Asking Draft World Leave Safety whether the draft should warn before leaving.
- Showing a dimmed destructive confirmation dialog when the backend reports unsafe leave state.
- Explaining which draft items will be discarded and that uploaded global assets remain available.
- Keeping the user on draft World Detail when they choose `Keep Editing` or when leave/discard requests fail.
- Calling confirmed-leave only after the user chooses `Discard Draft`.
- Returning to World Hub after safe leave or confirmed draft discard.

Draft Abandon Confirmation UI does not own:

- Browser refresh prompts, tab-close prompts, or browser-history warning behavior.
- Backend leave-safety policy or ingestion phase safety decisions.
- Draft creation, draft persistence, source staging internals, or source commit behavior.
- Uploaded asset deletion.
- Committed-world deletion or committed-world cleanup.
- Customize fields, Ingestion controls, or World Hub committed-world rendering.
- App logging for normal confirmation or cancel behavior.

## Normal Flow

When the user activates `Worlds` from committed World Detail, the page routes directly to World Hub.

When the user activates `Worlds` from draft World Detail with a draft ID, the frontend asks Draft World Leave Safety for the current leave state. If the backend says leaving is safe, the frontend routes to World Hub without a dialog. If the backend says leaving should warn, the frontend opens the confirmation dialog.

The dialog explains that leaving now affects draft world name and description, selected background and font choices, staged sources and extraction setup, and uploaded global assets. The discard list is separated from the remain-available list. `Keep Editing` closes the dialog with draft state unchanged. `Discard Draft` calls confirmed-leave, then returns to World Hub after the backend accepts the discard.

## Inputs

Draft Abandon Confirmation UI receives the current frontend world mode, optional draft ID, the user's `Worlds` navigation action, and the backend leave-state and confirmed-leave responses.

It does not receive raw source file paths, source text, uploaded asset file contents, committed-world database rows, or browser lifecycle events.

## Outputs

The system produces visible UI state: the dimmed modal, impact lists, destructive and safe actions, disabled in-flight controls, and quiet inline error text when leave-state or discard requests fail.

It may trigger frontend route changes to World Hub and may call the existing confirmed-leave endpoint. It does not create World Hub entries, write files, delete uploaded assets, or emit app logs.

## User-Facing Behavior

The confirmation dialog uses the current cinematic glass visual language and slightly dims the World Detail background. Its title is `Discard draft world?`, its intro ends with `Leaving now will affect the following items:`, and the impact sections are shown as bullet lists.

The `Worlds` nav label stays stable while the leave-state request is in flight so the navigation pill does not shift before the dialog appears.

## Failure Behavior

If the leave-state check fails, the user stays on draft World Detail and sees a quiet inline navigation error. If confirmed discard fails, the dialog remains open and shows an inline failure message. Neither normal failure path should create console spam.

## System Interactions

Draft Abandon Confirmation UI interacts with:

- World Detail Page Shell, which renders the parent `Worlds` navigation and hosts the dialog.
- Draft World Detail API, which provides the draft ID and rehydrated draft detail used by World Detail.
- Draft World Leave Safety, which decides whether the draft should warn and whether confirmed leave should discard temporary state.
- Temporary Source Staging State, which is discarded by the backend only after confirmed dangerous leave.
- World Hub Page, which is the destination after safe leave or confirmed discard.

It must stay separate from browser lifecycle prompts, uploaded asset storage, committed-world storage, source commit orchestration, graph extraction, retrieval, and chat behavior.

## Current Edge Cases

Internal edge cases:

- Committed World Detail navigation returns to World Hub without showing the draft dialog.
- Draft mode without a draft ID routes to World Hub without attempting discard.
- `Keep Editing` closes the dialog without changing draft state.
- In-flight leave checks and discard calls disable the relevant controls without changing the `Worlds` label.
- Failed leave checks and discard calls keep the user in draft World Detail.

Cross-system edge cases:

- The dialog appears only for in-app `Worlds` navigation, not browser refresh or tab close.
- Tab switching between `Customize` and `Ingestion` must not call leave-state or confirmed-leave.
- Confirmed discard must not create a World Hub entry.
- Confirmed discard must not delete uploaded global assets or committed-world data.
- Safe-zone leave must not discard draft or staging state.

## Invariants

- The backend remains the source of truth for whether draft leave should warn.
- A confirmed dangerous leave must call existing confirmed-leave behavior before returning to World Hub.
- Canceling the dialog must keep draft state unchanged.
- The impact copy must keep discarded items separate from remain-available items.
- Browser refresh and tab close must remain outside this UI guard.
- Normal confirmation and cancel behavior must not add app logging.

## Implementation Landmarks

- `frontend/src/draft-abandon-navigation.ts` owns the frontend leave-state and confirmed-leave navigation hook.
- `frontend/src/draft-abandon-confirmation-dialog.tsx` owns the confirmation dialog structure and copy.
- `frontend/src/world-detail-page.tsx` wires the World Detail `Worlds` control to the guard.
- `frontend/src/styles.css` owns the current dialog and dimmed-overlay styling.
- `frontend/src/draft-world-api.ts` exposes the leave-state and confirmed-leave helpers.

## What AI/Coders Must Check Before Changing This System

Before editing Draft Abandon Confirmation UI, check:

- Whether the backend leave-state contract still uses the same safe-zone boundary.
- Whether the dialog still avoids browser refresh and tab-close prompts.
- Whether committed World Detail and tab switching still avoid draft discard behavior.
- Whether failed leave/discard requests keep the user on draft World Detail.
- Whether copy still says uploaded global assets remain available without implying they are deleted.
- Whether route changes still avoid creating committed world records or frontend-only drafts.
