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

Each record has two views:

- Byte View: the exact raw content sent, nothing hidden or reformatted
- Clean View: a readable formatted version of the same data

X-Ray records are saved per message so you can go back and inspect any point
in a conversation, not just the most recent one.
