import json
import logging
import threading

import httpx
import pytest

from vysol.embeddings import GeminiEmbeddings, ProfileEmbeddings, EmbeddingFailure, InputTooLarge, ProcessingPaused, DIMENSIONS


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


def test_query_embedding_uses_gemini_retrieval_query_prefix():
    def respond(request):
        body = json.loads(request.content)
        assert body["content"]["parts"] == [{"text": "task: search result | query: The latest message"}]
        return httpx.Response(200, json={"embedding": {"values": [1] + [0] * (DIMENSIONS - 1)}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        values = GeminiEmbeddings(client).embed_query(
            "The latest message", "synthetic", threading.Event(), logging.getLogger())
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


def test_google_profile_uses_task_type_and_selected_dimensions():
    def respond(request):
        body = json.loads(request.content)
        assert request.url.path.endswith("/models/gemini-embedding-2:embedContent")
        assert request.headers["x-goog-api-key"] == "synthetic"
        assert body["content"]["parts"] == [{"text": "A saved passage"}]
        assert body["embedContentConfig"] == {
            "taskType": "RETRIEVAL_DOCUMENT", "autoTruncate": False, "outputDimensionality": 3,
        }
        return httpx.Response(200, json={"embedding": {"values": [3, 0, 4]}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        values = ProfileEmbeddings(client).embed_profile(
            "A saved passage", {"provider": "google"}, "synthetic", "gemini-embedding-2", 3,
            "document", threading.Event(), logging.getLogger(),
        )
    assert values == [0.6, 0, 0.8]


def test_openai_profile_uses_embeddings_endpoint_and_default_dimensions():
    def respond(request):
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer synthetic"
        assert body == {"model": "text-embedding-3-small", "input": "A query", "encoding_format": "float"}
        return httpx.Response(200, json={"data": [{"embedding": [0, 2, 0]}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        values = ProfileEmbeddings(client).embed_profile(
            "A query", {"provider": "openai"}, "synthetic", "text-embedding-3-small", 3,
            "query", threading.Event(), logging.getLogger(),
        )
    assert values == [0, 1, 0]


def test_openai_compatible_profile_allows_missing_key_and_uses_saved_base_url():
    def respond(request):
        body = json.loads(request.content)
        assert request.url == "https://embeddings.example/v1/embeddings"
        assert "Authorization" not in request.headers
        assert body == {"model": "provider-embedding", "input": "A passage"}
        return httpx.Response(200, json={"data": [{"embedding": [1, 0, 0, 0]}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        values = ProfileEmbeddings(client).embed_profile(
            "A passage", {"provider": "openai_compatible", "base_url": "https://embeddings.example/v1"},
            "", "provider-embedding", None, "document", threading.Event(), logging.getLogger(),
        )
    assert values == [1, 0, 0, 0]
