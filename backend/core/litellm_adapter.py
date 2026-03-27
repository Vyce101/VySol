"""Thin LiteLLM request helpers without router or fallback usage."""

from __future__ import annotations

from typing import Any, Iterable

import litellm

from .ai_catalog import ensure_litellm_version


def _normalize_response_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            return {}
    if hasattr(value, "dict"):
        try:
            return value.dict()
        except Exception:
            return {}
    return {}


def _coerce_message_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                    continue
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "".join(parts)
    return str(value or "")


def _extract_thinking_blocks(payload: Any) -> str:
    if not isinstance(payload, list):
        return ""
    collected: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "thinking" and isinstance(item.get("thinking"), str):
            collected.append(item["thinking"])
    return "".join(collected)


def build_litellm_credentials(provider: str, credential: dict[str, Any] | None) -> dict[str, Any]:
    entry = dict(credential or {})
    kwargs: dict[str, Any] = {}
    api_key = str(entry.get("api_key") or "").strip()
    api_base = str(entry.get("api_base") or entry.get("base_url") or "").strip()
    api_version = str(entry.get("api_version") or "").strip()
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base.rstrip("/")
    if api_version:
        kwargs["api_version"] = api_version

    if provider == "vertex_ai":
        project = str(entry.get("vertex_project") or "").strip()
        location = str(entry.get("vertex_location") or "").strip()
        credentials = str(entry.get("vertex_credentials") or "").strip()
        if project:
            kwargs["vertex_ai_project"] = project
            kwargs["vertex_project"] = project
        if location:
            kwargs["vertex_ai_location"] = location
            kwargs["vertex_location"] = location
        if credentials:
            kwargs["vertex_ai_credentials"] = credentials
            kwargs["vertex_credentials"] = credentials
    return kwargs


def build_completion_kwargs(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
    stream: bool = False,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_litellm_version()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    kwargs.update(build_litellm_credentials(provider, credential))
    for key, value in dict(params or {}).items():
        if value is None:
            continue
        kwargs[key] = value
    if response_format is not None:
        kwargs["response_format"] = response_format
    if provider == "chatgpt":
        kwargs["custom_llm_provider"] = "chatgpt"
    elif provider == "openai_compatible":
        kwargs["custom_llm_provider"] = "openai"
    else:
        kwargs["custom_llm_provider"] = provider
    return kwargs


def completion(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _normalize_response_payload(
        litellm.completion(
            **build_completion_kwargs(
                provider=provider,
                model=model,
                messages=messages,
                params=params,
                credential=credential,
                stream=False,
                response_format=response_format,
            )
        )
    )


async def acompletion(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await litellm.acompletion(
        **build_completion_kwargs(
            provider=provider,
            model=model,
            messages=messages,
            params=params,
            credential=credential,
            stream=False,
            response_format=response_format,
        )
    )
    return _normalize_response_payload(response)


def stream_completion(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
    response_format: dict[str, Any] | None = None,
) -> Iterable[dict[str, Any]]:
    stream = litellm.completion(
        **build_completion_kwargs(
            provider=provider,
            model=model,
            messages=messages,
            params=params,
            credential=credential,
            stream=True,
            response_format=response_format,
        )
    )
    for chunk in stream:
        yield _normalize_response_payload(chunk)


def extract_stream_delta_text(chunk: dict[str, Any]) -> str:
    choice = ((chunk.get("choices") or [{}])[0]) if isinstance(chunk, dict) else {}
    delta = choice.get("delta") or {}
    return _coerce_message_text(delta.get("content"))


def extract_stream_delta_reasoning(chunk: dict[str, Any]) -> str:
    choice = ((chunk.get("choices") or [{}])[0]) if isinstance(chunk, dict) else {}
    delta = choice.get("delta") or {}
    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    return _extract_thinking_blocks(delta.get("thinking_blocks"))


def extract_response_text(response: dict[str, Any]) -> str:
    choice = ((response.get("choices") or [{}])[0]) if isinstance(response, dict) else {}
    message = choice.get("message") or {}
    return _coerce_message_text(message.get("content"))


def extract_response_reasoning(response: dict[str, Any]) -> str:
    choice = ((response.get("choices") or [{}])[0]) if isinstance(response, dict) else {}
    message = choice.get("message") or {}
    reasoning = message.get("reasoning_content") or message.get("reasoning") or choice.get("reasoning")
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    return _extract_thinking_blocks(message.get("thinking_blocks"))


def extract_usage(response: dict[str, Any]) -> dict[str, int]:
    usage_payload = response.get("usage") or {}
    return {
        "input_tokens": int(
            usage_payload.get("prompt_tokens")
            or usage_payload.get("input_tokens")
            or usage_payload.get("prompt_token_count")
            or 0
        ),
        "output_tokens": int(
            usage_payload.get("completion_tokens")
            or usage_payload.get("output_tokens")
            or usage_payload.get("candidates_token_count")
            or 0
        ),
    }


def build_embedding_kwargs(
    *,
    provider: str,
    model: str,
    input_value: str | list[str],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_litellm_version()
    kwargs: dict[str, Any] = {
        "model": model,
        "input": input_value,
    }
    kwargs.update(build_litellm_credentials(provider, credential))
    for key, value in dict(params or {}).items():
        if value is None:
            continue
        kwargs[key] = value
    if provider == "chatgpt":
        kwargs["custom_llm_provider"] = "chatgpt"
    elif provider == "openai_compatible":
        kwargs["custom_llm_provider"] = "openai"
    else:
        kwargs["custom_llm_provider"] = provider
    return kwargs


def embedding(
    *,
    provider: str,
    model: str,
    input_value: str | list[str],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
) -> list[list[float]]:
    response = _normalize_response_payload(
        litellm.embedding(
            **build_embedding_kwargs(
                provider=provider,
                model=model,
                input_value=input_value,
                params=params,
                credential=credential,
            )
        )
    )
    output: list[list[float]] = []
    for item in response.get("data") or []:
        if isinstance(item, dict) and isinstance(item.get("embedding"), list):
            output.append([float(value) for value in item["embedding"]])
    return output


async def aembedding(
    *,
    provider: str,
    model: str,
    input_value: str | list[str],
    params: dict[str, Any] | None = None,
    credential: dict[str, Any] | None = None,
) -> list[list[float]]:
    response = _normalize_response_payload(
        await litellm.aembedding(
            **build_embedding_kwargs(
                provider=provider,
                model=model,
                input_value=input_value,
                params=params,
                credential=credential,
            )
        )
    )
    output: list[list[float]] = []
    for item in response.get("data") or []:
        if isinstance(item, dict) and isinstance(item.get("embedding"), list):
            output.append([float(value) for value in item["embedding"]])
    return output
