from dataclasses import dataclass
import sqlite3

from app.logger import get_logger
from app.storage.assets import (
    ASSET_TYPE_FONT,
    ASSET_TYPE_IMAGE,
    AssetMetadata,
    get_asset_metadata,
)

logger = get_logger()

MAIN_DEFAULT_BACKGROUND_ASSET_ID = "builtin-image-main-world"
MAIN_DEFAULT_FONT_ASSET_ID = "builtin-font-inter"


@dataclass(frozen=True)
class BuiltInAssetReference:
    asset_id: str
    asset_type: str
    display_name: str
    stored_path: str
    full_font_name: str | None = None


BUILT_IN_IMAGE_ASSETS = (
    BuiltInAssetReference(
        asset_id="builtin-image-dark-academy",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Dark Academy",
        stored_path="app/assets/images/Dark Academy.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-desert-ruins",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Desert Ruins",
        stored_path="app/assets/images/Desert Ruins.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-fantasy-valley",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Fantasy Valley",
        stored_path="app/assets/images/Fantasy Valley.png",
    ),
    BuiltInAssetReference(
        asset_id=MAIN_DEFAULT_BACKGROUND_ASSET_ID,
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Main World Image",
        stored_path="app/assets/images/Main World Image.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-moonlit-shrine",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Moonlit Shrine",
        stored_path="app/assets/images/Moonlit Shrine.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-neon-city",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Neon City",
        stored_path="app/assets/images/Neon City.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-ruined-battlefield",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Ruined Battlefield",
        stored_path="app/assets/images/Ruined Battlefield.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-sky-islands",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Sky Islands",
        stored_path="app/assets/images/Sky Islands.png",
    ),
    BuiltInAssetReference(
        asset_id="builtin-image-snowfield-aurora",
        asset_type=ASSET_TYPE_IMAGE,
        display_name="Snowfield Aurora",
        stored_path="app/assets/images/Snowfield Aurora.png",
    ),
)

BUILT_IN_FONT_ASSETS = (
    BuiltInAssetReference(
        asset_id="builtin-font-almendra-bold",
        asset_type=ASSET_TYPE_FONT,
        display_name="Almendra Bold",
        stored_path="app/assets/fonts/Almendra/Almendra-Bold.ttf",
        full_font_name="Almendra Bold",
    ),
    BuiltInAssetReference(
        asset_id="builtin-font-cinzel-bold",
        asset_type=ASSET_TYPE_FONT,
        display_name="Cinzel Bold",
        stored_path="app/assets/fonts/Cinzel/Cinzel-Bold.ttf",
        full_font_name="Cinzel Bold",
    ),
    BuiltInAssetReference(
        asset_id="builtin-font-im-fell-english-sc-regular",
        asset_type=ASSET_TYPE_FONT,
        display_name="IM Fell English SC Regular",
        stored_path="app/assets/fonts/IM_Fell_English_SC/IMFellEnglishSC-Regular.ttf",
        full_font_name="IM Fell English SC Regular",
    ),
    BuiltInAssetReference(
        asset_id=MAIN_DEFAULT_FONT_ASSET_ID,
        asset_type=ASSET_TYPE_FONT,
        display_name="Inter",
        stored_path="app/assets/fonts/Inter/Inter-VariableFont_opsz,wght.ttf",
        full_font_name="Inter",
    ),
    BuiltInAssetReference(
        asset_id="builtin-font-orbitron-bold",
        asset_type=ASSET_TYPE_FONT,
        display_name="Orbitron Bold",
        stored_path="app/assets/fonts/Orbitron/Orbitron-Bold.ttf",
        full_font_name="Orbitron Bold",
    ),
)

BUILT_IN_ASSETS = BUILT_IN_IMAGE_ASSETS + BUILT_IN_FONT_ASSETS


def seed_default_asset_references(connection: sqlite3.Connection) -> None:
    rows = [
        (
            asset.asset_id,
            asset.asset_type,
            asset.display_name,
            asset.stored_path,
            None,
            1,
            asset.full_font_name,
        )
        for asset in BUILT_IN_ASSETS
    ]

    try:
        connection.executemany(
            """
            INSERT INTO assets (
                asset_id,
                asset_type,
                display_name,
                stored_path,
                file_hash,
                is_built_in,
                full_font_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                asset_type = excluded.asset_type,
                display_name = excluded.display_name,
                stored_path = excluded.stored_path,
                file_hash = excluded.file_hash,
                is_built_in = excluded.is_built_in,
                full_font_name = excluded.full_font_name
            """,
            rows,
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        logger.error("Failed to seed default asset references.", exc_info=True)
        raise

    logger.info("Seeded default asset references.")
    for asset in BUILT_IN_ASSETS:
        logger.debug("Seeded default asset reference ID: %s", asset.asset_id)


def get_main_default_background_asset(
    connection: sqlite3.Connection | None = None,
) -> AssetMetadata | None:
    return get_built_in_default_asset_reference(
        MAIN_DEFAULT_BACKGROUND_ASSET_ID,
        ASSET_TYPE_IMAGE,
        "main default background",
        connection,
    )


def get_main_default_font_asset(
    connection: sqlite3.Connection | None = None,
) -> AssetMetadata | None:
    return get_built_in_default_asset_reference(
        MAIN_DEFAULT_FONT_ASSET_ID,
        ASSET_TYPE_FONT,
        "main default font",
        connection,
    )


def get_built_in_default_asset_reference(
    asset_id: str,
    expected_asset_type: str,
    lookup_name: str,
    connection: sqlite3.Connection | None = None,
) -> AssetMetadata | None:
    asset = get_asset_metadata(asset_id, connection or get_database_connection())
    if asset is None or not is_matching_built_in_asset(asset, expected_asset_type):
        logger.error("Missing built-in default asset reference: %s", lookup_name)
        logger.debug("Missing built-in default asset ID: %s", asset_id)
        return None

    logger.info("Default asset lookup succeeded: %s", lookup_name)
    logger.debug("Default asset lookup ID: %s", asset.asset_id)
    return asset


def is_matching_built_in_asset(asset: AssetMetadata, expected_asset_type: str) -> bool:
    return asset.is_built_in and asset.asset_type == expected_asset_type


def get_database_connection() -> sqlite3.Connection:
    from app.storage.database import get_global_connection as get_connection

    return get_connection()
