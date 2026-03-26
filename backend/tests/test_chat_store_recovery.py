import json

import pytest

from core import chat_store


def test_chat_store_recovers_orphan_backup(tmp_path, monkeypatch):
    world_id = "w1"
    chats_dir = tmp_path / world_id / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)

    bak_path = chats_dir / "chat-abc.bak1"
    payload = {
        "id": "chat-abc",
        "title": "Recovered",
        "created_at": "2026-03-20T00:00:00+00:00",
        "updated_at": "2026-03-20T01:00:00+00:00",
        "messages": [{"role": "user", "content": "hello"}],
    }
    with open(bak_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    monkeypatch.setattr(chat_store, "world_dir", lambda wid: tmp_path / wid)
    store = chat_store.ChatStore(world_id)

    recovered = store.get_chat("chat-abc")
    assert recovered is not None
    assert recovered["title"] == "Recovered"
    assert len(recovered["messages"]) == 1
    assert (chats_dir / "chat-abc" / "meta.json").exists()


def test_chat_store_returns_latest_page_and_older_cursor(tmp_path, monkeypatch):
    world_id = "w2"
    monkeypatch.setattr(chat_store, "world_dir", lambda wid: tmp_path / wid)
    store = chat_store.ChatStore(world_id)
    created = store.create_chat("New Chat")

    messages = [
        {
            "message_id": f"m-{index}",
            "role": "user" if index % 2 == 0 else "model",
            "content": f"message {index}",
            "status": "complete",
        }
        for index in range(25)
    ]
    store.save_chat(created["id"], {**created, "messages": messages}, expected_version=created["version"])

    latest_page = store.get_chat_page(created["id"])
    assert latest_page is not None
    assert len(latest_page["messages"]) == 20
    assert latest_page["messages"][0]["message_id"] == "m-5"
    assert latest_page["messages"][-1]["message_id"] == "m-24"
    assert latest_page["has_more"] is True
    assert latest_page["cursor"] == 20
    assert latest_page["history_integrity"] is None

    older_page = store.get_chat_page(created["id"], cursor=latest_page["cursor"])
    assert older_page is not None
    assert len(older_page["messages"]) == 5
    assert older_page["messages"][0]["message_id"] == "m-0"
    assert older_page["has_more"] is False

    pages_dir = tmp_path / world_id / "chats" / created["id"] / "pages"
    assert (pages_dir / "v2" / "page-000001.json").exists()
    assert (pages_dir / "v2" / "page-000002.json").exists()
    assert not (pages_dir / "page-000001.json").exists()


def test_chat_store_exposes_history_integrity_when_meta_total_exceeds_pages(tmp_path, monkeypatch):
    world_id = "w3"
    chat_id = "chat-meta-mismatch"
    monkeypatch.setattr(chat_store, "world_dir", lambda wid: tmp_path / wid)

    chat_dir = tmp_path / world_id / "chats" / chat_id
    pages_dir = chat_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": chat_id,
        "title": "Broken",
        "has_manual_title": False,
        "created_at": "2026-03-26T00:00:00+00:00",
        "updated_at": "2026-03-26T00:00:00+00:00",
        "version": 0,
        "storage_version": 2,
        "page_size": 20,
        "total_messages": 30,
    }
    with open(chat_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    messages = [
        {
            "message_id": f"m-{index}",
            "role": "user" if index % 2 == 0 else "model",
            "content": f"message {index}",
            "status": "complete",
        }
        for index in range(20)
    ]
    with open(pages_dir / "page-000001.json", "w", encoding="utf-8") as f:
        json.dump({"messages": messages}, f)

    store = chat_store.ChatStore(world_id)
    latest_page = store.get_chat_page(chat_id)

    assert latest_page is not None
    assert latest_page["total_messages"] == 20
    assert len(latest_page["messages"]) == 20
    assert latest_page["messages"][0]["message_id"] == "m-0"
    assert latest_page["messages"][-1]["message_id"] == "m-19"
    assert latest_page["has_more"] is False
    assert latest_page["cursor"] is None
    assert latest_page["history_integrity"] == {
        "status": "degraded",
        "code": "messages_missing",
        "message": (
            "Older saved chat history is missing from disk. "
            "Showing the 20 messages still available here; "
            "about 10 older messages could not be recovered."
        ),
        "recorded_total": 30,
        "persisted_total_at_detection": 20,
        "missing_messages_estimate": 10,
    }

    reloaded_meta = json.loads((chat_dir / "meta.json").read_text(encoding="utf-8"))
    assert reloaded_meta["total_messages"] == 30
    assert "history_integrity" not in reloaded_meta


def test_chat_store_reads_windows_from_actual_page_boundaries(tmp_path, monkeypatch):
    world_id = "w4"
    chat_id = "chat-variable-pages"
    monkeypatch.setattr(chat_store, "world_dir", lambda wid: tmp_path / wid)

    chat_dir = tmp_path / world_id / "chats" / chat_id
    pages_dir = chat_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": chat_id,
        "title": "Variable Pages",
        "has_manual_title": False,
        "created_at": "2026-03-26T00:00:00+00:00",
        "updated_at": "2026-03-26T00:00:00+00:00",
        "version": 0,
        "storage_version": 2,
        "page_size": 20,
        "total_messages": 25,
    }
    with open(chat_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    all_messages = [
        {
            "message_id": f"m-{index}",
            "role": "user" if index % 2 == 0 else "model",
            "content": f"message {index}",
            "status": "complete",
        }
        for index in range(25)
    ]
    page_slices = (
        all_messages[:10],
        all_messages[10:20],
        all_messages[20:25],
    )
    for page_index, page_messages in enumerate(page_slices, start=1):
        with open(pages_dir / f"page-{page_index:06d}.json", "w", encoding="utf-8") as f:
            json.dump({"messages": page_messages}, f)

    store = chat_store.ChatStore(world_id)
    latest_page = store.get_chat_page(chat_id)
    older_page = store.get_chat_page(chat_id, cursor=latest_page["cursor"])

    assert latest_page is not None
    assert len(latest_page["messages"]) == 20
    assert latest_page["messages"][0]["message_id"] == "m-5"
    assert latest_page["messages"][-1]["message_id"] == "m-24"
    assert latest_page["cursor"] == 20

    assert older_page is not None
    assert len(older_page["messages"]) == 5
    assert older_page["messages"][0]["message_id"] == "m-0"
    assert older_page["messages"][-1]["message_id"] == "m-4"
    assert older_page["has_more"] is False


def test_chat_store_failed_multi_page_save_keeps_previous_active_page_set(tmp_path, monkeypatch):
    world_id = "w5"
    monkeypatch.setattr(chat_store, "world_dir", lambda wid: tmp_path / wid)
    store = chat_store.ChatStore(world_id)
    created = store.create_chat("Durable")

    initial_messages = [
        {
            "message_id": f"m-{index}",
            "role": "user" if index % 2 == 0 else "model",
            "content": f"message {index}",
            "status": "complete",
        }
        for index in range(25)
    ]
    saved = store.save_chat(
        created["id"],
        {**created, "messages": initial_messages},
        expected_version=created["version"],
    )
    assert saved["version"] == 2

    original_dump = chat_store.dump_json_atomic

    def flaky_dump(path, payload, *args, **kwargs):
        if str(path).replace("\\", "/").endswith("v3/page-000002.json"):
            raise OSError("simulated write failure")
        return original_dump(path, payload, *args, **kwargs)

    monkeypatch.setattr(chat_store, "dump_json_atomic", flaky_dump)

    next_messages = [
        {
            "message_id": f"n-{index}",
            "role": "user" if index % 2 == 0 else "model",
            "content": f"next {index}",
            "status": "complete",
        }
        for index in range(45)
    ]

    with pytest.raises(OSError, match="simulated write failure"):
        store.save_chat(
            created["id"],
            {**saved, "messages": next_messages},
            expected_version=saved["version"],
        )

    latest_page = store.get_chat_page(created["id"])
    assert latest_page is not None
    assert latest_page["messages"][0]["message_id"] == "m-5"
    assert latest_page["messages"][-1]["message_id"] == "m-24"
    assert latest_page["history_integrity"] is None

    meta = json.loads((tmp_path / world_id / "chats" / created["id"] / "meta.json").read_text(encoding="utf-8"))
    assert meta["active_page_set"] == "v2"
    assert (tmp_path / world_id / "chats" / created["id"] / "pages" / "v3" / "page-000001.json").exists()


def test_chat_store_preserves_detected_history_integrity_on_later_save(tmp_path, monkeypatch):
    world_id = "w6"
    chat_id = "chat-preserve-integrity"
    monkeypatch.setattr(chat_store, "world_dir", lambda wid: tmp_path / wid)

    chat_dir = tmp_path / world_id / "chats" / chat_id
    pages_dir = chat_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": chat_id,
        "title": "Broken",
        "has_manual_title": False,
        "created_at": "2026-03-26T00:00:00+00:00",
        "updated_at": "2026-03-26T00:00:00+00:00",
        "version": 0,
        "storage_version": 2,
        "page_size": 20,
        "total_messages": 30,
    }
    with open(chat_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    messages = [
        {
            "message_id": f"m-{index}",
            "role": "user" if index % 2 == 0 else "model",
            "content": f"message {index}",
            "status": "complete",
        }
        for index in range(20)
    ]
    with open(pages_dir / "page-000001.json", "w", encoding="utf-8") as f:
        json.dump({"messages": messages}, f)

    store = chat_store.ChatStore(world_id)
    degraded = store.get_chat(chat_id)
    assert degraded is not None
    assert degraded["history_integrity"]["missing_messages_estimate"] == 10

    repaired_view = store.save_chat(
        chat_id,
        {
            **degraded,
            "messages": [
                *degraded["messages"],
                {
                    "message_id": "m-20",
                    "role": "user",
                    "content": "message 20",
                    "status": "complete",
                },
            ],
        },
        expected_version=degraded["version"],
    )

    assert repaired_view["version"] == 1
    page = store.get_chat_page(chat_id)
    assert page is not None
    assert page["total_messages"] == 21
    assert page["history_integrity"] == degraded["history_integrity"]

    persisted_meta = json.loads((chat_dir / "meta.json").read_text(encoding="utf-8"))
    assert persisted_meta["active_page_set"] == "v1"
    assert persisted_meta["history_integrity"] == degraded["history_integrity"]
