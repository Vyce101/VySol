# Changelog

All notable user-visible changes to this project will be documented in this file.

## [Unreleased]

### Added

- Initial GraphRAG backend and frontend with a resilient local launcher.
- Split setup and usage docs into dedicated guides for setup, walkthrough, and features.
- Added a dedicated system diagram page and linked it from the README.
- Added branding assets and a README logo.
- Added entity resolution run modes, including `Exact only` and `Exact + chooser/combiner`.
- Added per-key Gemini API key toggles and a dedicated repo-local pytest temp folder.
- Added the VySol browser/header branding icon using the square logo asset.
- Added a per-message `Context Graph` view in Context X-Ray for newer chat messages.
- Added a Safety Review Queue for extraction safety blocks, including one-shot recovery for already-collapsed blocked chunks and in-app chunk editing/testing.
- Added inline chat renaming in the sidebar, with conflict-safe saves that preserve Recent ordering.
- Added a world-specific `Re-ingest` settings editor for editing saved chunk settings, glean amount, world-local ingest prompts, and repaired-chunk reuse before starting a full rebuild.
- Added a `New Nodes` entity-resolution metric that tracks graph growth since the last completed entity-resolution run when a saved baseline exists.
- Added crash-safe world duplication from the home page, including copied chats/settings/graph data, temporary duplicate preview cards, and bottom-right duplication progress tracking.

### Changed

- Refreshed docs and aligned runtime defaults.
- Corrected project branding capitalization to `VySol`.
- Refined the README positioning, added a `Common Uses` section to present roleplay in pre-existing fictional worlds as VySol's personal origin while broadening the documented use cases, and clarified the current macOS/Linux manual-setup support wording.
- Documented entity resolution run modes.
- Documented API key toggle behavior in the walkthrough and Google AI Studio key guide.
- Renamed the default embedding model to `gemini-embedding-2-preview`.
- Changed retrieval entry-node indexing to use one persistent vector per current graph node, with `Re-embed All` rebuilding from the current saved graph state.
- Changed model-context assembly and Context X-Ray to preserve real graph nodes even when different nodes share the same display name, instead of fake-merging them by label.
- Changed `# RAG Chunks` context assembly to keep full chunk text and `[B#:C#]` provenance tags while ordering included chunks by temporal provenance.
- Changed graph node sizing and force spacing so high-connection nodes scale larger and crowded hubs spread farther apart in the graph viewers.
- Changed ingestion rebuild controls so `Re-embed All` now verifies the original ingested source set, ignores brand-new pending sources, and blocks when older ingested files changed or need a clean rebuild.
- Changed safety-review editing to use one editable `Raw Chunk` field with immutable original text, repeatable test/reset flows, and clearer rebuild guards around repaired chunk overrides.
- Changed graph extraction to use chunk-body text plus separate reference-only overlap context, while keeping prefixed combined chunk text for embeddings, chat provenance, and storage.
- Changed safety-review editing to show overlap separately from the editable chunk body and exposed a dedicated Graph Architect glean prompt in the prompt editor.
- Changed `Re-embed All` to reuse active repaired chunk bodies when the locked ingest snapshot still matches, while full rebuild paths remain blocked until overrides are discarded.
- Changed entity resolution to expose per-run unique-node embedding batch and delay controls in the UI.
- Changed the entity-resolution modal to replace the old top stat-card strip with a split controls/last-run summary layout, rename exact-only result counters to `Exact Matches` and `Left Unchanged`, and move per-setting helper copy into tooltips.
- Changed the ingest page to use one `Re-ingest` rebuild action with a read-only world snapshot on the main page and world-local saved prompt precedence (`world -> global -> default`) for ingest/entity-resolution prompts.
- Changed full `Re-ingest` to optionally reuse repaired chunk overrides when the chunk map stays the same instead of forcing users through separate rebuild buttons and warning cards.
- Changed the ingest UI so `Re-ingest` settings open in an in-page popup, `Books in This World` collapses inside the left control column, `Safety Queue` opens as an on-page workspace, and `Retry All Failures` appears only when failures exist.

### Fixed

- Fixed entity resolution so runs stage graph and unique-node-index changes until the full run succeeds, failed chooser/combiner/provider paths surface real backend errors instead of silent degradation, and stale unique-node vectors are now treated as repairable missing coverage instead of silently counting as healthy.
- Fixed world duplication so completed duplicates no longer inherit stale resume/checkpoint state, copied ingest logs, or source-world chunk provenance that could later make the duplicate regress into a fake `partial_failure` state.
- Fixed world-duplication preview cards so active duplicates no longer disappear during normal polling, source cards lock the duplicate action while a copy is running, and world-card status pills/stats now keep a consistent compact layout across different worlds.
- Fixed ingest-family color consistency so dark mode uses the intended purple accent, light mode uses the intended blue accent, safety-review passed states reuse the same success green, and washed-out or invisible ingest progress/book/status accents render correctly again.
- Fixed glean default/input behavior and clarified the currently supported OS.
- Fixed launcher startup state detection.
- Fixed Gemini chat payload assembly for the Gemini SDK request shape.
- Fixed graph node focus visibility by adding a subtle white hover glow and a stronger selected-node glow in both the graph tab and Context Graph viewer.
- Fixed graph edge hover details to show source and target names plus provenance in the graph viewer.
- Fixed graph viewer startup layout so first-open graphs spread correctly and auto-fit no longer hijacks manual navigation.
- Fixed graph node hitboxes, shared graph-viewer modal sizing, context-graph interaction regressions, and uniform edge hover behavior across the graph tab and Context Graph.
- Fixed Context Graph role visibility by explicitly labeling entry nodes versus expanded nodes in the graph legend, tooltips, and inspector.
- Fixed chunk extraction edge binding so newly extracted edges attach to the exact node UUIDs created for that chunk instead of an older same-name node elsewhere in the graph.
- Fixed safety-block retry handling so blocked chunks stay in the safety-review flow, retries do not collapse them into fake extraction success, and stale review popups/testing states recover cleanly.
- Fixed chat thread switching so in-flight replies and history versions stay isolated to the correct chat tab instead of leaking across chats.
- Fixed chat auto-scroll so any upward scroll disables snapping until the user reaches the bottom again.
- Fixed chat markdown rendering so saved replies can display real headings, GFM tables, code blocks, and block spacing correctly instead of flattening or mis-spacing markdown content.
- Fixed long-chat typing lag by isolating the composer draft from expensive history rerenders, and grouped chat retrieval controls into collapsed `General`, `Chunk`, `Graph`, and `Prompt` sections.
- Fixed Gemini key rotation so extraction, embeddings, retrieval, and Gemini chat wait through shared cooldown windows, fail over on transient timeout/connect failures, and stop skipping extra keys after some retries.
- Fixed ingest progress so long pauses now surface as queued slot or API-key cooldown waits instead of looking like the run silently froze.
- Fixed the ingest page so adding or deleting pending books refreshes the action controls immediately instead of showing stale `Start Ingestion` / completion state until a page reload.
- Fixed ingest progress UI flicker by switching the main ingest page and floating global status panel to stable world-level extraction/embedding summaries instead of last-agent phase swapping.
- Fixed the main ingest progress header to show stable `Unique Graph Nodes` and `Embedded Unique Nodes` counters with lightweight hover explanations tied to entity-resolution behavior.
- Fixed the ingest action panel by removing redundant sidebar progress boxes and duplicate repaired-chunk warnings, capitalizing `Input Progress`, and moving disabled-action explanations into tooltip/info affordances.
- Fixed ingest abort-state handling so the main progress area keeps `Aborting...` state stable across refreshes and SSE reconnects, and abort requests against missing worlds now fail correctly instead of silently succeeding.
- Fixed entity-resolution abort/startup handling so stop requests surface an explicit `Aborting` phase, finished runs are not overwritten by late aborts, and failed startup paths no longer leave ghost active runs behind.

### Removed

- Removed obsolete frontend-local README/test-writing clutter that no longer belonged in the shipped project.
