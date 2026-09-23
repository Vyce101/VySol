"""Gemini retrieval embeddings with bounded retries and no input truncation."""

import math
import random
import threading

import httpx

MODEL = "gemini-embedding-2"
DIMENSIONS = 768
INPUT_FORMAT_VERSION = 1
MODELS = [{"id": MODEL, "name": "Gemini Embedding 2", "provider": "google"}]


class EmbeddingFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class InputTooLarge(EmbeddingFailure):
    def __init__(self):
        super().__init__("input_too_large", "This passage exceeds the model's input limit.")


class ProcessingPaused(Exception):
    pass


class GeminiEmbeddings:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client

    def embed(self, text: str, secret: str, stop: threading.Event, logger) -> list[float]:
        client = self.client or httpx.Client(timeout=httpx.Timeout(45, connect=10))
        try:
            for attempt in range(4):
                if stop.is_set():
                    raise ProcessingPaused()
                response = None
                try:
                    response = client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:embedContent",
                        headers={"x-goog-api-key": secret},
                        json={"content": {"parts": [{"text": f"title: none | text: {text}"}]},
                              "embedContentConfig": {"outputDimensionality": DIMENSIONS,
                                                     "autoTruncate": False}},
                    )
                except httpx.TransportError:
                    pass
                if response is not None and response.is_success:
                    try:
                        values = response.json()["embedding"]["values"]
                        if (not isinstance(values, list) or len(values) != DIMENSIONS
                                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                       or not math.isfinite(v) or abs(v) > 1e30 for v in values)):
                            raise ValueError()
                        norm = math.sqrt(sum(v * v for v in values))
                        if norm == 0:
                            raise ValueError()
                        return [v / norm for v in values]
                    except (KeyError, TypeError, ValueError):
                        raise EmbeddingFailure("invalid_vector", "Google returned an invalid embedding. Retry this attempt.") from None
                if response is not None and response.status_code in (401, 403):
                    raise EmbeddingFailure("credentials", "Google rejected this key or its access. Check Providers in Settings.")
                if response is not None and response.status_code == 400:
                    # Only an explicit size error permits changing chunk boundaries.
                    try:
                        message = str(response.json().get("error", {}).get("message", "")).lower()
                    except (ValueError, AttributeError):
                        message = ""
                    if any(term in message for term in ("token", "input size", "input length")) and any(
                            term in message for term in ("exceed", "too long", "too large", "maximum")):
                        raise InputTooLarge()
                if response is not None and response.status_code != 429 and response.status_code < 500:
                    raise EmbeddingFailure("provider_request", "Google could not process this request. Check the model and key, then retry.")
                if attempt == 3:
                    raise EmbeddingFailure("provider_unavailable", "Google is unavailable or its usage limit was reached.")
                delay = 2 ** attempt + random.uniform(0, 0.5)
                if response is not None:
                    try:
                        delay = max(delay, min(30, float(response.headers.get("retry-after", "0"))))
                    except ValueError:
                        pass
                logger.warning("Embedding request retry attempt=%d", attempt + 1)
                if stop.wait(delay):
                    raise ProcessingPaused()
        finally:
            if self.client is None:
                client.close()
