from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 4000
DEFAULT_MAX_LOOKBACK_SIZE = 1000
DEFAULT_OVERLAP_SIZE = 400


@dataclass(frozen=True)
class SplitterSettings:
    chunk_size: int
    max_lookback_size: int
    overlap_size: int


def create_default_splitter_settings() -> SplitterSettings:
    return SplitterSettings(
        chunk_size=DEFAULT_CHUNK_SIZE,
        max_lookback_size=DEFAULT_MAX_LOOKBACK_SIZE,
        overlap_size=DEFAULT_OVERLAP_SIZE,
    )
