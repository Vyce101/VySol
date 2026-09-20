"""Publish complete book directories under a per-world interprocess lock."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from filelock import FileLock

from .models import ErrorCode, ImportedBook, ImportFailure, Upload

CONVERTER_VERSION = 1
WORLD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
RESERVED_NAMES = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


def validate_upload(upload: Upload) -> tuple[str, str]:
    name = upload.filename
    if (not isinstance(name, str) or not name or any(0xD800 <= ord(char) <= 0xDFFF for char in name)
            or len(name.encode("utf-8")) > 240
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)
            or name.endswith((".", " ")) or name.split(".")[0].casefold() in RESERVED_NAMES):
        raise ImportFailure(ErrorCode.INVALID_INPUT, "Supply a safe filename without directory components.")
    stem, separator, extension = name.rpartition(".")
    if not separator or extension.casefold() not in {"txt", "epub"}:
        raise ImportFailure(ErrorCode.UNSUPPORTED_FORMAT, "Only TXT and EPUB uploads are supported.")
    comparison_name = stem.strip().casefold()
    if not comparison_name or not isinstance(upload.content, bytes):
        raise ImportFailure(ErrorCode.INVALID_INPUT, "Supply a nonempty book name and binary file content.")
    return comparison_name, stem + ".txt"


def safe_directory(root: Path, *parts: str) -> Path:
    destination = root.joinpath(*parts)
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ImportFailure(ErrorCode.STORAGE_FAILURE, "Storage path escapes the configured data directory.")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


@contextmanager
def world_storage(root: Path, world_id: str):
    if not isinstance(world_id, str) or not WORLD_ID.fullmatch(world_id) or world_id.casefold() in RESERVED_NAMES:
        raise ImportFailure(ErrorCode.INVALID_INPUT, "Supply a world identifier using letters, digits, underscores, or hyphens.")
    # Hashing keeps world IDs case-sensitive even on Windows filesystems.
    world_key = hashlib.sha256(world_id.encode("utf-8")).hexdigest()
    locks = safe_directory(root, "locks")
    lock_path = locks / f"{world_key}.lock"
    if lock_path.is_symlink():
        raise ImportFailure(ErrorCode.STORAGE_FAILURE, "Invalid storage lock path.")
    with FileLock(lock_path, timeout=30):
        books = safe_directory(root, "worlds", world_key, "books")
        yield books


def book_destination(books: Path, comparison_name: str) -> Path:
    key = hashlib.sha256(comparison_name.encode("utf-8")).hexdigest()
    destination = books / key
    if destination.exists() or destination.is_symlink():
        raise ImportFailure(ErrorCode.DUPLICATE_NAME, "This world already contains a book with that name.")
    return destination


def publish_book(root: Path, destination: Path, world_id: str, upload: Upload,
                 comparison_name: str, text_name: str, text: str) -> ImportedBook:
    staging_root = safe_directory(root, "staging")
    stage = Path(tempfile.mkdtemp(prefix="import-", dir=staging_root))
    book_id = uuid4().hex
    try:
        (stage / "original").mkdir()
        (stage / "text").mkdir()
        (stage / "original" / upload.filename).write_bytes(upload.content)
        (stage / "text" / text_name).write_bytes(text.encode("utf-8"))
        metadata = {
            "book_id": book_id, "world_id": world_id,
            "original_filename": upload.filename, "text_filename": text_name,
            "comparison_name": comparison_name, "converter_version": CONVERTER_VERSION,
        }
        (stage / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        stage.rename(destination)
    finally:
        # Only remove this operation's generated staging directory, never user paths.
        if stage.exists():
            shutil.rmtree(stage)
    return ImportedBook(book_id, world_id, destination / "original" / upload.filename,
                        destination / "text" / text_name)
