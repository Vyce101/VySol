# Walkthrough

## Settings Walkthrough

Open the settings sidebar from the home screen before you ingest your first world.

### API Keys

- Only Gemini API keys are supported in VySol's built-in key management flow
- Click the `+` button to add each key
- Saved keys stay stored in Settings even when you toggle them off
- Only active saved keys participate in key rotation
- If every saved key is inactive, VySol can still fall back to `GEMINI_API_KEY` from your local environment

Key Rotation Mode:

- `Fail Over`: keeps using the current key until it hits a rate limit, then moves to the next one
- `Round Robin`: rotates across keys to spread load more evenly

Per-key toggle behavior:

- `ON` means the key is active and eligible for rotation
- `OFF` means the key stays saved on disk but is skipped by `Fail Over` and `Round Robin`
- The Settings sidebar shows how many keys are active versus how many are stored

Cooldown behavior:

- If all active Gemini keys are temporarily cooling down, VySol can wait and continue when a key becomes available again instead of always failing immediately
- During ingest, this appears as `Waiting for API key cooldown`

Need help getting a Google AI Studio key?

- See [How To Get Google AI Studio API Keys](walkthrough/google-ai-studio-api-keys.md)

### Ingestion Performance

These settings are global and separate graph extraction from embedding so one stage does not slow the other down unnecessarily.

- Graph Extraction Batch Size:
  the number of extraction slots that can run at the same time
- Graph Extraction Slot Delay:
  how long that extraction slot waits after finishing before it can take another item
- Embedding Batch Size:
  the number of embedding slots that can run at the same time
- Embedding Slot Delay:
  how long that embedding slot waits after finishing before it can take another item

Important behavior:

- Batch size is parallel slots, not a wait-for-all barrier
- Slot delay starts the moment that individual slot finishes
- Each slot cools down independently

### AI Models

Shipped defaults:

- Graph Architect Model: `gemini-3.1-flash-lite-preview` with `minimal` thinking
- Chat Model: `gemini-3-flash-preview` with `high` thinking
- Entity Chooser Model: `gemini-3.1-flash-lite-preview` with `high` thinking
- Entity Combiner Model: `gemini-3.1-flash-lite-preview` with `high` thinking
- Default Embedding Model: `gemini-embedding-2-preview`

Graph Architect Model:

- This is the extraction model used to turn text chunks into entities and relationships
- Lighter, faster models usually work best here because ingestion can make many calls
- A Gemini Flash-class model is a good fit for most users

Thinking:

- Gemini model rows now show a `Thinking` control next to the model field
- If the current model name matches a supported Gemini 3 family, VySol shows a built-in dropdown instead of a free-text field
- `Gemini 3.1 Pro` supports `low`, `medium`, and `high`
- `Gemini 3.1 Flash-Lite` supports `minimal`, `low`, `medium`, and `high`
- `Gemini 3 Flash` supports `minimal`, `low`, `medium`, and `high`
- Leaving the dropdown blank means `use the model's provider default`

Chat Provider:

- `Google (Gemini)` uses the normal Gemini chat model field (uses API keys from Google AI Studio)
- `IntenseRP Next` lets you point chat at a local IntenseRP-compatible endpoint instead

IntenseRP Next:

- GitHub: [LyubomirT/intense-rp-next](https://github.com/LyubomirT/intense-rp-next)
- This path is optional
- You must enter the endpoint URL yourself
- No API key management is built into VySol for this provider path
- Extraction, entity resolution, and embeddings still follow the Gemini-side model and key flow
- Using IntenseRP Next and any provider behind it is subject to that provider's own terms of service

Chat Model:

- This is the model used to answer chat requests

Entity Chooser Model:

- This is the entity-resolution model that decides which candidate entities are actually the same entity as the current anchor entity

Entity Combiner Model:

- After the chooser selects matching entities, the combiner rewrites the merged result
- It chooses the best final display name and creates one final description from the chosen group

Default Embedding Model:

- This is the default embedding model for new worlds
- The shipped default is `gemini-embedding-2-preview`

Unsupported Gemini models and manual thinking entry:

- If you type a Gemini model name that does not match one of VySol's built-in Gemini 3 dropdown families, the `Thinking` row shows `Built-in thinking dropdown not supported`
- Click the pencil button to open the manual thinking field for that model slot
- Enter only one raw value in that field
- If you enter digits only, such as `512` or `1024`, VySol sends that as a Gemini `thinkingBudget`
- If you enter text, such as `high`, `medium`, or another provider-documented level name, VySol sends that as a Gemini `thinkingLevel`
- Do not type wrappers such as `thinking.thinkingLevel=high`, `thinkingBudget=1024`, `level: high`, or JSON
- Good manual examples: `high`, `medium`, `minimal`, `1024`
- Bad manual examples: `thinkingLevel=high`, `thinking.thinkingLevel=high`, `{ "thinkingLevel": "high" }`
- If you are unsure what values a custom Gemini model accepts, check that model family's provider docs first and then enter only the final raw value VySol should send
- The default embedding model does not support thinking controls in VySol

Disable Safety Filters:

- This relaxes Gemini content moderation behavior for creative or edge-case writing workflows

## Creating A World

1. Click `Create World`.
2. Give the world a name.
3. Upload source files.

Supported source format:

- `.txt` only

For most casual use cases, the defaults are already more than enough.

## Duplicating A World

You can duplicate a world from the home page overflow menu.

What gets copied:

- World settings and saved ingest snapshot
- Source files and graph data
- Chats
- Safety-review data and repaired-chunk overrides
- Chunk vectors and unique-node vectors

Important behavior:

- A duplicate starts as a temporary preview card on the home page
- The bottom-right world activity panel shows duplication progress while the copy runs
- The temporary duplicate card is not openable until validation finishes
- Copied chats become independent files inside the new world, so continuing a chat in the duplicate does not change the original world's chat
- VySol does not carry over transient runtime ingest state like old resume/checkpoint state or old ingest logs
- If the app or backend crashes before duplication finishes, the incomplete duplicate is discarded and you must start duplication again manually

## Ingestion Settings

Brand-new worlds now show an inline `Ingestion Setup` editor on the main ingest page before the first run starts.

After a world has ingest history, the main ingest page switches back to a read-only snapshot and editable settings move into the `Re-ingest` popup.

That popup lets you change:

- Chunk size
- Chunk overlap
- World embedding model
- Graph Architect glean amount

Shipped defaults:

- Chunk size: `4000`
- Chunk overlap: `150`
- World embedding model: `gemini-embedding-2-preview`
- Graph Architect glean amount: `1`

What they mean:

- Chunk Size:
  How much text goes into each chunk before ingestion splits it
- Chunk Overlap:
  How much trailing context is carried into the next chunk to solve pronoun/entity name problems
- World Embedding Model:
  The embedding model used for that world's vectors
- Graph Architect Glean Amount:
  Extra extraction passes that try to catch additional graph details after the first pass

Important behavior:

- Brand-new worlds can edit settings and prompts inline before the first ingest starts
- Once a world has resumable or completed ingest history, the main page returns to a read-only snapshot of the world's saved settings and effective prompts
- Clicking the small settings icon next to `Re-ingest` opens the editable world-specific setup popup for rebuilds
- Starting either the first ingest or `Re-ingest` with edited values saves those settings as the world's new defaults

## Prompt Snapshot

Brand-new worlds can edit prompt overrides inline before the first ingest starts.

After the first ingest, the main page shows a read-only `Prompt Snapshot`, and rebuild-time prompt edits move to the `Re-ingest` popup.

Graph Architect Prompt:

- Controls how the extraction model turns text into entities and relationships
- Receives the chunk body plus any overlap as separate inputs, so overlap is reference-only context instead of part of the extractable body

Graph Architect Glean Prompt:

- Controls how later extraction passes continue after the first graph pass
- Lets you tune how the glean step uses previously extracted entities and relationships to find missed graph details

Entity Resolution Chooser Prompt:

- Controls how strictly the chooser decides whether two entities are really the same thing

Entity Resolution Combiner Prompt:

- Controls how chosen duplicate entities are merged into one final name and description

Prompt precedence:

- World override
- Global custom prompt from Settings
- Shipped default prompt

Important:

- The chooser and combiner prompts matter only when you run `Exact + chooser/combiner`
- `Exact only` does not call either model stage
- `Exact only` still needs to rebuild the unique-node index before the run is complete

## Ingestion Flow

Basic flow:

1. Add one or more `.txt` files.
2. Expand `Books in This World` if you want to review the current source list from the left column.
3. For a brand-new world, review and edit the inline `Ingestion Setup` panel before starting the first run.
4. Click `Start Ingestion` for a brand-new world, `Resume` for pending/resumable work, or `Re-ingest` for a full rebuild.
5. After a world has ingest history, use the `Re-ingest` popup from the settings icon next to `Re-ingest` when you want different chunk settings or world-specific prompt changes for a rebuild.

Reading the ingest progress header:

- The main ingest header now stays stable at the world level instead of flipping between extraction and embedding worker events
- `Chunks Extracted` means chunks whose graph extraction has been durably written
- `Chunks Embedded` means chunks whose chunk vectors have been durably written
- `Unique Graph Nodes` means the current unique nodes in the saved graph
- `Embedded Unique Nodes` means how many current unique graph nodes still have matching embeddings in the unique-node index
- After chunk work finishes, world-level progress can continue through `unique_node_rebuild` and `audit_finalization` before the run is actually done
- `World Blockers` highlights graph/vector audit problems that are not tied to a single chunk and therefore do not belong under `Failed Records`
- Each source row in `Books in This World` now also shows `Embedded X / Y`, where `X` is the number of chunks from that source whose embeddings are fully finished and `Y` is that source's total chunk count

Important note about node counts:

- `Unique Graph Nodes` and `Embedded Unique Nodes` reflect the current merged graph state, not raw per-chunk extraction totals
- Those counts can change after entity resolution merges duplicate entities and refreshes unique-node embeddings
- A current node can still count as missing here if its old vector row exists but no longer matches the node's current merged text

Wait states during ingest:

- `Queued for extraction slot` means extraction workers are busy and this run is waiting for an extraction slot
- `Queued for embedding slot` means embedding workers are busy and this run is waiting for an embedding slot
- `Waiting for API key cooldown` means the active Gemini key pool is temporarily cooling down and the run is waiting to continue
- Short pauses in these states are normal and do not automatically mean the ingest failed

After ingestion finishes:

1. Click `Resolve Entities`.
2. Pick a run mode: `Exact only` for a fast normalized-name cleanup pass, or `Exact + chooser/combiner` for the full duplicate-resolution workflow.
3. Let entity resolution run.

If extraction hits a safety block:

- The ingest log warns you as soon as the block is detected
- Use the `Safety Queue` button in the left control column to open the blocked-chunk workspace on the same page
- Each review item keeps a read-only `[B#:C#]` prefix, a separate read-only overlap box when overlap exists, and one editable `Chunk Body` field
- `Test` retries that exact chunk with your edited chunk body while keeping the original source chunk untouched
- If you intentionally clear the editable `Chunk Body`, that blank body is now tested as-is instead of silently snapping back to the old chunk text
- If overlap exists and the body is blank, the test uses that overlap-only context instead of secretly retesting the original chunk body
- `Reset to Original` always restores the true original source chunk, even after multiple edits or a prior successful repair
- `Reset to Live` restores the currently live repaired chunk text when that item already has a passed live repair
- A passed blank repair still counts as a real live repaired chunk, so `Reset to Live` and later rebuild/reuse flows continue to treat it as the active repaired version
- If a retest fails after a previous repair already passed, the world keeps using that last live repaired chunk until a newer test fully passes
- `Reset Chunk` deletes the live ingest data for that chunk and keeps the item in the Safety Queue so the chunk can be rebuilt truthfully
- `Reset Chunk` removes that chunk's live chunk vector, chunk-scoped graph artifacts, and other chunk-level ingest state instead of pretending the problem is gone
- If the world already completed entity resolution, `Reset Chunk` warns when merged entity descriptions may still include information that came from that chunk
- In that case, the queue item cannot directly discard those already-merged entity descriptions; use `Re-ingest` if you need those merged descriptions rebuilt cleanly too

Entity-resolution controls:

- `Resolution mode` chooses whether the run stops after exact normalized matching or continues into chooser/combiner review
- Exact-only still rebuilds the unique-node index before it reports success
- `Complete` now means the merge result and the unique-node index refresh both committed successfully
- If entity resolution fails, the run now reports the backend reason instead of a generic stream disconnect and avoids keeping partial live merges
- `Top K candidates` is used only for `Exact + chooser/combiner`
- `Embedding batch size` controls unique-node embedding rebuild batch size for that entity-resolution run
- `Embedding delay (seconds)` adds a per-batch cooldown to that same unique-node embedding rebuild step
- The embedding controls apply to entity resolution only; they do not change ingest or `Re-embed All`
- The entity-resolution status panel now shows `Embedded N / N` during the unique-node index rebuild, using the post-merge unique-node total instead of the raw pre-merge extraction total
- Exact-only summaries now label unresolved exact-pass leftovers as `Left Unchanged`

## Rebuild And Retry Actions

Use the rebuild and retry actions based on what went wrong:

`Re-embed All`

- Clears and rebuilds chunk vectors from the previously fully ingested source set and unique-node vectors from the current saved graph state
- Ignores brand-new pending sources you added after the last clean ingest
- Is blocked if an older ingested source is missing, changed, partial, failed, or comes from an older world that never recorded source snapshots
- Uses active repaired chunk bodies when the locked source snapshot and chunk map still match
- Is blocked while this world still has unresolved safety-review work, because the rebuild would otherwise operate on incomplete repair state
- Use this when you change only the world embedding model or need to rebuild vectors without re-extracting the graph

`Re-ingest`

- Fully rebuilds chunks, extraction, graph data, and vectors using the world's currently saved ingest settings and world-specific prompt overrides
- The main `Re-ingest` button uses the saved settings exactly as shown in the read-only snapshot on the ingest page
- The small settings icon next to `Re-ingest` opens a popup where you can edit chunk settings, glean amount, embedding model, and the world-local ingest/entity-resolution prompts before starting the rebuild
- Each prompt in that popup opens in its own collapsible section so you can expand only the prompt you want to edit
- Starting `Re-ingest` from that popup saves those values as the world's new saved settings and prompt overrides
- If this world has repaired chunk overrides, `Re-ingest` can optionally reuse them when chunk size and overlap stay the same

`Retry All Failures`

- Retries both failed extraction and failed embedding work
- Also skips unresolved Safety Review Queue chunks and leaves those to the review flow
- Only appears when the world is idle and `Failed Records` is greater than `0`
- World-level blockers are shown separately, so a missing `Retry All Failures` button does not mean the world is automatically healthy if the header still shows `World Blockers`

Important behavior:

- `Resume` is the normal path when you simply add another new source after a previous ingest
- If the failure-help box appears, the normal order is `Resume` -> `Retry All Failures` -> `Add failed chunks to Safety Queue` -> `Fix Safety Queue`
- `Resume` only appears when there is still non-Safety-Queue ingest work left to run; if only Safety Queue items remain, keep working there instead
- When you add or remove pending sources, the ingest action area now refreshes immediately so `Resume`, `Re-ingest`, and completion state stay in sync without leaving the page
- `Re-embed All` is intentionally narrower than a full rebuild and will now explain when it is unsafe
- `Re-embed All` can reuse active repaired chunk bodies when its locked-source checks still pass
- `Re-ingest` can also reuse repaired chunk bodies, but only when chunk size and overlap stay the same and you leave repaired-chunk reuse enabled
- `Retry All Failures` only appears when there are actual failed records outside the Safety Queue to retry, so no button can also mean the remaining failures already belong to the Safety Queue
- `Retry` actions only repair failures inside the currently locked ingest; they do not apply new chunk settings
- `Add failed chunks to Safety Queue` is a manual fallback for stubborn extraction failures that still need repair work after `Resume` and `Retry All Failures`
- That action is only for the current world and current failed chunks; it moves those failed chunks into the Safety Queue for editing and does not teach future ingests to always treat them as safety-blocked

## Chat

Open a world, create a new chat, and use the right-side retrieval settings to tune behavior.

The retrieval sidebar is grouped into collapsible sections. All sections start collapsed, and you can open more than one at a time:

`General Settings`

`Send Thinking`

- This toggle appears only when the chat provider is `Google (Gemini)`
- It is `on` by default in the shipped app defaults
- Turning it on asks Gemini to include thought content when the chosen model and provider path support it
- When Gemini returns thought content, VySol saves it with the message and renders a collapsible `Model Thinking` block above the normal reply text
- Turning it off keeps normal replies and skips requesting thought content from Gemini
- This toggle does not affect `IntenseRP Next`

`Vector Query (Msgs)`

- How many recent messages are used to build the retrieval search vector

`Chat History Context (Msgs)`

- How many previous chat messages are sent as chat history context

`Chunk Settings`

`Top K Chunks`

- How many standard chunk matches are sent into chat context

`Graph Settings`

`Entry Nodes`

- How many graph entry nodes are selected before graph expansion begins
- Entry-node retrieval now ranks against one persistent vector per current graph node, not repeated chunk-local node occurrences

`Graph Hops`

- How far the graph expansion walks outward from the selected entry nodes

`Max Graph Nodes`

- A hard cap on how many graph nodes can be included
- Actual returned graph size can still be lower if the selected entry nodes simply do not reach that many unique nodes

`Prompt`

`Chat System Prompt`

- The system-level instruction that shapes how the model answers in chat
