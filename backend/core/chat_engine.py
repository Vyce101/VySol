"""Chat engine: builds prompt, performs retrieval, streams response via Gemini or IntenseRP Next."""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Generator

from google import genai
from google.genai import types

from .config import (
    SLOT_CHAT,
    load_prompt,
    load_settings,
    resolve_gemini_thinking_settings,
    resolve_groq_reasoning_effort,
    resolve_slot_provider,
)
from .intenserp_provider import stream_intenserp_chat
from .key_manager import classify_transient_provider_error, get_key_manager, jittered_delay
from .openai_compatible_provider import create_openai_compatible_chat_completion, stream_openai_compatible_chat
from .retrieval_engine import RetrievalEngine

logger = logging.getLogger(__name__)


def _serialize_gemini_payload_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {
            "__kind__": "bytes",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, (list, tuple)):
        return [_serialize_gemini_payload_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _serialize_gemini_payload_value(item)
            for key, item in value.items()
            if item is not None
        }
    if hasattr(value, "model_dump"):
        try:
            return _serialize_gemini_payload_value(value.model_dump(exclude_none=True))
        except Exception:
            return None
    return value


def _deserialize_gemini_payload_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_deserialize_gemini_payload_value(item) for item in value]
    if isinstance(value, dict):
        if value.get("__kind__") == "bytes" and isinstance(value.get("base64"), str):
            try:
                return base64.b64decode(value["base64"])
            except Exception:
                return None
        return {
            str(key): _deserialize_gemini_payload_value(item)
            for key, item in value.items()
        }
    return value


def _serialize_gemini_part(part: Any) -> dict[str, Any] | None:
    serialized = _serialize_gemini_payload_value(part)
    if isinstance(serialized, dict) and serialized:
        return serialized

    text = getattr(part, "text", None)
    thought = getattr(part, "thought", None)
    thought_signature = getattr(part, "thought_signature", None)

    payload: dict[str, Any] = {}
    if isinstance(text, str) and text:
        payload["text"] = text
    if isinstance(thought, bool):
        payload["thought"] = thought
    if isinstance(thought_signature, (bytes, bytearray)) and thought_signature:
        payload["thought_signature"] = {
            "__kind__": "bytes",
            "base64": base64.b64encode(bytes(thought_signature)).decode("ascii"),
        }
    return payload or None


def _extract_gemini_chunk_parts(chunk: Any) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for candidate in list(getattr(chunk, "candidates", None) or []):
        content = getattr(candidate, "content", None)
        for part in list(getattr(content, "parts", None) or []):
            serialized_part = _serialize_gemini_part(part)
            if serialized_part:
                serialized.append(serialized_part)
    return serialized


def _build_gemini_sdk_parts(text: str, parts_payload: list[dict[str, Any]] | None = None) -> list[types.Part]:
    built_parts: list[types.Part] = []
    for raw_part in list(parts_payload or []):
        if not isinstance(raw_part, dict):
            continue

        try:
            restored_part = _deserialize_gemini_payload_value(raw_part)
            if isinstance(restored_part, dict):
                built_parts.append(types.Part.model_validate(restored_part))
                continue
        except Exception:
            pass

        part_kwargs: dict[str, Any] = {}
        raw_text = raw_part.get("text")
        if isinstance(raw_text, str) and raw_text:
            part_kwargs["text"] = raw_text

        raw_thought = raw_part.get("thought")
        if isinstance(raw_thought, bool):
            part_kwargs["thought"] = raw_thought

        raw_signature = raw_part.get("thought_signature")
        if isinstance(raw_signature, str) and raw_signature:
            try:
                part_kwargs["thought_signature"] = base64.b64decode(raw_signature)
            except Exception:
                pass

        if part_kwargs:
            built_parts.append(types.Part(**part_kwargs))

    if built_parts:
        return built_parts
    return [types.Part.from_text(text=text)]


def _build_gemini_sdk_content(role: str, text: str, parts_payload: list[dict[str, Any]] | None = None) -> types.Content:
    parts = _build_gemini_sdk_parts(text, parts_payload)
    if role == "assistant":
        return types.ModelContent(parts=parts)
    return types.UserContent(parts=parts)


def _build_gemini_debug_content(role: str, text: str, parts_payload: list[dict[str, Any]] | None = None) -> dict:
    gemini_role = "model" if role == "assistant" else "user"
    if parts_payload:
        return {"role": gemini_role, "parts": parts_payload}
    return {"role": gemini_role, "parts": [text]}


def _iter_text_tokens(text: str, *, chunk_size: int = 18) -> Generator[str, None, None]:
    if not text:
        return
    if len(text) <= chunk_size:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            next_space = text.rfind(" ", start, end)
            if next_space > start:
                end = next_space + 1
        yield text[start:end]
        start = end


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

    try:
        retriever = RetrievalEngine(world_id)

        # Determine retrieval query context length.
        context_msgs = settings.get("retrieval_context_messages", 3)
        if isinstance(settings_override, dict) and "retrieval_context_messages" in settings_override:
            context_msgs = settings_override["retrieval_context_messages"]

        query_parts = []
        if context_msgs > 1 and history:
            subset = history[-(context_msgs - 1):]
            for m in subset:
                role = m.get("role", "user")
                content = m.get("content", "")
                if content:
                    query_parts.append(f"{role}: {content}")
        query_parts.append(f"user: {message}")
        retrieval_query = "\n".join(query_parts)

        retrieval_result = retriever.retrieve(retrieval_query, settings_override=settings_override)
        context_string = retrieval_result["context_string"]
        nodes_used = retrieval_result.get("graph_nodes", [])
        retrieval_meta = retrieval_result.get("retrieval_meta", {})
        context_graph = retrieval_result.get("context_graph")

        system_prompt = load_prompt("chat_system_prompt")
        full_system = f"{system_prompt}\n\n{context_string}" if context_string else system_prompt

        chat_provider = resolve_slot_provider(settings, SLOT_CHAT)

        chat_history_msgs = settings.get("chat_history_messages", 1000)
        if isinstance(settings_override, dict) and "chat_history_messages" in settings_override:
            chat_history_msgs = settings_override["chat_history_messages"]
        sliced_history = history[-chat_history_msgs:] if history else []

        # Build canonical turn ordering: system context, prior turns, current user turn.
        if sliced_history:
            full_system = f"{full_system}\n\n# Chat History"
        gemini_messages_payload = [{"role": "system", "content": full_system}]
        intenserp_messages_payload = [{"role": "system", "content": full_system}]
        if sliced_history:
            for turn in sliced_history:
                role = "assistant" if turn.get("role") == "model" else turn.get("role", "user")
                history_message = {
                    "role": role,
                    "content": turn.get("content", ""),
                }
                if isinstance(turn.get("gemini_parts"), list):
                    history_message["gemini_parts"] = turn.get("gemini_parts")
                gemini_messages_payload.append(history_message)
                intenserp_messages_payload.append({
                    "role": role,
                    "content": turn.get("content", ""),
                })
        gemini_messages_payload.append({"role": "user", "content": message})
        intenserp_messages_payload.append({"role": "user", "content": message})

        model_name = settings.get("default_model_chat", "gemini-3-flash-preview")
        intenserp_model_id = settings.get("intenserp_model_id", "glm-chat")
        captured_at = datetime.now(timezone.utc).isoformat()

        gemini_sdk_contents = []
        gemini_debug_contents = []
        for msg in gemini_messages_payload:
            if msg["role"] == "system":
                continue
            parts_payload = msg.get("gemini_parts") if isinstance(msg.get("gemini_parts"), list) else None
            gemini_sdk_contents.append(_build_gemini_sdk_content(msg["role"], msg["content"], parts_payload))
            gemini_debug_contents.append(_build_gemini_debug_content(msg["role"], msg["content"], parts_payload))

        # context_payload stays model-context only. Metadata goes to context_meta.
        gemini_context_payload = {
            "system_instruction": full_system,
            "contents": gemini_debug_contents,
        }
        gemini_context_meta = {
            "schema_version": "model_context.v1",
            "provider": "gemini",
            "model": model_name,
            "captured_stage": "pre_provider_call",
            "captured_at": captured_at,
        }
        if retrieval_meta:
            gemini_context_meta["retrieval"] = retrieval_meta
        if context_graph:
            gemini_context_meta["visualization"] = {
                "context_graph": context_graph,
            }
        intenserp_context_payload = {
            "messages": intenserp_messages_payload,
        }
        intenserp_context_meta = {
            "schema_version": "model_context.v1",
            "provider": "intenserp",
            "model": intenserp_model_id,
            "captured_stage": "pre_provider_call",
            "captured_at": captured_at,
        }
        if retrieval_meta:
            intenserp_context_meta["retrieval"] = retrieval_meta
        if context_graph:
            intenserp_context_meta["visualization"] = {
                "context_graph": context_graph,
            }

        if chat_provider == "intenserp":
            for chunk in stream_intenserp_chat(
                messages_payload=intenserp_messages_payload,
                nodes_used=nodes_used,
                settings=settings,
            ):
                if chunk.startswith("data: "):
                    d_str = chunk[6:].strip()
                    if d_str.startswith("{"):
                        try:
                            d = json.loads(d_str)
                            if d.get("event") == "done":
                                d["context_payload"] = intenserp_context_payload
                                d["context_meta"] = intenserp_context_meta
                                yield f"data: {json.dumps(d)}\n\n"
                                continue
                        except Exception:
                            pass
                yield chunk
            return

        if chat_provider != "gemini":
            reasoning_effort = resolve_groq_reasoning_effort(
                settings,
                slot_key="default_model_chat",
                model_name=model_name,
            )
            include_reasoning = bool(settings.get("groq_chat_include_reasoning"))
            openai_context_payload = {
                "messages": intenserp_messages_payload,
            }
            openai_context_meta = {
                "schema_version": "model_context.v1",
                "provider": chat_provider,
                "model": model_name,
                "captured_stage": "pre_provider_call",
                "captured_at": captured_at,
            }
            if reasoning_effort:
                openai_context_meta["reasoning_effort"] = reasoning_effort
            if include_reasoning:
                openai_context_meta["include_reasoning"] = True
            if retrieval_meta:
                openai_context_meta["retrieval"] = retrieval_meta
            if context_graph:
                openai_context_meta["visualization"] = {
                    "context_graph": context_graph,
                }

            groq_payload: dict[str, Any] = {
                "model": model_name,
                "messages": intenserp_messages_payload,
                "temperature": 1.0,
                "max_completion_tokens": 4096,
            }
            if reasoning_effort:
                groq_payload["reasoning_effort"] = reasoning_effort
            if include_reasoning:
                groq_payload["include_reasoning"] = True

            if include_reasoning:
                response = create_openai_compatible_chat_completion(chat_provider, groq_payload)
                choice = ((response.get("choices") or [{}])[0]) if isinstance(response, dict) else {}
                message_payload = choice.get("message") or {}
                content = str(message_payload.get("content") or "")
                reasoning_text = str(
                    message_payload.get("reasoning")
                    or message_payload.get("reasoning_content")
                    or choice.get("reasoning")
                    or ""
                )
                for token in _iter_text_tokens(content):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                done_payload = {
                    "event": "done",
                    "nodes_used": nodes_used,
                    "context_payload": openai_context_payload,
                    "context_meta": openai_context_meta,
                    "thought_text": reasoning_text,
                }
                yield f"data: {json.dumps(done_payload)}\n\n"
                return

            content_parts: list[str] = []
            reasoning_text = ""
            for event in stream_openai_compatible_chat(chat_provider, groq_payload):
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                reasoning_delta = delta.get("reasoning") or delta.get("reasoning_content")
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_text += reasoning_delta
                content = delta.get("content")
                if isinstance(content, str) and content:
                    content_parts.append(content)
                    yield f"data: {json.dumps({'token': content})}\n\n"

            done_payload = {
                "event": "done",
                "nodes_used": nodes_used,
                "context_payload": openai_context_payload,
                "context_meta": openai_context_meta,
                "thought_text": reasoning_text,
            }
            yield f"data: {json.dumps(done_payload)}\n\n"
            return

        disable_safety = settings.get("disable_safety_filters", False)
        safety_settings = None
        if disable_safety:
            safety_settings = [
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            ]

        config_kwargs: dict[str, Any] = {
            "system_instruction": full_system,
            "temperature": 1.0,
            "safety_settings": safety_settings,
        }
        thinking_config = resolve_gemini_thinking_settings(
            settings,
            slot_key="default_model_chat",
            model_name=model_name,
            include_thoughts=bool(settings.get("gemini_chat_send_thinking")),
        )
        if thinking_config:
            config_kwargs["thinking_config"] = types.ThinkingConfig(**thinking_config)
        config = types.GenerateContentConfig(**config_kwargs)

        km = get_key_manager()
        backoff = [2, 4, 8]
        max_retries = 3

        for attempt in range(max_retries):
            key_idx: int | None = None
            emitted_token = False
            try:
                api_key, key_idx = km.wait_for_available_key()
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content_stream(
                    model=model_name,
                    contents=gemini_sdk_contents,
                    config=config,
                )

                gemini_parts: list[dict[str, Any]] = []
                thought_text = ""
                for chunk in response:
                    serialized_parts = _extract_gemini_chunk_parts(chunk)
                    if serialized_parts:
                        for part_payload in serialized_parts:
                            gemini_parts.append(part_payload)
                            text = part_payload.get("text")
                            if not isinstance(text, str) or not text:
                                continue
                            emitted_token = True
                            if part_payload.get("thought") is True:
                                thought_text += text
                                yield f"data: {json.dumps({'thought_token': text})}\n\n"
                            else:
                                yield f"data: {json.dumps({'token': text})}\n\n"
                        continue

                    if chunk.text:
                        emitted_token = True
                        gemini_parts.append({"text": chunk.text, "thought": False})
                        yield f"data: {json.dumps({'token': chunk.text})}\n\n"

                done_payload = {
                    "event": "done",
                    "nodes_used": nodes_used,
                    "context_payload": gemini_context_payload,
                    "context_meta": gemini_context_meta,
                    "thought_text": thought_text,
                    "gemini_parts": gemini_parts,
                }
                yield f"data: {json.dumps(done_payload)}\n\n"
                return
            except Exception as e:
                if emitted_token:
                    raise
                transient_kind = classify_transient_provider_error(e)
                if transient_kind and key_idx is not None:
                    km.report_error(key_idx, transient_kind)
                    if attempt < max_retries - 1:
                        time.sleep(jittered_delay(backoff[attempt]))
                        continue
                raise

    except Exception as e:
        logger.exception("Chat stream error for world %s", world_id)
        yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
