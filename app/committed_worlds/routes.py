from urllib.parse import quote

import sqlite3
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.logger import get_logger
from app.storage.database import get_global_connection
from app.storage.committed_sources import CommittedSource, list_committed_sources
from app.storage.world_databases import open_existing_world_database
from app.storage.world_splitter_settings import (
    StoredWorldSplitterSettings,
    get_world_splitter_settings,
)
from app.storage.worlds import (
    CommittedWorld,
    get_committed_world,
    list_committed_worlds_by_recent_use,
)

router = APIRouter(prefix="/worlds", tags=["worlds"])
logger = get_logger()


class CommittedWorldCardResponse(BaseModel):
    world_id: str
    display_name: str
    description: str | None
    background_asset_id: str
    background_image_url: str
    font_asset_id: str
    font_file_url: str
    last_used_at: str


class CommittedWorldSplitterSettingsResponse(BaseModel):
    chunk_size: int
    max_lookback_size: int
    overlap_size: int
    splitter_version: str
    is_locked: bool


class CommittedSourceSummaryResponse(BaseModel):
    source_id: str
    original_filename: str
    source_file_type: str
    book_number: int
    committed_at: str


class CommittedWorldDetailResponse(BaseModel):
    world_id: str
    display_name: str
    description: str | None
    background_asset_id: str
    background_image_url: str
    font_asset_id: str
    font_file_url: str
    last_used_at: str
    splitter_settings: CommittedWorldSplitterSettingsResponse
    committed_sources: list[CommittedSourceSummaryResponse]


def get_database_connection_dependency() -> sqlite3.Connection:
    return get_global_connection()


@router.get(
    "",
    response_model=list[CommittedWorldCardResponse],
    status_code=status.HTTP_200_OK,
)
def list_committed_world_cards(
    connection: sqlite3.Connection = Depends(get_database_connection_dependency),
) -> list[CommittedWorldCardResponse]:
    return [
        build_committed_world_card_response(world)
        for world in list_committed_worlds_by_recent_use(connection)
    ]


@router.get(
    "/{world_id}/detail",
    response_model=CommittedWorldDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_committed_world_detail(
    world_id: str,
    connection: sqlite3.Connection = Depends(get_database_connection_dependency),
) -> CommittedWorldDetailResponse:
    try:
        return load_committed_world_detail(world_id, connection)
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "Failed to load committed world detail: error_type=%s",
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Committed world detail could not be loaded.",
        ) from error


def load_committed_world_detail(
    world_id: str,
    connection: sqlite3.Connection,
) -> CommittedWorldDetailResponse:
    world = get_committed_world(world_id, connection)
    if world is None:
        logger.error("Missing committed world index record for detail load.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Committed world was not found.",
        )

    world_connection: sqlite3.Connection | None = None
    try:
        world_connection = open_existing_world_database(world.world_id)
        splitter_settings = get_world_splitter_settings(world_connection)
        if splitter_settings is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Committed world splitter settings could not be loaded.",
            )

        if not splitter_settings.is_locked:
            logger.error("Committed world detail load found unlocked splitter settings.")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Committed world splitter settings are not locked.",
            )

        committed_sources = list_committed_sources(world_connection)
    finally:
        if world_connection is not None:
            world_connection.close()

    return build_committed_world_detail_response(
        world,
        splitter_settings,
        committed_sources,
    )


def build_committed_world_card_response(
    world: CommittedWorld,
) -> CommittedWorldCardResponse:
    return CommittedWorldCardResponse(
        world_id=world.world_id,
        display_name=world.display_name,
        description=world.description,
        background_asset_id=world.background_asset_id,
        background_image_url=build_asset_file_url(world.background_asset_id),
        font_asset_id=world.font_asset_id,
        font_file_url=build_asset_file_url(world.font_asset_id),
        last_used_at=world.last_used_at,
    )


def build_committed_world_detail_response(
    world: CommittedWorld,
    splitter_settings: StoredWorldSplitterSettings,
    committed_sources: list[CommittedSource],
) -> CommittedWorldDetailResponse:
    return CommittedWorldDetailResponse(
        world_id=world.world_id,
        display_name=world.display_name,
        description=world.description,
        background_asset_id=world.background_asset_id,
        background_image_url=build_asset_file_url(world.background_asset_id),
        font_asset_id=world.font_asset_id,
        font_file_url=build_asset_file_url(world.font_asset_id),
        last_used_at=world.last_used_at,
        splitter_settings=build_splitter_settings_response(splitter_settings),
        committed_sources=[
            build_committed_source_summary_response(source)
            for source in committed_sources
        ],
    )


def build_splitter_settings_response(
    splitter_settings: StoredWorldSplitterSettings,
) -> CommittedWorldSplitterSettingsResponse:
    return CommittedWorldSplitterSettingsResponse(
        chunk_size=splitter_settings.chunk_size,
        max_lookback_size=splitter_settings.max_lookback_size,
        overlap_size=splitter_settings.overlap_size,
        splitter_version=splitter_settings.splitter_version,
        is_locked=splitter_settings.is_locked,
    )


def build_committed_source_summary_response(
    source: CommittedSource,
) -> CommittedSourceSummaryResponse:
    return CommittedSourceSummaryResponse(
        source_id=source.source_id,
        original_filename=source.original_filename,
        source_file_type=source.source_file_type,
        book_number=source.book_number,
        committed_at=source.committed_at,
    )


def build_asset_file_url(asset_id: str) -> str:
    return f"/assets/{quote(asset_id, safe='')}/file"
