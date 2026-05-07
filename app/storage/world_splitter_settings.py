from dataclasses import dataclass
import sqlite3
from typing import Any

from app.draft_worlds.splitter_settings import create_default_splitter_settings
from app.logger import get_logger

logger = get_logger()
SETTINGS_ID = 1
UNLOCKED = 0
LOCKED = 1


@dataclass(frozen=True)
class StoredWorldSplitterSettings:
    chunk_size: int
    max_lookback_size: int
    overlap_size: int
    splitter_version: str
    is_locked: bool


def create_default_world_splitter_settings(
    connection: sqlite3.Connection,
) -> StoredWorldSplitterSettings:
    default_settings = create_default_splitter_settings()
    stored_settings = StoredWorldSplitterSettings(
        chunk_size=default_settings.chunk_size,
        max_lookback_size=default_settings.max_lookback_size,
        overlap_size=default_settings.overlap_size,
        splitter_version=default_settings.splitter_version,
        is_locked=False,
    )

    try:
        connection.execute(
            """
            INSERT INTO world_splitter_settings (
                settings_id,
                chunk_size,
                max_lookback_size,
                overlap_size,
                splitter_version,
                is_locked
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                SETTINGS_ID,
                stored_settings.chunk_size,
                stored_settings.max_lookback_size,
                stored_settings.overlap_size,
                stored_settings.splitter_version,
                UNLOCKED,
            ),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        logger.error("Failed to create world splitter settings.", exc_info=True)
        raise

    logger.info("Created world splitter settings.")
    log_splitter_settings_debug(stored_settings)
    return stored_settings


def get_world_splitter_settings(
    connection: sqlite3.Connection,
) -> StoredWorldSplitterSettings | None:
    try:
        rows = connection.execute(
            """
            SELECT
                chunk_size,
                max_lookback_size,
                overlap_size,
                splitter_version,
                is_locked
            FROM world_splitter_settings
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error("Failed to read world splitter settings.", exc_info=True)
        raise

    if not rows:
        logger.error("Missing world splitter settings.")
        return None

    if len(rows) != 1:
        logger.error("Invalid world splitter settings state.")
        return None

    stored_settings = world_splitter_settings_from_row(rows[0])
    if stored_settings is None:
        logger.error("Invalid world splitter settings state.")
        return None

    return stored_settings


def lock_world_splitter_settings(
    connection: sqlite3.Connection,
) -> StoredWorldSplitterSettings | None:
    existing_settings = get_world_splitter_settings(connection)
    if existing_settings is None:
        return None

    try:
        cursor = connection.execute(
            """
            UPDATE world_splitter_settings
            SET is_locked = ?
            WHERE settings_id = ?
            """,
            (LOCKED, SETTINGS_ID),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        logger.error("Failed to lock world splitter settings.", exc_info=True)
        raise

    if cursor.rowcount != 1:
        logger.error("Missing world splitter settings.")
        return None

    locked_settings = StoredWorldSplitterSettings(
        chunk_size=existing_settings.chunk_size,
        max_lookback_size=existing_settings.max_lookback_size,
        overlap_size=existing_settings.overlap_size,
        splitter_version=existing_settings.splitter_version,
        is_locked=True,
    )
    logger.info("Locked world splitter settings.")
    log_splitter_settings_debug(locked_settings)
    return locked_settings


def world_splitter_settings_from_row(
    row: sqlite3.Row,
) -> StoredWorldSplitterSettings | None:
    chunk_size = row["chunk_size"]
    max_lookback_size = row["max_lookback_size"]
    overlap_size = row["overlap_size"]
    splitter_version = row["splitter_version"]
    is_locked = row["is_locked"]

    if not has_valid_setting_state(
        chunk_size,
        max_lookback_size,
        overlap_size,
        splitter_version,
        is_locked,
    ):
        return None

    return StoredWorldSplitterSettings(
        chunk_size=chunk_size,
        max_lookback_size=max_lookback_size,
        overlap_size=overlap_size,
        splitter_version=splitter_version,
        is_locked=is_locked == LOCKED,
    )


def has_valid_setting_state(
    chunk_size: Any,
    max_lookback_size: Any,
    overlap_size: Any,
    splitter_version: Any,
    is_locked: Any,
) -> bool:
    return (
        type(chunk_size) is int
        and type(max_lookback_size) is int
        and type(overlap_size) is int
        and type(splitter_version) is str
        and type(is_locked) is int
        and chunk_size >= 1
        and max_lookback_size >= 0
        and max_lookback_size < chunk_size
        and overlap_size >= 0
        and bool(splitter_version.strip())
        and is_locked in (UNLOCKED, LOCKED)
    )


def log_splitter_settings_debug(settings: StoredWorldSplitterSettings) -> None:
    logger.debug(
        "World splitter settings: chunk_size=%s max_lookback_size=%s "
        "overlap_size=%s splitter_version=%s",
        settings.chunk_size,
        settings.max_lookback_size,
        settings.overlap_size,
        settings.splitter_version,
    )
