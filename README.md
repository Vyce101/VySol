# VySol

<p align="center">
  <img src="docs/assets/branding/social.png" alt="VySol logo" width="560">
</p>

![License](https://img.shields.io/badge/license-AGPLv3-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![Node](https://img.shields.io/badge/node-18%2B-339933)
![Status](https://img.shields.io/badge/status-active-success)
![AI Assisted](https://img.shields.io/badge/AI-assisted-1f6feb)

VySol is an accessible local-first graph RAG app built to make ingestion, graph extraction, entity resolution, embeddings, and chat easy to set up and use in one place.

You can ingest plain-text source material, control how the graph is built, resolve duplicate entities after ingestion, review and repair extraction safety blocks in-app, and chat with both chunk retrieval and graph context without leaving the app.

Entity resolution supports a fast `Exact only` cleanup pass or a fuller `Exact + chooser/combiner` workflow after ingestion, plus per-run unique-node embedding batch and delay controls.

Global settings now split into a preset-backed `Configuration` tab and a shared `Key Library`. Gemini and Groq can be selected per text-model slot, IntenseRP Next stays chat-only, and embedding settings are provider-aware even though this build still only enables Gemini embeddings.

This project is licensed under the GNU AGPLv3. Companies requiring a commercial license should see [COMMERCIAL.md](COMMERCIAL.md).

## Supported OS

- Windows: Supported (`VySol.bat` launcher)
- macOS/Linux: Manual setup only for now (coming soon)

## What This Project Is

VySol was personally developed for roleplay in pre-existing fictional worlds, but it is designed to be useful anywhere local-first graph RAG is helpful.

It gives you one place to:

- Ingest source text into a world
- Extract entities and relationships into a graph
- Rebuild vectors or fully rebuild ingests when needed
- Resolve duplicate entities after ingestion
- Switch between saved global configuration presets while reusing one shared per-provider credential library
- Repair blocked chunks with the Safety Review Queue and reusable chunk-body overrides
- Chat against chunk retrieval and graph context together
- Trace every graph edge back to its source document and chunk, useful for chronological documents
- Inspect exactly what context was sent for every chat message with Context X-Ray

## Common Uses

- Roleplay in pre-existing fictional worlds
- Anyone who wants easy-to-use, fast-setup local-first graph RAG for their own corpus or workflow
- Original worldbuilding and lore management
- Continuity checking across long-running stories or document sets
- Personal knowledge bases with traceable source grounding
- Studying large document collections with graph-backed chat
- Organizing technical documentation and internal knowledge
- Investigating timelines and connections across archival or reference material
- Inspectable local-first RAG over private text corpora

## Where To Read Next

- Setup and First Run (`Start in 60 Seconds`): [docs/SETUP.md](docs/SETUP.md)
- Full App Walkthrough (Settings, Ingestion, and Chat): [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)
- Core Features (Entity Resolution, Graph Provenance, Context X-Ray): [docs/FEATURES.md](docs/FEATURES.md)
- Changelog and Release History: [CHANGELOG.md](CHANGELOG.md)
- System Architecture Diagram: [docs/DIAGRAM.md](docs/DIAGRAM.md)
- License Terms: [LICENSE](LICENSE)
- Commercial Licensing: [COMMERCIAL.md](COMMERCIAL.md)
