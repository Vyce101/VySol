# VySol

<p align="center">
  <img src="docs/assets/branding/horizontal.png" alt="VySol logo" width="560">
</p>

![License](https://img.shields.io/badge/license-AGPLv3-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![Node](https://img.shields.io/badge/node-18%2B-339933)
![Status](https://img.shields.io/badge/status-active-success)

VySol is an accessible local-first graph RAG app built to make ingestion, graph extraction, entity resolution, embeddings, and chat easy to set up and use in one place.

You can ingest plain-text source material, control how the graph is built, resolve duplicate entities after ingestion, and chat with both chunk retrieval and graph context without leaving the app.

Entity resolution supports a fast `Exact only` cleanup pass or a fuller `Exact + chooser/combiner` workflow after ingestion.

This project is licensed under the GNU AGPLv3. Companies requiring a commercial license should see [COMMERCIAL.md](COMMERCIAL.md).

## Supported OS

- Windows: Supported (`VySol.bat` launcher)
- macOS/Linux: Manual setup only (no supported launcher path yet)

## What This Project Is

VySol is meant to be a graph RAG app that is easy to use, easy to set up, and flexible enough for people who want control over how their graph is made.

It gives you one place to:

- Ingest source text into a world
- Extract entities and relationships into a graph
- Rebuild vectors or fully rebuild ingests when needed
- Resolve duplicate entities after ingestion
- Chat against chunk retrieval and graph context together
- Trace every graph edge back to its source document and chunk, useful for chronological documents
- Inspect exactly what context was sent for every chat message with Context X-Ray

## Where To Read Next


[Start in 60 Seconds](docs/SETUP.md#start-in-60-seconds)

- Setup and First Run: [docs/SETUP.md](docs/SETUP.md)
- Full App Walkthrough (Settings, Ingestion, and Chat): [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)
- System Architecture Diagram: [docs/DIAGRAM.md](docs/DIAGRAM.md)
- Core Features (Entity Resolution, Graph Provenance, Context X-Ray): [docs/FEATURES.md](docs/FEATURES.md)
- License Terms: [LICENSE](LICENSE)
- Commercial Licensing: [COMMERCIAL.md](COMMERCIAL.md)
