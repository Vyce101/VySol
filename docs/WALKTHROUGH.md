# Walkthrough

## Settings Walkthrough

Open the settings sidebar from the home screen before you ingest your first world.

### Configuration And Key Library

The global settings drawer now has two top-level tabs:

- `Configuration`: preset-backed global behavior
- `Key Library`: shared provider credentials for the whole app

Presets:

- The shipped `Default` preset is locked
- Locked means it stays the baseline preset name and cannot be renamed
- `Save As New Preset` clones the current Configuration into a new editable preset
- Switching the preset dropdown applies immediately
- Edits in `Configuration` auto-save into the active preset
- `Key Library` is not part of presets

Key Library:

- Use the provider dropdown to manage Gemini, Groq, IntenseRP Next, and any future providers the app knows about
- Credential entries are shared across all presets for that provider
- Gemini and Groq entries store API keys
- IntenseRP Next stores a base URL instead of an API key
- Saved entries stay stored even when you toggle them off
- Only enabled and fully filled entries join the live provider pool

Fallback behavior:

- If no ready Gemini library entry is enabled, VySol can still fall back to `GEMINI_API_KEY`
- If no ready Groq library entry is enabled, VySol can still fall back to `GROQ_API_KEY`
- If no ready IntenseRP entry is enabled, VySol can still fall back to `INTENSERP_BASE_URL`

Key Rotation Mode:

- `Fail Over`: keeps using the current provider key until it hits a rate limit, then moves to the next one
- `Round Robin`: rotates across that provider's enabled keys to spread load more evenly

Provider status dots:

- Each provider-backed row in `Configuration` shows a status dot
- A red dot means the selected provider is missing required shared credentials or is not supported for that slot
- Hovering the dot explains the exact problem, such as missing Groq keys or an unsupported embedding backend

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
- Default Embedding Provider: `Google (Gemini)`
- Default Embedding Model: `gemini-embedding-2-preview`

Provider family rows:

- Graph Architect, Chat, Entity Chooser, Entity Combiner, and Default Embeddings each have their own provider row
- `Google (Gemini)` is available for all shipped text slots and embeddings
- `OpenAI-compatible` opens a second provider dropdown underneath it; `Groq` is the only implementation provider in this build
- `IntenseRP Next` remains a separate chat-only provider option

What Groq supports right now:

- Chat
- Graph Architect
- Entity Chooser
- Entity Combiner

What Groq does not support in this build:

- Embeddings
- Gemini-only safety controls
- Gemini-only thinking controls

Graph Architect Model:

- This is the extraction model used to turn text chunks into entities and relationships
- Lighter, faster models usually work best here because ingestion can make many calls
- A Gemini Flash-class model is a good fit for most users

Gemini thinking:

- Gemini model rows now show a `Thinking` control next to the model field
- If the current model name matches a supported Gemini 3 family, VySol shows a built-in dropdown instead of a free-text field
- `Gemini 3.1 Pro` supports `low`, `medium`, and `high`
- `Gemini 3.1 Flash-Lite` supports `minimal`, `low`, `medium`, and `high`
- `Gemini 3 Flash` supports `minimal`, `low`, `medium`, and `high`
- Leaving the dropdown blank means `use the model's provider default`
- Known Gemini catalog models that do not support a built-in thinking dropdown now show a visible unsupported note instead of silently hiding the row
- Custom or unknown Gemini model ids get an advanced manual thinking field because VySol cannot truthfully infer their supported presets

Groq reasoning:

- Groq model rows resolve reasoning support per model, not just per provider
- `openai/gpt-oss-20b` and `openai/gpt-oss-120b` show `low`, `medium`, and `high`
- `qwen/qwen3-32b` shows `none` plus `Reasoning On (provider default)`, which keeps the provider's own default distinct from VySol's blank `Use model default` state
- Known Groq catalog models without reasoning support show a visible unsupported note instead of silently hiding the row
- Custom or unknown Groq model ids get an advanced manual reasoning field because VySol cannot safely infer their supported presets
- The setting is still stored per Groq-backed slot, but VySol now ignores stale saved reasoning values when the currently selected model does not support them
- Chat also gets a Groq-only `Include Reasoning` toggle
- VySol does not fake live thought-token streaming for Groq; if reasoning is returned, it is attached after the reply completes

Chat providers:

- `Google (Gemini)` uses the normal Gemini chat model field and Gemini key pool
- `OpenAI-compatible > Groq` uses the Groq key pool from `Key Library`
- `IntenseRP Next` lets you point chat at a local IntenseRP-compatible endpoint instead

IntenseRP Next:

- GitHub: [LyubomirT/intense-rp-next](https://github.com/LyubomirT/intense-rp-next)
- This path is optional
- You add the endpoint URL in `Key Library`
- No API key is required by VySol for this provider path
- Extraction, entity resolution, and embeddings do not use IntenseRP Next
- Using IntenseRP Next and any provider behind it is subject to that provider's own terms of service

Chat Model:

- This is the model used to answer chat requests

Entity Chooser Model:

- This is the entity-resolution model that decides which candidate entities are actually the same entity as the current anchor entity

Entity Combiner Model:

- After the chooser selects matching entities, the combiner rewrites the merged result
- It chooses the best final display name and creates one final description from the chosen group

Default Embedding Model:

- This is the default embedding model for new worlds when the embedding provider is `Google (Gemini)`
- The shipped default is `gemini-embedding-2-preview`
- VySol also stores an embedding provider, both globally and per world
- If you switch embeddings to `OpenAI-compatible > Groq`, the UI tells the truth and blocks ingest/re-embed because Groq embeddings are not available in this build

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
- The embedding slot does not use Gemini thinking controls in VySol

Gemini safety:

- `Disable Safety Filters` is Gemini-only
- It appears only when one of the selected model rows is using Gemini
- Groq and IntenseRP do not show a fake safety toggle in Configuration

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
- World embedding provider
- World embedding model
- Graph Architect glean amount

Shipped defaults:

- Chunk size: `4000`
- Chunk overlap: `150`
- World embedding provider: `Google (Gemini)`
- World embedding model: `gemini-embedding-2-preview`
- Graph Architect glean amount: `1`

What they mean:

- Chunk Size:
  How much text goes into each chunk before ingestion splits it
- Chunk Overlap:
  How much trailing context is carried into the next chunk to solve pronoun/entity name problems
- World Embedding Provider:
  Which provider family and implementation provider new vectors should use for that world
- World Embedding Model:
  The embedding model used for that world's vectors
- Graph Architect Glean Amount:
  Extra extraction passes that try to catch additional graph details after the first pass

Important behavior:

- Brand-new worlds can edit settings and prompts inline before the first ingest starts
- Once a world has resumable or completed ingest history, the main page returns to a read-only snapshot of the world's saved settings and effective prompts
- Clicking the small settings icon next to `Re-ingest` opens the editable world-specific setup popup for rebuilds
- Starting either the first ingest or `Re-ingest` with edited values saves those settings as the world's new defaults
- If the selected world embedding provider is not actually available yet, such as `OpenAI-compatible > Groq` in this build, ingest and `Re-embed All` are blocked with a truthful explanation instead of pretending the provider works

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
- `Exact only` now runs as `exact match scan -> exact winner embedding -> exact apply`
- Only the changed winners from that run are re-embedded; untouched entities are left alone

## Ingestion Flow

Basic flow:

1. Add one or more `.txt` files.
2. Expand `Books in This World` if you want to review the current source list from the left column.
3. For a brand-new world, review and edit the inline `Ingestion Setup` panel before starting the first run.
4. Click `Start Ingestion` for a brand-new world, `Resume` for pending/resumable work, or `Re-ingest` for a full rebuild.
5. After a world has ingest history, use the `Re-ingest` popup from the settings icon next to `Re-ingest` when you want different chunk settings or world-specific prompt changes for a rebuild.

Reading the ingest progress header:

- The ingest page now boots from a lightweight runtime summary, so the world status, counters, and resume state can appear before heavier audit data finishes loading
- The main ingest header now stays stable at the world level instead of flipping between extraction and embedding worker events
- `Chunks Extracted` means chunks whose graph extraction has been durably written
- `Chunks Embedded` means chunks whose chunk vectors have been durably written
- `Unique Graph Nodes` means the current unique nodes in the saved graph
- `Embedded Unique Nodes` means how many current unique graph nodes still have matching embeddings in the unique-node index
- Per-chunk embedding completion now reports only chunk-vector completion; unique-node vector totals are reported later by the world-level rebuild phase instead of falsely claiming `0 node vectors` mid-run
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

Abort behavior:

- `Abort` is a soft cancel: VySol stops waiting on slow model and embedding responses as soon as it can and moves the run toward `Aborting` and then `Aborted`
- Late provider responses from an aborted run are ignored instead of being allowed to write graph data, vectors, checkpoints, or misleading SSE progress after the stop request

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
- A top-level `Retry All Safety Queue` action can batch unresolved items that have not fully passed yet, using the current draft text for editable items
- Its batch size and delay settings apply only to that bulk retry run, and locked items are reported and skipped instead of being silently rewritten

Entity-resolution controls:

- `Resolution mode` chooses whether the run stops after exact normalized matching or continues into chooser/combiner review
- `Exact only` is available when the current graph's unique-node coverage is trustworthy, even if some unrelated chunk-level ingest failures still exist
- `Exact + chooser/combiner` stays locked until the world is fully healthy
- Exact-only now runs in three main phases: scan exact groups, embed the changed winners, then apply the embedded exact batches
- Completed embedded batches are committed live during the run instead of waiting for one giant final exact-only swap
- `Resume Resolution` appears when a previous run already committed some work and still has pending exact or AI merges left to finish
- `Complete` now means no pending exact or AI work remains
- If entity resolution fails, the run now reports the backend reason instead of a generic stream disconnect, keeps already committed embedded merges, and leaves the unfinished remainder resumable when possible
- `Top K candidates` is used only for `Exact + chooser/combiner`
- `Embedding batch size` controls entity resolution's changed-winner embedding batches for exact winners and later AI winners
- `Embedding delay (seconds)` adds a per-batch cooldown to that same changed-winner embedding step
- The embedding controls apply to entity resolution only; they do not change ingest or `Re-embed All`
- When Gemini embedding throttles entity resolution, the status can now explicitly show that it is waiting for embedding API cooldown instead of just appearing hung
- The entity-resolution status panel now shows `Embedded N / N` against the winners being embedded for that run, not the raw pre-merge extraction total
- Exact-only summaries now label unresolved exact-pass leftovers as `Left Unchanged`

## Rebuild And Retry Actions

Use the rebuild and retry actions based on what went wrong:

`Re-embed All`

- Clears and rebuilds chunk vectors from the previously fully ingested source set and unique-node vectors from the current saved graph state
- Ignores brand-new pending sources you added after the last clean ingest
- Is blocked if an older ingested source is missing, changed, partial, failed, or comes from an older world that never recorded source snapshots
- Uses active repaired chunk bodies when the locked source snapshot and chunk map still match
- Is blocked while this world still has unresolved safety-review work, because the rebuild would otherwise operate on incomplete repair state
- During the final full unique-node rebuild, VySol stages the replacement node-vector collection and swaps it into place only after the rebuild succeeds, so aborting there does not leave the live node-vector index half-written
- Use this when you change only the world embedding provider/model or need to rebuild vectors without re-extracting the graph

`Re-ingest`

- Fully rebuilds chunks, extraction, graph data, and vectors using the world's currently saved ingest settings and world-specific prompt overrides
- The main `Re-ingest` button uses the saved settings exactly as shown in the read-only snapshot on the ingest page
- The small settings icon next to `Re-ingest` opens a popup where you can edit chunk settings, embedding provider/model, glean amount, and the world-local ingest/entity-resolution prompts before starting the rebuild
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
- `Retry All Safety Queue` is separate from `Retry All Failures`: it reruns unresolved queue items that still need repair work, and it is blocked while a live ingest run is active

## Chat

Open a world, create a new chat, and use the right-side retrieval settings to tune behavior.

The retrieval sidebar is grouped into collapsible sections. All sections start collapsed, and you can open more than one at a time:

`General Settings`

`Provider-specific extras`

- `Send Thinking` appears only when the chat provider is `Google (Gemini)`
- It is `on` by default in the shipped app defaults
- Turning it on asks Gemini to include thought content when the chosen model and provider path support it
- When Gemini returns thought content, VySol saves it with the message and renders a collapsible `Model Thinking` block above the normal reply text
- `Include Reasoning` appears only when the chat provider is `OpenAI-compatible > Groq`
- Turning it on asks Groq for reasoning when that model/provider path supports it
- Groq reasoning, when returned, is attached after the reply instead of streaming as live thought tokens
- `IntenseRP Next` shows neither of these provider-specific toggles

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
- VySol applies the cap after graph candidates are ranked, so lowering the cap keeps the highest-relevance reachable nodes instead of changing the walk order arbitrarily
- Actual returned graph size can still be lower if the selected entry nodes simply do not reach that many unique nodes

`Max Neighbors Per Node`

- Caps each kept node's final retained neighbors in the retrieved context graph
- The cap applies after final node selection, not during discovery
- VySol keeps only mutual top-N retained connections, so no node in the final `Context Graph` should end up above that cap

`Max Node Description (Chars)`

- Caps each retrieved node description before prompt context is assembled
- The truncation happens before the final context size is counted
- `0` disables the per-node description cap

`Context Limit (Chars)`

- Lives under `General Settings`
- If the final built retrieval context is larger than this limit, VySol does not send the request to the model
- Instead, VySol saves a normal model-side reply explaining that the request was skipped because the retrieval context exceeded the limit
- `0` disables the overall context limit

`Prompt`

`Chat System Prompt`

- The system-level instruction that shapes how the model answers in chat
