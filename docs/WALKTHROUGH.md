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

Graph Architect Model:

- This is the extraction model used to turn text chunks into entities and relationships
- Lighter, faster models usually work best here because ingestion can make many calls
- A Gemini Flash-class model is a good fit for most users

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

Disable Safety Filters:

- This relaxes Gemini content moderation behavior for creative or edge-case writing workflows

## Creating A World

1. Click `Create World`.
2. Give the world a name.
3. Upload source files.

Supported source format:

- `.txt` only

For most casual use cases, the defaults are already more than enough.

## Ingestion Settings

On the world ingest page you can control:

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

Important save behavior:

- If you change any settings, click `Save Graph Architect Settings` before ingestion
- If you edit prompts, use each prompt's own `Save` button before ingestion
- Chunk size, chunk overlap, and world embedding model are taken from the values currently shown when you start or rebuild ingestion

## Prompt Editor

The prompt editor lets you override the shipped defaults, but the defaults are enough for most users.

Graph Architect Prompt:

- Controls how the extraction model turns text into entities and relationships

Entity Resolution Chooser Prompt:

- Controls how strictly the chooser decides whether two entities are really the same thing

Entity Resolution Combiner Prompt:

- Controls how chosen duplicate entities are merged into one final name and description

Important:

- The chooser and combiner prompts matter only when you run `Exact + chooser/combiner`
- `Exact only` does not call either model stage

## Ingestion Flow

Basic flow:

1. Add one or more `.txt` files.
2. Review the ingestion settings.
3. Save Graph Architect settings if you changed any settings.
4. Save any custom prompts if you changed them.
5. Click `Start Ingestion`.

After ingestion finishes:

1. Click `Resolve Entities`.
2. Pick a run mode: `Exact only` for a fast normalized-name cleanup pass, or `Exact + chooser/combiner` for the full duplicate-resolution workflow.
3. Let entity resolution run.

Entity-resolution controls:

- `Resolution mode` chooses whether the run stops after exact normalized matching or continues into chooser/combiner review
- `Top K candidates` is used only for `Exact + chooser/combiner`

## Rebuild And Retry Actions

Use the rebuild and retry actions based on what went wrong:

`Re-embed All`

- Clears and rebuilds chunk vectors from the previously fully ingested source set and unique-node vectors from the current saved graph state
- Ignores brand-new pending sources you added after the last clean ingest
- Is blocked if an older ingested source is missing, changed, partial, failed, or comes from an older world that never recorded source snapshots
- Use this when you change only the world embedding model or need to rebuild vectors without re-extracting the graph

`Re-ingest With Previous Settings`

- Fully rebuilds chunks, extraction, graph data, and vectors using the world's locked previous ingest settings
- Use this when `Re-embed All` says the prior ingested source set changed and you want a clean rebuild without adopting whatever draft chunk settings are currently in the form

`Rechunk And Re-ingest`

- Fully rebuilds chunks, extraction, graph data, and vectors using the settings currently shown in the form
- Use this when chunk settings changed on purpose or when you want a full clean rebuild with new settings

`Retry Embedding Failures`

- Retries only failed embedding work

`Retry Extraction Failures`

- Retries only failed extraction work

`Retry All Failures`

- Retries both failed extraction and failed embedding work

Important behavior:

- `Resume` is the normal path when you simply add another new source after a previous ingest
- `Re-embed All` is intentionally narrower than a full rebuild and will now explain when it is unsafe
- `Retry` actions only repair failures inside the currently locked ingest; they do not apply new chunk settings

## Chat

Open a world, create a new chat, and use the right-side retrieval settings to tune behavior.

Chat settings:

`Top K Chunks`

- How many standard chunk matches are sent into chat context

`Entry Nodes`

- How many graph entry nodes are selected before graph expansion begins
- If number of entry nodes matches or exceedes the total amount of nodes, all edges will be placed into context for future queries until brought below the amount of nodes inside the ingested world

`Graph Hops`

- How far the graph expansion walks outward from the selected entry nodes

`Max Graph Nodes`

- A hard cap on how many graph nodes can be included

`Vector Query (Msgs)`

- How many recent messages are used to build the retrieval search vector

`Chat History Context (Msgs)`

- How many previous chat messages are sent as chat history context

`Chat System Prompt`

- The system-level instruction that shapes how the model answers in chat
