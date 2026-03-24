# Core Safety / Always Applies

- This file is for you, the assistant, and it is meant to control your behavior and help you and future instances of you to make your coding abilties better with less mistakes.
- If you believe any new rule, command, note, reminder, or instruction should be added to this file, do not add it on your own.
- First ask the user about it and wait for the user's final approval before adding anything new to this file, you may ask even if you beleive it may interupt the flow of the work if you believe it would be helpful to add.
- Never delete or overwrite user data in local runtime folders like `saved_worlds/`, `settings/settings.json`, `Corpus/`, or env files without explicit confirmation in that same turn.
- Treat anything under `saved_worlds/`, `Corpus/`, and live settings/env files as personal data by default, not disposable project files.
- If a task involves licensing, commercial terms, or public-release legal wording, avoid inventing legal conclusions and flag that final legal review is still the user's responsibility.
- When adding ignore rules, confirm whether the user wants data merely ignored, moved, or actually deleted.
- The assistant can and should suggest improvements to this `AGENTS.md` when helpful, but must never apply `AGENTS.md` rule changes without explicit user approval in that same turn.
- When running terminal commands in this repo, always prefer `-LiteralPath` (and absolute paths where possible) for path operations so bracketed folder names are handled safely.
- For any delete/remove action, prefer repo-scoped relative targets, run a preview/safety check first (for example `-WhatIf` plus exact target existence), and only execute deletion when the target exactly matches the intended file(s), never broad drive-level patterns.

# Before Starting Work

- Check the `Pattern Bug Logger` before planning changes in areas related to previous bugs.
- If you find a conflict between the user's request and the existing architecture, call it out instead of forcing a messy patch.
- If you discover a likely bug unrelated to the current task, mention it briefly but do not fix it unless the user asks or it blocks the task.
- If you need to make an assumption because the user did not specify something important, stop and ask the user for clarification before implementing it.

# While Making A Plan Document (If In Planning Mode)

- If operating in planning mode and writing a plan document for implementation, always include a section that clearly explains the pseudocode of how the code will work. This should describe the actual implementation flow, data movement, branching, and key logic in code-like steps, not just high-level project tasks.
- While planning, check whether the proposed change is likely to break or weaken any other existing feature or workflow. If it might, inform the user clearly, give reasonable suggestions or safer alternatives, and let the user make the final call before implementation.
- Keep pseudocode readable by default. Prefer plain-English behavior flow over implementation-heavy notation unless low-level detail is genuinely necessary to explain the logic.
- Start with what the system will do step by step from the user's point of view or feature flow, then add only the minimum implementation notes needed to make the plan unambiguous.
- Avoid leading with framework hooks, helper names, ref names, or scheduling primitives unless they are central to the bug or design.
- Prefer outcome-oriented wording such as what gets loaded, when layout happens, or when the user regains control, instead of describing internal mechanics first.
- Use code-shaped pseudocode only for genuinely tricky branching, state transitions, or data flow that would be harder to understand in plain language.

# While Implementing

- Re-check relevant `Pattern Bug Logger` entries while coding in areas touched by previous bugs.
- If you are about to touch user data, migrations, file paths, storage locations, auth, or secrets handling, stop and ask the user for permission first.
- After any coding task that changes tracked files, keep the repo publish-safe by default unless the user says the change is private or local-only.

This means:

- Do not add secrets, live env values, personal data, or saved-world data to tracked files.
- Do not hardcode machine-specific paths, usernames, or local directories.
- If a new env var is needed, add it to an `.example` file and mention it in the docs.
- If a new local data, cache, or output folder is introduced, make sure it is git-ignored.
- If a change would require deleting or moving user data, stop and ask first.

# Before Testing

- Do a quick GitHub-safety check on the edited files:
- No secrets.
- No hardcoded local paths.
- No accidental user data.
- New env vars documented and added to `.example` files.
- New local output folders are git-ignored.
- Re-read your own changed files once before running tests.
- For user-visible frontend changes or bug fixes involving clicks, routing, modals, forms, theme behavior, or browser state, prefer verifying with Playwright instead of relying only on static inspection.
- Before relying on Playwright for app verification, always ask the user to make sure the code/app is already launched; do not assume the assistant can reliably boot the full local stack from the current environment.
- When running `pytest` in this repo, do not override `--basetemp` or `cache_dir` unless the user explicitly asks. Use the shared `pytest.ini` defaults so test temp files stay in the one intended location.
- Do not create ad hoc repo-root or `backend/` pytest temp folders such as `pytest_*`, `.pytest_*`, `_codex_pytest_*`, or manual temp-workaround directories just to get around cleanup problems. If pytest cleanup fails, report it and stop inventing new temp roots inside the repo.
- When reviewing docs after testing, follow the `Documentation Map` below to decide where approved documentation changes belong.
- Run a GitHub-safety check before testing.
- After coding, always do a UI truthfulness and silent-failure pass against the real code paths, not just the happy path. Check whether the UI can ever imply success, completion, availability, or live state that the backend or persisted data does not actually guarantee, especially across retries, partial failures, stale refreshes, and recovery flows. If the mismatch has a small safe fix, make it. If making it truthful requires a broader workflow or architecture change, stop and explain that to the user before continuing. If no mismatch is found, continue.

# Before Commit / Push

- Always do a `GitHub-ready pass` before any commit or push, even if the user did not say the exact trigger phrase.
- Scan the changed files for secrets, hardcoded local paths, local-only runtime data, and generated artifacts.
- Review whether `CHANGELOG.md` and the existing docs should be updated.
- Make sure `CHANGELOG.md` reflects new user-visible changes under `## [Unreleased]`.
- Check the existing docs, including the files in the `Documentation Map`, to see whether setup requirements, user workflow, feature behavior, release history, licensing context, or public-facing guidance changed.
- Check whether any new local-only data, cache, build, temp, artifact, or machine-specific files/folders should be added to `.gitignore`. If yes, quickly inform the user and ask whether they want those ignore rules added before commit/push.
- If docs other than `CHANGELOG.md` should change, do not commit or push yet. Ask the user which docs they want updated, make those approved changes with them, and once the doc work is done ask whether they are ready to continue with commit/push.
- Review top-level repo hygiene, launcher scripts, licensing and docs consistency, and anything that would confuse a clean downloader.
- Report anything that still needs manual action, like key rotation or git-history cleanup.

## Commands

If the user says `Full public-release pass`, do this:

- Do the normal `GitHub-ready pass`.
- Also review top-level repo hygiene, launcher scripts, licensing and docs consistency, and anything that would confuse a clean downloader.

If the user says `commit`, do this:

- The assistant must choose and stage files intentionally for that commit.
- Do not default to `git add .` unless the user explicitly asks to commit everything.
- Group related changes into focused separate commits when practical, then show what was staged before committing.

# If User Asks To Release

- Keep one root `CHANGELOG.md` as the source of truth for release history.
- Keep `## [Unreleased]` at the top of `CHANGELOG.md`.
- Move `Unreleased` entries into a versioned section only when releasing, not on every push.
- Use changelog categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.
- Use semantic versioning (`MAJOR.MINOR.PATCH`).
- Use release section heading format: `## [X.Y.Z] - YYYY-MM-DD`.
- On release day, always check the current date from the system/terminal in that same turn before writing the release date; never guess.
- Keep release metadata in sync:
- `CHANGELOG.md` version/date
- Git tag `vX.Y.Z`
- GitHub Release title/notes
- If a release has breaking behavior, include a clear breaking-change note and migration guidance.

# Reference: Pattern Bug Logger

- Keep a `Pattern Bug Logger` section in this file for pattern-level lessons from real bugs.
- Log the pattern, trigger shape, failure mode, prevention principle, and safe future behavior.
- Do not log line-level blame or one-off implementation details unless the user explicitly asks for that level of detail.
- Write entries so a future assistant with no chat history can recognize and avoid repeating the same class of mistake during later refactors.
- When writing entries, prefer broad reusable failure patterns over code-location notes, function-name reminders, or repo trivia. If an entry would stop being useful after a refactor, rename, or file move, it is too implementation-specific for this logger.

## How To Use It

- Check the `Pattern Bug Logger` before making changes in areas related to previous bugs.
- Use it as a guardrail during planning, implementation, reviews, and bug fixes.
- Apply entries as broad prevention guidance, not as a reason to cargo-cult old code or block necessary improvements.
- When a bug is fixed, decide whether it revealed a reusable pattern that should be logged for future work.
- At the end of every bug-fixing task, suggest to the user any pattern-level lesson that may be worth adding to this logger, but never add or change logger entries without explicit approval in that same turn.

## Entry Format

- `Pattern:` the reusable mistake shape or risky interaction.
- `What tends to trigger it:` the general conditions that make it likely.
- `Failure mode:` how it breaks in practice.
- `Prevent it by:` the principle future changes should follow.
- `Watch for when changing:` the areas or kinds of code where the pattern matters most.

## Logged Patterns

- `Pattern:` Shared per-page UI state can leak across tab/thread switches when async fetch or stream callbacks are not scoped to the owning resource.
- `What tends to trigger it:` one screen reuses global message, version, or streaming state across multiple chats while background requests are still in flight.
- `Failure mode:` switching to chat B while chat A is still loading or streaming can show chat A's latest reply on top of chat B's history, or save edits against the wrong thread version.
- `Prevent it by:` keeping state keyed by resource id, stamping fetch and stream requests, and ignoring stale callbacks unless they still match the latest request for that same resource.
- `Watch for when changing:` chat tabs, background streaming, optimistic UI updates, edit, delete, or regenerate flows, and any page that swaps between multiple live resources.

- `Pattern:` Broken setup-state detection can repeatedly force repair/install paths and turn a recoverable local-environment issue into a larger startup failure.
- `What tends to trigger it:` invalid or missing cache/stamp state, partial environment rebuilds, interrupted installs, or native dependency files that may be locked by running processes.
- `Failure mode:` startup repeatedly re-enters setup work, attempts package repair unnecessarily, and can worsen a damaged local environment instead of cleanly skipping or isolating recovery.
- `Prevent it by:` making setup-state checks robust, validating cached markers before trusting them, preferring repairable and clearly logged recovery paths, and avoiding repeated heavy repair work when local environment state is obviously inconsistent.
- `Watch for when changing:` launch scripts, dependency bootstrap logic, virtualenv management, cache/stamp files, file-watcher dependencies, and any startup automation that mixes validation with repair.

- `Pattern:` Do not reuse human-readable or debug payload shapes as live provider request payloads when an SDK expects stricter typed inputs.
- `What tends to trigger it:` hand-built request dicts, SDK upgrades, provider swaps, or trying to use one payload for both UI/debug display and actual API transport.
- `Failure mode:` provider validation fails before generation starts, often surfacing raw schema or Pydantic errors in the UI even though app state and user input are otherwise valid.
- `Prevent it by:` keeping provider-bound payload assembly separate from persisted/debug payloads, using SDK helper types for live calls, and adding tests that validate the exact request shape sent to the provider.
- `Watch for when changing:` chat providers, SDK integrations, context-capture/X-Ray features, prompt serialization, and any path where one structure is used for both display and transport.

- `Pattern:` Shared interactive graph components can silently regress when their host layout contracts are not preserved across page and modal reuse.
- `What tends to trigger it:` extracting a graph or canvas viewer into a reusable component, then mounting it in containers with different flex, height, overflow, or inspector/sidebar behavior.
- `Failure mode:` the graph appears clipped, disappears, loses stable viewport behavior, or works in one host while breaking in another.
- `Prevent it by:` treating width, height, overflow, and resize behavior as part of the component contract, then re-checking every host layout after the refactor instead of assuming the shared component is self-sizing.
- `Watch for when changing:` shared graph viewers, modal bodies, flex layouts, resize logic, inspectors, and any visualization moved from a page into a reusable wrapper.

- `Pattern:` In custom-rendered canvas graphs, pointer geometry must stay in sync with visible geometry.
- `What tends to trigger it:` custom node sizing or canvas drawing while hover and click detection still rely on library defaults or stale hit-area logic.
- `Failure mode:` edge hovers steal focus from visible nodes, clicks only work near the center, or interaction no longer matches what the user sees on screen.
- `Prevent it by:` reusing the same radius, position, and shape logic for both visible rendering and invisible pointer-area painting so the hitbox always matches the drawn object.
- `Watch for when changing:` node sizing, custom canvas rendering, hit testing, hover tooltips, click selection, and edge-hover tuning.

- `Pattern:` Retrieval settings that promise unique entities can behave misleadingly if the vector index ranks repeated occurrence records instead of current entities.
- `What tends to trigger it:` indexing nodes per chunk or per occurrence, then deduping after similarity search while exposing the control as `entry nodes` or another unique-entity concept.
- `Failure mode:` high requested entry-node counts collapse into only one or two actual graph seeds, making retrieval settings feel broken even though the vector search technically returned many hits.
- `Prevent it by:` making the retrieval index match the product meaning of the setting, using one persistent record per current graph entity when the system is supposed to retrieve unique entities, and rebuilding that index whenever the graph entity set changes.
- `Watch for when changing:` retrieval ranking, vector-store schemas, entity-resolution flows, re-embed flows, context assembly, and X-Ray retrieval diagnostics.

- `Pattern:` Historical inspection views should capture the exact derived artifact they need at generation time instead of reconstructing it later from loosely related payloads.
- `What tends to trigger it:` adding debug, X-Ray, or visualization views after the main transport payload already exists and trying to derive missing structure from text blobs or partial metadata.
- `Failure mode:` inspection views disagree with what the model actually saw, disappear for some messages, or depend on brittle frontend reconstruction paths.
- `Prevent it by:` storing the exact inspection artifact in dedicated metadata at capture time while keeping transport payloads, debug payloads, and visualization payloads separated by purpose.
- `Watch for when changing:` Context X-Ray, provider payload capture, prompt assembly, visualization snapshots, and any per-message historical debug view.

- `Pattern:` Graph/layout startup logic can fire before a visualization instance and its bounds are actually ready.
- `What tends to trigger it:` async component mount, container measurement racing graph initialization, or force-layout setup tied only to data load or fixed timing.
- `Failure mode:` first render appears clumped, initial auto-fit does nothing or behaves inconsistently, and manual fit works later when the graph has finally stabilized.
- `Prevent it by:` gating initial layout and fit on both a live graph instance and usable graph bounds, instead of relying only on loaded data or timers.
- `Watch for when changing:` graph viewers, canvas/SVG visualizations, force-layout setup, dynamic imports, and mount-time auto-fit behavior.

- `Pattern:` Readiness plumbing for interactive canvases can break pointer interaction even when rendering still appears correct.
- `What tends to trigger it:` callback-ref/state rerender loops, mount-time ref replacement, or added readiness control flow around a third-party visualization instance.
- `Failure mode:` the graph renders and may auto-layout correctly, but pan, zoom, hover, or tooltip interaction stops working or becomes inconsistent.
- `Prevent it by:` preferring the simplest stable instance wiring, treating ref/readiness changes as high-risk for interaction regressions, and re-verifying pointer behavior after refactor changes.
- `Watch for when changing:` graph refs, hover handlers, zoom/pan behavior, dynamic imports, and canvas-based visualization libraries.

- `Pattern:` `Re-embed All` can become misleading or destructive if it silently operates on a different source set than the one that produced the current graph.
- `What tends to trigger it:` newly added pending sources, deleted or edited ingested files, legacy worlds without source snapshots, partial ingest state, or chunk-setting drift between the locked world ingest and the current vault contents.
- `Failure mode:` users think they are only rebuilding vectors for the current graph, but the operation actually touches changed sources, misses required rebuilds, or creates graph/vector drift that a clean full ingest would have avoided.
- `Prevent it by:` verifying that `Re-embed All` only runs against the same previously fully ingested source set, ignoring brand-new pending sources, and blocking the action with a precise reason whenever any prior source is missing, changed, partial, or lacks a trustworthy ingest snapshot.
- `Watch for when changing:` ingest/rebuild actions, source metadata, source-vault handling, retry/resume flows, re-embed eligibility checks, and any UI copy that describes rebuild behavior.

- `Pattern:` Graph extraction can corrupt identity when chunk-local edges are resolved through global same-name lookup instead of the exact node ids created for that chunk.
- `What tends to trigger it:` duplicate display names across books or chunks, post-entity-resolution ingests, or extraction code that creates nodes first and then resolves edges later by normalized name.
- `Failure mode:` a new duplicate node is created for the chunk, but its extracted edges attach to an older same-name node elsewhere in the graph, producing mismatched neighborhoods and misleading retrieval context.
- `Prevent it by:` keeping a chunk-local map from extracted node references to the UUIDs created during that chunk write, then writing that chunk's edges directly against those UUIDs while leaving cross-chunk merging to entity resolution.
- `Watch for when changing:` graph extraction persistence, node/edge write order, duplicate-name handling, entity-resolution interactions, and any refactor that changes how extracted edge endpoints are resolved.

- `Pattern:` Durable chunk-repair overrides can be silently lost or invalidated if rebuild paths treat saved source text as the only ingest truth.
- `What tends to trigger it:` safety-review queues, chunk-level edited retry flows, temporary override caches, or any ingest repair path that stores chunk replacements outside the original source file.
- `Failure mode:` rebuild or re-embed actions ignore active repaired chunks, users lose successful manual fixes without a clear warning, or retry flows mix stale source text with override-backed graph/vector state.
- `Prevent it by:` treating active chunk overrides as first-class ingest state, surfacing them in eligibility checks and status payloads, and blocking destructive rebuild paths until the override state is explicitly resolved or discarded.
- `Watch for when changing:` ingest retry/test flows, safety-review tooling, source snapshot logic, rebuild/re-embed eligibility guards, chunk assembly, and any UI copy that implies what content a rebuild will use.

- `Pattern:` Editable repair workflows become confusing or destructive when original source text, current draft text, and last-applied live override are collapsed into one field or one status.
- `What tends to trigger it:` safety-review editors, chunk-level retry UIs, “reset” actions, or any repair flow where users can keep iterating after a partial or successful fix.
- `Failure mode:` reset restores the wrong version, successful repairs become read-only too early, later failed edits can overwrite the last known-good repair, or the UI shows stale/apparently contradictory chunk states.
- `Prevent it by:` keeping immutable source-original text, the current editable draft, and the last successfully applied override as separate state, then computing UI status from which version is live versus which version is being edited.
- `Watch for when changing:` safety-review state models, repair editors, reset/test/discard actions, override-backed chunk loading, and any workflow that lets users re-edit already repaired content.

- `Pattern:` Transient in-flight review states can get stuck if durable status is reused to mean both “request currently running” and “latest persisted outcome.”
- `What tends to trigger it:` async test/retry actions, failure handlers that recompute status after an exception, or state machines that only store one `status` field without a separate in-flight flag.
- `Failure mode:` the UI stays on `Testing...`, buttons remain disabled, repaired items disappear or sort incorrectly, and later refreshes keep honoring a stale transient state even though the request already finished.
- `Prevent it by:` tracking active in-flight work separately from the persisted review outcome, clearing the in-flight flag on every success and failure path, and making status recomputation derive from current durable state instead of a stale transient label.
- `Watch for when changing:` safety-review test flows, retry queues, async action handlers, status badges, button disabled logic, and any backend/frontend code that persists transient request state.

- `Pattern:` One-off recovery paths must not bypass rebuild and re-embed safety guards if they can leave live override-backed ingest state behind.
- `What tends to trigger it:` manual rescue tools, migration-only repair flows, temporary exception logic for special-case reviews, or code that treats recovery-origin items as not needing the same eligibility rules as normal repairs.
- `Failure mode:` rebuild or re-embed actions appear ready even though repaired chunks are still backed by override text, so a later maintenance action silently drops or desynchronizes those repairs.
- `Prevent it by:` making eligibility and rebuild guards reason about actual live override-backed state rather than the origin label of the repair, and only exempting one-off recovery items when they truly cannot affect current graph or vector content.
- `Watch for when changing:` manual rescue flows, safety-review summaries, rebuild and re-embed guards, override retention, ingest eligibility APIs, and any code that branches on repair origin.

- `Pattern:` Shared Gemini key rotation settings are not enough if Gemini-backed call sites classify transient failures differently or wait on cooldown exhaustion through different helper paths.
- `What tends to trigger it:` extraction, embedding, retrieval, and chat paths growing separate retry logic over time, especially when some paths only cool keys down on `429/500` while others also see timeout or temporary-connect failures.
- `Failure mode:` round robin and fail-over look inconsistent, some workflows fail fast while others recover, cooldown storms produce scattered chunk failures, and the app appears unreliable even though the provider pool later resumes.
- `Prevent it by:` centralizing transient-error classification and cooldown handling, making every Gemini key-managed path use the same wait/retry contract, and avoiding extra caller-side index movement after key selection already advanced.
- `Watch for when changing:` Gemini provider integrations, embedding/retrieval helpers, streaming chat setup, retry wrappers, and any code that chooses or cools API keys.

- `Pattern:` Ingest progress can look stalled when durable status flips to live before workers acquire scheduler slots or API keys and before the next visible phase event is emitted.
- `What tends to trigger it:` concurrent chunk workers, stage schedulers with cooldowns, shared API-key pools, or progress UIs that only show coarse `extracting` / `embedding` phases once work has already started.
- `Failure mode:` the UI looks frozen for several seconds even though chunk tasks are only queued or waiting for key recovery, making users think the run has hung or a new source never actually started.
- `Prevent it by:` surfacing queued and key-wait states explicitly, preserving those wait snapshots in checkpoint/status payloads so reloads see them too, and logging long waits separately from actual failures.
- `Watch for when changing:` ingest progress payloads, checkpoint/status endpoints, scheduler acquisition flow, shared key waits, global ingest widgets, and any log rendering that explains in-flight work.

- `Pattern:` Ingest action controls can desync when source-list mutations refresh only part of the page state.
- `What tends to trigger it:` uploading or deleting sources on a screen where button visibility depends on multiple async slices such as `sources`, checkpoint/resume state, world summary, or rebuild eligibility.
- `Failure mode:` the page shows the wrong primary action, such as `Start Ingestion` instead of `Resume`/`Start Over`, until the user reloads or navigates away and back.
- `Prevent it by:` refreshing every state source that participates in the action decision after source mutations, or deriving the control state from one authoritative payload instead of mixed stale slices.
- `Watch for when changing:` source upload/delete flows, ingest action buttons, checkpoint loading, world summary loading, and any UI that mixes independently fetched status data.

- `Pattern:` Cancellable background jobs need both an explicit `abort requested` phase and a recovery path for orphaned `in_progress` runs.
- `What tends to trigger it:` the UI marks a run active before worker startup fully succeeds, or a worker crashes/exits while persisted status still says `in_progress` and the abort control remains available.
- `Failure mode:` abort appears to do nothing, repeated clicks are ignored, the UI stays stuck on `Running` or `Aborting`, or users cannot tell whether the stop request was accepted versus the worker already being gone.
- `Prevent it by:` separating `aborting` from terminal `aborted`, tying ownership to a per-run token or event, and letting abort or recovery logic finalize stale `in_progress` state when no live worker still owns it.
- `Watch for when changing:` background thread/task launchers, startup preflight code, SSE/progress status plumbing, retry or resume flows, and any page that exposes `Abort` or `Stop` controls.

- `Pattern:` Rendering bugs in model output should be fixed in the renderer or styles first, not by globally forcing providers to change output format.
- `What tends to trigger it:` markdown or rich-text output looks wrong in one surface, and the quickest seeming fix is to add a permanent prompt rule that coerces every reply into one format.
- `Failure mode:` the original display bug may remain, while unrelated workflows like roleplay, plain chat, or custom prompt behavior become unnaturally rigid because the model is now over-constrained everywhere.
- `Prevent it by:` verifying the saved/raw model output before changing prompts, then fixing parsing, sanitization, block handling, or CSS in the affected renderer before adding any global output-format instruction.
- `Watch for when changing:` chat renderers, markdown/HTML support, prompt defaults, provider response formatting rules, and any feature where model output is post-processed for display.

- `Pattern:` High-frequency draft state should not live at the same level as expensive history rendering.
- `What tends to trigger it:` chat, search, or editor screens where the root component owns both rapidly changing input text and a long markdown-rich message history or other heavy child tree.
- `Failure mode:` every keystroke rerenders the full history, reparses markdown, and makes typing feel delayed or sticky once the thread grows.
- `Prevent it by:` isolating draft state inside a local composer, memoizing expensive history rows, and keeping unrelated sidebar or control changes from invalidating the message tree.
- `Watch for when changing:` chat composers, long activity feeds, markdown renderers, streaming message UIs, settings sidebars, and any screen where a small input sits above a large rendered history.

- `Pattern:` World duplication can silently corrupt ingest health if it copies world-id-bound provenance verbatim or carries over transient runtime ingest files.
- `What tends to trigger it:` cloning a world by copying stored files and vector records directly, especially when chunk ids, graph provenance, safety-review ids, failure records, checkpoints, or ingest logs still encode the source world id.
- `Failure mode:` the duplicate may look healthy at first, then later regress into fake `partial_failure`, show `Resume` or stale failure history, or lose graph/extraction coverage because the copied provenance still points back to the source world.
- `Prevent it by:` treating duplication as a transform, not a raw copy: rewrite every durable world-bound chunk/provenance reference to the target world id, exclude transient runtime ingest artifacts like checkpoints and old logs, and run a post-copy integrity check before finalizing the duplicate as a normal world.
- `Watch for when changing:` world duplication, import/export, backup/restore, ingest audits, chunk-id formats, graph `source_chunks`, safety-review persistence, vector-store record ids, and any workflow that copies world-local state across world ids.

- `Pattern:` Shared SSE helpers can lie about job state if they hardcode one page's terminal-event rules for every stream consumer.
- `What tends to trigger it:` reusing a generic EventSource wrapper across pages whose backends emit non-terminal `error` events, mixed status/event shapes, or stream-specific completion rules.
- `Failure mode:` the UI closes the live stream too early, misses later progress or terminal updates, and can leave users staring at stale progress until a separate refresh happens to succeed.
- `Prevent it by:` keeping terminal detection configurable per stream, basing it on the actual backend contract for that workflow, and surfacing snapshot-refresh failures as stale-state warnings instead of silently trusting old UI state.
- `Watch for when changing:` shared SSE helpers, ingest and entity-resolution progress streams, reconnect/final-refresh flows, and any page that reconciles live events with snapshot fetches.

- `Pattern:` Recovery actions become misleading when button and endpoint eligibility is based on raw failure presence instead of work that the selected recovery path can still act on.
- `What tends to trigger it:` screens that offer `Resume`, `Retry`, or similar ingest recovery actions while some failures have already been handed off to a separate workflow such as the Safety Queue or another manual repair path.
- `Failure mode:` the UI keeps showing recovery actions that immediately reject or do nothing, users loop between unavailable actions, and the real next step is hidden behind a different queue or panel.
- `Prevent it by:` deriving recovery availability from actionable remaining work after subtracting failures already owned by another workflow, and reusing the same eligibility rules in backend guards, checkpoint payloads, summaries, and frontend visibility logic.
- `Watch for when changing:` ingest action gating, checkpoint/resume logic, retry endpoints, failure summaries, Safety Queue status, and any page that mixes raw failure counts with workflow-specific ownership.

- `Pattern:` Summary and detail views for the same workflow can drift into a false empty state when they come from separate data paths and the detail-path failure is silently swallowed.
- `What tends to trigger it:` one screen gets high-level counts from world or checkpoint metadata, but loads the actual item list from a separate endpoint that can fail independently.
- `Failure mode:` the UI shows nonzero summary counts while the main panel says there are no items, making it look like user data disappeared when the detail request actually failed.
- `Prevent it by:` treating the detail fetch as a first-class dependency, surfacing its failure explicitly, and only showing an empty-state message when both summary and detail data agree that the list is truly empty.
- `Watch for when changing:` queue panels, dashboards with summary chips plus detailed tables, snapshot-plus-detail screens, and any page that mixes world metadata with separate per-feature fetches.

- `Pattern:` Minor parser-level formatting damage in backend startup paths can masquerade as catastrophic user-data loss when the frontend silently treats API failure as an empty local state.
- `What tends to trigger it:` automated formatting or hand edits that dedent a single line out of an async method, `try` block, or other import-time code path in modules loaded during app startup.
- `Failure mode:` the backend never finishes booting, worlds/settings endpoints never answer, and the frontend shows an empty world list or blank settings as if saved data disappeared even though the files still exist on disk.
- `Prevent it by:` running a backend compile/import smoke check after edits to startup-critical modules and surfacing backend-load failures explicitly in the UI instead of collapsing them into normal empty states.
- `Watch for when changing:` startup/import wiring, shared backend core modules, launcher verification steps, world-list loading, settings loading, and any empty-state UI that depends on API reachability.

- `Pattern:` Force-graph render-layer types can drift from app-domain graph types when runtime-hydrated link endpoints and library-owned refs are treated like plain stored data.
- `What tends to trigger it:` dynamic imports of graph libraries, hand-rolled ref handles, callback signatures copied from app interfaces, or assuming `link.source` and `link.target` always stay as raw ids instead of sometimes becoming hydrated node objects.
- `Failure mode:` TypeScript starts rejecting valid graph callbacks, endpoint access narrows to `never`, ref methods mismatch the real library contract, and developers are tempted to patch over it with unsafe casts that hide real runtime shapes.
- `Prevent it by:` keeping app-domain node/link interfaces separate from render-layer `NodeObject` and `LinkObject` aliases, normalizing endpoint ids through a helper that accepts ids or hydrated objects, and typing graph refs against the library's actual generic method interface.
- `Watch for when changing:` interactive graph viewers, canvas tooltip/label callbacks, force-layout helpers, dynamic graph imports, ref wiring, and any code that reads `source` or `target` from graph-library links.

- `Pattern:` Provider-scoped settings UIs become misleading when shared cards keep rendering generic controls that do not apply to the resolved provider.
- `What tends to trigger it:` one settings component is reused across Gemini, OpenAI-compatible, IntenseRP, or future providers, but field visibility is driven by slot defaults instead of provider capabilities.
- `Failure mode:` the UI shows fields like a generic `Model`, safety toggle, or reasoning control for a provider path that does not actually use them, so users think a saved setting will affect behavior when the backend ignores it.
- `Prevent it by:` deriving visible controls from the resolved provider capability set for that slot, hiding unsupported settings entirely or replacing them with truthful provider-specific fields, and checking the live UI against real provider routing after refactors.
- `Watch for when changing:` global settings sidebars, provider/model selectors, preset-backed configuration UIs, capability badges, and any shared settings card reused across multiple provider backends.

# Reference: Documentation Map

- Reference for doc locations when suggesting or applying approved documentation updates.
- If a new `.md` file is created and meant to be part of the project’s maintained documentation, note that it should be added to this `Documentation Map`.
- `README.md`: project landing page, high-level overview, and "Where To Read Next" links.
- `CHANGELOG.md`: release history, `Unreleased` work, and versioned user-visible changes.
- `LICENSE`: license text for the open-source codebase.
- `COMMERCIAL.md`: commercial licensing path/terms context.
- `VySol.bat`: Windows launcher behavior and setup flow reference when launcher-facing docs need verification.
- `docs/SETUP.md`: Windows quick start, manual setup, and first-run behavior.
- `docs/WALKTHROUGH.md`: practical user flow: global settings, ingestion setup/workflow/retries, and chat settings.
- `docs/FEATURES.md`: deeper feature explanations (graph provenance, entity resolution, context X-Ray).
- `docs/DIAGRAM.md`: system architecture/flow diagram (Mermaid), expected to grow over time.
- `docs/walkthrough/google-ai-studio-api-keys.md`: child guide for obtaining and safely using Google AI Studio API keys.
- `docs/assets/branding/`: branding assets referenced by docs and README.
- `backend/.env.example`: backend environment-variable example and setup reference.
- `frontend/.env.local.example`: frontend environment-variable example and setup reference.
- `pytest.ini`: local test-runner behavior reference when test instructions change.
- `AGENTS.md`: assistant behavior rules and safety/process guardrails.

# Reference: Brand Color Reference

- Source of truth: `frontend/app/globals.css` CSS variables.
- Light mode is the canonical brand palette and should be treated as the primary brand identity.
- Light mode colors:
- Main: `#0892d0` (`--primary`)
- Secondary: `#ffffff` (`--background`)
- Accent: `#1b2430` (`--text-primary`)
- Dark mode colors:
- Main: `#7c3aed` (`--primary`)
- Secondary: `#0f0f0f` (`--background`)
- Accent: `#a78bfa` (`--primary-light`)
