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

## Where To Read Next

- Setup and first run: [docs/SETUP.md](docs/SETUP.md)
- Full app walkthrough (settings, ingestion, and chat): [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)
- System architecture diagram: [docs/DIAGRAM.md](docs/DIAGRAM.md)
- Core features (entity resolution, graph provenance, context X-Ray): [docs/FEATURES.md](docs/FEATURES.md)
- License terms: [LICENSE](LICENSE)
- Commercial licensing: [COMMERCIAL.md](COMMERCIAL.md)
