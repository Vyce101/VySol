import asyncio

from core import ingestion_engine
from routers import worlds as worlds_router


def _empty_safety_summary() -> dict:
    return {
        "total_reviews": 0,
        "unresolved_reviews": 0,
        "resolved_reviews": 0,
        "active_override_reviews": 0,
        "blocked_reviews": 0,
        "draft_reviews": 0,
        "testing_reviews": 0,
        "blocks_rebuild": False,
        "blocking_message": None,
    }


def test_get_ingestion_audit_snapshot_uses_live_summary_for_active_runs(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "total_nodes": 5,
        "embedded_unique_nodes": 3,
        "ingestion_blocking_issues": [{"code": "waiting"}],
        "sources": [
            {
                "source_id": "source-1",
                "display_name": "Book 1",
                "chunk_count": 4,
                "status": "ingesting",
                "extracted_chunks": [0, 1, 2],
                "embedded_chunks": [0, 1],
                "stage_failures": [],
            }
        ],
    }
    called = {"audit": False}

    def fail_audit(*args, **kwargs):
        called["audit"] = True
        raise AssertionError("live audit snapshot should not call the heavy audit path")

    monkeypatch.setattr(ingestion_engine, "has_active_ingestion_run", lambda world_id: True)
    monkeypatch.setattr(ingestion_engine, "audit_ingestion_integrity", fail_audit)

    summary = ingestion_engine.get_ingestion_audit_snapshot("world-1", meta=meta, synthesize_failures=False, persist=False)

    assert called["audit"] is False
    assert summary["world"]["expected_chunks"] == 4
    assert summary["world"]["extracted_chunks"] == 3
    assert summary["world"]["embedded_chunks"] == 2
    assert summary["world"]["current_unique_nodes"] == 5
    assert summary["world"]["embedded_unique_nodes"] == 3
    assert summary["world"]["expected_node_vectors"] == 5
    assert summary["blocking_issues"] == [{"code": "waiting"}]


def test_list_worlds_returns_trimmed_world_cards(monkeypatch):
    monkeypatch.setattr(
        worlds_router,
        "_collect_worlds",
        lambda: [
            {
                "world_id": "world-1",
                "world_name": "Alpha",
                "created_at": "2026-03-24T10:00:00+00:00",
                "ingestion_status": "pending",
                "total_chunks": 7,
                "total_nodes": 12,
                "total_edges": 18,
                "sources": [
                    {"source_id": "source-1", "status": "pending", "display_name": "Book 1"},
                ],
                "ingestion_audit": {"world": {"expected_chunks": 999}},
                "ingest_settings": {"embedding_model": "should-not-leak"},
                "duplication_locked": True,
            }
        ],
    )

    payload = asyncio.run(worlds_router.list_worlds())

    assert payload == [
        {
            "world_id": "world-1",
            "world_name": "Alpha",
            "created_at": "2026-03-24T10:00:00+00:00",
            "ingestion_status": "pending",
            "total_chunks": 7,
            "total_nodes": 12,
            "total_edges": 18,
            "sources": [{"source_id": "source-1", "status": "pending"}],
            "is_temporary_duplicate": False,
            "duplication_status": None,
            "duplication_progress_percent": 0,
            "duplication_source_world_id": None,
            "duplication_source_world_name": None,
            "active_duplication_run": False,
            "duplication_locked": True,
            "duplication_error": None,
        }
    ]


def test_get_world_skips_heavy_checks_during_active_ingest(monkeypatch):
    meta = {
        "world_id": "world-1",
        "world_name": "Alpha",
        "ingestion_status": "in_progress",
        "total_chunks": 4,
        "total_nodes": 6,
        "total_edges": 5,
        "sources": [],
    }
    captured: dict[str, object] = {}

    def fake_audit_snapshot(world_id: str, *, meta=None, synthesize_failures=True, persist=True):
        captured["synthesize_failures"] = synthesize_failures
        captured["persist"] = persist
        return {
            "world": {"expected_chunks": 4, "embedded_chunks": 2},
            "sources": [],
            "failures": [],
            "blocking_issues": [],
        }

    monkeypatch.setattr(worlds_router, "recover_stale_ingestion", lambda world_id: dict(meta))
    monkeypatch.setattr(worlds_router, "has_active_ingestion_run", lambda world_id: True)
    monkeypatch.setattr(worlds_router, "get_ingestion_audit_snapshot", fake_audit_snapshot)
    monkeypatch.setattr(worlds_router, "get_safety_review_summary", lambda world_id: _empty_safety_summary())
    monkeypatch.setattr(worlds_router, "get_reembed_eligibility", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")))
    monkeypatch.setattr(
        worlds_router,
        "get_world_ingest_settings",
        lambda meta=None: {
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_provider": "gemini",
            "embedding_openai_compatible_provider": "groq",
        },
    )

    payload = asyncio.run(worlds_router.get_world("world-1"))

    assert captured == {
        "synthesize_failures": False,
        "persist": False,
    }
    assert payload["active_ingestion_run"] is True
    assert payload["ingestion_audit"]["world"]["embedded_chunks"] == 2
    assert payload["reembed_eligibility"]["reason_code"] == "ingestion_in_progress"
    assert payload["embedding_provider"] == "gemini"


def test_list_sources_skips_audit_during_active_ingest(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "sources": [{"source_id": "source-1", "status": "ingesting"}],
    }
    calls = {"audit": 0}

    def fake_audit_snapshot(*args, **kwargs):
        calls["audit"] += 1
        return {}

    monkeypatch.setattr(worlds_router, "recover_stale_ingestion", lambda world_id: meta)
    monkeypatch.setattr(worlds_router, "has_active_ingestion_run", lambda world_id: True)
    monkeypatch.setattr(worlds_router, "get_ingestion_audit_snapshot", fake_audit_snapshot)

    payload = asyncio.run(worlds_router.list_sources("world-1"))

    assert calls["audit"] == 0
    assert payload == meta["sources"]


def test_checkpoint_info_uses_live_audit_snapshot_during_active_ingest(monkeypatch):
    meta = {
        "world_id": "world-1",
        "ingestion_status": "in_progress",
        "sources": [
            {
                "source_id": "source-1",
                "display_name": "Book 1",
                "book_number": 1,
                "chunk_count": 4,
                "status": "ingesting",
                "failed_chunks": [],
                "stage_failures": [],
                "extracted_chunks": [0, 1, 2],
                "embedded_chunks": [0, 1],
            }
        ],
        "total_nodes": 6,
        "embedded_unique_nodes": 4,
        "ingestion_blocking_issues": [],
    }
    checkpoint = {
        "source_id": "source-1",
        "last_completed_chunk_index": 1,
        "chunks_total": 4,
    }
    captured: dict[str, object] = {}

    def fake_audit_snapshot(world_id: str, *, meta=None, synthesize_failures=True, persist=True):
        captured["synthesize_failures"] = synthesize_failures
        captured["persist"] = persist
        return {
            "world": {
                "expected_chunks": 4,
                "extracted_chunks": 3,
                "embedded_chunks": 2,
                "current_unique_nodes": 6,
                "embedded_unique_nodes": 4,
                "failed_records": 0,
                "blocking_issues": 0,
                "sources_total": 1,
                "sources_complete": 0,
                "sources_partial_failure": 0,
                "synthesized_failures": 0,
            },
            "failures": [],
            "blocking_issues": [],
        }

    monkeypatch.setattr(ingestion_engine, "recover_stale_ingestion", lambda world_id: meta)
    monkeypatch.setattr(ingestion_engine, "_load_checkpoint", lambda world_id: checkpoint)
    monkeypatch.setattr(ingestion_engine, "_load_meta", lambda world_id: meta)
    monkeypatch.setattr(ingestion_engine, "has_active_ingestion_run", lambda world_id: True)
    monkeypatch.setattr(ingestion_engine, "get_ingestion_audit_snapshot", fake_audit_snapshot)
    monkeypatch.setattr(ingestion_engine, "get_safety_review_summary", lambda world_id: _empty_safety_summary())
    monkeypatch.setattr(ingestion_engine, "get_actionable_resume_sources", lambda world_id, sources=None: list(sources or []))
    monkeypatch.setattr(
        ingestion_engine,
        "_build_progress_event",
        lambda *args, **kwargs: {
            "progress_phase": "chunk_embedding",
            "progress_scope": "source",
            "completed_chunks_current_phase": 2,
            "total_chunks_current_phase": 4,
            "active_ingestion_run": True,
        },
    )

    payload = ingestion_engine.get_checkpoint_info("world-1")

    assert captured == {
        "synthesize_failures": False,
        "persist": False,
    }
    assert payload["stage_counters"]["embedded_chunks"] == 2
    assert payload["stage_counters"]["embedded_unique_nodes"] == 4
    assert payload["active_ingestion_run"] is True
