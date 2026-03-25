import asyncio
import json
from pathlib import Path
import shutil
import uuid

import pytest
from fastapi import HTTPException

from core import chat_store
from routers import chat as chat_router


def _make_store(monkeypatch, world_id: str) -> chat_store.ChatStore:
    world_root = chat_store.world_dir(world_id)
    if world_root.exists():
        shutil.rmtree(world_root)
    world_root.mkdir(parents=True, exist_ok=True)

    meta_path = world_root / "world_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(chat_router, "world_meta_path", lambda wid: meta_path)
    return chat_store.ChatStore(world_id)


async def _consume_stream(response) -> list[str]:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    return chunks


async def _read_one_and_close(response) -> str:
    iterator = response.body_iterator
    first = await iterator.__anext__()
    await iterator.aclose()
    return first.decode("utf-8") if isinstance(first, bytes) else first


def _parse_sse(chunks: list[str]) -> list[dict]:
    events = []
    for chunk in chunks:
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:].strip()))
    return events


def test_update_history_rejects_stale_base_version(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Durable")

    result = asyncio.run(chat_router.update_chat_history(
        world_id,
        created["id"],
        chat_router.UpdateChatHistoryRequest(
            messages=[{"role": "user", "content": "hello"}],
            base_version=created["version"],
        ),
    ))

    assert result["version"] == created["version"] + 1
    assert result["messages"][0]["status"] == "complete"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_router.update_chat_history(
            world_id,
            created["id"],
            chat_router.UpdateChatHistoryRequest(
                messages=[{"role": "user", "content": "stale"}],
                base_version=created["version"],
            ),
        ))

    assert exc_info.value.status_code == 409


def test_rename_chat_updates_title_preserves_updated_at_and_lists_version(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Original")
    before = store.get_chat(created["id"])

    renamed = asyncio.run(chat_router.rename_chat(
        world_id,
        created["id"],
        chat_router.RenameChatRequest(
            title="  Renamed Chat  ",
            base_version=created["version"],
        ),
    ))

    saved = store.get_chat(created["id"])
    listed = store.list_chats()

    assert renamed["title"] == "Renamed Chat"
    assert renamed["version"] == created["version"] + 1
    assert saved is not None
    assert saved["title"] == "Renamed Chat"
    assert saved["version"] == created["version"] + 1
    assert before is not None
    assert saved["updated_at"] == before["updated_at"]
    assert listed[0]["id"] == created["id"]
    assert listed[0]["version"] == saved["version"]
    assert listed[0]["updated_at"] == before["updated_at"]


def test_rename_chat_rejects_blank_title(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Original")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_router.rename_chat(
            world_id,
            created["id"],
            chat_router.RenameChatRequest(
                title="   ",
                base_version=created["version"],
            ),
        ))

    assert exc_info.value.status_code == 400


def test_rename_chat_rejects_stale_base_version(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Original")

    first = asyncio.run(chat_router.rename_chat(
        world_id,
        created["id"],
        chat_router.RenameChatRequest(
            title="First Rename",
            base_version=created["version"],
        ),
    ))
    assert first["version"] == created["version"] + 1

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_router.rename_chat(
            world_id,
            created["id"],
            chat_router.RenameChatRequest(
                title="Second Rename",
                base_version=created["version"],
            ),
        ))

    assert exc_info.value.status_code == 409


def test_stream_reply_persists_placeholder_before_done_and_finishes_saved(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Durable")

    def fake_stream_chat(*, world_id, message, history, settings_override=None):
        yield f"data: {json.dumps({'token': 'hello'})}\n\n"
        yield f"data: {json.dumps({'token': ' world'})}\n\n"
        yield f"data: {json.dumps({'event': 'done', 'nodes_used': [{'id': 'n1'}], 'context_payload': {'messages': []}, 'context_meta': {'provider': 'test'}})}\n\n"

    monkeypatch.setattr(chat_router, "stream_chat", fake_stream_chat)

    response = asyncio.run(chat_router.stream_chat_message(
        world_id,
        created["id"],
        chat_router.ChatRequest(message="Hi there"),
    ))

    seeded = store.get_chat(created["id"])
    assert seeded is not None
    assert seeded["version"] == created["version"] + 1
    assert seeded["messages"][-2]["role"] == "user"
    assert seeded["messages"][-2]["content"] == "Hi there"
    assert seeded["messages"][-1]["role"] == "model"
    assert seeded["messages"][-1]["status"] == "streaming"

    chunks = asyncio.run(_consume_stream(response))
    events = _parse_sse(chunks)
    done_event = [event for event in events if event.get("event") == "done"][0]

    saved = store.get_chat(created["id"])
    assert saved is not None
    assert saved["version"] == done_event["chat_version"]
    assert saved["messages"][-1]["status"] == "complete"
    assert saved["messages"][-1]["content"] == "hello world"
    assert saved["messages"][-1]["context_meta"] == {"provider": "test"}


def test_stream_disconnect_marks_model_turn_incomplete(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Durable")

    def fake_stream_chat(*, world_id, message, history, settings_override=None):
        yield f"data: {json.dumps({'token': 'partial'})}\n\n"
        yield f"data: {json.dumps({'token': ' reply'})}\n\n"

    monkeypatch.setattr(chat_router, "stream_chat", fake_stream_chat)

    response = asyncio.run(chat_router.stream_chat_message(
        world_id,
        created["id"],
        chat_router.ChatRequest(message="Hi there"),
    ))

    first_chunk = asyncio.run(_read_one_and_close(response))
    assert "partial" in first_chunk

    saved = store.get_chat(created["id"])
    assert saved is not None
    assert saved["messages"][-1]["status"] == "incomplete"
    assert saved["messages"][-1]["content"] == "partial"


def test_get_chat_messages_returns_latest_page(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Durable")
    stored = store.save_chat(
        created["id"],
        {
            **created,
            "messages": [
                {
                    "message_id": f"m-{index}",
                    "role": "user" if index % 2 == 0 else "model",
                    "content": f"message {index}",
                    "status": "complete",
                }
                for index in range(25)
            ],
        },
        expected_version=created["version"],
    )

    page = asyncio.run(chat_router.get_chat_messages(world_id, created["id"]))

    assert page["version"] == stored["version"]
    assert len(page["messages"]) == 20
    assert page["messages"][0]["message_id"] == "m-5"
    assert page["cursor"] == 20


def test_regenerate_from_model_message_truncates_and_returns_prompt(monkeypatch):
    world_id = f"world-{uuid.uuid4()}"
    store = _make_store(monkeypatch, world_id)
    created = store.create_chat("Durable")
    saved = store.save_chat(
        created["id"],
        {
            **created,
            "messages": [
                {"message_id": "u-1", "role": "user", "content": "hello", "status": "complete"},
                {"message_id": "m-1", "role": "model", "content": "hi", "status": "complete"},
                {"message_id": "u-2", "role": "user", "content": "again", "status": "complete"},
                {"message_id": "m-2", "role": "model", "content": "reply", "status": "complete"},
            ],
        },
        expected_version=created["version"],
    )

    payload = asyncio.run(
        chat_router.regenerate_from_message(
            world_id,
            created["id"],
            "m-2",
            chat_router.VersionedMutationRequest(base_version=saved["version"]),
        )
    )

    truncated = store.get_chat(created["id"])
    assert payload["resend_message"] == "again"
    assert truncated is not None
    assert [message["message_id"] for message in truncated["messages"]] == ["u-1", "m-1"]
