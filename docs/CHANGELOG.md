# Changelog

## 2026-09-25

### Added

- Added Chronicles with separate saved conversations in each World, book passage retrieval, streamed AI responses, Chronicle search, and shared chat settings.
- Added a Chronicle Chat Appearance setting for artwork shading during chat.

### Changed

- Ordered World cards by recorded activity and ranked World search results without changing card positions.

## 2026-09-23

### Added

- Added lossless book chunking and Gemini Embedding 2 embeddings. Chunking prefers paragraph breaks, line breaks, sentence punctuation, then spaces within a configurable search window.
- Added creation progress on world cards, independent processing for multiple worlds, pause/resume, saved checkpoints, and confirmed discard. Interrupted processing resumes only when requested.
- Added AI Connections settings with Google selection, reusable credential numbers, masked keys with explicit reveal, and locally stored API keys.
- Added world Overview pages with ordered stories, live chunk progress, and saved processing details.

### Changed

- Replaced the Create World dialog with a full page for books, embedding selection, and processing settings. Draft books can be reordered or removed before submission.
- Redesigned Worlds and Settings with full-page navigation, calmer artwork overlays, responsive cards, and reduced-motion support.
- Required every book to finish conversion, chunking, and embedding before accepting a world. Submitted attempts cannot be edited, and accepted book text and order stay fixed. Existing worlds are preserved without automatic embedding.

## 2026-09-20

- Added TXT and EPUB book imports with preserved originals, separate text copies, and per-world duplicate checks.

- Added Quickstart, world creation, reference, and development documentation, with updated documentation home and README links.

- Added stronger, smooth shelf wheel scrolling.
- Fixed shelf wheel scrolling and flashes when switching pages or hovering Create World.

- Added saved shelf/grid layouts and viewport-aware sizing.
- Redesigned Settings and the empty homepage, hid creation search, and added Logo 2 as the browser icon.

- Added world-search suggestions and temporary sample/empty homepage previews.
- Improved Settings contrast, aligned homepage titles, and returned successful creation to Worlds.

- Added the local Worlds homepage, world creation, and Developer settings.
- Added persistent worlds and recovery for interrupted book-import responses.
- Added a Windows launcher that prepares the app and stops its owned processes on close.

## 2026-09-19

- Added the Retype documentation site.
- Added VySol documentation branding and image assets.
- Added automatic GitHub Pages documentation deployment on documentation changes.
- Simplified the Retype documentation to a single landing page.
- Moved the changelog to `docs/CHANGELOG.md`.
- Fixed the Retype logo and transparent hero assets and removed landing-page metadata text.
