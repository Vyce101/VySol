"""Chat endpoints: SSE streaming, paged history, and targeted mutations."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.chat_engine import stream_chat
from core.chat_store import CHAT_PAGE_SIZE, ChatStore, ChatVersionConflictError
from core.config import world_meta_path

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    settings_override: dict | None = None


class CreateChatRequest(BaseModel):
    title: str = "New Chat"


class RenameChatRequest(BaseModel):
    title: str
    base_version: int


class UpdateChatHistoryRequest(BaseModel):
    messages: list[dict]
    base_version: int


class UpdateMessageRequest(BaseModel):
    content: str
    base_version: int


class VersionedMutationRequest(BaseModel):
    base_version: int


def _build_generation_history(messages: list[dict]) -> list[dict]:
    history: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = message.get("content", "")
        status = message.get("status") or "complete"
        if role not in {"user", "model"}:
            continue
        if role == "model" and status != "complete":
            continue

        history_entry = {
            "role": role,
            "content": content,
        }
        gemini_parts = message.get("gemini_parts")
        if isinstance(gemini_parts, list):
            history_entry["gemini_parts"] = gemini_parts
        history.append(history_entry)
    return history


def _serialize_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _page_payload(store: ChatStore, chat_id: str) -> dict:
    page = store.get_chat_page(chat_id, page_size=CHAT_PAGE_SIZE)
    if not page:
        raise HTTPException(status_code=404, detail="Chat not found")
    return page


def _find_message_index(messages: list[dict], message_id: str) -> int:
    for index, message in enumerate(messages):
        if str(message.get("message_id") or "") == message_id:
            return index
    return -1


def _update_message_state(
    store: ChatStore,
    chat_id: str,
    fallback_chat: dict,
    message_id: str,
    *,
    status: str,
    content: str,
    thought_text: str = "",
    gemini_parts: list | None = None,
    nodes_used: list | None = None,
    context_payload: dict | None = None,
    context_meta: dict | None = None,
) -> dict:
    latest_chat = store.get_chat(chat_id) or fallback_chat
    latest_messages = list(latest_chat.get("messages", []))

    for idx, message in enumerate(latest_messages):
        if message.get("message_id") != message_id:
            continue

        updated = dict(message)
        updated["status"] = status
        updated["content"] = content
        updated["thought_text"] = thought_text
        if gemini_parts is not None:
            updated["gemini_parts"] = gemini_parts
        if nodes_used is not None:
            updated["nodes_used"] = nodes_used
        if context_payload is not None:
            updated["context_payload"] = context_payload
        if context_meta is not None:
            updated["context_meta"] = context_meta
        latest_messages[idx] = updated
        break
    else:
        latest_messages.append({
            "message_id": message_id,
            "role": "model",
            "status": status,
            "content": content,
            "thought_text": thought_text,
            "gemini_parts": gemini_parts or [],
            "nodes_used": nodes_used or [],
            "context_payload": context_payload or {},
            "context_meta": context_meta or {},
        })

    latest_chat["messages"] = latest_messages
    return store.save_chat(chat_id, latest_chat, expected_version=latest_chat.get("version", 0))


@router.get("/{world_id}/chats")
async def list_chats(world_id: str):
    try:
        store = ChatStore(world_id)
        return store.list_chats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{world_id}/chats/summaries")
async def list_chat_summaries(world_id: str):
    try:
        store = ChatStore(world_id)
        return store.list_chats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{world_id}/chats")
async def create_chat(world_id: str, req: CreateChatRequest | None = None):
    try:
        title = req.title if req else "New Chat"
        store = ChatStore(world_id)
        return store.create_chat(title=title)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{world_id}/chats/{chat_id}")
async def get_chat(world_id: str, chat_id: str):
    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.get("/{world_id}/chats/{chat_id}/messages")
async def get_chat_messages(world_id: str, chat_id: str, cursor: int | None = None, limit: int = CHAT_PAGE_SIZE):
    store = ChatStore(world_id)
    page = store.get_chat_page(chat_id, cursor=cursor, page_size=limit)
    if not page:
        raise HTTPException(status_code=404, detail="Chat not found")
    return page


@router.patch("/{world_id}/chats/{chat_id}")
async def rename_chat(world_id: str, chat_id: str, req: RenameChatRequest):
    store = ChatStore(world_id)
    try:
        renamed = store.rename_chat(chat_id, req.title, expected_version=req.base_version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reload the chat list and try again.")
    if not renamed:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {
        "id": renamed["id"],
        "title": renamed["title"],
        "created_at": renamed["created_at"],
        "updated_at": renamed["updated_at"],
        "version": renamed["version"],
        "has_manual_title": renamed.get("has_manual_title", True),
    }


@router.delete("/{world_id}/chats/{chat_id}")
async def delete_chat(world_id: str, chat_id: str):
    store = ChatStore(world_id)
    if not store.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"success": True}


@router.put("/{world_id}/chats/{chat_id}/history")
async def update_chat_history(world_id: str, chat_id: str, req: UpdateChatHistoryRequest):
    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat["messages"] = req.messages
    try:
        saved = store.save_chat(chat_id, chat, expected_version=req.base_version)
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reloaded the latest saved messages.")
    return {
        "success": True,
        "version": saved["version"],
        "messages": saved["messages"],
    }


@router.patch("/{world_id}/chats/{chat_id}/messages/{message_id}")
async def update_chat_message(world_id: str, chat_id: str, message_id: str, req: UpdateMessageRequest):
    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = list(chat.get("messages", []))
    index = _find_message_index(messages, message_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="Message not found")

    updated = dict(messages[index])
    updated["content"] = req.content
    if updated.get("role") == "model":
        updated["thought_text"] = ""
        updated["gemini_parts"] = []
        updated["nodes_used"] = []
        updated["context_payload"] = {}
        updated["context_meta"] = {}
    messages[index] = updated
    chat["messages"] = messages

    try:
        store.save_chat(chat_id, chat, expected_version=req.base_version)
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reloaded the latest saved messages.")
    return _page_payload(store, chat_id)


@router.post("/{world_id}/chats/{chat_id}/messages/{message_id}/delete")
async def delete_chat_message(world_id: str, chat_id: str, message_id: str, req: VersionedMutationRequest):
    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = list(chat.get("messages", []))
    index = _find_message_index(messages, message_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="Message not found")

    messages.pop(index)
    chat["messages"] = messages
    try:
        store.save_chat(chat_id, chat, expected_version=req.base_version)
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reloaded the latest saved messages.")
    return _page_payload(store, chat_id)


@router.post("/{world_id}/chats/{chat_id}/messages/{message_id}/truncate")
async def truncate_chat_from_message(world_id: str, chat_id: str, message_id: str, req: VersionedMutationRequest):
    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = list(chat.get("messages", []))
    index = _find_message_index(messages, message_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="Message not found")

    chat["messages"] = messages[:index]
    try:
        store.save_chat(chat_id, chat, expected_version=req.base_version)
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reloaded the latest saved messages.")
    return _page_payload(store, chat_id)


@router.post("/{world_id}/chats/{chat_id}/messages/{message_id}/regenerate")
async def regenerate_from_message(world_id: str, chat_id: str, message_id: str, req: VersionedMutationRequest):
    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = list(chat.get("messages", []))
    index = _find_message_index(messages, message_id)
    if index < 0:
        raise HTTPException(status_code=404, detail="Message not found")

    target = messages[index]
    prompt_to_resend = str(target.get("content") or "")
    truncate_index = index

    if target.get("role") == "model":
        previous_user_index = -1
        for candidate in range(index - 1, -1, -1):
            if messages[candidate].get("role") == "user":
                previous_user_index = candidate
                break
        if previous_user_index < 0:
            raise HTTPException(status_code=400, detail="Could not find the user message to regenerate from.")
        prompt_to_resend = str(messages[previous_user_index].get("content") or "")
        truncate_index = previous_user_index

    chat["messages"] = messages[:truncate_index]
    try:
        store.save_chat(chat_id, chat, expected_version=req.base_version)
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reloaded the latest saved messages.")

    page = _page_payload(store, chat_id)
    page["resend_message"] = prompt_to_resend
    return page


@router.post("/{world_id}/chats/{chat_id}/message")
async def stream_chat_message(world_id: str, chat_id: str, req: ChatRequest):
    path = world_meta_path(world_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="World not found")

    store = ChatStore(world_id)
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    history = _build_generation_history(chat.get("messages", []))
    user_turn = {
        "message_id": str(uuid.uuid4()),
        "role": "user",
        "content": req.message,
        "status": "complete",
    }
    model_turn = {
        "message_id": str(uuid.uuid4()),
        "role": "model",
        "content": "",
        "thought_text": "",
        "gemini_parts": [],
        "status": "streaming",
        "nodes_used": [],
        "context_payload": {},
        "context_meta": {},
    }
    seeded_chat = {
        **chat,
        "messages": [
            *chat.get("messages", []),
            user_turn,
            model_turn,
        ],
    }
    try:
        persisted_chat = store.save_chat(chat_id, seeded_chat, expected_version=chat.get("version", 0))
    except ChatVersionConflictError:
        raise HTTPException(status_code=409, detail="This chat changed in another tab. Reload the chat and try again.")

    def event_stream():
        full_text = ""
        thought_text = ""
        gemini_parts = []
        nodes_used = []
        context_payload = {}
        context_meta = {}
        completed = False
        disconnected = False
        error_message: str | None = None

        try:
            for chunk in stream_chat(
                world_id=world_id,
                message=req.message,
                history=history,
                settings_override=req.settings_override,
            ):
                if not chunk.startswith("data: "):
                    yield chunk
                    continue

                data_str = chunk[6:].strip()
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                if data.get("event") == "error":
                    error_message = (
                        data.get("message")
                        if isinstance(data.get("message"), str)
                        else "The server failed while processing the chat request."
                    )
                    break

                if "token" in data:
                    full_text += data["token"]
                    yield chunk
                    continue

                if "thought_token" in data:
                    thought_token = data["thought_token"]
                    if isinstance(thought_token, str):
                        thought_text += thought_token
                    yield chunk
                    continue

                if data.get("event") == "done":
                    nodes_used = data.get("nodes_used", [])
                    context_payload = data.get("context_payload", {})
                    context_meta = data.get("context_meta", {})
                    if isinstance(data.get("thought_text"), str) and not thought_text:
                        thought_text = data["thought_text"]
                    if isinstance(data.get("gemini_parts"), list):
                        gemini_parts = data["gemini_parts"]
                    completed = True
                    break

                yield chunk
        except GeneratorExit:
            disconnected = True
            raise
        except Exception as exc:
            error_message = str(exc) or "The chat stream ended unexpectedly."
        finally:
            if completed:
                saved = _update_message_state(
                    store,
                    chat_id,
                    persisted_chat,
                    model_turn["message_id"],
                    status="complete",
                    content=full_text,
                    thought_text=thought_text,
                    gemini_parts=gemini_parts,
                    nodes_used=nodes_used,
                    context_payload=context_payload,
                    context_meta=context_meta,
                )
                if not disconnected:
                    yield _serialize_sse({
                        "event": "done",
                        "persisted": True,
                        "message_id": model_turn["message_id"],
                        "chat_version": saved["version"],
                        "nodes_used": nodes_used,
                        "context_payload": context_payload,
                        "context_meta": context_meta,
                        "thought_text": thought_text,
                        "gemini_parts": gemini_parts,
                    })
            else:
                saved = _update_message_state(
                    store,
                    chat_id,
                    persisted_chat,
                    model_turn["message_id"],
                    status="incomplete",
                    content=full_text,
                    thought_text=thought_text,
                    gemini_parts=gemini_parts,
                    nodes_used=nodes_used,
                    context_payload=context_payload,
                    context_meta=context_meta,
                )

                if not disconnected:
                    yield _serialize_sse({
                        "event": "error",
                        "message": error_message or "The reply was interrupted before it finished saving.",
                        "message_id": model_turn["message_id"],
                        "chat_version": saved["version"],
                        "status": "incomplete",
                    })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{world_id}/chat")
async def chat_legacy(world_id: str, req: ChatRequest):
    path = world_meta_path(world_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="World not found")

    def event_stream():
        yield from stream_chat(
            world_id=world_id,
            message=req.message,
            history=[],
            settings_override=req.settings_override,
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
