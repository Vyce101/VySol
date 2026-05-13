from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.storage.asset_files import resolve_asset_file_path

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get(
    "/{asset_id}/file",
    status_code=status.HTTP_200_OK,
)
def read_asset_file(asset_id: str) -> FileResponse:
    asset_file_path = resolve_asset_file_path(asset_id)

    if not is_readable_file(asset_file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset file was not found.",
        )

    return FileResponse(asset_file_path)


def is_readable_file(path: Path | None) -> bool:
    return path is not None and path.is_file()
