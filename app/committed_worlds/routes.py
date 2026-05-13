from urllib.parse import quote

import sqlite3
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.storage.database import get_global_connection
from app.storage.worlds import CommittedWorld, list_committed_worlds

router = APIRouter(prefix="/worlds", tags=["worlds"])


class CommittedWorldCardResponse(BaseModel):
    world_id: str
    display_name: str
    description: str | None
    background_asset_id: str
    background_image_url: str


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
        for world in list_committed_worlds(connection)
    ]


def build_committed_world_card_response(
    world: CommittedWorld,
) -> CommittedWorldCardResponse:
    return CommittedWorldCardResponse(
        world_id=world.world_id,
        display_name=world.display_name,
        description=world.description,
        background_asset_id=world.background_asset_id,
        background_image_url=build_asset_file_url(world.background_asset_id),
    )


def build_asset_file_url(asset_id: str) -> str:
    return f"/assets/{quote(asset_id, safe='')}/file"
