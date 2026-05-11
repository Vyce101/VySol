from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from app.ingestion.staging.source_type_filter import build_source_staging_list
from app.logger import get_logger

logger = get_logger()

SOURCE_ORDER_KIND_COMMITTED = "committed"
SOURCE_ORDER_KIND_STAGED = "staged"


class SourceStagingStateError(ValueError):
    pass


class SourceReorderValidationError(SourceStagingStateError):
    pass


@dataclass(frozen=True)
class SourceOrderItem:
    source_kind: str
    source_id: str


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

        return self._remove_staging_entry_from_state(
            staging_context_id,
            state,
            staging_entry_id,
        )

    def remove_existing_world_source_item(
        self,
        staging_context_id: str,
        source_item: SourceOrderItem,
    ) -> SourceStagingState | None:
        state = self.get_staging_state(staging_context_id)
        if state is None:
            return None

        if type(source_item) is not SourceOrderItem:
            log_invalid_source_removal("Source removal item is invalid.")
            return state

        if source_item.source_kind == SOURCE_ORDER_KIND_COMMITTED:
            log_invalid_source_removal("Committed sources cannot be removed before commit.")
            return state

        if source_item.source_kind != SOURCE_ORDER_KIND_STAGED:
            log_invalid_source_removal("Source removal item kind is invalid.")
            return state

        return self._remove_staging_entry_from_state(
            staging_context_id,
            state,
            source_item.source_id,
        )

    def _remove_staging_entry_from_state(
        self,
        staging_context_id: str,
        state: SourceStagingState,
        staging_entry_id: str,
    ) -> SourceStagingState:
        try:
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
        except Exception as error:
            logger.error("Failed to remove temporary source staging entry.", exc_info=True)
            raise RuntimeError("Failed to remove temporary source staging entry.") from error

        removed_count = len(state.entries) - len(updated_entries)
        logger.debug(
            "Removed temporary source staging entry: staging_context_id=%s "
            "staging_entry_id=%s count=%s",
            staging_context_id,
            staging_entry_id,
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
        log_staged_reorder(reordered_entries)
        return updated_state

    def reorder_existing_world_staging_entries(
        self,
        staging_context_id: str,
        committed_source_ids: Sequence[str],
        ordered_source_items: Sequence[SourceOrderItem],
    ) -> SourceStagingState | None:
        state = self.get_staging_state(staging_context_id)
        if state is None:
            return None

        ordered_staging_entry_ids = get_ordered_existing_world_staging_entry_ids(
            state.entries,
            committed_source_ids,
            ordered_source_items,
        )
        reordered_entries = reorder_entries(
            state.entries,
            ordered_staging_entry_ids,
        )
        updated_state = SourceStagingState(
            staging_context_id=state.staging_context_id,
            entries=reordered_entries,
        )
        self._staging_states[staging_context_id] = updated_state
        log_staged_reorder(reordered_entries)
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

    if len(entries_by_id) != len(tuple(entries)):
        reject_staging_state("Temporary source staging entry IDs must be unique.")

    if set(ordered_entry_ids) != set(entries_by_id):
        reject_invalid_reorder("Temporary source staging reorder IDs must match entries.")

    if len(ordered_entry_ids) != len(entries_by_id):
        reject_invalid_reorder("Temporary source staging reorder IDs must be unique.")

    return tuple(entries_by_id[entry_id] for entry_id in ordered_entry_ids)


def get_ordered_existing_world_staging_entry_ids(
    entries: Sequence[TemporarySourceStagingEntry],
    committed_source_ids: Sequence[str],
    ordered_source_items: Sequence[SourceOrderItem],
) -> tuple[str, ...]:
    committed_ids = tuple(committed_source_ids)
    source_items = validate_source_order_items(ordered_source_items)
    ordered_committed_ids = tuple(
        item.source_id
        for item in source_items
        if item.source_kind == SOURCE_ORDER_KIND_COMMITTED
    )

    if ordered_committed_ids != committed_ids:
        reject_invalid_reorder("Committed source order cannot be changed.")

    if source_items[: len(committed_ids)] != tuple(
        SourceOrderItem(SOURCE_ORDER_KIND_COMMITTED, source_id)
        for source_id in committed_ids
    ):
        reject_invalid_reorder("Staged sources cannot be inserted before committed sources.")

    ordered_staging_entry_ids = tuple(
        item.source_id
        for item in source_items
        if item.source_kind == SOURCE_ORDER_KIND_STAGED
    )
    known_source_ids = set(committed_ids) | {
        entry.staging_entry_id for entry in entries
    }

    for item in source_items:
        if item.source_kind not in {
            SOURCE_ORDER_KIND_COMMITTED,
            SOURCE_ORDER_KIND_STAGED,
        }:
            reject_invalid_reorder("Source reorder item kind is invalid.")

        if item.source_id not in known_source_ids:
            reject_invalid_reorder("Source reorder item ID is unknown.")

    expected_item_count = len(committed_ids) + len(entries)
    if len(source_items) != expected_item_count:
        reject_invalid_reorder("Source reorder request must include every source once.")

    if len(set(source_items)) != len(source_items):
        reject_invalid_reorder("Source reorder request source IDs must be unique.")

    return ordered_staging_entry_ids


def validate_source_order_items(
    ordered_source_items: Sequence[SourceOrderItem],
) -> tuple[SourceOrderItem, ...]:
    source_items = tuple(ordered_source_items)

    for item in source_items:
        if type(item) is not SourceOrderItem:
            reject_invalid_reorder("Source reorder item is invalid.")

    return source_items


def log_staged_reorder(entries: Sequence[TemporarySourceStagingEntry]) -> None:
    staged_order = tuple(
        (order_index, entry.staging_entry_id)
        for order_index, entry in enumerate(entries)
    )
    logger.debug("Reordered temporary source staging entries: %s", staged_order)


def log_invalid_source_removal(message: str) -> None:
    logger.warning("Invalid temporary source removal request: %s", message)


def reject_invalid_reorder(message: str) -> NoReturn:
    logger.warning("Invalid temporary source reorder request: %s", message)
    raise SourceReorderValidationError(message)


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


def remove_existing_world_source_item(
    staging_context_id: str,
    source_item: SourceOrderItem,
) -> SourceStagingState | None:
    return _source_staging_state_registry.remove_existing_world_source_item(
        staging_context_id,
        source_item,
    )


def reorder_staging_entries(
    staging_context_id: str,
    ordered_staging_entry_ids: Sequence[str],
) -> SourceStagingState | None:
    return _source_staging_state_registry.reorder_staging_entries(
        staging_context_id,
        ordered_staging_entry_ids,
    )


def reorder_existing_world_staging_entries(
    staging_context_id: str,
    committed_source_ids: Sequence[str],
    ordered_source_items: Sequence[SourceOrderItem],
) -> SourceStagingState | None:
    return _source_staging_state_registry.reorder_existing_world_staging_entries(
        staging_context_id,
        committed_source_ids,
        ordered_source_items,
    )


def discard_staging_context(staging_context_id: str) -> SourceStagingState | None:
    return _source_staging_state_registry.discard_staging_context(staging_context_id)
