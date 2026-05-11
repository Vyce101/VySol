import re
import shutil
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from app.logger import get_logger
from app.storage.asset_deduplication import calculate_asset_file_hash
from app.storage.assets import (
    ASSET_TYPE_FONT,
    ASSET_TYPE_IMAGE,
    AssetMetadata,
    AssetMetadataValidationError,
    NewAssetMetadata,
    create_asset_metadata,
    get_asset_metadata,
)
from app.storage.paths import (
    REPO_ROOT,
    get_font_assets_directory,
    get_image_assets_directory,
)

logger = get_logger()

SAFE_SUFFIX_PATTERN = re.compile(r"^\.[A-Za-z0-9]{1,16}$")

ASSET_STORAGE_DIRECTORIES = {
    ASSET_TYPE_IMAGE: get_image_assets_directory,
    ASSET_TYPE_FONT: get_font_assets_directory,
}

ASSET_DISPLAY_NAME_FALLBACKS = {
    ASSET_TYPE_IMAGE: "Uploaded image",
    ASSET_TYPE_FONT: "Uploaded font",
}


def store_uploaded_asset_file(
    asset_type: str,
    source_file_path: Path,
    original_filename: str,
    connection: sqlite3.Connection | None = None,
) -> AssetMetadata:
    asset_directory = get_asset_storage_directory(asset_type)
    asset_id = str(uuid4())
    safe_suffix = get_safe_filename_suffix(original_filename)
    destination_path = asset_directory / f"{asset_id}{safe_suffix}"
    ensure_path_is_inside_directory(destination_path, asset_directory)
    stored_path = get_repo_relative_posix_path(destination_path)
    display_name = get_default_display_name(asset_type, original_filename)
    file_hash = calculate_asset_file_hash(source_file_path)

    try:
        asset_directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file_path, destination_path)
    except OSError:
        logger.error("Failed to copy uploaded asset file.", exc_info=True)
        raise

    asset_metadata = create_asset_metadata(
        NewAssetMetadata(
            asset_id=asset_id,
            asset_type=asset_type,
            display_name=display_name,
            stored_path=stored_path,
            is_built_in=False,
            file_hash=file_hash,
            original_filename=original_filename,
        ),
        connection,
    )
    logger.info("Stored uploaded asset file: %s", asset_metadata.asset_id)
    return asset_metadata


def resolve_asset_file_path(
    asset_id: str,
    connection: sqlite3.Connection | None = None,
) -> Path | None:
    asset_metadata = get_asset_metadata(asset_id, connection)
    if asset_metadata is None:
        return None

    stored_path = PurePosixPath(asset_metadata.stored_path)
    if stored_path.is_absolute() or ".." in stored_path.parts:
        logger.error("Rejected unsafe stored asset path.")
        return None

    resolved_path = (REPO_ROOT / Path(*stored_path.parts)).resolve()
    try:
        ensure_path_is_inside_directory(resolved_path, REPO_ROOT.resolve())
    except ValueError:
        logger.error("Rejected unsafe stored asset path.")
        return None

    return resolved_path


def get_asset_storage_directory(asset_type: str) -> Path:
    get_directory = ASSET_STORAGE_DIRECTORIES.get(asset_type)
    if get_directory is None:
        logger.warning("Unsupported asset file type rejected.")
        raise AssetMetadataValidationError("Asset file storage has an unsupported type.")

    return get_directory()


def get_safe_filename_suffix(original_filename: str) -> str:
    filename = get_filename_component(original_filename)
    suffix = Path(filename).suffix
    if not suffix:
        return ""

    if SAFE_SUFFIX_PATTERN.fullmatch(suffix):
        return suffix.lower()

    logger.warning("Unsupported asset filename suffix ignored.")
    return ""


def get_default_display_name(asset_type: str, original_filename: str) -> str:
    filename = get_filename_component(original_filename)
    display_name = Path(filename).stem.strip()
    if display_name and display_name not in {".", ".."}:
        return display_name

    logger.warning("Unsupported asset filename display name ignored.")
    return ASSET_DISPLAY_NAME_FALLBACKS[asset_type]


def get_filename_component(original_filename: str) -> str:
    windows_name = PureWindowsPath(original_filename).name
    posix_name = PurePosixPath(original_filename).name
    filename = PureWindowsPath(posix_name).name

    if filename != original_filename or windows_name != original_filename:
        logger.warning("Unsupported asset filename path pattern ignored.")

    return filename


def ensure_path_is_inside_directory(path: Path, directory: Path) -> None:
    resolved_path = path.resolve()
    resolved_directory = directory.resolve()
    if not resolved_path.is_relative_to(resolved_directory):
        logger.error("Rejected unsafe asset storage path.")
        raise ValueError("Asset storage path must stay inside its storage directory.")


def get_repo_relative_posix_path(path: Path) -> str:
    try:
        relative_path = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        logger.error("Rejected unsafe asset storage path.")
        raise

    return relative_path.as_posix()
