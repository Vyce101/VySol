<h1 align="center">VySol</h1>

<p align="center">
  <img src="docs/assets/Butterfly-logo-with-background_compressed.png" alt="VySol butterfly logo" width="1080">
</p>

VySol is an early-stage roleplay and world-simulation app for building believable scenes inside established fictional worlds.

<p align="center">
  <a href="docs/QUICKSTART.md"><img alt="QUICKSTART: Windows" src="https://img.shields.io/badge/QUICKSTART-Windows-0892D0?labelColor=4A5568"></a>
  <img alt="Status: rebuild alpha" src="https://img.shields.io/badge/status-rebuild--alpha-F59E0B?labelColor=4A5568">
  <a href="https://vyce101.github.io/VySol/"><img alt="Docs: latest main" src="https://img.shields.io/badge/docs-latest%20main-0892D0?labelColor=4A5568"></a>
  <img alt="License: AGPLv3" src="https://img.shields.io/badge/license-AGPLv3-0892D0?labelColor=4A5568">
</p>

## Table of Contents

- [What It Solves](#what-it-solves)
- [What It Does](#what-it-does)
- [Why It Is Different](#why-it-is-different)
- [Major Milestones Roadmap](#major-milestones-roadmap)
- [Links](#links)

## What It Solves

VySol is for roleplayers who want established fictional worlds to feel coherent, explorable, and persistent across long-running scenes. Normal chat, static lore documents, summaries, and standard RAG can all help, but they often lose the context that makes a scene believable.

Standard chunk retrieval can find text that looks similar to the current message, but it often misses why a character acts a certain way, what world rules constrain a scene, or which past events should matter now. VySol exists to become a world-simulation workspace where characters, places, events, rules, and knowledge grow into connected systems that can bring that missing context back into play.

Standard RAG retrieves what was mentioned. VySol retrieves what matters.

## What It Does

VySol is being built around a graph extraction pipeline. The intended pipeline takes persisted story chunks and runs resumable extraction passes that turn prose into raw node and edge candidates: characters, places, objects, factions, events, rules, and relationships that can later become graph context.

This matters because fictional worlds do not break only because a model forgot a sentence. They break because the model missed the relationship behind the sentence: why a character acts angry, which rule makes a spell impossible, what earlier mistake still shapes a scene, or which place, faction, or object carries hidden context.

The graph pipeline is intended to sit on top of local source ingestion, chunking, embedding, provider-key scheduling, saved manifests, Qdrant vectors, and local Neo4j manifestation work. Those systems exist to make graph extraction resumable and inspectable, while the graph extraction pipeline is the main feature direction being presented here.

## Why It Is Different

VySol targets the missing cause, not just the matching scene.

In tools like SillyTavern, long-running roleplay often depends on lorebooks, memory entries, summaries, or normal chunk retrieval. Those can help, but they still tend to retrieve what looks similar to the current message. If a character is arguing right now, the system may retrieve another argument scene while missing the childhood abuse, self-blame, betrayal, oath, or world rule that actually explains why the argument matters.

VySol is being built around that pain. The goal is not only to retrieve a matching chunk, but to recover the connected background that a human reader would know belongs in the scene even when the wording is not semantically similar. That same structure is also meant to support richer world simulation over time, where characters, rules, places, and past events can shape what should happen next.

## Major Milestones Roadmap

### Knowledge Graph Extraction Pipeline

The knowledge graph extraction pipeline is the part that turns story text into structured world context. VySol will take persisted story chunks and run resumable extraction passes that identify raw node and edge candidates: characters, places, objects, factions, events, rules, and relationships that can later become graph context.

### Retrieval Engine

The retrieval engine is the part that turns the ingested world into useful roleplay context. Instead of only grabbing similar text, it will combine relevant chunks, graph nodes, relationships, and chat history so the AI has a better chance of remembering why a scene matters.

### Temporal Indexer

VySol will track where information comes from in the story, such as which book and chunk produced it. This is meant to help the AI understand story order, avoid future spoilers when needed, and keep facts grounded to the point in the world where they were actually known.

### Entity Resolution

Large fictional worlds repeat the same characters, places, and concepts in many forms. VySol will merge matching entities so the graph does not become cluttered with duplicates, while still preserving important details instead of flattening everything into a tiny summary.

### Retrieval Benchmark Mode

Benchmark mode will let users compare different retrieval styles on the same world. You will be able to ask one question and see how chunk-only retrieval, graph-only retrieval, and hybrid retrieval behave side by side.

### Failed Chunk Repair And Retry

If one chunk fails during ingestion, VySol will let users review that specific chunk, retry it, or repair it without throwing away the whole world. This is meant to make large ingestions less fragile when a provider blocks, times out, or returns unusable output.

## Links

- [Documentation](https://vyce101.github.io/VySol/) - These docs track the latest main branch. Released app builds may not include every documented feature yet.
- [QUICKSTART](docs/QUICKSTART.md)
- [CHANGELOG](docs/CHANGELOG.md) - See unreleased changes that are only available in the latest commits.
- [LICENSE](LICENSE)
