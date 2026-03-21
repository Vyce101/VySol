"""Chat engine: builds prompt, performs retrieval, streams response via Gemini or IntenseRP Next."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Generator

from google import genai
from google.genai import types

from .config import load_prompt, load_settings
from .intenserp_provider import stream_intenserp_chat
from .key_manager import get_key_manager
from .retrieval_engine import RetrievalEngine

logger = logging.getLogger(__name__)


def _build_gemini_sdk_content(role: str, text: str) -> types.Content:
    part = types.Part.from_text(text=text)
    if role == "assistant":
        return types.ModelContent(parts=[part])
    return types.UserContent(parts=[part])


def _build_gemini_debug_content(role: str, text: str) -> dict:
    gemini_role = "model" if role == "assistant" else "user"
    return {"role": gemini_role, "parts": [text]}


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

        chat_provider = settings.get("chat_provider", "gemini")

        chat_history_msgs = settings.get("chat_history_messages", 1000)
        if isinstance(settings_override, dict) and "chat_history_messages" in settings_override:
            chat_history_msgs = settings_override["chat_history_messages"]
        sliced_history = history[-chat_history_msgs:] if history else []

        # Build canonical turn ordering: system context, prior turns, current user turn.
        if sliced_history:
            full_system = f"{full_system}\n\n# Chat History"
        messages_payload = [{"role": "system", "content": full_system}]
        if sliced_history:
            for turn in sliced_history:
                role = "assistant" if turn.get("role") == "model" else turn.get("role", "user")
                messages_payload.append({"role": role, "content": turn.get("content", "")})
        messages_payload.append({"role": "user", "content": message})

        model_name = settings.get("default_model_chat", "gemini-flash-latest")
        intenserp_model_id = settings.get("intenserp_model_id", "glm-chat")
        captured_at = datetime.now(timezone.utc).isoformat()

        gemini_sdk_contents = []
        gemini_debug_contents = []
        for msg in messages_payload:
            if msg["role"] == "system":
                continue
            gemini_sdk_contents.append(_build_gemini_sdk_content(msg["role"], msg["content"]))
            gemini_debug_contents.append(_build_gemini_debug_content(msg["role"], msg["content"]))

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
            "messages": messages_payload,
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
                messages_payload=messages_payload,
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

        km = get_key_manager()
        api_key, _ = km.get_active_key()
        client = genai.Client(api_key=api_key)

        disable_safety = settings.get("disable_safety_filters", False)
        safety_settings = None
        if disable_safety:
            safety_settings = [
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            ]

        config = types.GenerateContentConfig(
            system_instruction=full_system,
            temperature=1.0,
            safety_settings=safety_settings,
        )

        response = client.models.generate_content_stream(
            model=model_name,
            contents=gemini_sdk_contents,
            config=config,
        )

        for chunk in response:
            if chunk.text:
                yield f"data: {json.dumps({'token': chunk.text})}\n\n"

        done_payload = {
            "event": "done",
            "nodes_used": nodes_used,
            "context_payload": gemini_context_payload,
            "context_meta": gemini_context_meta,
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    except Exception as e:
        logger.exception("Chat stream error for world %s", world_id)
        yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
