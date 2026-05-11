import sqlite3

from app.logger import get_logger
from app.storage.asset_files import resolve_asset_file_path
from app.storage.assets import get_asset_metadata
from app.storage.database import get_global_connection
from app.storage.worlds import has_committed_world_asset_reference

logger = get_logger()


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
