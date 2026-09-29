"""Provider chat requests use documented fields and omit unknown controls."""

import json
import threading

import httpx
import pytest

from vysol.chat_requests import effective_level, request_for
from vysol.chronicles import ChronicleService
from vysol.chronicles_api import ChronicleSettings


def capabilities(**changes):
    value = {"output_limit": 64000, "reasoning_levels": ["low", "medium", "high"],
             "reasoning_default": "medium", "reasoning_off": True,
             "thinking_levels": ["low", "medium", "high"], "thinking_default": "medium",
             "thinking_off": False}
    value.update(changes)
    return value


def test_native_chat_requests_translate_supported_controls():
    settings = {"output_limit": "max", "reasoning": "high"}
    endpoint, headers, payload = request_for("google", "gemini-3.8-flash", "Hello", "secret", None,
                                             settings, capabilities())
    assert endpoint.endswith("/interactions")
    assert headers["x-goog-api-key"] == "secret"
    assert payload["generation_config"]["max_output_tokens"] == 64000
    assert payload["generation_config"]["thinking_level"] == "high"
    assert "thinking_summaries" not in payload["generation_config"]
    assert "temperature" not in payload["generation_config"]
    assert "tools" not in payload

    endpoint, _, payload = request_for("openai", "gpt-6-sol", "Hello", "secret", None,
                                       settings, capabilities())
    assert endpoint.endswith("/responses")
    assert payload["max_output_tokens"] == 64000
    assert payload["reasoning"] == {"effort": "high"}
    assert "temperature" not in payload and "top_p" not in payload

    endpoint, headers, payload = request_for("anthropic", "claude-opus-5-5", "Hello", "secret", None,
                                             settings, capabilities())
    assert endpoint.endswith("/messages")
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["max_tokens"] == 64000
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "high"}

    endpoint, _, payload = request_for("deepseek", "deepseek-flash", "Hello", "secret", None,
                                       {**settings, "reasoning": "off"}, capabilities())
    assert endpoint.endswith("/chat/completions")
    assert payload["reasoning_effort"] == "none"
    assert "temperature" not in payload and "top_p" not in payload


def test_compatible_overrides_are_opt_in_and_unknown_limits_are_omitted():
    unknown = {"output_limit": None, "reasoning_levels": None}
    settings = {"output_limit": "max", "reasoning": "high", "compatible_overrides": {}}
    endpoint, headers, payload = request_for("openai_compatible", "local-chat", "Hello", "", "http://localhost:1234/v1",
                                             settings, unknown)
    assert endpoint == "http://localhost:1234/v1/chat/completions"
    assert "Authorization" not in headers
    assert "max_tokens" not in payload and "reasoning_effort" not in payload
    assert "temperature" not in payload

    settings["compatible_overrides"] = {"temperature": 0.7, "stop": ["END"], "unsafe": "ignored"}
    _, _, payload = request_for("openai_compatible", "local-chat", "Hello", "", "http://localhost:1234/v1",
                                 settings, unknown)
    assert payload["temperature"] == 0.7
    assert payload["stop"] == ["END"]
    assert "unsafe" not in payload

    settings["output_limit"] = 2048
    _, _, payload = request_for("openai_compatible", "local-chat", "Hello", "", "http://localhost:1234/v1",
                                 settings, unknown)
    assert payload["max_tokens"] == 2048


def test_unsupported_shared_reasoning_uses_model_option_without_overwriting_preference():
    options = capabilities(reasoning_levels=["low", "high"], reasoning_default="high", reasoning_off=False)
    assert effective_level("medium", options) == "low"
    assert effective_level("off", options) == "high"
    assert effective_level("auto", options) == "high"


def test_google_dynamic_and_off_defaults_leave_thinking_level_to_provider():
    dynamic = capabilities(thinking_default="auto", thinking_off=False)
    off_by_default = capabilities(thinking_default="off", thinking_off=True)
    assert effective_level("auto", dynamic, google=True) is None
    assert effective_level("auto", off_by_default, google=True) is None
    _, _, payload = request_for("google", "gemini-3.8-flash", "Hello", "secret", None,
                                {"reasoning": "auto", "output_limit": "max"}, dynamic)
    assert "thinking_level" not in payload["generation_config"]


def test_gemini_25_pro_uses_generate_content_with_optional_numeric_budget():
    assert ChronicleSettings(thinking_budget=128).thinking_budget == 128
    assert ChronicleSettings(thinking_budget=0).thinking_budget == 0
    with pytest.raises(ValueError, match="thinking_budget"):
        ChronicleSettings(thinking_budget=-1)
    settings = {"output_limit": "max", "reasoning": "high", "thinking_budget": None}
    pro_options = capabilities(
        output_limit=65536,
        thinking_budget={"minimum": 128, "maximum": 32768,
                         "default": "dynamic", "allow_zero": False},
    )
    endpoint, _, payload = request_for("google", "gemini-2.5-pro", "Hello", "secret", None,
                                       settings, pro_options)
    assert endpoint.endswith("/gemini-2.5-pro:streamGenerateContent?alt=sse")
    assert payload == {"contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
                       "generationConfig": {"maxOutputTokens": 65536}}

    _, _, payload = request_for("google", "gemini-2.5-pro", "Hello", "secret", None,
                                {**settings, "thinking_budget": 32768}, pro_options)
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 32768}
    _, _, payload = request_for("google", "gemini-2.5-pro", "Hello", "secret", None,
                                {**settings, "thinking_budget": 0}, pro_options)
    assert "thinkingConfig" not in payload["generationConfig"]


@pytest.mark.parametrize(("model", "minimum", "maximum", "default", "budget"), [
    ("gemini-2.5-flash", 0, 24576, "dynamic", 0),
    ("gemini-2.5-flash-lite", 512, 24576, "off", 0),
    ("gemini-2.5-flash-lite", 512, 24576, "off", 512),
])
def test_gemini_25_flash_models_use_generate_content_numeric_budgets(
        model, minimum, maximum, default, budget):
    options = capabilities(
        output_limit=65536,
        thinking_budget={"minimum": minimum, "maximum": maximum,
                         "default": default, "allow_zero": True},
    )
    endpoint, _, payload = request_for(
        "google", model, "Hello", "secret", None,
        {"output_limit": "max", "reasoning": "auto", "thinking_budget": budget}, options,
    )

    assert endpoint.endswith(f"/{model}:streamGenerateContent?alt=sse")
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": budget}

    _, _, payload = request_for(
        "google", model, "Hello", "secret", None,
        {"output_limit": "max", "reasoning": "auto", "thinking_budget": maximum + 1}, options,
    )
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": maximum}


def test_anthropic_manual_thinking_uses_budget_and_rejects_too_small_output():
    manual = capabilities(thinking_mode="manual", output_limit=8192)
    _, _, payload = request_for("anthropic", "claude-haiku-4-5", "Hello", "secret", None,
                                {"output_limit": "max", "reasoning": "medium"}, manual)
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert "output_config" not in payload

    try:
        request_for("anthropic", "claude-haiku-4-5", "Hello", "secret", None,
                    {"output_limit": 512, "reasoning": "medium"}, manual)
    except ValueError as exc:
        assert "Output Limit" in str(exc)
    else:
        raise AssertionError("Manual thinking cannot fit inside the selected Output Limit")


def test_stream_events_from_each_provider():
    assert ChronicleService._standard_event("openai", '{"type":"response.output_text.delta","delta":"A"}') == [("answer", "A")]
    assert ChronicleService._standard_event("anthropic", '{"type":"content_block_delta","delta":{"type":"text_delta","text":"B"}}') == [("answer", "B")]
    assert ChronicleService._standard_event("deepseek", '{"choices":[{"delta":{"reasoning_content":"Think","content":"C"}}]}') == [("thinking", "Think"), ("answer", "C")]
    assert ChronicleService._standard_event("openai_compatible", "[DONE]") == [("completed", "")]


def test_provider_stream_contracts_send_answer_deltas():
    streams = {
        "openai": 'data: {"type":"response.output_text.delta","delta":"OpenAI"}\n\n'
                  'data: {"type":"response.completed"}\n\n',
        "anthropic": 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Claude"}}\n\n'
                     'data: {"type":"message_stop"}\n\n',
        "deepseek": 'data: {"choices":[{"delta":{"content":"DeepSeek"}}]}\n\n'
                    'data: [DONE]\n\n',
        "openai_compatible": 'data: {"choices":[{"delta":{"content":"Local"}}]}\n\n'
                             'data: [DONE]\n\n',
    }
    for provider, body in streams.items():
        seen = []

        def handler(request):
            seen.append((str(request.url), json.loads(request.content)))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

        service = object.__new__(ChronicleService)
        service.chat_client = httpx.Client(transport=httpx.MockTransport(handler))
        service.guard = threading.RLock()
        service.responses = {}
        settings = {"model": "model", "output_limit": "max", "reasoning": "auto", "compatible_overrides": {}}
        credential = {"provider": provider, "base_url": "http://localhost:1234/v1",
                      "model_profile": {"capabilities": capabilities()}}
        try:
            deltas = list(service._provider_deltas(settings, credential, "Hello", "secret", ("c", "r"), threading.Event()))
        finally:
            service.chat_client.close()
        assert len(seen) == 1
        assert len(deltas) == 1 and deltas[0][0] == "answer"
        assert "web_search" not in seen[0][1]


def test_gemini_25_pro_stream_reads_generate_content_chunks():
    body = ('data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}\n\n'
            'data: {"candidates":[{"content":{"parts":[{"text":" world"}]},"finishReason":"STOP"}]}\n\n')
    seen = []

    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    service = object.__new__(ChronicleService)
    service.chat_client = httpx.Client(transport=httpx.MockTransport(handler))
    service.guard = threading.RLock()
    service.responses = {}
    settings = {"model": "gemini-2.5-pro", "output_limit": "max", "reasoning": "auto",
                "thinking_budget": 1024}
    credential = {"provider": "google", "model_profile": {
        "api": "generate_content",
        "capabilities": capabilities(
            output_limit=65536,
            thinking_budget={"minimum": 128, "maximum": 32768,
                             "default": "dynamic", "allow_zero": False},
        ),
    }}
    try:
        deltas = list(service._provider_deltas(settings, credential, "Hello", "secret", ("c", "r"), threading.Event()))
    finally:
        service.chat_client.close()
    assert deltas == [("answer", "Hello"), ("answer", " world")]
    assert seen[0][0].endswith("/gemini-2.5-pro:streamGenerateContent?alt=sse")
    assert seen[0][1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 1024}
