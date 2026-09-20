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
| `frontend/src/` | Navigation, draft/file selections, import progress, search, artwork previews, and settings controls. |
| `src/vysol/server.py` | Local HTTP boundary, bounded upload reading, import receipts/reconciliation, and static frontend/artwork delivery. |
| `src/vysol/worlds.py` | World identity, metadata, listing order, and saved settings. |
| `src/vysol/books/` | Strict format conversion and per-book publication, independently callable from Python. |
| `launcher/` | Windows preparation, readiness checks, and ownership of app subprocesses. |

The browser creates a world, then uploads its selected books individually. Synchronous import work runs through `run_in_threadpool`, outside the API event loop. The API enforces the upload bound while consuming request chunks, before constructing the importer's in-memory `Upload`.

Conversion does not perform AI processing or produce structured story data. TXT decoding is in `books/text.py`; EPUB extraction uses ZIP reading, defusedxml package parsing, and Beautiful Soup content extraction in `books/epub.py`. Storage and coordination remain in separate modules.

## Persistence and recovery

World display names are not storage identities. The UI generates a UUID per creation draft; repeated creation requests with that UUID return the existing world. Reusing an ID with a different name does not rename it. Separate worlds may share a display name.

```text
data/
  worlds/<SHA-256 of world ID>/
    world.json
    artwork.png                    # Only for a world with custom runtime artwork
    books/<SHA-256 of comparison name>/
      original/<uploaded filename>
      text/<working filename>
      metadata.json
    imports/<operation UUID>.json
  settings.json
  locks/
  staging/
  logs/
  frontend-build.json
```

World metadata records `id`, `name`, `created_at`, `last_used_at`, and `artwork`. Book metadata records `book_id`, `world_id`, `original_filename`, `text_filename`, `comparison_name`, and `converter_version`. These records contain import identity, not story structure.

The importer locks a world while checking duplicate names, converting, and publishing. It prepares the original, working text, and metadata in one staging directory, then renames that directory into the destination. Handled failures clean up their staging directory and do not reserve a book name. A forcibly terminated process may leave unaccepted staging files; they are not treated as imported books. Do not replace this publication step with separate visible writes of the two copies.

World metadata and settings use locking and atomic JSON replacement. Settings default to `background_speed: normal` and `world_layout: shelf`; older files missing a setting receive its default. A speed-only update preserves the saved layout.

Each HTTP book attempt has a UUID. A pending receipt records its comparison name and original-content SHA-256 digest. Reconciliation can recognize a published book after interruption of the final receipt write only when both match. A completed receipt returns its recorded outcome; an active attempt remains pending, and an unconfirmed inactive attempt is unknown. A definitive failed attempt gets a new UUID when retried; an uncertain response keeps its UUID for reconciliation. Successful imports are not resent.

The React creation view stays mounted across tabs to retain files and foreground progress. File objects are never persisted across reloads. Creation and import success returns to Worlds; partial failure leaves the form available against the existing world.

## Local API contract

Paths below are relative to the server. Responses expose public identifiers, filenames, and user-readable outcomes; the HTTP layer does not return the importer's private filesystem paths.

| Method and path | Contract |
| --- | --- |
| `GET /api/health` | Returns `status: ready` and `app: vysol`. |
| `GET /api/worlds` | Lists world records, prioritizing recorded last-use time, otherwise creation time. |
| `POST /api/worlds` | JSON `{id, name}`. `id` is a UUID; `name` is nonblank, at most 200 characters, and stored with surrounding whitespace trimmed. Creation is idempotent by ID. |
| `GET /api/worlds/{world_id}/books` | Lists `id`, `filename`, and `comparison_name` for accepted books. |
| `PUT /api/worlds/{world_id}/imports/{operation_id}` | Raw file bytes; percent-encoded filename in `X-Filename`. Normal result contains `status: done`, `filename`, `book_id`, `error`, and `message`. |
| `GET /api/worlds/{world_id}/imports/{operation_id}` | Reconciles an attempt; status is `unknown`, `pending`, or `done`. Clients must not assume every status has the same fields. |
| `GET /api/settings` | Returns `background_speed` and `world_layout`. |
| `PUT /api/settings` | Requires `background_speed` (`fast`, `normal`, `slow`); optional `world_layout` (`shelf`, `grid`). Returns saved settings. |
| `GET /api/worlds/{world_id}/artwork` | Serves the registered runtime artwork or bundled Frostwake; accepts no arbitrary filesystem path. |

HTTP 200 does not guarantee book success: inspect `error` in the result. Exceeding the stream limit returns HTTP 413. Invalid request fields produce 422, missing worlds produce 404, and handled storage failures produce 503 with a public message.

The server binds to loopback through the supported commands. Middleware validates the host and rejects cross-origin/cross-site browser requests. This is a local application boundary, not an authentication system for public hosting.

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

The standalone importer accepts a 1–128 character world ID beginning with an ASCII letter or digit, followed by letters, digits, underscores, or hyphens, excluding reserved names. It does not create application world metadata. The HTTP application uses UUIDs and must create its world first.

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

When changing imports, preserve original bytes, strict decoding, per-world name collisions, complete-directory publication, and digest-based reconciliation. Exercise interrupted writes and concurrent attempts, not only successful conversion.

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
