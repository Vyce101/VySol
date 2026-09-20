"""Public inputs and outcomes for book imports."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ErrorCode(StrEnum):
    DUPLICATE_NAME = "duplicate_name"
    UNSUPPORTED_FORMAT = "unsupported_format"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_EPUB = "invalid_epub"
    INVALID_INPUT = "invalid_input"
    EMPTY_BOOK = "empty_book"
    SIZE_LIMIT = "size_limit"
    STORAGE_FAILURE = "storage_failure"


class ImportFailure(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Upload:
    filename: str
    content: bytes


@dataclass(frozen=True)
class ImportLimits:
    max_upload_bytes: int = 100 * 1024 * 1024
    max_archive_entries: int = 10_000
    max_uncompressed_bytes: int = 500 * 1024 * 1024

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("Import limits must be positive.")


@dataclass(frozen=True)
class ImportedBook:
    book_id: str
    world_id: str
    original_path: Path
    text_path: Path


@dataclass(frozen=True)
class ImportResult:
    filename: str
    book: ImportedBook | None = None
    error: ErrorCode | None = None
    message: str | None = None

