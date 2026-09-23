---
label: Create a world
order: 80
---
# Create a world

Build a world from one or more TXT or EPUB books. VySol saves it as a completed world only after every book has been converted, split into chunks, and embedded. Successful creation fixes its source text and book order.

## Before you start

Open **Settings > Providers**, choose **Add API key**, and give your Google AI Studio / Gemini API key a name. Keys are stored as plain-text files in the ignored `data/credentials/` folder (or `credentials/` under your configured runtime directory). VySol displays their names, never their saved secrets. Anyone who can read this folder or its backups can read the keys. Creating embeddings sends your book chunks to Google and uses that key's API allowance.

## Arrange and review

1. On Worlds, choose **+** beside **Your Worlds**. On an empty homepage, use **Create World**. Both reopen your unfinished attempt if one exists.
2. In **Books**, enter a nonblank world name and add at least one TXT or EPUB file. Drag the six-dot handles to reorder books. With a handle focused, use the up/down arrow keys. Remove selections with their X buttons. Conversion has not started at this stage.
3. In **Processing**, select your named key and **Gemini Embedding 2**. The last submitted model and key are selected by default. If the key was deleted, select a replacement. **Manage API keys** opens Providers; **Return to creation** brings you back with your draft intact.
4. Keep the default chunk settings or adjust them. Hover over, focus, or tap **?** beside **Chunking** for a plain-language explanation. See [Creation processing settings](reference.md#creation-processing-settings) for exact defaults, limits, and an example of how the search distance affects chunk size.
5. In **Review**, check the book order and settings, then choose **Create World**. Uploads begin now. All books are converted and chunked before any embedding requests are sent.

Closing the creation window before selecting **Create World** clears its name, selected books, and processing settings. Reloading also loses these unsaved selections. Once submitted, the attempt and its processing progress are saved locally.

## Follow progress

The pending world appears in your collection immediately, labeled **Creating**, **Paused**, or **Attention**. **Attention** appears in red when processing fails. Open the card to see books complete above the total chunks embedded, followed by each book's progress or error explanation. You can close the modal or browser while the backend is processing. Completion changes the same card into a completed world without navigating away.

**Pause** stops processing after the current operation. **Resume** continues using saved results. Closing the launcher stops processing; after restarting VySol, open the pending card and choose **Resume**. VySol never restarts paid API requests automatically.

Completed uploads and processing checkpoints survive restarts. If an upload did not finish, **Resume** retries it while its file remains available in the browser session. After a reload loses that file selection, discard the attempt and start again. A request whose response was lost before its checkpoint may be repeated and billed again.

## Retry or discard an attempt

Submission fixes the world name, book list, order, model, key selection, and chunk settings. Submitted attempts cannot be edited, including while paused or failed. To change them or correct a source file, discard the attempt and start again.

Failures show an explanation beside the affected book. **Resume** retries processing with the same settings and reuses completed embeddings. For temporary Google failures, retry when the service or your allowance is available. For an invalid key, pause processing and replace that saved key's secret in **Settings > Providers**, then resume. If the credential was deleted, discard and start again with another key.

For file problems, see [supported books and limits](reference.md#supported-books) and [duplicate names](reference.md#duplicate-book-names). All books must succeed before the world is accepted.

**Discard** asks for confirmation, stops processing, and removes that unfinished attempt and its saved work. Closing the modal after submission keeps that attempt. Only one unfinished attempt is supported at a time.

Accepted source books cannot be removed, replaced, reordered, or extended. Older worlds remain as they were; they are not automatically embedded or assigned a historical book order. Reading, retrieval, scene extraction, graph indexing, and roleplay are not part of this flow yet.
