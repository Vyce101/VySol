from uuid import uuid4

from app.draft_worlds.splitter_settings import (
    SplitterSettings,
    create_default_splitter_settings,
)
from app.draft_worlds.world import DraftWorld
from app.logger import get_logger

logger = get_logger()


class DraftWorldRegistry:
    def __init__(self) -> None:
        self._draft_worlds: dict[str, DraftWorld] = {}

    def create_draft_world(self) -> DraftWorld:
        try:
            splitter_settings = create_default_splitter_settings()
        except Exception:
            logger.error(
                "Failed to create default draft splitter settings.",
                exc_info=True,
            )
            raise

        draft_world = DraftWorld(
            draft_id=str(uuid4()),
            splitter_settings=splitter_settings,
        )
        self._draft_worlds[draft_world.draft_id] = draft_world
        return draft_world

    def get_draft_world(self, draft_id: str) -> DraftWorld | None:
        return self._draft_worlds.get(draft_id)

    def update_draft_splitter_settings(
        self,
        draft_id: str,
        splitter_settings: SplitterSettings,
    ) -> DraftWorld | None:
        draft_world = self.get_draft_world(draft_id)
        if draft_world is None:
            return None

        updated_draft_world = DraftWorld(
            draft_id=draft_world.draft_id,
            splitter_settings=splitter_settings,
        )
        self._draft_worlds[draft_id] = updated_draft_world
        return updated_draft_world

    def discard_draft_world(self, draft_id: str) -> DraftWorld | None:
        return self._draft_worlds.pop(draft_id, None)


_draft_world_registry = DraftWorldRegistry()


def get_draft_world_registry() -> DraftWorldRegistry:
    return _draft_world_registry


def create_draft_world() -> DraftWorld:
    return _draft_world_registry.create_draft_world()


def get_draft_world(draft_id: str) -> DraftWorld | None:
    return _draft_world_registry.get_draft_world(draft_id)


def update_draft_splitter_settings(
    draft_id: str,
    splitter_settings: SplitterSettings,
) -> DraftWorld | None:
    return _draft_world_registry.update_draft_splitter_settings(
        draft_id,
        splitter_settings,
    )


def discard_draft_world(draft_id: str) -> DraftWorld | None:
    return _draft_world_registry.discard_draft_world(draft_id)
