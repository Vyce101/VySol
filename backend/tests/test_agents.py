import asyncio
from types import SimpleNamespace

import httpx

from core import agents


def test_call_agent_retries_timeout_on_next_key(monkeypatch):
    class DummyKM:
        def __init__(self):
            self.calls = 0
            self.reported: list[tuple[int, str]] = []

        async def await_active_key(self, *, jitter_seconds: float = 0.25):
            keys = [("k1", 0), ("k2", 1)]
            key = keys[min(self.calls, len(keys) - 1)]
            self.calls += 1
            return key

        def report_error(self, key_index: int, error_type: str) -> None:
            self.reported.append((key_index, error_type))

    class DummyAioModels:
        def __init__(self, api_key: str):
            self.api_key = api_key

        async def generate_content(self, *, model, contents, config):
            if self.api_key == "k1":
                raise RuntimeError("request timed out")
            return SimpleNamespace(
                candidates=[SimpleNamespace(content=object())],
                text='{"nodes": [], "edges": []}',
                usage_metadata=SimpleNamespace(prompt_token_count=11, candidates_token_count=7),
                prompt_feedback=None,
            )

    class DummyClient:
        def __init__(self, api_key: str):
            self.aio = SimpleNamespace(models=DummyAioModels(api_key))

    dummy_km = DummyKM()

    monkeypatch.setattr(agents, "get_key_manager", lambda: dummy_km)
    monkeypatch.setattr(agents, "load_settings", lambda: {"disable_safety_filters": False})
    monkeypatch.setattr(agents, "load_prompt", lambda key: "SYSTEM")
    monkeypatch.setattr(agents.genai, "Client", DummyClient)

    parsed, usage = asyncio.run(
        agents._call_agent(
            prompt_key="graph_architect_prompt",
            user_content="chunk text",
            model_name="gemini-test",
            temperature=0.1,
        )
    )

    assert parsed == {"nodes": [], "edges": []}
    assert usage == {"input_tokens": 11, "output_tokens": 7}
    assert dummy_km.reported == [(0, "timeout")]


def test_call_agent_groq_ignores_reasoning_for_known_unsupported_models(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_completion(provider: str, payload: dict, **kwargs):
        captured["provider"] = provider
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": '{"nodes": [], "edges": []}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }

    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "high",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key: "SYSTEM")
    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion", fake_completion)

    parsed, usage = asyncio.run(
        agents._call_agent(
            prompt_key="graph_architect_prompt",
            user_content="chunk text",
            model_name="llama-3.3-70b-versatile",
            temperature=0.1,
        )
    )

    assert parsed == {"nodes": [], "edges": []}
    assert usage == {"input_tokens": 5, "output_tokens": 3}
    assert captured["provider"] == "groq"
    assert "reasoning_effort" not in captured["payload"]


def test_call_agent_groq_preserves_manual_reasoning_for_unknown_models(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_completion(provider: str, payload: dict, **kwargs):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": '{"nodes": [], "edges": []}'}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "medium",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key: "SYSTEM")
    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion", fake_completion)

    asyncio.run(
        agents._call_agent(
            prompt_key="graph_architect_prompt",
            user_content="chunk text",
            model_name="custom/groq-model",
            temperature=0.1,
        )
    )

    assert captured["payload"]["reasoning_effort"] == "medium"


def test_call_agent_groq_rate_limit_default_strategy_surfaces_first_rate_limit(monkeypatch):
    call_count = {"value": 0}

    async def fake_completion(provider: str, payload: dict, **kwargs):
        call_count["value"] += 1
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key: "SYSTEM")
    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion", fake_completion)

    try:
        asyncio.run(
            agents._call_agent(
                prompt_key="graph_architect_prompt",
                user_content="chunk text",
                model_name="openai/gpt-oss-20b",
                temperature=0.1,
            )
        )
    except agents.AgentCallError as exc:
        assert exc.kind == "rate_limit"
        assert "429" in str(exc)
    else:
        raise AssertionError("Expected AgentCallError for Groq 429.")

    assert call_count["value"] == 1


def test_call_agent_groq_falls_back_from_json_schema_to_json_object_on_400(monkeypatch):
    seen_response_formats: list[str] = []

    async def fake_completion(provider: str, payload: dict, **kwargs):
        response_format = payload.get("response_format") or {}
        seen_response_formats.append(str(response_format.get("type") or ""))
        if response_format.get("type") == "json_schema":
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            response = httpx.Response(
                400,
                request=request,
                json={"error": {"message": "json_schema response_format is unsupported for this model"}},
            )
            raise httpx.HTTPStatusError("400 Bad Request", request=request, response=response)
        return {
            "choices": [{"message": {"content": '{"nodes": [], "edges": []}'}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key: "SYSTEM")
    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion", fake_completion)

    parsed, usage = asyncio.run(
        agents._call_agent(
            prompt_key="graph_architect_prompt",
            user_content="chunk text",
            model_name="moonshotai/kimi-k2-instruct-0905",
            temperature=0.1,
        )
    )

    assert parsed == {"nodes": [], "edges": []}
    assert usage == {"input_tokens": 4, "output_tokens": 2}
    assert seen_response_formats == ["json_schema", "json_object"]


def test_call_agent_fail_fast_groq_falls_back_from_json_schema_to_json_object_on_400(monkeypatch):
    seen_response_formats: list[str] = []

    async def fake_completion(provider: str, payload: dict, *, api_key: str, base_url=None, timeout: float = 120.0):
        response_format = payload.get("response_format") or {}
        seen_response_formats.append(str(response_format.get("type") or ""))
        if response_format.get("type") == "json_schema":
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            response = httpx.Response(
                400,
                request=request,
                json={"error": {"message": "json_schema response_format is unsupported for this model"}},
            )
            raise httpx.HTTPStatusError("400 Bad Request", request=request, response=response)
        return {
            "choices": [{"message": {"content": '{"nodes": [], "edges": []}'}}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 3},
        }

    monkeypatch.setattr(
        agents,
        "load_settings",
        lambda: {
            "default_model_flash_provider": "openai_compatible",
            "default_model_flash_openai_compatible_provider": "groq",
            "default_model_flash_groq_reasoning_effort": "",
        },
    )
    monkeypatch.setattr(agents, "load_prompt", lambda key: "SYSTEM")
    monkeypatch.setattr(agents, "get_provider_pool", lambda provider: [{"api_key": "key-1"}])
    monkeypatch.setattr(agents, "async_create_openai_compatible_chat_completion_for_api_key", fake_completion)

    parsed, usage = asyncio.run(
        agents._call_agent(
            prompt_key="graph_architect_prompt",
            user_content="chunk text",
            model_name="moonshotai/kimi-k2-instruct-0905",
            temperature=0.1,
            transient_key_strategy="fail_fast_no_cooldown",
        )
    )

    assert parsed == {"nodes": [], "edges": []}
    assert usage == {"input_tokens": 6, "output_tokens": 3}
    assert seen_response_formats == ["json_schema", "json_object"]
