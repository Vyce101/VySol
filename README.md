# Vysol

Vysol is an accessible local-first graph RAG app built to make ingestion, graph extraction, entity resolution, embeddings, and chat easy to set up and use in one place.

You can ingest plain-text source material, control how the graph is built, resolve duplicate entities after ingestion, and chat with both chunk retrieval and graph context without leaving the app.

This project is licensed under the GNU AGPLv3. Companies requiring a commercial license should see [COMMERCIAL.md](COMMERCIAL.md).

## What This Project Is

Vysol is meant to be a graph RAG app that is easy to use, easy to set up, and flexible enough for people who want control over how their graph is made.

It gives you one place to:

- ingest source text into a world
- extract entities and relationships into a graph
- rebuild vectors or fully rebuild ingests when needed
- resolve duplicate entities after ingestion
- chat against chunk retrieval and graph context together
- trace every graph edge back to its source document and chunk, useful for chronological documents
- inspect exactly what context was sent for every chat message with Context X-Ray

## Quick Start For Windows

If you are on Windows, the easiest path is:

1. Run [VySol.bat](VySol.bat).
2. Let it check for supported Python and Node.js versions.
3. If something is missing, it will try to install it with `winget`.
4. It will create or reuse the backend virtual environment, install dependencies, and launch the app.

What `VySol.bat` expects:

- Windows
- `winget` available if prerequisites need to be installed
- Python 3.10 or newer
- Node.js 18 or newer

If Python and Node are already installed, the launcher will reuse them instead of reinstalling them.

## Manual Setup

If you do not want to use the batch file, you can run the app manually.

Requirements:

- Python 3.10 or newer
- Node.js 18 or newer
- npm

Backend:

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

By default the frontend talks to `http://localhost:8000`.

## First Run Behavior

- `settings/settings.json` is created automatically when the backend first needs a live settings file
- local worlds, graphs, vectors, and chat history are stored under `saved_worlds/`
- Gemini API keys added in the app are stored locally in `settings/settings.json`
- this public repo does not ship with live secrets, saved worlds, imported corpora, or personal runtime data

## Settings Walkthrough

Open the settings sidebar from the home screen before you ingest your first world.

### API Keys

- only Gemini API keys are supported in VySol's built-in key management flow
- click the `+` button to add each key
- all saved keys participate in key rotation

Key Rotation Mode:

- `Fail Over`: keeps using the current key until it hits a rate limit, then moves to the next one
- `Round Robin`: rotates across keys to spread load more evenly

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

- batch size is parallel slots, not a wait-for-all barrier
- slot delay starts the moment that individual slot finishes
- each slot cools down independently

### AI Models

Graph Architect Model:

- this is the extraction model used to turn text chunks into entities and relationships
- lighter, faster models usually work best here because ingestion can make many calls
- a Gemini Flash-class model is a good fit for most users

Chat Provider:

- `Google (Gemini)` uses the normal Gemini chat model field (uses API keys from Google AI Studio)
- `IntenseRP Next` lets you point chat at a local IntenseRP-compatible endpoint instead

IntenseRP Next:

- GitHub: [LyubomirT/intense-rp-next](https://github.com/LyubomirT/intense-rp-next)
- this path is optional
- you must enter the endpoint URL yourself
- no API key management is built into VySol for this provider path
- extraction, entity resolution, and embeddings still follow the Gemini-side model and key flow
- using IntenseRP Next and any provider behind it is subject to that provider's own terms of service

Chat Model:

- this is the model used to answer chat requests

Entity Chooser Model:

- this is the entity-resolution model that decides which candidate entities are actually the same entity as the current anchor entity

Entity Combiner Model:

- after the chooser selects matching entities, the combiner rewrites the merged result
- it chooses the best final display name and creates one final description from the chosen group

Default Embedding Model:

- this is the default embedding model for new worlds
- the shipped default is `gemini-embedding-002-preview`

Disable Safety Filters:

- this relaxes Gemini content moderation behavior for creative or edge-case writing workflows

## Creating A World

1. Click `Create World`.
2. Give the world a name.
3. Upload source files.

Supported source format:

- `.txt` only

For most casual use cases, the defaults are already more than enough.

## Ingestion Settings

On the world ingest page you can control:

- chunk size
- chunk overlap
- world embedding model
- Graph Architect glean amount

Shipped defaults:

- chunk size: `4000`
- chunk overlap: `150`
- world embedding model: `gemini-embedding-002-preview`
- Graph Architect glean amount: `1`

What they mean:

- Chunk Size:
  how much text goes into each chunk before ingestion splits it
- Chunk Overlap:
  how much trailing context is carried into the next chunk to solve pronoun/entity name problems
- World Embedding Model:
  the embedding model used for that world's vectors
- Graph Architect Glean Amount:
  extra extraction passes that try to catch additional graph details after the first pass

Important save behavior:

- if you change any settings, click `Save Graph Architect Settings` before ingestion
- if you edit prompts, use each prompt's own `Save` button before ingestion
- chunk size, chunk overlap, and world embedding model are taken from the values currently shown when you start or rebuild ingestion

## Prompt Editor

The prompt editor lets you override the shipped defaults, but the defaults are enough for most users.

Graph Architect Prompt:

- controls how the extraction model turns text into entities and relationships

Entity Resolution Chooser Prompt:

- controls how strictly the chooser decides whether two entities are really the same thing

Entity Resolution Combiner Prompt:

- controls how chosen duplicate entities are merged into one final name and description

## Ingestion Flow

Basic flow:

1. Add one or more `.txt` files.
2. Review the ingestion settings.
3. Save Graph Architect settings if you changed any settings.
4. Save any custom prompts if you changed them.
5. Click `Start Ingestion`.

After ingestion finishes:

1. Click `Resolve Entities`.
2. Let entity resolution run.

## How Entity Resolution Works

Entity resolution happens in two stages.

First:

- the app does an exact normalized-name pass
- this can auto-resolve obvious duplicates without spending chooser model calls

Then:

- the app has a master list of all entities and chooses Top K most similiar entities via vector search
- the chooser model decides which candidates are actually the same entity as the anchor
- the combiner model merges the chosen group into one canonical result
- all entities that were merged are removed from the master list
- repeat

## Graph Provenance

Every edge extracted into the graph is temporally indexed to its source document and chunk as BN:CN with the N' being numbers.

Each document completed during ingestion is assigned a book number, starting at 1 and incrementing in input order. Chunk numbering resets on every document completion.

This means every relationship in the graph carries:

- which book it came from
- which chunk within that book it came from

What this gives you:

- full source traceability for any extracted relationship
- the ability to see when a relationship was first established across a multi-document ingest
- a foundation for spotting contradictions between sources
- auditability for workflows where knowing the origin of extracted information matters
- an ai model with better temporal understanding

## Context X-Ray

Every chat message saves a full record of exactly what was sent to the model.

Context X-Ray lets you open any message and see:

- the system prompt
- entry nodes selected for graph expansion
- all nodes and edges included in context
- RAG chunks retrieved
- chat history sent

Each record has two views:

- Byte View: the exact raw content sent, nothing hidden or reformatted
- Clean View: a readable formatted version of the same data

X-Ray records are saved per message so you can go back and inspect any point
in a conversation, not just the most recent one.

### Graph View (Planned)

A future update will add a visual graph view inside X-Ray that shows only the
nodes and edges that were actually sent for that message. Non-selected nodes
will be visible at reduced opacity and remain hoverable so you can still
inspect their data. Selected and non-selected nodes will behave consistently
on hover, showing the same edge and node detail either way.

## Rebuild And Retry Actions

Use the rebuild and retry actions based on what went wrong:

`Re-embed All`

- clears and rebuilds chunk and node vectors only
- use this when you change the world embedding model or need to rebuild vectors without re-extracting the graph

`Rechunk And Re-ingest`

- fully rebuilds chunks, extraction, graph data, and vectors
- use this when chunk settings changed or when you want a full clean rebuild

`Retry Embedding Failures`

- retries only failed embedding work

`Retry Extraction Failures`

- retries only failed extraction work

`Retry All Failures`

- retries both failed extraction and failed embedding work

## Chat

Open a world, create a new chat, and use the right-side retrieval settings to tune behavior.

Chat settings:

`Top K Chunks`

- how many standard chunk matches are sent into chat context

`Entry Nodes`

- how many graph entry nodes are selected before graph expansion begins
- if number of entry nodes matches or exceedes the total amount of nodes, all edges will be placed into context for future queries until brought below the amount of nodes inside the ingested world

`Graph Hops`

- how far the graph expansion walks outward from the selected entry nodes

`Max Graph Nodes`

- a hard cap on how many graph nodes can be included

`Vector Query (Msgs)`

- how many recent messages are used to build the retrieval search vector

`Chat History Context (Msgs)`

- how many previous chat messages are sent as chat history context

`Chat System Prompt`

- the system-level instruction that shapes how the model answers in chat

## Local Data

VySol stores local runtime data in predictable places:

- settings and API keys: `settings/settings.json`
- worlds, graph files, vectors, and chat history: `saved_worlds/`

Those locations are meant to stay local and are ignored in the repo.

## License

This repository is licensed under the GNU AGPLv3.

In short:

- if you use or modify this project and distribute it, the AGPL terms apply
- if your company needs a proprietary or closed-source license, see [COMMERCIAL.md](COMMERCIAL.md)

## Support And Contributions

There is no formal support or contribution program. This is a solo project maintained casually.
