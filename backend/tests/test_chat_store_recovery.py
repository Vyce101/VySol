import json

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

    older_page = store.get_chat_page(created["id"], cursor=latest_page["cursor"])
    assert older_page is not None
    assert len(older_page["messages"]) == 5
    assert older_page["messages"][0]["message_id"] == "m-0"
    assert older_page["has_more"] is False
