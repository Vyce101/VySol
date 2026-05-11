from dataclasses import dataclass
import sqlite3
from collections.abc import Iterable

from app.logger import get_logger
from app.storage.asset_files import resolve_asset_file_path
from app.storage.assets import ASSET_TYPE_FONT, ASSET_TYPE_IMAGE, get_asset_metadata
from app.storage.database import get_global_connection
from app.storage.default_assets import (
    MAIN_DEFAULT_BACKGROUND_ASSET_ID,
    MAIN_DEFAULT_FONT_ASSET_ID,
)
from app.storage.worlds import (
    CommittedWorldAssetReference,
    has_committed_world_asset_reference,
    list_committed_world_asset_references,
    replace_committed_world_background_asset_references,
    replace_committed_world_font_asset_references,
)

logger = get_logger()


@dataclass(frozen=True)
class AssetDeletionImpact:
    asset_id: str
    asset_type: str
    affected_worlds: list[CommittedWorldAssetReference]


def delete_unused_uploaded_asset(
    asset_id: str,
    connection: sqlite3.Connection | None = None,
) -> bool:
    database_connection = connection if connection is not None else get_global_connection()
    asset = get_asset_metadata(asset_id, database_connection)
    if asset is None:
        return False

    if asset.is_built_in:
        logger.warning("Rejected built-in asset deletion attempt: %s", asset.asset_id)
        return False

    if has_committed_world_asset_reference(asset.asset_id, database_connection):
        return False

    asset_file_path = resolve_asset_file_path(asset.asset_id, database_connection)
    if asset_file_path is None:
        return False

    try:
        cursor = database_connection.execute(
            """
            DELETE FROM assets
            WHERE asset_id = ? AND is_built_in = 0
            """,
            (asset.asset_id,),
        )
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to delete uploaded asset metadata.", exc_info=True)
        raise

    if cursor.rowcount == 0:
        database_connection.rollback()
        return False

    try:
        asset_file_path.unlink()
    except OSError:
        database_connection.rollback()
        logger.error("Failed to delete uploaded asset file.", exc_info=True)
        raise

    try:
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to delete uploaded asset metadata.", exc_info=True)
        raise

    logger.info("Deleted unused uploaded asset: %s", asset.asset_id)
    return True


def get_uploaded_asset_deletion_impact(
    asset_id: str,
    connection: sqlite3.Connection | None = None,
) -> AssetDeletionImpact | None:
    database_connection = connection if connection is not None else get_global_connection()
    asset = get_asset_metadata(asset_id, database_connection)
    if asset is None:
        return None

    if asset.is_built_in:
        logger.warning("Rejected built-in asset deletion attempt: %s", asset.asset_id)
        return None

    affected_worlds = list_committed_world_asset_references(
        asset.asset_id,
        database_connection,
    )
    logger.info(
        "Looked up affected committed worlds for uploaded asset deletion: %s",
        len(affected_worlds),
    )
    return AssetDeletionImpact(
        asset_id=asset.asset_id,
        asset_type=asset.asset_type,
        affected_worlds=affected_worlds,
    )


def delete_uploaded_asset_with_fallback(
    asset_id: str,
    confirmed_world_ids: Iterable[str],
    connection: sqlite3.Connection | None = None,
) -> bool:
    database_connection = connection if connection is not None else get_global_connection()
    asset = get_asset_metadata(asset_id, database_connection)
    if asset is None:
        return False

    if asset.is_built_in:
        logger.warning("Rejected built-in asset deletion attempt: %s", asset.asset_id)
        return False

    asset_file_path = resolve_asset_file_path(asset.asset_id, database_connection)
    if asset_file_path is None:
        return False

    confirmed_world_id_set = frozenset(confirmed_world_ids)
    fallback_asset_id = get_fallback_asset_id(asset.asset_type)
    if fallback_asset_id is None:
        return False

    try:
        database_connection.execute("BEGIN")
        affected_worlds = list_committed_world_asset_references(
            asset.asset_id,
            database_connection,
        )
        affected_world_id_set = frozenset(
            world.world_id for world in affected_worlds
        )
        if affected_world_id_set != confirmed_world_id_set:
            database_connection.rollback()
            return False

        updated_world_count = replace_committed_world_asset_references(
            asset.asset_id,
            asset.asset_type,
            fallback_asset_id,
            database_connection,
        )
        cursor = database_connection.execute(
            """
            DELETE FROM assets
            WHERE asset_id = ? AND is_built_in = 0
            """,
            (asset.asset_id,),
        )
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to delete uploaded asset with fallback.", exc_info=True)
        raise

    if cursor.rowcount == 0:
        database_connection.rollback()
        return False

    try:
        asset_file_path.unlink()
    except OSError:
        database_connection.rollback()
        logger.error("Failed to delete uploaded asset file.", exc_info=True)
        raise

    try:
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to delete uploaded asset with fallback.", exc_info=True)
        raise

    logger.info(
        "Updated committed world asset fallbacks for confirmed uploaded asset deletion: %s",
        updated_world_count,
    )
    logger.info("Deleted uploaded asset with fallback: %s", asset.asset_id)
    return True


def get_fallback_asset_id(asset_type: str) -> str | None:
    if asset_type == ASSET_TYPE_IMAGE:
        return MAIN_DEFAULT_BACKGROUND_ASSET_ID

    if asset_type == ASSET_TYPE_FONT:
        return MAIN_DEFAULT_FONT_ASSET_ID

    return None


def replace_committed_world_asset_references(
    asset_id: str,
    asset_type: str,
    fallback_asset_id: str,
    connection: sqlite3.Connection,
) -> int:
    if asset_type == ASSET_TYPE_IMAGE:
        return replace_committed_world_background_asset_references(
            asset_id,
            fallback_asset_id,
            connection,
        )

    if asset_type == ASSET_TYPE_FONT:
        return replace_committed_world_font_asset_references(
            asset_id,
            fallback_asset_id,
            connection,
        )

    return 0
