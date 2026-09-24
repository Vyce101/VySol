---
label: Create a world
order: 80
---
# Create a world

Build a world from one or more TXT or EPUB books. VySol saves it as a completed world only after every book has been converted, split into chunks, and embedded. Once creation starts, its books and their order are fixed.

## Before you start

Open **Settings > AI Connections**, choose **Select Connections**, and enable Google. Expand the Google connection, choose **Add Credential**, enter a name and a Google AI Studio API key, then choose **Save Changes**. Saved secrets are stored as plain-text files in the local runtime `credentials/` folder. The eye control can reveal a saved key on this device. Anyone who can read that folder or its backups can read the keys. Creating embeddings sends your book chunks to Google and uses that key's API allowance.

## Create a world

1. On Worlds, choose **New World** beside **Your Worlds**. On an empty homepage, choose **Create World**.
2. Enter a **World Name** and add at least one TXT or EPUB file under **Stories**. Drag the six-dot handles to set reading order, or use the up/down arrow keys with a handle focused. The red X removes a draft selection.
3. Under **Processing**, select **Gemini Embedding 2** and a saved Google credential. If you need a credential, open **AI Connections** from this page; closing Settings returns to your draft.
4. Keep the defaults or expand **Advanced Settings** to adjust **Maximum Chunk Size** and **Boundary Search Distance**. See [Creation processing settings](reference.md#creation-processing-settings) for values and limits.
5. Choose **Create World**. Uploads begin, then all books are converted and chunked before embedding requests start.

The draft is held in the browser session until submission. Reloading loses unsaved file selections. Once submitted, its progress is saved locally and the next **New World** opens a fresh draft. You can create other worlds while one is processing.

## Follow progress

The pending world appears in Worlds with a **Creating**, **Paused**, or **Attention** status. Open it to see ordered Stories, each book's completion or embedded chunks out of total chunks, and **World Details**. The world continues processing after you leave its page or close the browser.

**Pause** stops after the current operation. **Resume** continues from saved results. Closing the launcher pauses unfinished processing; after restarting VySol, open the pending world and choose **Resume**. VySol does not restart paid API requests automatically.

Completed uploads and processing checkpoints survive restarts. An interrupted upload can retry while its file is still available in the browser session. After a reload loses that file selection, discard the attempt and start again. A request whose response was lost before its checkpoint may be repeated and billed again.

## Retry or discard

Submitted books, order, model, credential selection, and chunk settings cannot be edited, even when processing is paused or fails. **Resume** retries with the same settings and reuses completed embeddings. For an invalid key, pause processing, replace that credential's secret in **Settings > AI Connections**, then resume. If the credential was deleted or a source file needs changing, discard and start again.

**Discard World** asks for confirmation and removes that unfinished attempt and its saved work. Other unfinished worlds are unaffected. For file problems, see [supported books and limits](reference.md#supported-books) and [duplicate names](reference.md#duplicate-book-names).

When all books succeed, the same Overview becomes **Ready**. Its ordered source books cannot be removed, replaced, reordered, or extended. Reading, retrieval, scene extraction, graph indexing, and roleplay are not part of this flow yet.
