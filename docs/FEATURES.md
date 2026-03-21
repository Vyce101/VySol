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
- Stops after the exact pass finishes

`Exact + chooser/combiner`

- Starts with the same normalized exact pass
- Then builds a Top K candidate list for each remaining anchor entity with vector search
- The chooser model decides which candidates are actually the same entity as the anchor
- The combiner model merges the chosen group into one canonical result
- All entities that were merged are removed from the remaining list
- Repeat until the unresolved list is exhausted

Important behavior:

- Exact-only runs never enter candidate search, chooser, or combiner phases
- Exact + chooser/combiner runs still preserve temporal graph edges while merging entities
- Older data that predates the new run-mode field still maps safely to the previous behavior

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

## Ingest Rebuild Safety

VySol now treats `Re-embed All` as a narrow vector-maintenance operation, not a catch-all rebuild button.

Important behavior:

- `Re-embed All` only runs against sources that were already fully ingested in the current world
- Newly added pending sources are ignored by `Re-embed All`; use `Resume` to ingest those
- `Re-embed All` is blocked if a previously ingested source is missing, changed, partially ingested, failed, or comes from an older world that predates stored source snapshots
- When that happens, the UI points you to either `Retry`, `Resume`, `Re-ingest With Previous Settings`, or `Rechunk And Re-ingest` depending on what changed
- `Re-ingest With Previous Settings` gives you a clean full rebuild path that reuses the world's locked prior chunk settings instead of the current draft values shown in the form

## Chunk-Local Graph Binding

During extraction, a chunk's nodes and edges are now bound together using the exact node UUIDs created for that chunk write.

This means:

- Newly extracted edges attach to the specific nodes created from that same chunk
- They no longer accidentally bind to an older same-name node elsewhere in the graph
- Cross-chunk duplicate cleanup is still handled later by entity resolution, where it belongs
