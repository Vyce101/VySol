"""Chat engine: builds prompt, performs retrieval, and streams response via LiteLLM."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Generator

from .config import SLOT_CHAT, load_prompt, load_settings, sanitize_settings
from .key_manager import assess_transient_provider_error, classify_transient_provider_error, get_key_manager, jittered_delay
from .litellm_adapter import extract_stream_delta_reasoning, extract_stream_delta_text, stream_completion
from .retrieval_engine import RetrievalEngine

logger = logging.getLogger(__name__)


def _build_context_limit_message(*, context_characters: int, limit_characters: int) -> str:
    return (
        "I did not send your prompt to the AI because the retrieved context was "
        f"{context_characters:,} characters, which is over your current Retrieval Settings "
        f"context limit of {limit_characters:,} characters. "
        "Increase `Context Limit (Chars)` or narrow retrieval, then try again."
    )


def _slot_chat_config(settings: dict[str, Any]) -> dict[str, Any]:
    slots = settings.get("slots")
    if isinstance(slots, dict) and isinstance(slots.get(SLOT_CHAT), dict):
        return dict(slots[SLOT_CHAT])
    return {
        "provider": str(settings.get("chat_provider") or "gemini"),
        "model": str(settings.get("default_model_chat") or ""),
        "params": {},
    }


def _build_messages_payload(
    *,
    system_prompt: str,
    history: list[dict[str, Any]] | None,
    message: str,
    chat_history_msgs: int,
) -> list[dict[str, Any]]:
    sliced_history = history[-chat_history_msgs:] if history else []
    full_system = system_prompt
    if sliced_history:
        full_system = f"{full_system}\n\n# Chat History"
    messages_payload = [{"role": "system", "content": full_system}]
    for turn in sliced_history:
        role = "assistant" if turn.get("role") == "model" else turn.get("role", "user")
        messages_payload.append(
            {
                "role": role,
                "content": turn.get("content", ""),
            }
        )
    messages_payload.append({"role": "user", "content": message})
    return messages_payload


def stream_chat(
    world_id: str,
    message: str,
    history: list[dict] | None = None,
    settings_override: dict | None = None,
) -> Generator[str, None, None]:
    """
    Stream a chat response as SSE events.

    Yields: 'data: {"token": "..."}\n\n' per token
    Final:  'data: {"event": "done", "nodes_used": [...]}\\n\\n'
    """
    settings = load_settings()
    if settings_override:
        settings.update(settings_override)
        settings = sanitize_settings(settings)

    try:
        retriever = RetrievalEngine(world_id)

        context_msgs = settings.get("retrieval_context_messages", 3)
        if isinstance(settings_override, dict) and "retrieval_context_messages" in settings_override:
            context_msgs = settings_override["retrieval_context_messages"]

        query_parts = []
        if context_msgs > 1 and history:
            subset = history[-(context_msgs - 1):]
            for turn in subset:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if content:
                    query_parts.append(f"{role}: {content}")
        query_parts.append(f"user: {message}")
        retrieval_query = "\n".join(query_parts)

        retrieval_result = retriever.retrieve(retrieval_query, settings_override=settings_override)
        context_string = retrieval_result["context_string"]
        nodes_used = retrieval_result.get("graph_nodes", [])
        retrieval_meta = retrieval_result.get("retrieval_meta", {})
        context_graph = retrieval_result.get("context_graph")
        context_characters = len(context_string)

        try:
            context_char_limit = max(0, int(settings.get("retrieval_context_char_limit", 0)))
        except (TypeError, ValueError):
            context_char_limit = 0
        if isinstance(settings_override, dict) and "retrieval_context_char_limit" in settings_override:
            try:
                context_char_limit = max(0, int(settings_override["retrieval_context_char_limit"]))
            except (TypeError, ValueError):
                context_char_limit = 0

        if context_char_limit > 0 and context_characters > context_char_limit:
            blocked_message = _build_context_limit_message(
                context_characters=context_characters,
                limit_characters=context_char_limit,
            )
            blocked_context_payload = {
                "blocked_by_context_limit": True,
                "context_characters": context_characters,
                "context_char_limit": context_char_limit,
                "message": blocked_message,
            }
            blocked_context_meta = {
                "blocked_by_context_limit": True,
                "retrieval": {
                    **retrieval_meta,
                    "retrieval_blocked": True,
                    "block_reason": "context_limit_exceeded",
                    "context_characters": context_characters,
                    "context_char_limit": context_char_limit,
                },
                "visualization": {
                    "context_graph": context_graph,
                },
            }
            yield f"data: {json.dumps({'token': blocked_message})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'nodes_used': nodes_used, 'context_payload': blocked_context_payload, 'context_meta': blocked_context_meta, 'thought_text': '', 'gemini_parts': []})}\n\n"
            return

        system_prompt = load_prompt("chat_system_prompt")
        full_system = f"{system_prompt}\n\n{context_string}" if context_string else system_prompt

        chat_history_msgs = settings.get("chat_history_messages", 1000)
        if isinstance(settings_override, dict) and "chat_history_messages" in settings_override:
            chat_history_msgs = settings_override["chat_history_messages"]

        messages_payload = _build_messages_payload(
            system_prompt=full_system,
            history=history,
            message=message,
            chat_history_msgs=chat_history_msgs,
        )

        slot_config = _slot_chat_config(settings)
        chat_provider = str(slot_config.get("provider") or settings.get("chat_provider") or "gemini")
        model_name = str(slot_config.get("model") or settings.get("default_model_chat") or "")
        slot_params = dict(slot_config.get("params") or {})
        captured_at = datetime.now(timezone.utc).isoformat()

        context_payload = {
            "messages": messages_payload,
            "params": slot_params,
        }
        context_meta = {
            "schema_version": "model_context.v2",
            "provider": chat_provider,
            "model": model_name,
            "captured_stage": "pre_provider_call",
            "captured_at": captured_at,
            "slot": SLOT_CHAT,
        }
        if retrieval_meta:
            context_meta["retrieval"] = retrieval_meta
        if context_graph:
            context_meta["visualization"] = {
                "context_graph": context_graph,
            }

        km = get_key_manager(chat_provider)
        backoff = [2, 4, 8]
        tried_indices: set[int] = set()
        request_backoff_attempts = 0
        reused_credential: tuple[dict[str, Any], int] | None = None

        while True:
            credential_index: int | None = None
            credential_entry: dict[str, Any] | None = None
            emitted_token = False
            thought_text = ""
            try:
                if reused_credential is not None:
                    credential_entry, credential_index = reused_credential
                    reused_credential = None
                else:
                    credential_entry, credential_index = km.wait_for_request_credential(tried_indices)

                for chunk in stream_completion(
                    provider=chat_provider,
                    model=model_name,
                    messages=messages_payload,
                    params=slot_params,
                    credential=credential_entry,
                ):
                    reasoning_delta = extract_stream_delta_reasoning(chunk)
                    if reasoning_delta:
                        emitted_token = True
                        thought_text += reasoning_delta
                        yield f"data: {json.dumps({'thought_token': reasoning_delta})}\n\n"

                    text_delta = extract_stream_delta_text(chunk)
                    if text_delta:
                        emitted_token = True
                        yield f"data: {json.dumps({'token': text_delta})}\n\n"

                done_payload = {
                    "event": "done",
                    "nodes_used": nodes_used,
                    "context_payload": context_payload,
                    "context_meta": context_meta,
                    "thought_text": thought_text,
                    "gemini_parts": [],
                }
                yield f"data: {json.dumps(done_payload)}\n\n"
                return
            except Exception as exc:
                if emitted_token:
                    raise

                assessment = assess_transient_provider_error(exc, provider=chat_provider)
                if assessment and credential_index is not None:
                    if assessment.action == "request_backoff" and credential_entry is not None:
                        request_backoff_attempts += 1
                        if request_backoff_attempts <= len(backoff):
                            delay = assessment.retry_after_seconds
                            if delay is None:
                                delay = backoff[min(request_backoff_attempts - 1, len(backoff) - 1)]
                            logger.warning(
                                "LiteLLM chat request throttled for world %s; retrying credential %s without cooldown (%s).",
                                world_id,
                                credential_index,
                                assessment.provider_message or exc,
                            )
                            time.sleep(jittered_delay(delay))
                            reused_credential = (credential_entry, credential_index)
                            continue
                        raise

                    if assessment.action == "cooldown_key":
                        request_backoff_attempts = 0
                        km.report_error(credential_index, assessment.kind)
                        tried_indices.add(credential_index)
                        delay = assessment.retry_after_seconds
                        if delay is None:
                            delay = backoff[min(len(tried_indices) - 1, len(backoff) - 1)]
                        time.sleep(jittered_delay(delay))
                        continue

                transient_kind = assessment.kind if assessment is not None else classify_transient_provider_error(exc)
                if transient_kind and credential_index is not None:
                    km.report_error(credential_index, transient_kind)
                    tried_indices.add(credential_index)
                    time.sleep(jittered_delay(0.5))
                    continue
                raise

    except Exception as exc:
        logger.exception("Chat stream error for world %s", world_id)
        yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"
