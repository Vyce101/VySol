import json
import logging
import threading

import httpx
import pytest

from vysol.embeddings import GeminiEmbeddings, EmbeddingFailure, InputTooLarge, ProcessingPaused, DIMENSIONS


class ImmediateStop:
    def __init__(self, cancel=False):
        self.waits = []
        self.cancel = cancel

    def is_set(self):
        return False

    def wait(self, seconds):
        self.waits.append(seconds)
        return self.cancel


def test_request_contract_and_normalized_vector():
    def respond(request):
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "synthetic"
        assert body["content"]["parts"] == [{"text": "title: none | text: Story"}]
        assert body["embedContentConfig"] == {"outputDimensionality": 768, "autoTruncate": False}
        return httpx.Response(200, json={"embedding": {"values": [2] + [0] * (DIMENSIONS - 1)}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        values = GeminiEmbeddings(client).embed("Story", "synthetic", threading.Event(), logging.getLogger())
        assert values == [1] + [0] * (DIMENSIONS - 1)


@pytest.mark.parametrize("status,body,expected", [
    (403, {"error": {"message": "private provider detail"}}, EmbeddingFailure),
    (400, {"error": {"message": "Input token count exceeds maximum"}}, InputTooLarge),
    (400, {"error": {"message": "Invalid model"}}, EmbeddingFailure),
    (200, {"embedding": {"values": [1, 2]}}, EmbeddingFailure),
    (200, {"embedding": {"values": [0] * DIMENSIONS}}, EmbeddingFailure),
    (200, {"embedding": {"values": [True] * DIMENSIONS}}, EmbeddingFailure),
])
def test_provider_failures_are_safe_and_specific(status, body, expected):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))) as client:
        with pytest.raises(expected) as error:
            GeminiEmbeddings(client).embed("Story", "synthetic", threading.Event(), logging.getLogger())
        assert "private provider detail" not in str(error.value)
        if expected is EmbeddingFailure:
            assert not isinstance(error.value, InputTooLarge)


def test_retry_is_bounded_and_can_pause_during_backoff():
    calls = []
    def unavailable(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"})
    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        stop = ImmediateStop()
        with pytest.raises(EmbeddingFailure):
            GeminiEmbeddings(client).embed("Story", "synthetic", stop, logging.getLogger())
        assert len(calls) == 4 and len(stop.waits) == 3
        with pytest.raises(ProcessingPaused):
            GeminiEmbeddings(client).embed("Story", "synthetic", ImmediateStop(cancel=True), logging.getLogger())
        assert len(calls) == 5
