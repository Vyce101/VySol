from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

from .entity_resolution_engine import (
    GraphStore,
    VectorStore,
    _abort_events,
    _active_runs,
    _build_exact_merge_entry,
    _choose_matches,
    _combine_entities,
    _commit_embedded_exact_batch,
    _commit_embedded_merge,
    _create_recovery_journal,
    _current_anchor_label_for_mode,
    _delete_recovery_journal,
    _embed_texts_abortable,
    _ensure_not_aborted,
    _entity_document,
    _get_unique_node_vector_store,
    _group_exact_matches,
    _journal_has_pending_work,
    _load_recovery_journal,
    _merge_group,
    _merge_status,
    _mode_uses_ai_pass,
    _mode_uses_exact_pass,
    _node_snapshot,
    _normalize_embedding_batch_size,
    _normalize_embedding_cooldown_seconds,
    _pending_merge_count,
    _persist_state_from_journal,
    _query_candidates,
    _reconcile_live_unique_node_drift,
    _recover_in_flight_transaction,
    _remove_completed_entries,
    _resume_status_message,
    _save_recovery_journal,
    _set_entry_status,
    _set_state,
    _sleep_with_abort,
    _state_payload_from_journal,
    _update_meta_from_state,
    _winner_vector_record,
    fail_entity_resolution_startup,
    push_sse_event,
    resolve_entity_resolution_mode,
)


async def start_entity_resolution_incremental(
    world_id: str,
    top_k: int,
    review_mode: bool,
    include_normalized_exact_pass: bool,
    resolution_mode: str,
    embedding_batch_size: int | None = None,
    embedding_cooldown_seconds: float | None = None,
) -> None:
    abort_event = _abort_events.get(world_id)
    if abort_event is None:
        abort_event = threading.Event()
        _abort_events[world_id] = abort_event
    _active_runs.add(world_id)

    live_graph_store: GraphStore | None = None
    unique_node_vector_store: VectorStore | None = None
    journal: dict[str, Any] | None = None
    try:
        live_graph_store = GraphStore(world_id)
        unique_node_vector_store = _get_unique_node_vector_store(world_id)
        journal = _load_recovery_journal(world_id)

        if journal and _journal_has_pending_work(journal):
            journal = dict(journal)
            normalized_resolution_mode = resolve_entity_resolution_mode(
                journal.get("resolution_mode"),
                bool(journal.get("include_normalized_exact_pass", True)),
                missing_default="exact_only",
            )
            top_k = int(journal.get("top_k") or max(1, top_k))
            review_mode = bool(journal.get("review_mode", review_mode))
            normalized_embedding_batch_size = _normalize_embedding_batch_size(
                journal.get("embedding_batch_size", embedding_batch_size)
            )
            normalized_embedding_cooldown_seconds = _normalize_embedding_cooldown_seconds(
                journal.get("embedding_cooldown_seconds", embedding_cooldown_seconds)
            )
            include_exact_pass = bool(journal.get("include_normalized_exact_pass", _mode_uses_exact_pass(normalized_resolution_mode)))
        else:
            normalized_resolution_mode = resolve_entity_resolution_mode(
                resolution_mode,
                include_normalized_exact_pass,
            )
            normalized_embedding_batch_size = _normalize_embedding_batch_size(embedding_batch_size)
            normalized_embedding_cooldown_seconds = _normalize_embedding_cooldown_seconds(embedding_cooldown_seconds)
            include_exact_pass = _mode_uses_exact_pass(normalized_resolution_mode)
            journal = _create_recovery_journal(
                world_id=world_id,
                top_k=max(1, top_k),
                review_mode=review_mode,
                resolution_mode=normalized_resolution_mode,
                include_normalized_exact_pass=include_exact_pass,
                embedding_batch_size=normalized_embedding_batch_size,
                embedding_cooldown_seconds=normalized_embedding_cooldown_seconds,
                total_entities=live_graph_store.get_node_count(),
                current_anchor_label=_current_anchor_label_for_mode(normalized_resolution_mode),
            )

        use_ai_pass = _mode_uses_ai_pass(normalized_resolution_mode)
        journal["top_k"] = max(1, top_k)
        journal["review_mode"] = bool(review_mode)
        journal["resolution_mode"] = normalized_resolution_mode
        journal["include_normalized_exact_pass"] = include_exact_pass
        journal["embedding_batch_size"] = normalized_embedding_batch_size
        journal["embedding_cooldown_seconds"] = normalized_embedding_cooldown_seconds
        journal["phase"] = "preparing"
        journal["message"] = "Preparing entity resolution."
        journal["reason"] = None
        journal = _save_recovery_journal(world_id, journal)
        journal, _ = _recover_in_flight_transaction(world_id, journal, live_graph_store, unique_node_vector_store)
        journal = _save_recovery_journal(world_id, journal)
        _persist_state_from_journal(
            world_id,
            journal,
            graph_store=live_graph_store,
            status="in_progress",
            phase="preparing",
            message="Preparing entity resolution.",
            reason=None,
            push_event="status",
        )

        async def _report_embedding_wait(
            *,
            phase: str,
            retry_after_seconds: float,
            message_prefix: str,
            current_anchor: dict[str, Any] | None = None,
            reason: str | None = None,
        ) -> None:
            wait_seconds = max(1, int(float(retry_after_seconds) + 0.999))
            wait_reason = reason or f"All embedding API keys are cooling down. Retry in about {wait_seconds} seconds."
            journal["phase"] = phase
            journal["message"] = f"{message_prefix} Waiting for embedding API cooldown (~{wait_seconds}s)."
            journal["reason"] = wait_reason
            _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="in_progress",
                phase=phase,
                message=str(journal.get("message")),
                reason=wait_reason,
                current_anchor=current_anchor,
                push_event="progress",
            )

        _ensure_not_aborted(world_id, abort_event)

        drift = _reconcile_live_unique_node_drift(world_id, live_graph_store, unique_node_vector_store)
        missing_ids = list(drift.get("missing_graph_node_ids", []) or [])
        if missing_ids:
            if int(journal.get("committed_merge_count") or 0) <= 0 and _pending_merge_count(journal) <= 0:
                _delete_recovery_journal(world_id)
                journal = None
            raise RuntimeError("Finish unique-node embedding repair before running entity resolution.")

        if live_graph_store.get_node_count() == 0 and int((journal or {}).get("initial_total_entities") or 0) == 0:
            empty_journal = journal or _create_recovery_journal(
                world_id=world_id,
                top_k=max(1, top_k),
                review_mode=review_mode,
                resolution_mode=normalized_resolution_mode,
                include_normalized_exact_pass=include_exact_pass,
                embedding_batch_size=normalized_embedding_batch_size,
                embedding_cooldown_seconds=normalized_embedding_cooldown_seconds,
                total_entities=0,
                current_anchor_label=_current_anchor_label_for_mode(normalized_resolution_mode),
            )
            complete_payload = _set_state(
                world_id,
                **_state_payload_from_journal(
                    empty_journal,
                    status="complete",
                    phase="complete",
                    message="No entities are available for resolution.",
                    reason=None,
                    can_resume=False,
                ),
            )
            _update_meta_from_state(world_id, complete_payload, live_graph_store)
            push_sse_event(world_id, {"event": "complete", **complete_payload})
            _delete_recovery_journal(world_id)
            return

        if include_exact_pass and not journal.get("exact_plan_complete"):
            journal["current_anchor_label"] = "Current Exact Match Group"
            journal["phase"] = "exact_match_scan"
            journal["message"] = "Scanning exact normalized match groups. Large worlds may take a bit here."
            journal["reason"] = None
            journal = _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="in_progress",
                phase="exact_match_scan",
                message="Scanning exact normalized match groups. Large worlds may take a bit here.",
                reason=None,
                push_event="progress",
            )
            exact_groups = _group_exact_matches(live_graph_store, list(live_graph_store.graph.nodes()))
            if exact_groups:
                journal["message"] = f"Scanning exact normalized match groups ({len(exact_groups)}/{len(exact_groups)})."
                journal["reason"] = None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="exact_match_scan",
                    message=str(journal.get("message")),
                    reason=None,
                    push_event="progress",
                )
            journal["pending_exact_groups"] = [
                [str(node_id) for node_id in group if str(node_id).strip()]
                for group in exact_groups
                if isinstance(group, list)
            ]
            journal["pending_exact_merges"] = list(journal.get("pending_exact_merges", []) or [])
            journal["exact_plan_complete"] = True
            journal["embedding_total_entities"] = int(journal.get("embedding_total_entities") or 0) + len(exact_groups)
            journal["phase"] = "exact_match_embedding"
            journal["message"] = (
                f"Queued {len(exact_groups)} exact normalized match groups for batched embedding."
                if exact_groups
                else "No exact normalized match groups were found."
            )
            journal = _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="in_progress",
                phase=str(journal.get("phase") or "exact_match_embedding"),
                message=str(journal.get("message") or "Embedding exact-match winners."),
                reason=None,
                push_event="progress",
            )

        if include_exact_pass and not journal.get("exact_phase_complete"):
            journal["current_anchor_label"] = "Current Exact Match Group"
            while True:
                pending_exact_entries = [
                    dict(entry)
                    for entry in journal.get("pending_exact_merges", []) or []
                    if isinstance(entry, dict) and _merge_status(entry) != "complete"
                ]
                if not pending_exact_entries:
                    pending_exact_groups = [
                        [str(node_id) for node_id in group if str(node_id).strip()]
                        for group in journal.get("pending_exact_groups", []) or []
                        if isinstance(group, list)
                    ]
                    if not pending_exact_groups:
                        journal["pending_exact_merges"] = []
                        journal["pending_exact_groups"] = []
                        journal["exact_phase_complete"] = True
                        journal = _save_recovery_journal(world_id, journal)
                        break

                    batch_groups = pending_exact_groups[:normalized_embedding_batch_size]
                    journal["pending_exact_groups"] = pending_exact_groups[normalized_embedding_batch_size:]
                    batch_entries = [
                        entry
                        for entry in (_build_exact_merge_entry(live_graph_store, group) for group in batch_groups)
                        if isinstance(entry, dict)
                    ]
                    journal["pending_exact_merges"] = batch_entries
                    journal["phase"] = "exact_match_embedding"
                    journal["message"] = (
                        f"Prepared {len(batch_entries)} exact groups for embedding; "
                        f"{len(journal.get('pending_exact_groups', []) or [])} exact groups remain queued."
                    )
                    journal["reason"] = None
                    journal = _save_recovery_journal(world_id, journal)
                    _persist_state_from_journal(
                        world_id,
                        journal,
                        graph_store=live_graph_store,
                        status="in_progress",
                        phase="exact_match_embedding",
                        message=str(journal.get("message")),
                        reason=None,
                        current_anchor=(
                            batch_entries[0].get("winner_snapshot")
                            if batch_entries and isinstance(batch_entries[0].get("winner_snapshot"), dict)
                            else None
                        ),
                        push_event="progress",
                    )
                    pending_exact_entries = [
                        dict(entry)
                        for entry in journal.get("pending_exact_merges", []) or []
                        if isinstance(entry, dict) and _merge_status(entry) != "complete"
                    ]
                    if not pending_exact_entries:
                        continue

                _ensure_not_aborted(world_id, abort_event)
                batch_entries = pending_exact_entries[:normalized_embedding_batch_size]
                batch_winners = [
                    entry.get("winner_snapshot")
                    for entry in batch_entries
                    if isinstance(entry.get("winner_snapshot"), dict)
                ]
                if not batch_winners:
                    attempted_entry_ids = {
                        str(entry.get("entry_id") or "").strip()
                        for entry in batch_entries
                        if isinstance(entry, dict) and str(entry.get("entry_id") or "").strip()
                    }
                    journal["pending_exact_merges"] = [
                        existing
                        for existing in journal.get("pending_exact_merges", []) or []
                        if isinstance(existing, dict)
                        and _merge_status(existing) != "complete"
                        and str(existing.get("entry_id") or "").strip() not in attempted_entry_ids
                    ]
                    journal = _save_recovery_journal(world_id, journal)
                    continue

                exact_total = int(journal.get("embedding_total_entities") or 0)
                exact_completed = int(journal.get("embedding_completed_entities") or 0)
                batch_start = exact_completed + 1
                batch_end = exact_completed + len(batch_winners)
                journal["phase"] = "exact_match_embedding"
                journal["message"] = (
                    f"Embedding exact winners {batch_start}-{batch_end} of {max(exact_total, batch_end)}."
                )
                journal["reason"] = None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="exact_match_embedding",
                    message=str(journal.get("message")),
                    reason=None,
                    current_anchor=batch_winners[0],
                    push_event="progress",
                )

                embeddings = await _embed_texts_abortable(
                    unique_node_vector_store,
                    [_entity_document(winner) for winner in batch_winners],
                    abort_event=abort_event,
                    wait_callback=lambda retry_after_seconds, anchor=batch_winners[0]: _report_embedding_wait(
                        phase="exact_match_embedding",
                        retry_after_seconds=retry_after_seconds,
                        message_prefix="Exact winner embedding is rate-limited.",
                        current_anchor=anchor if isinstance(anchor, dict) else None,
                    ),
                )
                _ensure_not_aborted(world_id, abort_event)

                journal["phase"] = "exact_match_apply"
                journal["message"] = f"Applying embedded exact-match batch of {len(batch_entries)}."
                journal["reason"] = None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="exact_match_apply",
                    message=str(journal.get("message")),
                    reason=None,
                    push_event="progress",
                )

                winner_records = [
                    _winner_vector_record(entry, embeddings[batch_offset])
                    for batch_offset, entry in enumerate(batch_entries)
                ]
                journal, committed_anchors = _commit_embedded_exact_batch(
                    world_id,
                    journal,
                    live_graph_store,
                    unique_node_vector_store,
                    batch_entries,
                    winner_records,
                )
                anchor_names = [
                    anchor.get("display_name")
                    for anchor in committed_anchors
                    if isinstance(anchor, dict) and str(anchor.get("display_name") or "").strip()
                ]
                journal["phase"] = "exact_match_apply"
                journal["message"] = (
                    f"Committed exact batch of {len(batch_entries)} merges."
                    if not anchor_names
                    else f"Committed exact batch of {len(batch_entries)} merges ending with {anchor_names[-1]}."
                )
                journal["reason"] = None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="exact_match_apply",
                    message=str(journal.get("message")),
                    reason=None,
                    current_anchor=(
                        committed_anchors[-1]
                        if committed_anchors and isinstance(committed_anchors[-1], dict)
                        else None
                    ),
                    push_event="progress",
                )

                journal["pending_exact_merges"] = _remove_completed_entries(list(journal.get("pending_exact_merges", []) or []))
                journal = _save_recovery_journal(world_id, journal)
                if journal.get("pending_exact_merges") or journal.get("pending_exact_groups"):
                    await _sleep_with_abort(abort_event, normalized_embedding_cooldown_seconds)

            journal["pending_exact_merges"] = _remove_completed_entries(list(journal.get("pending_exact_merges", []) or []))
            journal["pending_exact_groups"] = [
                [str(node_id) for node_id in group if str(node_id).strip()]
                for group in journal.get("pending_exact_groups", []) or []
                if isinstance(group, list)
            ]
            journal["exact_phase_complete"] = not journal.get("pending_exact_merges") and not journal.get("pending_exact_groups")
            journal = _save_recovery_journal(world_id, journal)

        if not use_ai_pass:
            complete_payload = _set_state(
                world_id,
                **_state_payload_from_journal(
                    journal,
                    status="complete",
                    phase="complete",
                    message="Exact-only entity resolution complete.",
                    reason=None,
                    can_resume=False,
                ),
            )
            _update_meta_from_state(world_id, complete_payload, live_graph_store)
            push_sse_event(world_id, {"event": "complete", **complete_payload})
            _delete_recovery_journal(world_id)
            return

        journal["current_anchor_label"] = "Current Anchor"
        if journal.get("ai_remaining_ids") is None:
            journal["ai_remaining_ids"] = [str(node_id) for node_id in live_graph_store.graph.nodes()]
            journal = _save_recovery_journal(world_id, journal)

        while not journal.get("ai_phase_complete"):
            _ensure_not_aborted(world_id, abort_event)

            pending_ai_entries = [
                dict(entry)
                for entry in journal.get("pending_ai_merges", []) or []
                if isinstance(entry, dict) and _merge_status(entry) != "complete"
            ]
            if pending_ai_entries:
                entry = pending_ai_entries[0]
                winner_snapshot = entry.get("winner_snapshot") if isinstance(entry.get("winner_snapshot"), dict) else None
                anchor_snapshot = winner_snapshot or (
                    entry.get("source_snapshots")[0]
                    if isinstance(entry.get("source_snapshots"), list) and entry.get("source_snapshots")
                    else None
                )
                if not winner_snapshot:
                    journal["pending_ai_merges"] = _set_entry_status(
                        list(journal.get("pending_ai_merges", []) or []),
                        str(entry.get("entry_id")),
                        "complete",
                    )
                    journal["pending_ai_merges"] = _remove_completed_entries(list(journal.get("pending_ai_merges", []) or []))
                    journal = _save_recovery_journal(world_id, journal)
                    continue

                journal["phase"] = "embedding"
                journal["message"] = (
                    f"Embedding merged entity for {winner_snapshot.get('display_name') or (anchor_snapshot or {}).get('display_name') or 'current anchor'}."
                )
                journal["reason"] = str(entry.get("chooser_reason") or "") or None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="embedding",
                    message=str(journal.get("message")),
                    reason=journal.get("reason"),
                    current_anchor=anchor_snapshot if isinstance(anchor_snapshot, dict) else None,
                    push_event="progress",
                )
                embedding = (
                    await _embed_texts_abortable(
                        unique_node_vector_store,
                        [_entity_document(winner_snapshot)],
                        abort_event=abort_event,
                        wait_callback=lambda retry_after_seconds, anchor=winner_snapshot: _report_embedding_wait(
                            phase="embedding",
                            retry_after_seconds=retry_after_seconds,
                            message_prefix="Merged-entity embedding is rate-limited.",
                            current_anchor=anchor if isinstance(anchor, dict) else None,
                            reason=str(entry.get("chooser_reason") or "") or None,
                        ),
                    )
                )[0]
                _ensure_not_aborted(world_id, abort_event)
                winner_record = _winner_vector_record(entry, embedding)
                journal, committed_anchor = _commit_embedded_merge(
                    world_id,
                    journal,
                    live_graph_store,
                    unique_node_vector_store,
                    entry,
                    winner_record,
                )
                removed_ids = {str(node_id) for node_id in entry.get("group_ids", []) or [] if str(node_id).strip()}
                journal["ai_remaining_ids"] = [
                    str(node_id)
                    for node_id in journal.get("ai_remaining_ids", []) or []
                    if str(node_id).strip() and str(node_id) not in removed_ids
                ]
                journal["phase"] = "applied"
                journal["message"] = (
                    f"Merged {len(removed_ids)} entities into {committed_anchor.get('display_name') if committed_anchor else winner_snapshot.get('display_name', 'merged entity')}."
                )
                journal["reason"] = str(entry.get("chooser_reason") or "") or None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="applied",
                    message=str(journal.get("message")),
                    reason=journal.get("reason"),
                    current_anchor=committed_anchor,
                    push_event="progress",
                )
                continue

            remaining_ids = [
                str(node_id)
                for node_id in journal.get("ai_remaining_ids", []) or []
                if str(node_id).strip() and str(node_id) in live_graph_store.graph.nodes
            ]
            journal["ai_remaining_ids"] = remaining_ids
            if not remaining_ids:
                journal["ai_phase_complete"] = True
                journal = _save_recovery_journal(world_id, journal)
                break

            anchor_id = remaining_ids[0]
            anchor = _node_snapshot(live_graph_store, anchor_id)
            if not anchor:
                journal["ai_remaining_ids"] = remaining_ids[1:]
                journal["resolved_entities"] = int(journal.get("resolved_entities") or 0) + 1
                journal["unresolved_entities"] = max(0, int(journal.get("unresolved_entities") or 0) - 1)
                journal["phase"] = "applied"
                journal["message"] = "Skipped an entity that no longer exists in the live graph."
                journal["reason"] = None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="applied",
                    message=str(journal.get("message")),
                    reason=None,
                    push_event="progress",
                )
                continue

            if len(remaining_ids) == 1:
                journal["resolved_entities"] = int(journal.get("resolved_entities") or 0) + 1
                journal["unresolved_entities"] = max(0, int(journal.get("unresolved_entities") or 0) - 1)
                journal["ai_remaining_ids"] = []
                journal["ai_phase_complete"] = True
                journal["phase"] = "applied"
                journal["message"] = f"No remaining candidates for {anchor['display_name']}."
                journal["reason"] = "Only one unresolved entity remained."
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="applied",
                    message=str(journal.get("message")),
                    reason=str(journal.get("reason")),
                    current_anchor=anchor,
                    push_event="progress",
                )
                break

            journal["phase"] = "candidate_search"
            journal["message"] = f"Searching candidate entities for {anchor['display_name']}."
            journal["reason"] = None
            journal = _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="in_progress",
                phase="candidate_search",
                message=str(journal.get("message")),
                reason=None,
                current_anchor=anchor,
                push_event="progress",
            )

            candidates = await _query_candidates(
                live_graph_store,
                unique_node_vector_store,
                anchor_id,
                remaining_ids,
                top_k,
                abort_event=abort_event,
                wait_callback=lambda retry_after_seconds, anchor=anchor: _report_embedding_wait(
                    phase="candidate_search",
                    retry_after_seconds=retry_after_seconds,
                    message_prefix="Candidate search embedding is rate-limited.",
                    current_anchor=anchor if isinstance(anchor, dict) else None,
                ),
            )
            _ensure_not_aborted(world_id, abort_event)
            journal["phase"] = "candidate_search"
            journal["message"] = f"Evaluating {len(candidates)} candidates for {anchor['display_name']}."
            journal["reason"] = None
            journal = _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="in_progress",
                phase="candidate_search",
                message=str(journal.get("message")),
                reason=None,
                current_anchor=anchor,
                current_candidates=candidates,
                push_event="progress",
            )

            chosen_ids: list[str] = []
            chooser_reason = "No candidates were selected."
            if candidates:
                journal["phase"] = "chooser"
                journal["message"] = f"Chooser evaluating {len(candidates)} candidate entities."
                journal["reason"] = None
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="chooser",
                    message=str(journal.get("message")),
                    reason=None,
                    current_anchor=anchor,
                    current_candidates=candidates,
                    push_event="progress",
                )
                chosen_ids, chooser_reason = await _choose_matches(anchor, candidates, world_id=world_id)
                _ensure_not_aborted(world_id, abort_event)
                chosen_ids = [node_id for node_id in chosen_ids if node_id in remaining_ids and node_id != anchor_id]

            if chosen_ids:
                group_ids = [anchor_id, *chosen_ids]
                nodes = [snapshot for snapshot in (_node_snapshot(live_graph_store, node_id) for node_id in group_ids) if snapshot]
                journal["phase"] = "combiner"
                journal["message"] = f"Merging {len(group_ids)} entities for {anchor['display_name']}."
                journal["reason"] = chooser_reason
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="combiner",
                    message=str(journal.get("message")),
                    reason=chooser_reason,
                    current_anchor=anchor,
                    current_candidates=candidates,
                    push_event="progress",
                )
                display_name, description = await _combine_entities(nodes, world_id=world_id)
                _ensure_not_aborted(world_id, abort_event)
                working_graph_store = GraphStore.from_graph(world_id, live_graph_store.graph.copy(as_view=False))
                _merge_group(working_graph_store, anchor_id, chosen_ids, display_name, description)
                winner_snapshot = _node_snapshot(working_graph_store, anchor_id)
                if not winner_snapshot:
                    raise RuntimeError("Failed to build the merged winner snapshot for entity resolution.")
                entry = {
                    "entry_id": uuid.uuid4().hex,
                    "strategy": "ai",
                    "status": "pending_embedding",
                    "winner_id": anchor_id,
                    "loser_ids": chosen_ids,
                    "group_ids": group_ids,
                    "group_size": len(group_ids),
                    "auto_resolved_pairs_delta": len(chosen_ids),
                    "winner_snapshot": winner_snapshot,
                    "source_snapshots": nodes,
                    "chooser_reason": chooser_reason,
                }
                journal["pending_ai_merges"] = list(journal.get("pending_ai_merges", []) or []) + [entry]
                journal["embedding_total_entities"] = int(journal.get("embedding_total_entities") or 0) + 1
                journal["phase"] = "embedding"
                journal["message"] = f"Embedding merged entity for {display_name}."
                journal["reason"] = chooser_reason
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="in_progress",
                    phase="embedding",
                    message=str(journal.get("message")),
                    reason=chooser_reason,
                    current_anchor=anchor,
                    current_candidates=candidates,
                    push_event="progress",
                )
                continue

            journal["resolved_entities"] = int(journal.get("resolved_entities") or 0) + 1
            journal["unresolved_entities"] = max(0, int(journal.get("unresolved_entities") or 0) - 1)
            journal["ai_remaining_ids"] = remaining_ids[1:]
            journal["phase"] = "applied"
            journal["message"] = f"No merge selected for {anchor['display_name']}."
            journal["reason"] = chooser_reason
            journal = _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="in_progress",
                phase="applied",
                message=str(journal.get("message")),
                reason=chooser_reason,
                current_anchor=anchor,
                push_event="progress",
            )
        complete_payload = _set_state(
            world_id,
            **_state_payload_from_journal(
                journal,
                status="complete",
                phase="complete",
                message="Entity resolution complete.",
                reason=None,
                can_resume=False,
            ),
        )
        _update_meta_from_state(world_id, complete_payload, live_graph_store)
        push_sse_event(world_id, {"event": "complete", **complete_payload})
        _delete_recovery_journal(world_id)
    except asyncio.CancelledError:
        if journal:
            if live_graph_store is not None and unique_node_vector_store is not None:
                journal, _ = _recover_in_flight_transaction(world_id, journal, live_graph_store, unique_node_vector_store)
            message = _resume_status_message(journal, prefix="Entity resolution aborted")
            journal["phase"] = "aborted"
            journal["message"] = message
            journal["reason"] = "aborted"
            journal = _save_recovery_journal(world_id, journal)
            _persist_state_from_journal(
                world_id,
                journal,
                graph_store=live_graph_store,
                status="aborted",
                phase="aborted",
                message=message,
                reason="aborted",
                push_event="aborted",
            )
        else:
            state = _set_state(
                world_id,
                status="aborted",
                phase="aborted",
                message="Entity resolution aborted.",
                reason="aborted",
                current_anchor=None,
                current_candidates=[],
                current_anchor_label=None,
                staging_collection_suffix=None,
                staging_graph_path=None,
                commit_pending=False,
                commit_state=None,
            )
            _update_meta_from_state(world_id, state, live_graph_store)
            push_sse_event(world_id, {"event": "aborted", **state})
    except Exception as exc:
        if journal:
            if live_graph_store is not None and unique_node_vector_store is not None:
                journal, _ = _recover_in_flight_transaction(world_id, journal, live_graph_store, unique_node_vector_store)
            if _journal_has_pending_work(journal):
                message = _resume_status_message(journal, prefix="Entity resolution failed")
                journal["phase"] = "error"
                journal["message"] = message
                journal["reason"] = str(exc)
                journal = _save_recovery_journal(world_id, journal)
                _persist_state_from_journal(
                    world_id,
                    journal,
                    graph_store=live_graph_store,
                    status="error",
                    phase="error",
                    message=message,
                    reason=str(exc),
                    push_event="error",
                )
            else:
                _delete_recovery_journal(world_id)
                fail_entity_resolution_startup(
                    world_id,
                    "Entity resolution failed.",
                    reason=str(exc),
                    graph_store=live_graph_store,
                )
        else:
            fail_entity_resolution_startup(
                world_id,
                "Entity resolution failed.",
                reason=str(exc),
                graph_store=live_graph_store,
            )
    finally:
        _active_runs.discard(world_id)
        if _abort_events.get(world_id) is abort_event:
            _abort_events.pop(world_id, None)
