# PDF Parser

PDF Parser is VySol's backend ingestion parser for turning text-based `.pdf` source files into readable in-memory text. It uses PyMuPDF to open PDF files and extract plain text from pages without running OCR, extracting images, cleaning PDFs, chunking text, or saving the full parsed result.

This page is for developers, power users, and AI coding agents that need to understand the PDF parsing contract before changing source ingestion, parser selection, chunk generation, committed source records, dependencies, or logging.

## Why It Exists

VySol needs PDF sources to enter the same text-first ingestion path as TXT and EPUB files. Many story and reference sources are distributed as PDFs, but PDF files can mix selectable text, images, covers, diagrams, illustrated pages, or broken structure in the same document.

Keeping PDF parsing separate from chunking and storage lets future commit-time ingestion prove that usable text exists before source metadata, chunks, embeddings, graph extraction, or persistent records are created.

## Ownership Boundary

PDF Parser owns:

- Opening PDF files through PyMuPDF.
- Reading the current file contents at parse time.
- Extracting plain text from pages in page order.
- Allowing PDFs that contain images, covers, diagrams, or illustrated pages.
- Ignoring image content while still accepting the PDF if usable text exists.
- Rejecting broken PDFs and PDFs with no usable text before downstream source commit work.
- Logging successful parse summaries at `INFO` without parsed text.
- Logging missing, non-file, or unavailable current PDF files at `WARNING`.
- Logging no-usable-text PDFs at `WARNING`.
- Logging broken PDF files, PyMuPDF failures, or unexpected extraction failures at `ERROR`.

PDF Parser does not own:

- OCR, image extraction, PDF cleanup, PDF repair, or visual analysis.
- Saving full parsed text to files, databases, manifests, or logs.
- Splitting chunks, calculating overlap, assigning source IDs, book numbers, chunk IDs, or hashes.
- Creating committed source metadata or chunk records.
- Creating embeddings, graph records, retrieval records, HTTP responses, UI state, or user-facing upload controls.

## Normal Flow

Backend ingestion code passes a PDF file path to the parser. The parser opens the current file at that path with PyMuPDF as a PDF document, walks pages in document order, and asks each page for plain text with sorted extraction.

Pages whose extracted text is only whitespace are skipped. Text-bearing pages are joined with blank lines. The returned string is the only successful output. The parser does not save source text, extract images, invoke OCR, chunk text, or create storage records. Later ingestion systems can pass the returned string into Main Chunk Generation only after this parse succeeds.

## Inputs

PDF Parser receives one source file path for a PDF file. It reads the file through PyMuPDF and receives page objects from that library.

It does not receive database connections, splitter settings, source metadata, provider responses, saved manifests, user-facing request objects, OCR settings, or image-processing settings.

## Outputs

The system returns an in-memory Python string containing extracted PDF text in page order. It also emits safe logs that can include page counts, text-bearing page counts, and character counts, but must not include parsed text or sensitive local path detail.

It does not create saved source text, final chunk objects, database rows, files, embeddings, graph records, HTTP responses, UI state, or saved progress.

## Failure Behavior

If the current path is missing, not a file, unavailable, broken, or contains no usable text, PDF Parser raises a PDF parse error. Missing, non-file, and unavailable current-file states are logged at `WARNING`; broken PDF, PyMuPDF, and unexpected extraction failures are logged at `ERROR`; no-usable-text PDFs are logged at `WARNING`. This blocks later source commit work from treating a missing, broken, scanned, or image-only PDF as usable input.

Logs must never include parsed PDF text or raw local paths.

## System Interactions

PDF Parser currently interacts with:

- Main Chunk Generation, which can receive parsed PDF strings after this parser succeeds.
- Split Point Search, indirectly through Main Chunk Generation after parsing.
- Future source commit orchestration, which should parse successfully before committing source metadata or chunks.
- Committed Source Storage and Chunk Storage, which should receive caller-prepared records only after parsing and chunk preparation happen outside those repositories.
- The central logger, which records parse summaries and failures without source text.

It must stay separate from storage repositories, splitter internals, route handlers, embeddings, graph extraction, retrieval, and UI systems.

## Current Edge Cases

Internal edge cases:

- Multi-page text PDFs are extracted in page order.
- Missing current files are rejected with path-safe warnings.
- Directory paths are rejected with path-safe warnings.
- PDFs with text plus images succeed and ignore the image content.
- Image-only PDFs are rejected because they provide no usable text.
- Whitespace-only extracted content is rejected as no usable text.
- Broken or non-PDF files are rejected as unreadable PDF sources.
- Unexpected text extraction failures are converted into PDF parse errors.

Cross-system edge cases:

- Future source commit work must parse before saving source metadata or chunks.
- Source staging may have selected an earlier file version, but PDF Parser must parse the current file at the path it receives.
- Main Chunk Generation must receive parsed text, not PDF paths, page objects, image data, or raw bytes.
- Chunk Storage must not infer that parser success has already assigned chunk IDs, book numbers, source IDs, or storage records.
- Logs must stay safe for public repositories and local machines by avoiding parsed text and full local paths.

## Invariants

- PDF parsing must use PyMuPDF for text extraction.
- Parser success means usable in-memory text was produced, not that source commit or chunk storage has happened.
- Parser failure must block downstream commit-time ingestion for that source.
- Missing, non-file, or unavailable current files must fail with path-safe warnings.
- PDF Parser must not snapshot, copy, or compare selected source versions.
- Parsed text must not be saved or logged by this parser.
- Images must not be extracted or treated as text by this parser.
- OCR must not be invoked inside this parser.
- Valid extracted text must not be chunked, deduplicated, embedded, stored, or turned into graph records here.
- This system must remain parser-only with no splitter, storage, route, UI, provider, embedding, graph, retrieval, or manifest responsibilities.

## Implementation Landmarks

- `app/ingestion/parsing` owns PDF parsing.
- `tests/test_pdf_parser.py` covers page order, image-plus-text success, no-text rejection, broken PDF rejection, missing current files, directory current paths, extraction failure handling, and log safety.

## What AI/Coders Must Check Before Changing This System

Before editing PDF Parser, check:

- Whether the change belongs in PDF parsing or in future source commit orchestration, chunk generation, storage, routing, embeddings, graph extraction, retrieval, or UI behavior.
- Whether parsing still uses PyMuPDF plain text extraction.
- Whether no path invokes OCR, image extraction, PDF cleanup, or text storage.
- Whether successful parsing still returns only in-memory text.
- Whether missing or unavailable current files still fail safely without raw paths.
- Whether no text extraction path logs parsed source text.
- Whether image-only sources still fail and image-plus-text sources still parse the text.
- Whether parser failures still block downstream source commit work.
- Whether tests cover broken sources, no usable text, image handling, text order, extraction failures, and log safety.
