from dataclasses import dataclass
import sqlite3
from typing import NoReturn
from uuid import uuid4

from app.logger import get_logger
from app.storage.database import get_global_connection

logger = get_logger()


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
                font_asset_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                committed_world.world_id,
                committed_world.display_name,
                display_name_key,
                committed_world.description,
                committed_world.background_asset_id,
                committed_world.font_asset_id,
            ),
        )
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to create committed world index record.", exc_info=True)
        raise

    logger.info("Created committed world index record: %s", committed_world.world_id)
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
                font_asset_id
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
        return None

    validated_world = validate_committed_world_update(world)
    display_name_key = get_display_name_key(validated_world.display_name)
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
                font_asset_id = ?
            WHERE world_id = ?
            """,
            (
                validated_world.display_name,
                display_name_key,
                validated_world.description,
                validated_world.background_asset_id,
                validated_world.font_asset_id,
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
    )
    logger.info("Updated committed world index record: %s", world_id)
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
                font_asset_id
            FROM worlds
            ORDER BY display_name_key, world_id
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error("Failed to list committed world index records.", exc_info=True)
        raise

    return [committed_world_from_row(row) for row in rows]


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


def committed_world_from_row(row: sqlite3.Row) -> CommittedWorld:
    return CommittedWorld(
        world_id=row["world_id"],
        display_name=row["display_name"],
        description=row["description"],
        background_asset_id=row["background_asset_id"],
        font_asset_id=row["font_asset_id"],
    )
