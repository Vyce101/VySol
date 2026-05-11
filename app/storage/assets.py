from dataclasses import dataclass
import sqlite3
from typing import NoReturn
from uuid import uuid4

from app.logger import get_logger
from app.storage.database import get_global_connection

logger = get_logger()

ASSET_TYPE_FONT = "font"
ASSET_TYPE_IMAGE = "image"
VALID_ASSET_TYPES = frozenset({ASSET_TYPE_FONT, ASSET_TYPE_IMAGE})


class AssetMetadataValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AssetMetadata:
    asset_id: str
    asset_type: str
    display_name: str
    stored_path: str
    file_hash: str | None
    is_built_in: bool
    full_font_name: str | None = None
    original_filename: str | None = None

    @property
    def is_user_uploaded(self) -> bool:
        return not self.is_built_in

    @property
    def is_deletable(self) -> bool:
        return not self.is_built_in


@dataclass(frozen=True)
class NewAssetMetadata:
    asset_type: str
    display_name: str
    stored_path: str
    is_built_in: bool
    file_hash: str | None = None
    full_font_name: str | None = None
    original_filename: str | None = None
    asset_id: str | None = None


def create_asset_metadata(
    metadata: NewAssetMetadata,
    connection: sqlite3.Connection | None = None,
) -> AssetMetadata:
    validated_metadata = validate_new_asset_metadata(metadata)
    asset_metadata = AssetMetadata(
        asset_id=validated_metadata.asset_id or str(uuid4()),
        asset_type=validated_metadata.asset_type,
        display_name=validated_metadata.display_name,
        stored_path=validated_metadata.stored_path,
        file_hash=validated_metadata.file_hash,
        is_built_in=validated_metadata.is_built_in,
        full_font_name=validated_metadata.full_font_name,
        original_filename=validated_metadata.original_filename,
    )
    database_connection = connection if connection is not None else get_global_connection()

    try:
        database_connection.execute(
            """
            INSERT INTO assets (
                asset_id,
                asset_type,
                display_name,
                stored_path,
                file_hash,
                is_built_in,
                full_font_name,
                original_filename
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_metadata.asset_id,
                asset_metadata.asset_type,
                asset_metadata.display_name,
                asset_metadata.stored_path,
                asset_metadata.file_hash,
                int(asset_metadata.is_built_in),
                asset_metadata.full_font_name,
                asset_metadata.original_filename,
            ),
        )
        database_connection.commit()
    except sqlite3.Error:
        database_connection.rollback()
        logger.error("Failed to create asset metadata.", exc_info=True)
        raise

    logger.info("Created asset metadata record: %s", asset_metadata.asset_id)
    return asset_metadata


def get_asset_metadata(
    asset_id: str,
    connection: sqlite3.Connection | None = None,
) -> AssetMetadata | None:
    database_connection = connection if connection is not None else get_global_connection()

    try:
        row = database_connection.execute(
            """
            SELECT
                asset_id,
                asset_type,
                display_name,
                stored_path,
                file_hash,
                is_built_in,
                full_font_name,
                original_filename
            FROM assets
            WHERE asset_id = ?
            """,
            (asset_id,),
        ).fetchone()
    except sqlite3.Error:
        logger.error("Failed to read asset metadata.", exc_info=True)
        raise

    if row is None:
        return None

    return asset_metadata_from_row(row)


def list_asset_metadata(
    connection: sqlite3.Connection | None = None,
) -> list[AssetMetadata]:
    database_connection = connection if connection is not None else get_global_connection()

    try:
        rows = database_connection.execute(
            """
            SELECT
                asset_id,
                asset_type,
                display_name,
                stored_path,
                file_hash,
                is_built_in,
                full_font_name,
                original_filename
            FROM assets
            ORDER BY lower(display_name), asset_id
            """
        ).fetchall()
    except sqlite3.Error:
        logger.error("Failed to list asset metadata.", exc_info=True)
        raise

    return [asset_metadata_from_row(row) for row in rows]


def validate_new_asset_metadata(metadata: NewAssetMetadata) -> NewAssetMetadata:
    if metadata.asset_type not in VALID_ASSET_TYPES:
        return reject_invalid_asset_metadata("Asset metadata has an unsupported type.")

    if not metadata.display_name.strip():
        return reject_invalid_asset_metadata("Asset metadata display name is required.")

    if not metadata.stored_path.strip():
        return reject_invalid_asset_metadata("Asset metadata stored path is required.")

    if metadata.asset_id is not None and not metadata.asset_id.strip():
        return reject_invalid_asset_metadata("Asset metadata ID is required when provided.")

    if not metadata.is_built_in and not has_text_value(metadata.file_hash):
        return reject_invalid_asset_metadata("Uploaded asset metadata requires a file hash.")

    return metadata


def reject_invalid_asset_metadata(message: str) -> NoReturn:
    logger.warning("Invalid asset metadata: %s", message)
    raise AssetMetadataValidationError(message)


def has_text_value(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def asset_metadata_from_row(row: sqlite3.Row) -> AssetMetadata:
    return AssetMetadata(
        asset_id=row["asset_id"],
        asset_type=row["asset_type"],
        display_name=row["display_name"],
        stored_path=row["stored_path"],
        file_hash=row["file_hash"],
        is_built_in=bool(row["is_built_in"]),
        full_font_name=row["full_font_name"],
        original_filename=row["original_filename"],
    )
