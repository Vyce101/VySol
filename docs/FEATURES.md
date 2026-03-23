# Features

## Graph Provenance

Every edge extracted into the graph is temporally indexed to its source document and chunk as BN:CN with the N' being numbers.

Each document completed during ingestion is assigned a book number, starting at 1 and incrementing in input order. Chunk numbering resets on every document completion.

This means every relationship in the graph carries:

- Which book it came from
- Which chunk within that book it came from

What this gives you:

- Full source traceability for any extracted relationship
- The ability to see when a relationship was first established across a multi-document ingest
- A foundation for spotting contradictions between sources
- Auditability for workflows where knowing the origin of extracted information matters
- An AI model with better temporal understanding

## How Entity Resolution Works

Entity resolution now has two run modes.

`Exact only`

- Runs the normalized-name pass only
- Auto-resolves obvious duplicates without spending chooser or combiner model calls
- Still rebuilds the unique-node index before the run is considered complete
- This is now the default mode for fresh and idle worlds

`Exact + chooser/combiner`

- Starts with the same normalized exact pass
- Then builds a Top K candidate list for each remaining anchor entity with vector search
- The chooser model decides which candidates are actually the same entity as the anchor
- The combiner model merges the chosen group into one canonical result
- All entities that were merged are removed from the remaining list
- Repeat until the unresolved list is exhausted

Important behavior:

- Exact-only runs never enter candidate search, chooser, or combiner phases
- Both run modes still need a successful unique-node index refresh before their results are finalized
- Entity resolution now stages graph and unique-node-index changes first and only commits them live after the full run succeeds
- If a chooser, combiner, embedding, or finalization step fails, the run now reports a real error instead of silently degrading or leaving partial live merges behind
- Exact + chooser/combiner runs still preserve temporal graph edges while merging entities
- Older data that predates the new run-mode field still maps safely to the previous behavior for historical status display instead of being relabeled to the new default
- Every run now also exposes unique-node embedding batch and delay controls for the index rebuild step used by entity resolution
- Those embedding controls affect only entity resolution's unique-node rebuild path, not chooser/combiner model calls and not normal ingestion

## Context X-Ray

Every chat message saves a full record of exactly what was sent to the model.

Context X-Ray lets you open any message and see:

- The system prompt
- Entry nodes selected for graph expansion
- All nodes and edges included in context
- RAG chunks retrieved
- Chat history sent
- The exact sent-context graph for newer messages

Each record has two views:

- Byte View: the exact raw content sent, nothing hidden or reformatted
- Clean View: a readable formatted version of the same data

Newer messages also include a `Context Graph` view.

- It shows the exact node-and-edge graph that was sent in that message's context
- It uses the same core graph interactions as the main graph view, including pan, zoom, node click, and hover details
- It is built from the same real context records the model actually saw, without fake-merging different nodes just because they share a display name
- It preserves duplicate display names when those names belong to different real graph nodes
- It marks entry nodes separately from graph-expanded nodes so you can see which nodes seeded graph expansion
- Older messages that predate graph capture continue to show the text/X-Ray views without attempting a live reconstruction

X-Ray records are saved per message so you can go back and inspect any point
in a conversation, not just the most recent one.

## Unique Node Retrieval

Chat retrieval now uses two persistent vector indexes:

- One vector per chunk for RAG chunk retrieval
- One vector per current graph node for entry-node retrieval

This means `Entry Nodes` now refer to real unique graph entities instead of repeated `(chunk, node)` occurrences.

Important behavior:

- A repeated entity that appears in many chunks no longer crowds out other entry candidates just because it had many chunk-local node records
- `Re-embed All` rebuilds chunk vectors from the saved chunks and rebuilds unique node vectors from the current saved graph state
- In `Exact + chooser/combiner`, the unique-node index is rebuilt immediately after the exact pass and then incrementally refreshed after later AI merges
- Existing worlds can migrate to this retrieval model by running `Re-embed All` once; world recreation is not required

## World Duplication

VySol can duplicate a world from the home page while keeping the copy crash-safe.

Important behavior:

- Duplication creates a new world id and a new world folder instead of linking the duplicate back to the source world
- Chats are copied into the duplicate world's own `chats` folder, so editing or continuing a copied chat in the duplicate does not modify the original world's chat history
- The home page shows a temporary duplicate preview card while the copy is running
- The floating bottom-right world activity panel shows duplication progress alongside other world activity
- VySol copies durable world state such as sources, graph data, safety-review state, repaired-chunk overrides, chunk vectors, and unique-node vectors
- VySol does not carry over transient runtime ingest artifacts such as old checkpoints or old ingest logs
- World-bound chunk provenance is rewritten to the new world id before the duplicate is finalized, so the copied world does not inherit fake extraction-coverage failures from the source world's chunk ids
- A post-copy ingest-integrity validation pass runs before the duplicate becomes a normal world
- If the app or backend crashes before duplication completes, the unfinished duplicate is discarded instead of resuming automatically later

## Ingest Rebuild Safety

VySol now treats `Re-embed All` as a narrow vector-maintenance operation and uses one clearer full rebuild action: `Re-ingest`.

Important behavior:

- `Re-embed All` only runs against sources that were already fully ingested in the current world
- Newly added pending sources are ignored by `Re-embed All`; use `Resume` to ingest those
- `Re-embed All` is blocked if a previously ingested source is missing, changed, partially ingested, failed, or comes from an older world that predates stored source snapshots
- `Re-embed All` reuses active repaired chunk bodies when the locked source snapshot and chunk map still match, so repaired text stays aligned with rebuilt vectors
- `Re-ingest` is now the single full rebuild path for chunks, extraction, graph data, and vectors
- Brand-new worlds now expose an inline first-run setup editor on the main ingest page so users can change chunk settings, glean amount, embedding model, and ingest/entity-resolution prompts before the first ingest starts
- After a world has ingest history, the main ingest page keeps the current world's ingest settings and prompt values as a read-only snapshot
- A `Re-ingest` popup on the main ingest page lets you edit those same world-local settings and prompts before starting a rebuild
- Each prompt editor in that popup is collapsible so you can expand only the prompt you need
- Starting either the first ingest or `Re-ingest` with edited values saves those values as the world's new saved defaults before the run begins
- If repaired chunk overrides exist, `Re-ingest` can optionally reuse them, but only when chunk size and overlap stay the same

## Stable Ingest Progress

VySol now shows ingestion progress as a stable world-level summary instead of letting the header bounce between whichever worker reported activity last.

Important behavior:

- `Chunks Extracted` tracks chunks whose graph extraction has been durably written
- `Chunks Embedded` tracks chunks whose chunk-vector embedding has been durably written
- `Unique Graph Nodes` tracks the current unique nodes in the saved graph
- `Embedded Unique Nodes` tracks how many current unique graph nodes still have matching embeddings in the unique-node index
- World-level vector rebuild work now has its own progress phases, so `Re-embed All` can continue through `unique_node_rebuild` and `audit_finalization` after chunk work reaches 100%
- World-scope blockers now surface separately from per-chunk `Failed Records`, instead of hiding only in the live agent log
- The node counters reflect the current merged graph state, not raw per-chunk extraction totals
- Because of that, node counts can change after entity resolution merges duplicate entities and refreshes unique-node embeddings
- If a node id exists in the index but its stored document no longer matches the current merged node text, it is treated as stale until repaired
- Wait states such as `Queued for extraction slot`, `Queued for embedding slot`, and `Waiting for API key cooldown` are shown as secondary activity context instead of replacing the main progress summary
- The floating global ingest panel stays compact and keeps the same calm world-level progress semantics without showing the full row set

## Safety Review Queue

VySol now keeps extraction safety blocks in a durable review queue instead of leaving them as manual text-hunting work.

Important behavior:

- Safety-blocked chunks warn in the live ingest log as soon as they are detected
- The queue groups blocked chunks by source and keeps the original source text separate from your editable repair draft
- Each item shows a read-only provenance prefix, a read-only overlap box when present, and one editable chunk-body field
- The `Safety Queue` opens as a dedicated panel from the main ingest page instead of sending you to a separate screen
- `Reset` always restores the original source chunk, not your last attempted edit
- A chunk is only considered repaired after extraction coverage and embedding both succeed for that edited chunk
- If a retest fails for another reason, such as a rate limit or provider error, the chunk stays unresolved instead of being treated as fixed
- Retry and resume actions skip unresolved Safety Queue chunks so they do not silently fall back to original source text
- The recommended recovery order is `Resume` first, then `Retry All Failures`, then `Add failed chunks to Safety Queue`, and finally fixing the remaining Safety Queue items
- If the only remaining failed chunks already belong to the Safety Queue, the main ingest page stops showing `Resume` and `Retry All Failures` and points you back to the queue instead
- `Add failed chunks to Safety Queue` is world-local and temporary; it moves stubborn failed extraction chunks into the review queue for editing when automatic retry paths did not clear them
- `Re-ingest` can optionally reuse repaired chunk overrides when the chunk map stays the same, and `Re-embed All` continues to respect those repaired chunk bodies when its locked-source checks still pass

## Extraction Payload Separation

Graph extraction now separates chunk-body text from overlap context.

Important behavior:

- `[B#:C#]` provenance tags still exist for embeddings, chat context, and stored chunk provenance
- Graph extraction and glean no longer see those tags as part of the extractable text
- Overlap is passed separately as reference-only context so pronoun and alias resolution still works
- Chunks are not re-split just for extraction, which keeps graph extraction aligned with embeddings and stored chunk provenance

## Chunk-Local Graph Binding

During extraction, a chunk's nodes and edges are now bound together using the exact node UUIDs created for that chunk write.

This means:

- Newly extracted edges attach to the specific nodes created from that same chunk
- They no longer accidentally bind to an older same-name node elsewhere in the graph
- Cross-chunk duplicate cleanup is still handled later by entity resolution, where it belongs
