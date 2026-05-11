# EPUB Parser

EPUB Parser is VySol's backend ingestion parser for turning supported `.epub` source files into readable in-memory text. It uses EbookLib to read EPUB structure, follows the EPUB spine as the reading order, and uses BeautifulSoup4 to extract text from EPUB XHTML and HTML documents.

This page is for developers, power users, and AI coding agents that need to understand the EPUB parsing contract before changing source ingestion, parser selection, chunk generation, committed source records, dependencies, or logging.

## Why It Exists

VySol needs EPUB sources to enter the same text-first ingestion path as other parsed source files. EPUB files are structured archives with manifest entries, images, navigation files, and reading-order metadata, so parsing must follow the spine instead of arbitrary archive or manifest order.

Keeping EPUB parsing separate from chunking and storage lets future commit-time ingestion prove that usable text exists before source metadata, chunks, embeddings, graph extraction, or persistent records are created.

## Ownership Boundary

EPUB Parser owns:

- Opening EPUB files through EbookLib.
- Reading EPUB document items in spine order.
- Extracting readable text from spine XHTML and HTML with BeautifulSoup4.
- Ignoring EPUB images when usable text exists elsewhere in the source.
- Preserving meaningful paragraph and line structure where practical.
- Rejecting malformed EPUB files and EPUB files with no usable text before downstream source commit work.
- Logging successful parse summaries at `INFO` without parsed text.
- Logging malformed EPUB or no-usable-text rejection at `WARNING`.
- Logging unexpected EPUB read or HTML extraction failures at `ERROR`.

EPUB Parser does not own:

- OCR, image extraction, EPUB editing, or EPUB repair.
- Using ZIP order, manifest order, filesystem order, or any random internal file order as a reading order.
- Saving full parsed text to files, databases, manifests, or logs.
- Splitting chunks, calculating overlap, assigning source IDs, book numbers, chunk IDs, or hashes.
- Creating committed source metadata or chunk records.
- Creating embeddings, graph records, retrieval records, HTTP responses, UI state, or user-facing upload controls.

## Normal Flow

Backend ingestion code passes an EPUB file path to the parser. The parser opens the file with EbookLib, walks the EPUB spine, resolves each spine item ID to a document item, and skips non-document spine items.

For each spine document, the parser reads the document content, removes non-readable HTML such as scripts, styles, navigation, metadata, and SVG content, then extracts block-aware text with BeautifulSoup4. Inline text inside a readable block is joined with spaces, readable blocks are joined with line breaks, and separate spine documents are joined with blank lines.

The returned string is the only successful output. The parser does not save source text, extract images, chunk text, or create storage records. Later ingestion systems can pass the returned string into Main Chunk Generation only after this parse succeeds.

## Inputs

EPUB Parser receives one source file path for an EPUB file. It reads the file through EbookLib and receives EPUB structure, spine entries, and document bytes from that library.

It does not receive database connections, splitter settings, source metadata, provider responses, saved manifests, user-facing request objects, or image-processing settings.

## Outputs

The system returns an in-memory Python string containing extracted EPUB text in spine order. It also emits safe logs that can include document counts and character counts, but must not include parsed text or sensitive local path detail.

It does not create saved source text, final chunk objects, database rows, files, embeddings, graph records, HTTP responses, UI state, or saved progress.

## Failure Behavior

If the EPUB is malformed, unreadable, has an invalid spine entry, or contains no usable text, EPUB Parser logs a `WARNING` and raises an EPUB parse error. This blocks later source commit work from treating a broken or image-only source as usable input.

If EbookLib, BeautifulSoup4, or HTML extraction fails unexpectedly, EPUB Parser logs an `ERROR` and raises an EPUB parse error. Logs must never include parsed book text.

## System Interactions

EPUB Parser currently interacts with:

- Main Chunk Generation, which can receive parsed EPUB strings after this parser succeeds.
- Split Point Search, indirectly through Main Chunk Generation after parsing.
- Future source commit orchestration, which should parse successfully before committing source metadata or chunks.
- Committed Source Storage and Chunk Storage, which should receive caller-prepared records only after parsing and chunk preparation happen outside those repositories.
- The central logger, which records parse summaries and failures without source text.

It must stay separate from storage repositories, splitter internals, route handlers, embeddings, graph extraction, retrieval, and UI systems.

## Current Edge Cases

Internal edge cases:

- Spine order controls parsed output order even when manifest or archive order differs.
- Non-document spine items are skipped rather than parsed as text.
- Missing or invalid spine document references are rejected as malformed EPUB structure.
- Image-only EPUBs are rejected because they provide no usable text.
- EPUBs with images plus readable text succeed and ignore images.
- Whitespace-only extracted content is rejected as no usable text.
- Non-readable HTML tags are removed before text extraction.
- Inline text within readable blocks is joined with spaces.
- Separate readable blocks are joined with line breaks.
- Separate spine documents are joined with blank lines.

Cross-system edge cases:

- Future source commit work must parse before saving source metadata or chunks.
- Main Chunk Generation must receive parsed text, not EPUB paths, archive entries, or raw document bytes.
- Chunk Storage must not infer that parser success has already assigned chunk IDs, book numbers, source IDs, or storage records.
- Logs must stay safe for public repositories and local machines by avoiding parsed text and full local paths.

## Invariants

- EPUB parsing must follow the EPUB spine and must not fall back to random archive, manifest, or filesystem order.
- Parser success means usable in-memory text was produced, not that source commit or chunk storage has happened.
- Parser failure must block downstream commit-time ingestion for that source.
- Parsed text must not be saved or logged by this parser.
- Images must not be extracted or treated as text by this parser.
- Valid extracted text must not be chunked, deduplicated, embedded, stored, or turned into graph records here.
- This system must remain parser-only with no splitter, storage, route, UI, provider, embedding, graph, retrieval, or manifest responsibilities.

## Implementation Landmarks

- `app/ingestion/parsing` owns EPUB parsing.
- `tests/test_epub_parser.py` covers spine order, text extraction structure, image-only rejection, image-plus-text success, malformed EPUB rejection, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing EPUB Parser, check:

- Whether the change belongs in EPUB parsing or in future source commit orchestration, chunk generation, storage, routing, embeddings, graph extraction, retrieval, or UI behavior.
- Whether parsing still follows the EPUB spine only.
- Whether no fallback order can accidentally parse documents out of reading order.
- Whether successful parsing still returns only in-memory text.
- Whether no text extraction path logs parsed book text.
- Whether image-only sources still fail and image-plus-text sources still parse the text.
- Whether parser failures still block downstream source commit work.
- Whether tests cover spine order, malformed sources, no usable text, image handling, text structure, and log safety.
