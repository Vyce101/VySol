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
| `frontend/src/ProvidersView.tsx` | Provider selection, numbered credentials, and explicit secret reveal and replacement. |
| `src/vysol/server.py` | Loopback HTTP boundary, lifecycle, static frontend, and artwork. |
| `src/vysol/creation_api.py` | Validated attempt, upload, and credential contracts. |
| `src/vysol/creation.py` | Independent per-world workers, recovery, and whole-world publication. |
| `src/vysol/creation_store.py` | SQLite checkpoints, operation IDs, ordered chunks, and vectors. |
| `src/vysol/embeddings.py` | Gemini requests, input formatting, vector validation, and bounded retries. |
| `src/vysol/credentials.py` | Injectable credential adapter and atomic local key files. |
| `src/vysol/books/` | Strict TXT/EPUB conversion, deterministic chunking, and legacy importer. |
| `src/vysol/worlds.py` | World metadata, listing, accepted book order, and settings. |
| `launcher/` | Windows preparation, readiness checks, and subprocess ownership. |

The browser submits a manifest, uploads all missing files, then starts processing. The submitted manifest cannot subsequently be edited. Bounded uploads and synchronous storage run outside the event loop. Each attempt has its own backend worker and stop signal, so several worlds can process independently. A lifetime file lock prevents a second worker service on the same runtime directory. An in-process guard protects starts, key changes, and publication.

Every book must upload, validate, convert, and chunk before embedding begins. Preparation failures are recorded per book and prevent all embedding requests. TXT decoding and EPUB extraction reuse the existing converters. Scene extraction and graph processing are not implemented.

The splitter preserves every Unicode code point of the working TXT in contiguous slices. It searches backward from the size limit, preferring paragraph boundaries, then line breaks, then `?`, `!`, or `.`, then whitespace, and finally a hard split. Within a boundary level it chooses the latest match. Punctuation stays in the preceding chunk; matching is character-based, without sentence parsing or abbreviation detection. Offsets count Python Unicode code points, not UTF-8 bytes or JavaScript UTF-16 units. Chunk settings satisfy `size > 0` and `0 <= search < size`.

`CHUNKER_VERSION` is 2; version 2 adds punctuation between line breaks and whitespace in the boundary priority. `CreationStore.add_chunks` records the version in each chunk's processing profile, which also contributes to its stable ID. Resume skips splitting for books already marked `chunked` and reuses their stored chunks and completed vectors. Updating the splitter does not automatically regenerate those chunks or rebuild accepted worlds. Newly generated chunks, including smaller replacements for an oversized input, use the current version.

The backend sends one chunk per Gemini request with retrieval-document formatting, `autoTruncate: false`, and 768 dimensions. The formatting prefix is separate from stored chunk text. Explicit size errors split only the affected chunk using the same boundary rules. Valid finite vectors are normalized and stored as little-endian float32 values. Transient failures retry at most four requests with cancellable backoff; other failures require attention. See Google's [embedding guide](https://ai.google.dev/gemini-api/docs/embeddings) and [REST configuration](https://ai.google.dev/api/embeddings#EmbedContentConfig).

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

Before submission, setup values and File objects exist only in the mounted creation component. Navigating to **AI Connections** keeps that component mounted so the Settings X can return to the draft. A page reload loses unsubmitted file selections. Successful submission clears the draft; the next Create World page starts fresh with the last submitted model/key defaults and standard chunk settings.

Submission begins durable recovery by saving the manifest before uploading books. Leaving the page while submission is in flight does not interrupt the uploads. Once an attempt exists, leaving preserves it; deletion requires the separate confirmed discard action.

Mutation commands carry a stable operation UUID and an expected revision. Replaying the same command returns saved state; reuse with different input or a stale revision is rejected. The browser retries an uncertain upload with the same operation ID. Incomplete uploads can retry while the browser retains their File objects; after reload, unavailable files require discarding and starting again.

Successful vectors checkpoint individually. Startup reconciles an interrupted directory publication by its creation ID; otherwise interrupted running work becomes paused without making API requests. A response lost before its checkpoint can cause a repeated billable request. Completed work is reused on resume. Submitted manifests are immutable: new save commands are rejected even while paused or failed. Exact operation replays still reconcile uncertain responses. Changing sources, order, or configuration requires discarding and starting a new attempt. The secret of the selected named credential may be replaced while processing is stopped.

Publication verifies text coverage and file digests, then atomically renames a complete prepared world directory into `worlds/`. The final SQLite checkpoint may be recovered from that directory. `sources_locked` prevents the shared importer from appending to accepted worlds. Old worlds retain their existing files and are not migrated or embedded. Discard stops the worker before deleting only the attempt's owned directory and cascading its SQLite records.

Secrets are plain-text UTF-8 files in the runtime `credentials/` folder. The default runtime directory is ignored by the repository, and the adapter writes a folder-level `.gitignore` for custom locations. Updates replace files atomically; failed replacements retain the previous secret. SQLite stores provider groups and credential sequence numbers; a new credential takes the lowest available number. Ordinary API responses contain identifiers and labels, not secrets. Explicit local key reveal is uncached and must not be logged. A running attempt's selected credential cannot be changed or removed. `create_app` accepts injected `vault` and `embedder` adapters for tests. Copy runtime data with the launcher stopped. Full runtime backups include the key files and must be kept private.

## Local API contract

Paths below are relative to the server. Ordinary responses contain public IDs, sanitized errors, per-book states, and aggregate progress. The explicit credential reveal route returns a saved secret to the local client.

| Method and path | Contract |
| --- | --- |
| `GET /api/health` | `status: ready`, `app: vysol`. |
| `GET /api/worlds` | Accepted worlds with book counts, ordered by last use or creation. |
| `GET /api/worlds/{id}` | Accepted or unfinished world details: ordered books, source lock, state, progress, and nullable processing settings. |
| `GET /api/worlds/{id}/books` | Book metadata, ordered by explicit positions where available. |
| `GET /api/creation` | Most recently updated unfinished attempt or null, retained for compatibility. |
| `GET /api/creations` | All unfinished attempts. |
| `GET /api/creation/{id}` | Specific attempt, including completed state for reconciliation. |
| `PUT /api/creation/{id}` | Manifest: operation ID, revision, name, key ID, config `{model,size,search}`, ordered books `{id,filename,size}`. |
| `PUT /api/creation/{id}/books/{book_id}` | Raw bytes, percent-encoded `X-Filename`, query `revision` and `operation_id`. |
| `POST /api/creation/{id}/start` | Start/resume with revision and operation ID. |
| `POST /api/creation/{id}/pause` | Pause with revision. |
| `DELETE /api/creation/{id}` | Discard with revision query; accepted worlds reject this action. |
| `GET /api/providers` | Provider groups and numbered credential metadata, supported models, and last submitted model/key defaults. |
| `POST /api/providers/connections` | Idempotently add the Google provider group. |
| `PUT /api/providers/connections/{id}` | Enable or disable a provider group while preserving credentials. |
| `PUT /api/providers/keys/{id}` | Name, provider `google`, optional connection ID, and optional write-only secret; a new key requires a secret. The response includes a stable sequence number. |
| `GET /api/providers/keys/{id}/secret` | Explicit uncached local reveal of a saved key. |
| `DELETE /api/providers/keys/{id}` | Delete secret and metadata unless used by running work. |
| `GET`, `PUT /api/settings` | Existing background speed and shelf/grid settings. |
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
