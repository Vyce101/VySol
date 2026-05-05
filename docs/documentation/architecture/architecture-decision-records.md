# Architecture Decision Records

Architecture Decision Records document meaningful technical decisions, the context behind them, and the trade offs accepted by the project.

## ADR 0001 - 05-05-2026 - Global SQLite Choice and Migration Strategy

**Status:** <span style="color: #22C55E; font-weight: 700;">Accepted</span>

**Supersedes:** None

**Superseded by:** None

**Owner(s)/Author(s):** Vyce101 and ChatGPT Assistant

**Affected Systems:** Backend storage, application startup, global database migrations, future world database boundaries

### Context of the problem

VySol needs a small, reliable foundation for app-global persistent state before adding world records, assets, ingestion, parser logic, chunk storage, or UI. The project also needs this storage to remain inside the repo-local user-owned area instead of an operating-system app-data directory.

The first bootstrap ticket established `user/data/app.sqlite` as the global application database location and required Python standard-library `sqlite3`, handwritten migrations, and `PRAGMA user_version` for schema versioning.

The database choice also needs to leave room for later separating global app state from per-world storage. Future worlds are expected to contain many chunks, nodes, and edges, with each item potentially carrying thousands of bits of text. Keeping the global database separate from future world databases should make world export easier, reduce the odds that corruption affects the whole app, and make simultaneous ingestion work easier to reason about later.

### Decision

Use a repo-local SQLite database at `user/data/app.sqlite` for global app storage.

Use Python standard-library `sqlite3` for database access, handwritten ordered migrations for schema changes, and `PRAGMA user_version` as the database schema version source.

Keep the first migration infrastructure-only. It creates only bootstrap metadata and sets schema version `1`; it does not create world records, asset records, ingestion tables, parser tables, chunk storage, or UI-facing data.

### Why this decision was made

The chosen approach keeps the storage foundation small, inspectable, and easy to package while the app is still early-stage. It avoids adding ORM or migration-framework complexity before the schema and application boundaries are mature.

SQLite is enough for the current app-global storage needs and should also support the expected later per-world storage shape: many chunks, nodes, and edges with substantial text payloads. The repo-local `user/data/` location keeps app data inside the project folder and avoids mixing application-owned storage with existing launcher runtime files.

### Decision Drivers

- Keep the bootstrap limited to global database infrastructure.
- Avoid storing user data outside the repo folder.
- Minimize dependency surface for early local app storage.
- Make migrations explicit and easy to inspect.
- Use a database that is enough for future world storage containing many chunks, nodes, and edges with substantial text payloads.
- Preserve a clear path to separate the global app database from future per-world databases.
- Make future world export simpler by keeping world data boundaries clear.
- Reduce the chance that one corrupted database damages all app and world data.
- Make future simultaneous ingestion easier by allowing work to target separate world databases instead of one shared global database.

### What it fixes

- Establishes a known global database location.
- Gives startup a way to create or open `app.sqlite`.
- Provides schema versioning through `PRAGMA user_version`.
- Gives future features a migration path before application data tables are added.
- Establishes a storage direction that can support future world exports.
- Creates a path toward separating global app state from per-world data to reduce whole-app corruption risk.
- Leaves room for future simultaneous ingest workflows that operate against separate world databases.

### Alternatives Considered

**SQLAlchemy and Alembic:** Stronger abstraction and migration tooling, but more dependency weight and conceptual overhead than needed for the bootstrap stage.

**aiosqlite:** Async-friendly if database calls later need to be awaited directly, but it adds a dependency and was not needed for the current startup bootstrap.

**Operating-system app-data folder:** Closer to packaged desktop-app conventions, but rejected because app data should not live outside this repo folder at this stage.

**`runtime/` storage:** Already existed for launcher logs and state, but was not chosen because it would blur launcher-owned runtime files with application-owned user data.

**Flat `user/app.sqlite`:** Simpler path, but less organized as more user-owned folders such as logs, cache, exports, or backups are added.

### Trade Offs

**Chosen approach benefits:** Minimal dependencies, simple packaging, direct transaction control, readable migrations, and a storage path that is easy to inspect and ignore from Git.

**Chosen approach costs:** Migrations must be maintained manually, schema evolution requires discipline, and the implementation provides less abstraction than an ORM.

**SQLAlchemy/Alembic benefits:** More mature migration ecosystem and database abstraction.

**SQLAlchemy/Alembic costs:** More moving parts, more learning overhead, and unnecessary dependency weight for the current bootstrap.

**aiosqlite benefits:** Better fit if future database work becomes heavily async.

**aiosqlite costs:** Extra dependency and no clear immediate benefit for this ticket.

### Consequences

#### Positive Consequences

- Startup can create and migrate the global app database before serving the app.
- Future schema changes have a clear migration mechanism.
- Local user data stays under ignored `user/` paths.
- The approach remains easy for a new developer to understand.
- Future world storage can be designed around clear per-world database boundaries.

#### Negative Consequences / Costs

- Migration ordering and transaction behavior must remain carefully maintained by hand.
- The project will need stronger migration review discipline as schema complexity grows.
- Future per-world database export, backup, recovery, and ingest rules still need to be designed.
- If future database access becomes async-heavy, the storage layer may need adaptation.

#### Future Consequences / Follow up work

- Add new handwritten migrations for future global settings and hub metadata.
- Decide the exact per-world database format before adding world records, assets, ingestion tables, parser tables, chunks, nodes, or edges.
- Revisit SQLAlchemy, Alembic, or `aiosqlite` only if schema complexity or async database usage justifies the dependency cost.
- Define backup, recovery, and export behavior before storing important user-created world data.

**Confidence:** High
