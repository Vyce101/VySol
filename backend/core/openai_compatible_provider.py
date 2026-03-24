"""Shared OpenAI-compatible provider helpers."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Generator

import httpx

from .config import PROVIDER_REGISTRY, get_provider_pool
from .key_manager import classify_transient_provider_error, get_key_manager, jittered_delay


def _get_provider_key_manager(provider: str):
    try:
        return get_key_manager(provider)
    except TypeError:
        return get_key_manager()


def _provider_base_url(provider: str) -> str:
    pool = get_provider_pool(provider)
    if pool:
        first = pool[0]
        base_url = str(first.get("base_url") or "").strip()
        if base_url:
            return base_url.rstrip("/")
    info = PROVIDER_REGISTRY.get(provider, {})
    return str(info.get("default_base_url") or "").rstrip("/")


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def stream_openai_compatible_chat(
    provider: str,
    payload: dict[str, Any],
    *,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> Generator[dict[str, Any], None, None]:
    """Yield parsed SSE JSON payloads from an OpenAI-compatible chat stream."""
    km = _get_provider_key_manager(provider)
    base_url = _provider_base_url(provider)
    backoff = [2, 4, 8]

    for attempt in range(max_retries):
        key_idx: int | None = None
        emitted = False
        try:
            api_key, key_idx = km.wait_for_available_key()
            with httpx.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers=_headers(api_key),
                json={**payload, "stream": True},
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        return
                    event = json.loads(data_str)
                    emitted = True
                    yield event
                return
        except Exception as exc:
            if emitted:
                raise
            transient_kind = classify_transient_provider_error(exc)
            if transient_kind and key_idx is not None:
                km.report_error(key_idx, transient_kind)
                if attempt < max_retries - 1:
                    import time
                    time.sleep(jittered_delay(backoff[attempt]))
                    continue
            raise


def create_openai_compatible_chat_completion(
    provider: str,
    payload: dict[str, Any],
    *,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Perform a non-streaming OpenAI-compatible chat completion request."""
    km = _get_provider_key_manager(provider)
    base_url = _provider_base_url(provider)
    backoff = [2, 4, 8]

    for attempt in range(max_retries):
        key_idx: int | None = None
        try:
            api_key, key_idx = km.wait_for_available_key()
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers=_headers(api_key),
                json={**payload, "stream": False},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            transient_kind = classify_transient_provider_error(exc)
            if transient_kind and key_idx is not None:
                km.report_error(key_idx, transient_kind)
                if attempt < max_retries - 1:
                    import time
                    time.sleep(jittered_delay(backoff[attempt]))
                    continue
            raise

    raise RuntimeError("OpenAI-compatible provider request failed.")


async def async_create_openai_compatible_chat_completion(
    provider: str,
    payload: dict[str, Any],
    *,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Async variant of create_openai_compatible_chat_completion()."""
    km = _get_provider_key_manager(provider)
    base_url = _provider_base_url(provider)
    backoff = [2, 4, 8]

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(max_retries):
            key_idx: int | None = None
            try:
                api_key, key_idx = await km.await_active_key()
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=_headers(api_key),
                    json={**payload, "stream": False},
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                transient_kind = classify_transient_provider_error(exc)
                if transient_kind and key_idx is not None:
                    km.report_error(key_idx, transient_kind)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(jittered_delay(backoff[attempt]))
                        continue
                raise

    raise RuntimeError("OpenAI-compatible provider request failed.")
