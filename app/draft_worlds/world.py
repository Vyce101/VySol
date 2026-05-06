from dataclasses import dataclass

from app.draft_worlds.splitter_settings import SplitterSettings


@dataclass(frozen=True)
class DraftWorld:
    draft_id: str
    splitter_settings: SplitterSettings
