# Changelog

All notable changes to VySol will be documented in this file.

## Unreleased

### Changed

- Changed staged source access and parser read failures so current missing or unreadable source files fail with path-safe warnings.
- Changed main chunk generation to return separate previous-context overlap for each chunk.
- Changed main chunk generation to include character offsets with each returned chunk.
- Changed committed world timestamps to ISO 8601 UTC format for naturally sortable SQLite values.
- Hardened world splitter settings storage so locked settings stay unchanged and splitter version stays backend-controlled.

### Added

- Added temporary parsed source output preparation so staged sources parse in order before future commit work.
- Added a Temporary Parsed Source Outputs concept page.
- Added temporary ingestion workspaces so each Start or Resume attempt has isolated non-committed scratch storage.
- Added a Temporary Ingestion Workspace concept page.
- Added backend ingestion attempt state tracking for idle, running, stopping, paused, and complete ingestion lifecycles.
- Added an Ingestion Attempt State concept page.
- Added backend staged source duplicate preflight so exact duplicate source content is rejected within the same world before book numbers are assigned.
- Added backend staged source hash preflight so readable staged source files can receive temporary SHA-256 hashes before future duplicate checks and commit logic.
- Added a Staged Source Hash Preflight concept page.
- Added backend staged source file access validation so missing or unreadable selected files can block future ingestion before parsing or commit work starts.
- Added a Staged Source File Access Validation concept page.
- Added graceful staged source removal protection so committed source removal attempts leave world data unchanged.
- Added backend staged source reorder guards that keep committed sources locked while preserving staged order.
- Added temporary in-memory source staging state for draft and existing-world add-source flows.
- Added a backend source type selection filter that keeps every selected source visible while blocking ingestion when unsupported file types are staged.
- Added a Source Type Selection Filter concept page.
- Added a backend source parser router for staged TXT, EPUB, and PDF sources.
- Added a Source Parser Router concept page.
- Added a backend PDF parser for extracting in-memory text from text-based PDF files.
- Added a PDF Parser concept page.
- Added a backend EPUB parser for extracting in-memory text from EPUB files in reading order.
- Added an EPUB Parser concept page.
- Added a backend TXT parser for clean in-memory text decoding before future source commits.
- Added a TXT Parser concept page.
- Added main chunk generation for ordered in-memory chunks from parsed text.
- Added backend split-point search for choosing one character-based ingestion boundary.
- Added a Split Point Search concept page.
- Added backend fallback deletion for uploaded assets used by committed worlds after affected worlds are confirmed.
- Added backend deletion for unused uploaded assets while protecting built-in and in-use assets.
- Added backend validation for uploaded font files before they are stored.
- Added a Font Upload Validation concept page.
- Added backend validation for uploaded image files before they are stored.
- Added safe backend storage for uploaded image and font asset files.
- Added a Safe Asset File Storage concept page.
- Added a backend asset deduplication helper that can identify already-known files before future upload storage creates another asset record.
- Added an Asset Hash Deduplication concept page.
- Added chunk storage in each world database with separate book numbers, chunk numbers, and overlap text.
- Added a Chunk Storage concept page.
- Added committed source metadata storage in each world database.
- Added a Committed Source Storage concept page.
- Added world-level splitter settings storage in each world database.
- Added a World Splitter Settings Storage concept page.
- Added per-world SQLite bootstrap for committed world databases.
- Added a World Database Bootstrap concept page.
- Added UUID-based committed world folder bootstrap under user-owned storage.
- Added splitter version metadata to draft world splitter settings.
- Added backend checks that reject invalid draft world splitter settings before future ingestion uses them.
- Added in-memory draft world splitter defaults for uncommitted ingestion setup.
- Added last-used timestamps so committed worlds can be sorted by most recent use.
- Added committed world index storage for saving committed world names, descriptions, and selected assets.
- Added a Committed World Index Storage concept page.
- Added seeded built-in default image and font asset references.
- Added asset metadata storage for image and font records.
- Added the global SQLite app database bootstrap with `PRAGMA user_version` migrations.
- Added a minimal FastAPI backend startup path and health check.
- Added pinned backend runtime requirements and `run.bat` dependency verification.
- Added Architecture documentation with the first Architecture Decision Record.
- Added the Guides parent documentation page.
- Added a Global App Storage concept page.
- Added the QUICKSTART documentation page.
- Expanded the README and Retype documentation home page.
- Added GitHub Pages documentation deployment with Retype.
- Added starter documentation structure under `docs`.
- Added safe launcher and update script skeletons for future app startup.
