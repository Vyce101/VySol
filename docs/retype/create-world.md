---
label: Create a world
order: 80
---
# Create a world

Build a world from one or more TXT or EPUB books. VySol saves it as a completed world only after every book has been converted, split into chunks, and embedded. Once creation starts, its books and their order are fixed.

## Before you start

Before creating a World, set up a usable **Embedding Profile** in **Settings > AI Connections**. See the [AI Connections guide](ai-connections.md) for provider setup, model discovery, credentials, and profile settings.

## Create a world

1. On Worlds, choose **New World** beside **Your Worlds**. On an empty homepage, choose **Create World**.
2. Enter a **World Name** and add at least one TXT or EPUB file under **Stories**. Drag the six-dot handles to set reading order, or use the up/down arrow keys with a handle focused. The red X removes a draft selection.
3. Under **Processing**, use the configured default **Embedding Profile** or choose another usable profile. The field shows its provider and model. To manage profiles, open **AI Connections** from this page; closing Settings returns to your draft.
4. Keep the defaults or expand **Advanced Settings** to adjust **Maximum Chunk Size** and **Boundary Search Distance**. See [Creation processing settings](reference.md#creation-processing-settings) for values and limits.
5. Choose **Create World**. Uploads begin, then all books are converted and chunked before embedding requests start.

The draft is held in the browser session until submission. Reloading loses unsaved file selections. Once submitted, its progress is saved locally and the next **New World** opens a fresh draft. You can create other worlds while one is processing.

## Follow progress

The pending world appears in Worlds with a **Creating**, **Paused**, or **Attention** status. Open it to see ordered Stories, each book's completion or embedded chunks out of total chunks, and **World Details**. The world continues processing after you leave its page or close the browser.

**World Details** groups the World's read-only Embedding and Chunking settings.

**Pause** stops after the current operation. **Resume** continues from saved results. Closing the launcher pauses unfinished processing; after restarting VySol, open the pending world and choose **Resume**. VySol does not restart paid API requests automatically.

Completed uploads and processing checkpoints survive restarts. An interrupted upload can retry while its file is still available in the browser session. After a reload loses that file selection, discard the attempt and start again. A request whose response was lost before its checkpoint may be repeated and billed again.

## Retry or discard

Submitted books, order, and chunk settings cannot be edited, even when processing is paused or fails. Once an unfinished World uses an **Embedding Profile**, only the profile's name can change; its connection, model, and dimensions are locked. **Resume** retries with the same settings and reuses completed embeddings. For an invalid key, pause processing, replace that credential's secret in **Settings > AI Connections**, then resume. A profile used by a completed World must keep the same provider, model, and dimensions; OpenAI-compatible connections must also keep the same Base URL. You can change its credential only to another one that preserves those settings. If a source file needs changing, discard and start again.

**Discard World** asks for confirmation and removes that unfinished attempt and its saved work. Other unfinished worlds are unaffected. For file problems, see [supported books and limits](reference.md#supported-books) and [duplicate names](reference.md#duplicate-book-names).

When all books succeed, the same Overview becomes **Ready**. Its ordered source books cannot be removed, replaced, reordered, or extended. You can then open a [Chronicle](chronicles.md) to chat using passages retrieved from those books. Book reading, scene extraction, and graph indexing are not part of this flow yet.
