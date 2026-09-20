"""Coordinate independent per-file imports for a future application caller."""

from collections.abc import Iterable
from pathlib import Path

from filelock import Timeout

from .epub import extract_epub
from .import_logging import import_logger
from .models import ErrorCode, ImportFailure, ImportLimits, ImportResult, Upload
from .storage import book_destination, publish_book, validate_upload, world_storage
from .text import decode_text


def import_books(world_id: str, uploads: Iterable[Upload], *, data_dir: Path | str = "data",
                 limits: ImportLimits | None = None) -> list[ImportResult]:
    """Import in input order; failures never undo successful books in the batch.

    data_dir is relative to the caller's working directory unless absolute.
    The future app should pass its configured absolute runtime-data directory.
    """
    limits = limits or ImportLimits()
    root = Path(data_dir).resolve()
    uploads = list(uploads)
    results = []
    try:
        with import_logger(root) as logger:
            for index, upload in enumerate(uploads):
                try:
                    comparison_name, text_name = validate_upload(upload)
                    if len(upload.content) > limits.max_upload_bytes:
                        raise ImportFailure(ErrorCode.SIZE_LIMIT, "Upload exceeds the configured size limit.")
                    with world_storage(root, world_id) as books:
                        destination = book_destination(books, comparison_name)
                        text = (decode_text(upload.content) if upload.filename.lower().endswith(".txt")
                                else extract_epub(upload.content, limits))
                        if not text.strip():
                            raise ImportFailure(ErrorCode.EMPTY_BOOK, "The book contains no extractable text.")
                        book = publish_book(root, destination, world_id, upload, comparison_name, text_name, text)
                    results.append(ImportResult(upload.filename, book=book))
                    logger.info("Book import succeeded book_id=%s batch_index=%d", book.book_id, index)
                except ImportFailure as exc:
                    results.append(ImportResult(upload.filename, error=exc.code, message=str(exc)))
                    logger.warning("Book import rejected batch_index=%d code=%s", index, exc.code)
                except (OSError, Timeout):
                    results.append(ImportResult(upload.filename, error=ErrorCode.STORAGE_FAILURE,
                                                message="Book storage is unavailable; retry the import."))
                    logger.error("Book import failed batch_index=%d code=storage_failure", index)
    except (OSError, Timeout, ImportFailure):
        # Initialization can fail before per-file processing (for example a read-only data directory).
        results.extend(ImportResult(upload.filename, error=ErrorCode.STORAGE_FAILURE,
                                    message="Book storage or logging is unavailable; retry the import.")
                       for upload in uploads[len(results):])
    return results
