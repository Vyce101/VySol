from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from app.ingestion.staging.source_type_filter import build_source_staging_list
from app.logger import get_logger

logger = get_logger()


class SourceStagingStateError(ValueError):
    pass


@dataclass(frozen=True)
class TemporarySourceStagingEntry:
    staging_entry_id: str
    source_file_path: Path
    source_file_type: str
    is_valid: bool
    error_message: str | None


@dataclass(frozen=True)
class SourceStagingState:
    staging_context_id: str
    entries: tuple[TemporarySourceStagingEntry, ...]


class SourceStagingStateRegistry:
    def __init__(self) -> None:
        self._staging_states: dict[str, SourceStagingState] = {}

    def create_staging_context(self, staging_context_id: str) -> SourceStagingState:
        state = SourceStagingState(
            staging_context_id=validate_staging_context_id(staging_context_id),
            entries=(),
        )
        self._staging_states[state.staging_context_id] = state
        return state

    def get_staging_state(self, staging_context_id: str) -> SourceStagingState | None:
        return self._staging_states.get(staging_context_id)

    def replace_staging_state(
        self,
        staging_context_id: str,
        entries: Sequence[TemporarySourceStagingEntry],
    ) -> SourceStagingState:
        state = SourceStagingState(
            staging_context_id=validate_staging_context_id(staging_context_id),
            entries=validate_temporary_staging_entries(entries),
        )
        self._staging_states[state.staging_context_id] = state
        return state

    def add_source_file_paths(
        self,
        staging_context_id: str,
        source_file_paths: Sequence[Path],
    ) -> SourceStagingState | None:
        state = self.get_staging_state(staging_context_id)
        if state is None:
            return None

        try:
            staging_items = build_source_staging_list(source_file_paths)
            added_entries = tuple(
                TemporarySourceStagingEntry(
                    staging_entry_id=str(uuid4()),
                    source_file_path=staging_item.source_file_path,
                    source_file_type=staging_item.source_file_type,
                    is_valid=staging_item.is_valid,
                    error_message=staging_item.error_message,
                )
                for staging_item in staging_items
            )
        except Exception as error:
            logger.error("Failed to add temporary source staging entries.", exc_info=True)
            raise RuntimeError(
                "Failed to add temporary source staging entries."
            ) from error

        updated_state = SourceStagingState(
            staging_context_id=state.staging_context_id,
            entries=state.entries + added_entries,
        )
        self._staging_states[staging_context_id] = updated_state
        logger.debug(
            "Added temporary source staging entries: staging_context_id=%s count=%s",
            staging_context_id,
            len(added_entries),
        )
        return updated_state

    def remove_staging_entry(
        self,
        staging_context_id: str,
        staging_entry_id: str,
    ) -> SourceStagingState | None:
        state = self.get_staging_state(staging_context_id)
        if state is None:
            return None

        updated_entries = tuple(
            entry
            for entry in state.entries
            if entry.staging_entry_id != staging_entry_id
        )
        updated_state = SourceStagingState(
            staging_context_id=state.staging_context_id,
            entries=updated_entries,
        )
        self._staging_states[staging_context_id] = updated_state
        removed_count = len(state.entries) - len(updated_entries)
        logger.debug(
            "Removed temporary source staging entries: staging_context_id=%s count=%s",
            staging_context_id,
            removed_count,
        )
        return updated_state

    def reorder_staging_entries(
        self,
        staging_context_id: str,
        ordered_staging_entry_ids: Sequence[str],
    ) -> SourceStagingState | None:
        state = self.get_staging_state(staging_context_id)
        if state is None:
            return None

        reordered_entries = reorder_entries(
            state.entries,
            ordered_staging_entry_ids,
        )
        updated_state = SourceStagingState(
            staging_context_id=state.staging_context_id,
            entries=reordered_entries,
        )
        self._staging_states[staging_context_id] = updated_state
        return updated_state

    def discard_staging_context(
        self,
        staging_context_id: str,
    ) -> SourceStagingState | None:
        return self._staging_states.pop(staging_context_id, None)


def validate_staging_context_id(staging_context_id: str) -> str:
    if type(staging_context_id) is str and staging_context_id.strip():
        return staging_context_id

    reject_staging_state("Temporary source staging context ID is required.")


def validate_temporary_staging_entries(
    entries: Sequence[TemporarySourceStagingEntry],
) -> tuple[TemporarySourceStagingEntry, ...]:
    validated_entries = tuple(entries)
    entry_ids = [entry.staging_entry_id for entry in validated_entries]

    if len(set(entry_ids)) != len(entry_ids):
        reject_staging_state("Temporary source staging entry IDs must be unique.")

    return validated_entries


def reorder_entries(
    entries: Sequence[TemporarySourceStagingEntry],
    ordered_staging_entry_ids: Sequence[str],
) -> tuple[TemporarySourceStagingEntry, ...]:
    entries_by_id = {entry.staging_entry_id: entry for entry in entries}
    ordered_entry_ids = tuple(ordered_staging_entry_ids)

    if set(ordered_entry_ids) != set(entries_by_id):
        reject_staging_state("Temporary source staging reorder IDs must match entries.")

    if len(ordered_entry_ids) != len(entries_by_id):
        reject_staging_state("Temporary source staging reorder IDs must be unique.")

    return tuple(entries_by_id[entry_id] for entry_id in ordered_entry_ids)


def reject_staging_state(message: str) -> NoReturn:
    logger.error("Temporary source staging state failure: %s", message)
    raise SourceStagingStateError(message)


_source_staging_state_registry = SourceStagingStateRegistry()


def create_staging_context(staging_context_id: str) -> SourceStagingState:
    return _source_staging_state_registry.create_staging_context(staging_context_id)


def get_staging_state(staging_context_id: str) -> SourceStagingState | None:
    return _source_staging_state_registry.get_staging_state(staging_context_id)


def replace_staging_state(
    staging_context_id: str,
    entries: Sequence[TemporarySourceStagingEntry],
) -> SourceStagingState:
    return _source_staging_state_registry.replace_staging_state(
        staging_context_id,
        entries,
    )


def add_source_file_paths(
    staging_context_id: str,
    source_file_paths: Sequence[Path],
) -> SourceStagingState | None:
    return _source_staging_state_registry.add_source_file_paths(
        staging_context_id,
        source_file_paths,
    )


def remove_staging_entry(
    staging_context_id: str,
    staging_entry_id: str,
) -> SourceStagingState | None:
    return _source_staging_state_registry.remove_staging_entry(
        staging_context_id,
        staging_entry_id,
    )


def reorder_staging_entries(
    staging_context_id: str,
    ordered_staging_entry_ids: Sequence[str],
) -> SourceStagingState | None:
    return _source_staging_state_registry.reorder_staging_entries(
        staging_context_id,
        ordered_staging_entry_ids,
    )


def discard_staging_context(staging_context_id: str) -> SourceStagingState | None:
    return _source_staging_state_registry.discard_staging_context(staging_context_id)
