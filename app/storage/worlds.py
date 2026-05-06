from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import NoReturn
from uuid import uuid4

from app.logger import get_logger
from app.storage.database import get_global_connection

logger = get_logger()
LAST_USED_AT_FORMAT = "%d-%m-%Y %H:%M:%S"


class CommittedWorldValidationError(ValueError):
    pass


class DuplicateCommittedWorldDisplayNameError(CommittedWorldValidationError):
    pass


@dataclass(frozen=True)
class CommittedWorld:
    world_id: str
    display_name: str
    description: str | None
    background_asset_id: str
    font_asset_id: str
    last_used_at: str


@dataclass(frozen=True)
class NewCommittedWorld:
    display_name: str
    background_asset_id: str
    font_asset_id: str
    description: str | None = None


@dataclass(frozen=True)
class CommittedWorldUpdate:
    display_name: str
    background_asset_id: str
    font_asset_id: str
    description: str | None = None


def create_committed_world(
    world: NewCommittedWorld,
    connection: sqlite3.Connection | None = None,
) -> CommittedWorld:
    validated_world = validate_new_committed_world(world)
    database_connection = connection if connection is not None else get_global_connection()
    display_name_key = get_display_name_key(validated_world.display_name)
    last_used_at = get_last_used_at_timestamp()
    reject_duplicate_display_name(
        database_connection,
        display_name_key,
        "Committed world display name already exists.",
    )
    committed_world = CommittedWorld(
        world_id=str(uuid4()),
        display_name=validated_world.display_name,
        description=validated_world.description,
        background_asset_id=validated_world.background_asset_id,
        font_asset_id=validated_world.font_asset_id,
        last_used_at=last_used_at,
    )

    try:
        database_connection.execute(
            """
            INSERT INTO worlds (
                world_id,
                display_name,
                display_name_key,
                description,
                background_asset_id,
                font_asset_id,
                last_used_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                committed_world.world_id,
                committed_world.display_name,
                display_name_key,
                committed_world.description,
                committed_world.background_asset_id,
                committed_world.font_asset_id,
                committed_world.last_used_at,
            ),
        )
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to create committed world index record.", exc_info=True)
        raise

    logger.info("Created committed world index record.")
    logger.debug("Created committed world index record: %s", committed_world.world_id)
    return committed_world


def get_committed_world(
    world_id: str,
    connection: sqlite3.Connection | None = None,
) -> CommittedWorld | None:
    database_connection = connection if connection is not None else get_global_connection()

    try:
        row = database_connection.execute(
            """
            SELECT
                world_id,
                display_name,
                description,
                background_asset_id,
                font_asset_id,
                last_used_at
            FROM worlds
            WHERE world_id = ?
            """,
            (world_id,),
        ).fetchone()
    except sqlite3.Error:
        logger.error("Failed to read committed world index record.", exc_info=True)
        raise

    if row is None:
        return None

    return committed_world_from_row(row)


def update_committed_world(
    world_id: str,
    world: CommittedWorldUpdate,
    connection: sqlite3.Connection | None = None,
) -> CommittedWorld | None:
    database_connection = connection if connection is not None else get_global_connection()
    if not has_committed_world(world_id, database_connection):
        logger.error("Missing committed world index record for update.")
        logger.debug("Missing committed world ID: %s", world_id)
        return None

    validated_world = validate_committed_world_update(world)
    display_name_key = get_display_name_key(validated_world.display_name)
    last_used_at = get_last_used_at_timestamp()
    reject_duplicate_display_name(
        database_connection,
        display_name_key,
        "Committed world display name already exists.",
        allowed_world_id=world_id,
    )

    try:
        cursor = database_connection.execute(
            """
            UPDATE worlds
            SET
                display_name = ?,
                display_name_key = ?,
                description = ?,
                background_asset_id = ?,
                font_asset_id = ?,
                last_used_at = ?
            WHERE world_id = ?
            """,
            (
                validated_world.display_name,
                display_name_key,
                validated_world.description,
                validated_world.background_asset_id,
                validated_world.font_asset_id,
                last_used_at,
                world_id,
            ),
        )
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to update committed world index record.", exc_info=True)
        raise

    if cursor.rowcount == 0:
        return None

    updated_world = CommittedWorld(
        world_id=world_id,
        display_name=validated_world.display_name,
        description=validated_world.description,
        background_asset_id=validated_world.background_asset_id,
        font_asset_id=validated_world.font_asset_id,
        last_used_at=last_used_at,
    )
    logger.info("Updated committed world index record.")
    logger.debug("Refreshed committed world last_used_at: %s %s", world_id, last_used_at)
    return updated_world


def list_committed_worlds(
    connection: sqlite3.Connection | None = None,
) -> list[CommittedWorld]:
    database_connection = connection if connection is not None else get_global_connection()

    try:
        rows = database_connection.execute(
            """
            SELECT
                world_id,
                display_name,
                description,
                background_asset_id,
                font_asset_id,
                last_used_at
            FROM worlds
            ORDER BY display_name_key, world_id
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error("Failed to list committed world index records.", exc_info=True)
        raise

    return [committed_world_from_row(row) for row in rows]


def list_committed_worlds_by_recent_use(
    connection: sqlite3.Connection | None = None,
) -> list[CommittedWorld]:
    database_connection = connection if connection is not None else get_global_connection()

    try:
        rows = database_connection.execute(
            """
            SELECT
                world_id,
                display_name,
                description,
                background_asset_id,
                font_asset_id,
                last_used_at
            FROM worlds
            ORDER BY
                substr(last_used_at, 7, 4) DESC,
                substr(last_used_at, 4, 2) DESC,
                substr(last_used_at, 1, 2) DESC,
                substr(last_used_at, 12, 8) DESC,
                display_name_key,
                world_id
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error(
            "Failed to list committed world index records by recent use.",
            exc_info=True,
        )
        raise

    return [committed_world_from_row(row) for row in rows]


def mark_committed_world_used(
    world_id: str,
    used_at: datetime | None = None,
    connection: sqlite3.Connection | None = None,
) -> CommittedWorld | None:
    database_connection = connection if connection is not None else get_global_connection()
    last_used_at = get_last_used_at_timestamp(used_at)

    try:
        cursor = database_connection.execute(
            """
            UPDATE worlds
            SET last_used_at = ?
            WHERE world_id = ?
            """,
            (last_used_at, world_id),
        )
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to update committed world last_used_at.", exc_info=True)
        logger.debug(
            "Failed committed world last_used_at update: %s %s",
            world_id,
            last_used_at,
        )
        raise

    if cursor.rowcount == 0:
        logger.error("Missing committed world index record for last_used_at update.")
        logger.debug("Missing committed world ID for last_used_at update: %s", world_id)
        return None

    logger.info("Updated committed world last_used_at.")
    logger.debug("Updated committed world last_used_at: %s %s", world_id, last_used_at)
    return get_committed_world(world_id, database_connection)


def has_committed_world(world_id: str, connection: sqlite3.Connection) -> bool:
    try:
        row = connection.execute(
            """
            SELECT world_id
            FROM worlds
            WHERE world_id = ?
            """,
            (world_id,),
        ).fetchone()
    except sqlite3.Error:
        logger.error("Failed to read committed world index record.", exc_info=True)
        raise

    return row is not None


def validate_new_committed_world(world: NewCommittedWorld) -> NewCommittedWorld:
    validate_committed_world_fields(
        world.display_name,
        world.background_asset_id,
        world.font_asset_id,
    )
    return world


def validate_committed_world_update(
    world: CommittedWorldUpdate,
) -> CommittedWorldUpdate:
    validate_committed_world_fields(
        world.display_name,
        world.background_asset_id,
        world.font_asset_id,
    )
    return world


def validate_committed_world_fields(
    display_name: str,
    background_asset_id: str,
    font_asset_id: str,
) -> None:
    if not display_name.strip():
        reject_invalid_committed_world("Committed world display name is required.")

    if not background_asset_id.strip():
        reject_invalid_committed_world(
            "Committed world background asset reference is required."
        )

    if not font_asset_id.strip():
        reject_invalid_committed_world("Committed world font asset reference is required.")


def reject_duplicate_display_name(
    connection: sqlite3.Connection,
    display_name_key: str,
    message: str,
    allowed_world_id: str | None = None,
) -> None:
    try:
        row = connection.execute(
            """
            SELECT world_id
            FROM worlds
            WHERE display_name_key = ?
            """,
            (display_name_key,),
        ).fetchone()
    except sqlite3.Error:
        logger.error("Failed to check committed world display name.", exc_info=True)
        raise

    if row is None or row["world_id"] == allowed_world_id:
        return

    logger.warning("Rejected duplicate committed world display name.")
    raise DuplicateCommittedWorldDisplayNameError(message)


def reject_invalid_committed_world(message: str) -> NoReturn:
    logger.warning("Invalid committed world index record: %s", message)
    raise CommittedWorldValidationError(message)


def get_display_name_key(display_name: str) -> str:
    return display_name.casefold()


def get_last_used_at_timestamp(used_at: datetime | None = None) -> str:
    timestamp = used_at if used_at is not None else datetime.now()
    return timestamp.strftime(LAST_USED_AT_FORMAT)


def committed_world_from_row(row: sqlite3.Row) -> CommittedWorld:
    return CommittedWorld(
        world_id=row["world_id"],
        display_name=row["display_name"],
        description=row["description"],
        background_asset_id=row["background_asset_id"],
        font_asset_id=row["font_asset_id"],
        last_used_at=row["last_used_at"],
    )
