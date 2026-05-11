import hashlib
import sqlite3
from pathlib import Path

from app.logger import get_logger
from app.storage.database import get_global_connection

logger = get_logger()

ASSET_HASH_ALGORITHM = "sha256"
ASSET_HASH_READ_SIZE = 1024 * 1024
HASH_LOG_PREFIX_LENGTH = 19


def find_duplicate_asset_id_by_file_hash(
    file_path: Path,
    connection: sqlite3.Connection | None = None,
) -> str | None:
    file_hash = calculate_asset_file_hash(file_path)
    database_connection = connection if connection is not None else get_global_connection()

    try:
        row = database_connection.execute(
            """
            SELECT asset_id
            FROM assets
            WHERE file_hash = ?
            ORDER BY asset_id
            LIMIT 1
            """,
            (file_hash,),
        ).fetchone()
    except sqlite3.Error:
        logger.error("Failed to search asset metadata by file hash.", exc_info=True)
        raise

    if row is None:
        return None

    asset_id = row["asset_id"]
    logger.info("Asset deduplication hit found.")
    logger.debug("Asset deduplication hit ID: %s", asset_id)
    logger.debug("Asset deduplication hash prefix: %s", file_hash[:HASH_LOG_PREFIX_LENGTH])
    return asset_id


def calculate_asset_file_hash(file_path: Path) -> str:
    file_hasher = hashlib.sha256()

    try:
        with file_path.open("rb") as asset_file:
            while chunk := asset_file.read(ASSET_HASH_READ_SIZE):
                file_hasher.update(chunk)
    except OSError:
        logger.error("Failed to read asset file for hashing.", exc_info=True)
        raise

    return f"{ASSET_HASH_ALGORITHM}:{file_hasher.hexdigest()}"
