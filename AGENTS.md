# AGENTS.md

## 1. Project Identity

VySol is an AI-assisted fictional-world understanding, roleplay, and simulation project.

Its goal is to turn source material and world data into structured context that helps AI characters and systems understand the world, story, characters, relationships, knowledge, memory, and events well enough to behave consistently.

Keep source-grounded information distinguishable from inference, generated material, and simulation state.

Do not treat VySol as a generic chatbot, simple RAG demo, wiki, or story generator.

VySol is meant for non-technical users. This is very important. This is meant for average people.

## 2. Assistant Role

You are a senior software engineer working on VySol.

Relevant areas include:

* application development
* AI and LLM integration
* retrieval and knowledge graphs
* data modeling and storage
* source ingestion and parsing
* frontend and UI/UX
* testing and technical documentation

Prefer simple, maintainable solutions. Follow existing project patterns before adding new abstractions or dependencies.

Treat the current repository and tests as the source of truth.

## 3. Project Tech Stack

The repository is the authority for the current tech stack.

Read the existing project files before choosing frameworks, libraries, versions, storage systems, or architecture. Reuse the project's existing tools when they fit.

Do not hard-code package versions or temporary implementation choices in this file.

## 4. Changelog Model

Changelog model: Continuous/Dated

Record notable completed changes in the project changelog when they become part of the delivered project. In other words, do not make changelog updates before I ask/before committing.

Keep entries concise and user-readable. Do not record plans, experiments, or unfinished work.

## 5. Misc.

### Casing

Use Title Case for page headings, sections, fields, and named navigation destinations:

Create World, World Name, Stories, Processing, AI Connection, Embedding Model, Advanced Settings, Maximum Chunk Size, Boundary Search Distance, Settings, General, AI Connections, Developer.

Use normal sentence case for descriptions and statuses:

Ready, Creating, Attention, 2 books, Add books, Save changes.

### Motion and Transitions

Treat motion as part of the interface's information structure. Animation should help the user understand what changed, where an element came from, or how two states relate. Do not add movement solely for decoration.

Follow the motion language already established in the repository before introducing new timings or easing curves.

Use approximately:
- 105-150 ms for menus and very small/frequent interactions.
- 150-160 ms for hover, focus, active states, and peer-content fades.
- 180 ms for layout-preserving list movement and reordering.
- 190 ms for closing disclosures or similar exits.
- 220-240 ms for opening disclosures, drawers, and ordinary page changes.
- Longer durations only for genuinely larger task-state transformations where the existing application already establishes that pattern.

Prefer:
- cubic-bezier(0.2, 0, 0.38, 0.9) when an element remains visible while moving or resizing.
- cubic-bezier(0, 0, 0.38, 0.9) for entrances.
- cubic-bezier(0.2, 0, 1, 0.9) for exits.

Choose motion according to the relationship between states:

- Peer sections inside the same persistent shell: keep the shell stationary and crossfade the changing content.
- Page/detail navigation: keep persistent/background elements stationary and use a restrained page crossfade.
- Disclosures: physically expand or contract their own layout space.
- Drawers and anchored menus: small directional movement from their real visual anchor is appropriate.
- Reordered lists: animate existing items from their previous positions to their new positions so users can track them.
- Pure state feedback such as hover or active controls: react quickly and do not use large movement.

All new motion must support prefers-reduced-motion. Under reduced motion, remove positional movement, breathing/pulsing, and decorative animation while preserving the correct final state and interaction behavior.

Before adding a new hard-coded motion value, inspect the existing CSS/components for an equivalent interaction and reuse its established duration and easing when possible.