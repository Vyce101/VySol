import httpx
import pytest
import time

from core import openai_compatible_provider
from core.key_manager import RequestKeyPoolExhaustedError


class _FakeKeyManager:
    def __init__(self, responses):
        self._responses = list(responses)
        self.wait_calls: list[set[int]] = []
        self.reported_errors: list[tuple[int, str]] = []

    def wait_for_request_key(self, tried_indices, *, jitter_seconds: float = 0.25):
        self.wait_calls.append(set(tried_indices or ()))
        if not self._responses:
            raise AssertionError("No more fake key responses configured.")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def report_error(self, key_index: int, error_type: str) -> None:
        self.reported_errors.append((key_index, error_type))


def test_single_key_timeout_surfaces_real_error_instead_of_pool_exhaustion(monkeypatch):
    fake_manager = _FakeKeyManager([
        ("only-key", 0),
        ("only-key", 0),
    ])

    monkeypatch.setattr(openai_compatible_provider, "_get_provider_key_manager", lambda provider: fake_manager)
    monkeypatch.setattr(openai_compatible_provider, "_provider_base_url", lambda provider: "https://example.test")
    monkeypatch.setattr(openai_compatible_provider, "jittered_delay", lambda delay, jitter_seconds=0.25: 0.0)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    def fake_post(*args, **kwargs):
        raise httpx.ReadTimeout("request timed out")

    monkeypatch.setattr(openai_compatible_provider.httpx, "post", fake_post)

    with pytest.raises(httpx.ReadTimeout):
        openai_compatible_provider.create_openai_compatible_chat_completion(
            "groq",
            {"messages": []},
            max_retries=2,
        )

    assert fake_manager.wait_calls == [set(), set()]
    assert fake_manager.reported_errors == [(0, "timeout"), (0, "timeout")]


def test_rate_limit_failover_raises_last_provider_error_after_all_keys_are_tried(monkeypatch):
    fake_manager = _FakeKeyManager([
        ("key-1", 0),
        ("key-2", 1),
        RequestKeyPoolExhaustedError("Every configured key for groq has already been tried for this request."),
    ])

    monkeypatch.setattr(openai_compatible_provider, "_get_provider_key_manager", lambda provider: fake_manager)
    monkeypatch.setattr(openai_compatible_provider, "_provider_base_url", lambda provider: "https://example.test")

    def fake_post(*args, **kwargs):
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(openai_compatible_provider.httpx, "post", fake_post)

    with pytest.raises(RuntimeError, match="429 rate limit"):
        openai_compatible_provider.create_openai_compatible_chat_completion(
            "groq",
            {"messages": []},
            max_retries=1,
        )

    assert fake_manager.wait_calls == [set(), {0}, {0, 1}]
    assert fake_manager.reported_errors == [(0, "429"), (1, "429")]
