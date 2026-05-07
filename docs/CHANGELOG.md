# Changelog

All notable changes to VySol will be documented in this file.

## Unreleased

### Added

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
