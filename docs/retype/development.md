---
order: 60
---
# Development

VySol currently runs a React/TypeScript browser interface and a Python processing layer on one local FastAPI server. This page documents the boundaries and recovery rules that matter when changing that implementation. User-facing options and limits are in [Reference](reference.md).

## Run from source

Use Python 3.12 and uv. The current frontend toolchain requires Node.js `^20.19.0 || >=22.12.0`; Node.js 24 with npm is the Windows Quickstart path. Python dependencies are locked in `uv.lock`; frontend dependencies are locked in `frontend/package-lock.json`.

From the repository root:

```shell
uv sync --locked
npm ci --prefix frontend
npm run build --prefix frontend
uv run uvicorn vysol.server:create_app --factory --host 127.0.0.1 --port 8765 --no-access-log
```

Open `http://127.0.0.1:8765/` after startup. This command runs the server directly; it does not provide the Windows launcher's browser opening or process supervision. Stop it with Ctrl+C. For normal Windows startup, use `Start.cmd` instead.

The frontend is served from `frontend/dist/client/`. Rebuild after frontend changes; restart the server after Python changes. The static worker output produced by the build does not implement the Python API and is not a standalone working VySol backend.

`VYSOL_DATA_DIR` selects runtime storage. Without it, direct server invocation resolves `data/` against the current working directory; `Start.cmd` runs from the repository root. `VYSOL_PORT` is a launcher option; direct uvicorn invocation uses its `--port` argument.

## Boundaries and flow

| Area | Responsibility |
| --- | --- |
| `frontend/src/CreateWorld.tsx` | Unsubmitted page, ordered selections, uploads, and progress. |
| `frontend/src/ChroniclesView.tsx`, `ChronicleChat.tsx`, and `ChronicleSettingsDrawer.tsx` | Chronicle lists, conversation and local drafts, streamed response display, and shared drawer settings. |
| `frontend/src/ProvidersView.tsx` and `EmbeddingProfiles.tsx` | Built-in provider groups, named credentials, model refresh, and World embedding choices. |
| `src/vysol/server.py` | Loopback HTTP boundary, lifecycle, static frontend, and artwork. |
| `src/vysol/creation_api.py` | Validated attempt, upload, and credential contracts. |
| `src/vysol/creation.py` | Independent per-world workers, recovery, and whole-world publication. |
| `src/vysol/creation_store.py` | SQLite checkpoints, operation IDs, ordered chunks, and vectors. |
| `src/vysol/chronicles.py` and `chronicles_api.py` | Chronicle persistence, retrieval, provider streaming, and local HTTP contracts. |
| `src/vysol/provider_catalog.py` and `provider_profiles.py` | Per-credential model discovery, cached capability data, and coded model profiles. |
| `src/vysol/chat_requests.py` | Chat request translation for each provider API. |
| `src/vysol/embedding_profiles.py` and `embedding_profiles_api.py` | Saved embedding choices, World vector specifications, and safe credential replacement. |
| `src/vysol/embeddings.py` | Provider embedding requests, vector validation, and bounded retries. |
| `src/vysol/credentials.py` | Injectable credential adapter and atomic local key files. |
| `src/vysol/books/` | Strict TXT/EPUB conversion, deterministic chunking, and legacy importer. |
| `src/vysol/worlds.py` | World metadata, listing, accepted book order, and settings. |
| `launcher/` | Windows preparation, readiness checks, and subprocess ownership. |

The browser submits a manifest, uploads all missing files, then starts processing. The submitted manifest cannot subsequently be edited. Bounded uploads and synchronous storage run outside the event loop. Each attempt has its own backend worker and stop signal, so several worlds can process independently. A lifetime file lock prevents a second worker service on the same runtime directory. An in-process guard protects starts, key changes, and publication.

Every book must upload, validate, convert, and chunk before embedding begins. Preparation failures are recorded per book and prevent all embedding requests. TXT decoding and EPUB extraction reuse the existing converters. Scene extraction and graph processing are not implemented.

The splitter preserves every Unicode code point of the working TXT in contiguous slices. It searches backward from the size limit, preferring paragraph boundaries, then line breaks, then `?`, `!`, or `.`, then whitespace, and finally a hard split. Within a boundary level it chooses the latest match. Punctuation stays in the preceding chunk; matching is character-based, without sentence parsing or abbreviation detection. Offsets count Python Unicode code points, not UTF-8 bytes or JavaScript UTF-16 units. Chunk settings satisfy `size > 0` and `0 <= search < size`.

`CHUNKER_VERSION` is 2; version 2 adds punctuation between line breaks and whitespace in the boundary priority. `CreationStore.add_chunks` records the version in each chunk's processing profile, which also contributes to its stable ID. Resume skips splitting for books already marked `chunked` and reuses their stored chunks and completed vectors. Updating the splitter does not automatically regenerate those chunks or rebuild accepted worlds. Newly generated chunks, including smaller replacements for an oversized input, use the current version.

Chronicle retrieval leaves stored chunks and embeddings unchanged. It embeds only the latest user message with the World's Embedding Profile, compares that vector with normalized vectors from the selected World, and keeps up to the configured number above Minimum Similarity. The preceding source characters are reconstructed from earlier contiguous chunks, so overlap can cross more than one chunk. The chat request includes previous user and answer text, selected passages with book names and source offsets, and the latest message. No roleplay system instruction or history truncation is added. The shared Chronicle chat credential never selects the retrieval embedding credential.

The backend sends one chunk per embedding request and checks the returned dimensions against the World's saved vector specification. New profiles use the model's highest known dimensions and input limit; a selected smaller OpenAI dimension is sent with each request. Keyless OpenAI-compatible embedding servers are supported when their fixed Base URL does not require a key. An unknown compatible embedding model must pass a preflight check before processing. Existing 768-dimensional Google Worlds retain their original input formatting and query prefix through a saved format version. Explicit size errors split only the affected chunk using the same boundary rules. Valid finite vectors are normalized and stored as little-endian float32 values. Transient failures retry with cancellable backoff; other failures require attention. See [Google embeddings](https://ai.google.dev/gemini-api/docs/embeddings) and [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings).

## Provider and model contracts

Model catalogs belong to individual credentials. Startup refreshes stale catalogs; saving a new credential or replacing its key and an explicit refresh also request an update. A failed refresh keeps the last successful catalog and reports its error and staleness. Catalog models are normalized into profiles with chat, embedding, token-limit, reasoning, and thinking capabilities. Chronicle request translation uses known capabilities to select supported controls and omit unsupported provider-specific fields; explicitly saved compatible overrides are forwarded. `create_app(..., catalog_client=...)` accepts an injected catalog HTTP client alongside `vault`, `embedder`, and `chat_client`.

| Provider | Model discovery | Chronicle chat | Embeddings |
| --- | --- | --- | --- |
| Google | Gemini model list | Gemini Interactions or streaming Generate Content | Gemini `embedContent` |
| OpenAI | `/v1/models` | Responses API | `/v1/embeddings` |
| Anthropic | `/v1/models` | Messages API | — |
| DeepSeek | `/models` | Chat Completions | — |
| OpenAI-compatible | Configured `/models` | Configured Chat Completions | Configured `/embeddings` |

Embedding Profiles select a credential, model, dimensions, and the model's highest known input limit. Only Google, OpenAI, and OpenAI-compatible credentials can back them. Worlds snapshot the vector specification, and Chronicle retrieval always uses that profile, independently of the shared chat connection. Create World uses the last-used profile, falling back to the configured default. Moving a World to another profile requires the same provider, model, dimensions, input format, and compatible Base URL. Credential deletion is blocked while any Embedding Profile references it or an unfinished creation depends on it.

## Persistence and recovery

```text
data/
  processing.sqlite3               # Attempts, chunks, vectors, labels, preferences, operation IDs
  credentials/
    .gitignore                     # Ignores all contents, including temporary writes
    <credential UUID>.key          # Plain-text secret; returned only by explicit reveal
  creations/<attempt UUID>/
    books/<book UUID>/source        # Original uploaded bytes
    books/<book UUID>/text          # UTF-8 working text
    world/                         # Complete directory prepared for publication
  worlds/<SHA-256 of world ID>/
    world.json
    artwork.png                    # Optional runtime artwork
    books/<SHA-256 of comparison name>/
      original/<uploaded filename>
      text/<working filename>
      metadata.json
  settings.json
  locks/
  staging/                         # Legacy standalone importer
  logs/
  frontend-build.json
```

The attempt UUID becomes the world ID. Stable book IDs survive reordering. Chunk IDs derive from the book, source span, text digest, and processing profile. SQLite stores explicit positions, offsets, source text digests, model, dimensions, and processing versions. These are source locations, not fictional chronology.

The same SQLite database stores World-scoped Chronicles, ordered messages, generation request IDs, and one shared Chronicle settings record. A client-generated request UUID prevents duplicate user messages on retry. One generation can run per Chronicle. User input is saved before retrieval and generation; streamed answer and readable thinking are saved separately. Stopping or failing preserves any usable partial result. A discarded unfinished World also loses its Chronicles. The browser receives distinct SSE events for user creation, thinking, answer, completion, and failure, and applies the selected answer reveal speed locally.

Unsent Chronicle drafts remain in `ChronicleChat` component state, keyed by Chronicle ID. They are not stored in SQLite. The component stays mounted while switching Chronicles in one World, so each draft returns when that Chronicle is reopened. Reloading or leaving and reopening the World loses those drafts. The message field recalculates its height from the active draft and scrolls internally after reaching its CSS height limit.

Before submission, setup values and File objects exist only in the mounted creation component. Navigating to **AI Connections** keeps that component mounted so the Settings X can return to the draft. A page reload loses unsubmitted file selections. Successful submission clears the draft; the next Create World page starts with the last used Embedding Profile or configured default and standard chunk settings.

Submission begins durable recovery by saving the manifest before uploading books. Leaving the page while submission is in flight does not interrupt the uploads. Once an attempt exists, leaving preserves it; deletion requires the separate confirmed discard action.

Mutation commands carry a stable operation UUID and an expected revision. Replaying the same command returns saved state; reuse with different input or a stale revision is rejected. The browser retries an uncertain upload with the same operation ID. Incomplete uploads can retry while the browser retains their File objects; after reload, unavailable files require discarding and starting again.

Successful vectors checkpoint individually. Startup reconciles an interrupted directory publication by its creation ID; otherwise interrupted running work becomes paused without making API requests. A response lost before its checkpoint can cause a repeated billable request. Completed work is reused on resume. Submitted manifests are immutable: new save commands are rejected even while paused or failed. Exact operation replays still reconcile uncertain responses. Changing sources, order, or configuration requires discarding and starting a new attempt. The secret of the selected named credential may be replaced while processing is stopped.

Publication verifies text coverage and file digests, then atomically renames a complete prepared world directory into `worlds/`. The final SQLite checkpoint may be recovered from that directory. `sources_locked` prevents the shared importer from appending to accepted worlds. Old worlds retain their existing files and are not migrated or embedded. Discard stops the worker before deleting only the attempt's owned directory and cascading its SQLite records.

Secrets are plain-text UTF-8 files in the runtime `credentials/` folder. The default runtime directory is ignored by the repository, and the adapter writes a folder-level `.gitignore` for custom locations. Updates replace files atomically; failed replacements retain the previous secret. SQLite stores provider groups, credential sequence numbers, per-credential model catalogs, and Embedding Profiles. A new credential takes the lowest available number. Ordinary API responses contain identifiers and labels, not secrets. Explicit local key reveal is uncached and must not be logged. OpenAI-compatible credentials may have no key; their Base URL is fixed after creation. `create_app` accepts injected `vault`, `embedder`, `chat_client`, and `catalog_client` adapters. Copy runtime data with the launcher stopped. Full runtime backups include the key files and must be kept private.

## Local API contract

Paths below are relative to the server. Ordinary responses contain public IDs, sanitized errors, per-book states, and aggregate progress. The explicit credential reveal route returns a saved secret to the local client.

| Method and path | Contract |
| --- | --- |
| `GET /api/health` | `status: ready`, `app: vysol`. |
| `GET /api/worlds` | Accepted worlds with book counts, ordered by last use or creation. |
| `GET /api/worlds/{id}` | Accepted or unfinished world details: ordered books, source lock, state, progress, nullable processing settings, and the active `embedding_profile` response. |
| `POST /api/worlds/{id}/activity` | Record activity for an accepted World. Opening a World in the interface does not call this route. |
| `GET /api/worlds/{id}/books` | Book metadata, ordered by explicit positions where available. |
| `GET /api/creation` | Most recently updated unfinished attempt or null, retained for compatibility. |
| `GET /api/creations` | All unfinished attempts. |
| `GET /api/creation/{id}` | Specific attempt, including completed state for reconciliation. |
| `PUT /api/creation/{id}` | Manifest: operation ID, revision, name, Embedding Profile ID, chunk config `{size,search}`, ordered books `{id,filename,size}`. The legacy `config.model` field is still accepted for old attempts; the profile controls new embeddings. The chosen profile and vector specification are snapshotted. |
| `PUT /api/creation/{id}/books/{book_id}` | Raw bytes, percent-encoded `X-Filename`, query `revision` and `operation_id`. |
| `POST /api/creation/{id}/start` | Start/resume with revision and operation ID. |
| `POST /api/creation/{id}/pause` | Pause with revision. |
| `DELETE /api/creation/{id}` | Discard with revision query; accepted worlds reject this action. |
| `GET /api/providers` | Built-in provider groups, credential metadata with cached model catalogs, and creation defaults. |
| `POST /api/providers/connections` | Idempotently select one of the built-in provider groups. |
| `PUT /api/providers/connections/{id}` | Enable or disable a provider group while preserving credentials. |
| `PUT /api/providers/keys/{id}` | Save a named provider credential. An OpenAI-compatible credential includes a fixed Base URL and may omit its key. The response includes a stable sequence number. |
| `GET /api/providers/keys/{id}/models` | Cached model catalog, last successful update time, last refresh error, and whether the catalog is stale. Each model includes normalized capability data. |
| `POST /api/providers/keys/{id}/models/refresh` | Refresh one credential's model list. A failure leaves the last successful list and its timestamp available. |
| `GET /api/providers/keys/{id}/secret` | Explicit uncached local reveal of a saved key. |
| `DELETE /api/providers/keys/{id}` | Delete secret and metadata unless any Embedding Profile references the credential or an unfinished creation depends on it. |
| `GET /api/embedding-profiles` | Profiles with provider, model, dimensions, maximum input size, usability, and World or pending-creation usage, plus default and last-used IDs. |
| `POST /api/embedding-profiles` | Create a named profile from a discovered Google, OpenAI, or OpenAI-compatible embedding model; omitted dimensions use the highest known value. |
| `PUT`, `DELETE /api/embedding-profiles/{id}` | Update or remove a profile, subject to World vector compatibility and usage checks. |
| `PUT /api/embedding-profiles/default` | Set or clear the default Create World profile with `{profile_id}`. |
| `POST /api/embedding-profiles/{id}/preflight` | Check an unknown compatible embedding model and record its returned dimensions. |
| `PUT /api/worlds/{id}/embedding-profile` | Move a World to an equivalent profile with the same provider, model, dimensions, endpoint, and input format. |
| `GET`, `PUT /api/settings` | Background transition speed, shelf/grid layout, and Chronicle Chat Appearance. |
| `GET`, `POST /api/worlds/{id}/chronicles` | List and create Chronicles for an accepted or unfinished World. |
| `GET`, `PATCH`, `DELETE /api/chronicles/{id}` | Chronicle detail, rename, and confirmed deletion from the interface. |
| `GET /api/chronicles/{id}/messages` | Saved messages in conversation order. |
| `POST /api/chronicles/{id}/messages/stream` | Send `{request_id,text}` and stream `user_message`, `thinking_delta`, `answer_delta`, `completed`, or `error` events. |
| `POST /api/chronicles/{id}/generations/{request_id}/stop` | Stop an active response and retain usable partial text. |
| `GET`, `PUT /api/chronicle-settings` | Shared model and connection, `output_limit` (`max` or a token count), capability-aware `reasoning`, optional `thinking_budget`, compatible-provider `compatible_overrides`, retrieval, streaming speed, section boundaries, and drawer section states. |
| `GET /api/worlds/{id}/artwork` | Registered artwork or bundled Frostwake. |

The old `POST /api/worlds` and `PUT /api/worlds/{id}/imports/{operation_id}` mutations return 410. They cannot bypass the new acceptance rules. Revision conflicts return 409; stream limits return 413; invalid input returns 422; handled storage failures return 503. The UI polls attempt state while work is pending.

The supported launcher binds to loopback. Middleware validates hosts and rejects cross-origin/cross-site browser requests. This is a local application boundary, not public-hosting authentication.

### Python importer

```python
from pathlib import Path
from vysol.books import Upload, import_books

results = import_books(
    "example-world",
    [Upload("Example.txt", b"An example story.")],
    data_dir=Path("data"),
)
for result in results:
    if result.error is not None:
        print(result.error, result.message)
    else:
        print(result.book.book_id)
```

`import_books(world_id, uploads, *, data_dir="data", limits=None)` processes uploads in input order and returns an `ImportResult` per file. Successful entries contain an `ImportedBook` with `book_id`, `world_id`, `original_path`, and `text_path`. Failed entries contain an error code and message. Earlier successes are retained.

The standalone importer accepts a 1–128 character world ID beginning with an ASCII letter or digit, followed by letters, digits, underscores, or hyphens, excluding reserved names. It does not create application world metadata. The HTTP application uses UUID creation attempts instead. This low-level importer is retained for existing callers and rejects worlds marked `sources_locked`; it is not the application creation flow.

Errors are `duplicate_name`, `unsupported_format`, `invalid_encoding`, `invalid_epub`, `invalid_input`, `empty_book`, `size_limit`, and `storage_failure`. Pass an `ImportLimits` instance to configure `max_upload_bytes`, `max_archive_entries`, or `max_uncompressed_bytes`; all must be positive. The API factory also accepts `limits` for embedded callers and tests.

## Windows lifecycle and logging

`Start.cmd` invokes the Python supervisor. The supervisor checks the port, runs locked dependency preparation, fingerprints frontend inputs, and rebuilds when the fingerprint changes or the built entrypoint is missing. Only after a successful health check does it open the browser.

`launcher/windows_job.py` creates children suspended, assigns them to a Windows Job Object with kill-on-close behavior, then resumes them. This ordering prevents setup tools from spawning unmanaged descendants before assignment. Closing the supervisor stops owned descendants. Startup failure or unexpected server exit closes the job and leaves the launcher window available for inspection. Do not replace this with process-name-based termination or include the user's browser in the owned job.

Application/import events use `books/import_logging.py`; launcher events use `launcher/start.py`. Both write to the terminal and runtime log files, rotating at 1 MiB with at most ten backups per log. Use operation IDs and error codes for diagnostics; do not add book contents or private filenames to routine logs.

## Verification and non-obvious checks

```shell
uv run pytest
npm test --prefix frontend
npm run build --prefix frontend
```

Tests are grouped under `tests/books/`, `tests/application/`, and `tests/launcher/`; frontend component tests live beside their features. Windows-specific lifecycle checks skip on other operating systems. Use synthetic books and temporary data directories.

When changing creation, preserve exact text reconstruction, original bytes, whole-batch acceptance, immutable sources, per-world name collisions, complete-directory publication, and digest-based reconciliation. Test retries, oversized-input splitting, missing credentials, submitted-manifest locking, restart recovery, and safe discard. Provider tests use synthetic text and mocked HTTP; an optional real-key smoke test must send only synthetic text and must not print the credential. Exercise interrupted writes and concurrent attempts, not only successful conversion.

When changing the UI, check rapid artwork switching and failed image loads: stale completions must not replace a newer preview. Leaving a card retains the preview, and search hover must not change it. Outgoing views must keep their geometry during fades. Check shelf/grid fit at both shorter desktop and narrow viewports, keyboard access, and reduced motion. Developer collection previews are session-only fixtures and must never seed or delete real worlds.

For launcher changes, check readiness failure, occupied ports, unexpected server exit, and descendant cleanup. Frontend build success alone does not verify any of these lifecycle or visual behaviors.

## Documentation changes

Retype source lives in `docs/retype/`. Build it locally with Retype CLI 4.6.0:

```shell
retype build docs/retype/retype.yml --output data/docs-preview
```

The configured labels and theme features require a Retype key. Without one, check the content locally using this PowerShell override, which leaves `retype.yml` unchanged:

```powershell
retype build docs/retype/retype.yml --output data/docs-preview --override '{"labels":null,"toc":null,"theme":null,"branding":{"baseColor":null}}'
```

This output stays in the ignored runtime directory. Check generated links and page navigation. The GitHub workflow in `.github/workflows/deploy-docs.yml` publishes documentation after qualifying pushes to `main`; a local build does not publish it.
