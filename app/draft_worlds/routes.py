from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.draft_worlds.registry import (
    DraftWorldRegistry,
    get_draft_world_registry,
)
from app.draft_worlds.splitter_settings import SplitterSettings
from app.draft_worlds.world import DraftWorld
from app.ingestion.staging import (
    SourceStagingState,
    SourceStagingStateRegistry,
    TemporarySourceStagingEntry,
    get_source_staging_state_registry,
)

router = APIRouter(prefix="/draft-worlds", tags=["draft-worlds"])


class SplitterSettingsResponse(BaseModel):
    chunk_size: int
    max_lookback_size: int
    overlap_size: int
    splitter_version: str


class StagedSourceResponse(BaseModel):
    staging_entry_id: str
    source_file_type: str
    is_valid: bool
    error_message: str | None


class DraftWorldDetailResponse(BaseModel):
    draft_id: str
    splitter_settings: SplitterSettingsResponse
    staged_sources: list[StagedSourceResponse]


def get_draft_registry_dependency() -> DraftWorldRegistry:
    return get_draft_world_registry()


def get_staging_registry_dependency() -> SourceStagingStateRegistry:
    return get_source_staging_state_registry()


@router.post(
    "",
    response_model=DraftWorldDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_draft_world_detail(
    draft_registry: Annotated[
        DraftWorldRegistry,
        Depends(get_draft_registry_dependency),
    ],
    staging_registry: Annotated[
        SourceStagingStateRegistry,
        Depends(get_staging_registry_dependency),
    ],
) -> DraftWorldDetailResponse:
    draft_world = draft_registry.create_draft_world()
    staging_state = staging_registry.create_staging_context(draft_world.draft_id)
    return build_draft_world_detail_response(draft_world, staging_state)


@router.get(
    "/{draft_id}",
    response_model=DraftWorldDetailResponse,
    status_code=status.HTTP_200_OK,
)
def read_draft_world_detail(
    draft_id: str,
    draft_registry: Annotated[
        DraftWorldRegistry,
        Depends(get_draft_registry_dependency),
    ],
    staging_registry: Annotated[
        SourceStagingStateRegistry,
        Depends(get_staging_registry_dependency),
    ],
) -> DraftWorldDetailResponse:
    draft_world = draft_registry.get_draft_world(draft_id)

    if draft_world is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft world was not found.",
        )

    staging_state = staging_registry.get_staging_state(draft_id)
    return build_draft_world_detail_response(draft_world, staging_state)


def build_draft_world_detail_response(
    draft_world: DraftWorld,
    staging_state: SourceStagingState | None,
) -> DraftWorldDetailResponse:
    return DraftWorldDetailResponse(
        draft_id=draft_world.draft_id,
        splitter_settings=build_splitter_settings_response(
            draft_world.splitter_settings,
        ),
        staged_sources=build_staged_source_responses(staging_state),
    )


def build_splitter_settings_response(
    splitter_settings: SplitterSettings,
) -> SplitterSettingsResponse:
    return SplitterSettingsResponse(
        chunk_size=splitter_settings.chunk_size,
        max_lookback_size=splitter_settings.max_lookback_size,
        overlap_size=splitter_settings.overlap_size,
        splitter_version=splitter_settings.splitter_version,
    )


def build_staged_source_responses(
    staging_state: SourceStagingState | None,
) -> list[StagedSourceResponse]:
    if staging_state is None:
        return []

    return [
        build_staged_source_response(entry)
        for entry in staging_state.entries
    ]


def build_staged_source_response(
    entry: TemporarySourceStagingEntry,
) -> StagedSourceResponse:
    return StagedSourceResponse(
        staging_entry_id=entry.staging_entry_id,
        source_file_type=entry.source_file_type,
        is_valid=entry.is_valid,
        error_message=entry.error_message,
    )
