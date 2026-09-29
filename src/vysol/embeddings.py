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
        return self._embed(f"title: none | text: {text}", secret, stop, logger)

    def embed_query(self, text: str, secret: str, stop: threading.Event, logger) -> list[float]:
        """Embed a retrieval query with Gemini Embedding 2's asymmetric query prefix."""
        return self._embed(f"task: search result | query: {text}", secret, stop, logger)

    def _embed(self, content: str, secret: str, stop: threading.Event, logger) -> list[float]:
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
                        json={"content": {"parts": [{"text": content}]},
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


class ProfileEmbeddings:
    """Provider embedding calls selected by a World’s saved embedding profile."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client

    def embed_profile(self, text: str, credential: dict, secret: str, model: str,
                      dimensions: int | None, purpose: str, stop: threading.Event, logger):
        provider = credential["provider"]
        client = self.client or httpx.Client(timeout=httpx.Timeout(45, connect=10))
        try:
            for attempt in range(4):
                if stop.is_set():
                    raise ProcessingPaused()
                response = None
                try:
                    if provider == "google":
                        response = self._google(client, secret, model, text, dimensions, purpose)
                    elif provider in {"openai", "openai_compatible"}:
                        response = self._openai(client, credential, secret, model, text)
                    else:
                        raise EmbeddingFailure(
                            "unsupported_provider",
                            "This connection does not support Embedding Profiles.",
                        )
                except httpx.TransportError:
                    pass
                if response is not None and response.is_success:
                    values = self._values(response, provider)
                    return self._normalize(values, dimensions, provider)
                if response is not None and response.status_code in (401, 403):
                    label = "Google" if provider == "google" else "OpenAI-compatible" if provider == "openai_compatible" else "OpenAI"
                    raise EmbeddingFailure(
                        "credentials",
                        f"{label} rejected this key or its access. Check AI Connections in Settings.",
                    )
                if response is not None and response.status_code == 400 and self._is_size_error(response):
                    raise InputTooLarge()
                if response is not None and response.status_code != 429 and response.status_code < 500:
                    raise EmbeddingFailure(
                        "provider_request",
                        "The embedding provider could not process this request. Check the model, connection, and key.",
                    )
                if attempt == 3:
                    raise EmbeddingFailure(
                        "provider_unavailable",
                        "The embedding provider is unavailable or its usage limit was reached.",
                    )
                delay = 2 ** attempt + random.uniform(0, 0.5)
                if response is not None:
                    try:
                        delay = max(delay, min(30, float(response.headers.get("retry-after", "0"))))
                    except ValueError:
                        pass
                logger.warning("Embedding request retry provider=%s attempt=%d", provider, attempt + 1)
                if stop.wait(delay):
                    raise ProcessingPaused()
        finally:
            if self.client is None:
                client.close()

    @staticmethod
    def _google(client, secret, model, text, dimensions, purpose):
        model_name = model.removeprefix("models/")
        config = {"autoTruncate": False}
        if not purpose.startswith("legacy_"):
            config["taskType"] = "RETRIEVAL_QUERY" if purpose == "query" else "RETRIEVAL_DOCUMENT"
        if dimensions is not None:
            config["outputDimensionality"] = dimensions
        return client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:embedContent",
            headers={"x-goog-api-key": secret},
            json={"content": {"parts": [{"text": text}]}, "embedContentConfig": config},
        )

    @staticmethod
    def _openai(client, credential, secret, model, text):
        provider = credential["provider"]
        base_url = credential.get("base_url") if provider == "openai_compatible" else "https://api.openai.com/v1"
        if not base_url:
            raise EmbeddingFailure("connection", "Add a Base URL to this compatible connection.")
        base_url = base_url.rstrip("/")
        endpoint = f"{base_url}/embeddings"
        body = {"model": model, "input": text}
        if provider == "openai":
            body["encoding_format"] = "float"
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        return client.post(endpoint, headers=headers, json=body)

    @staticmethod
    def _values(response, provider):
        try:
            if provider == "google":
                values = response.json()["embedding"]["values"]
            else:
                data = response.json()["data"]
                if not data:
                    raise ValueError()
                values = data[0]["embedding"]
            if not isinstance(values, list):
                raise ValueError()
            return values
        except (IndexError, KeyError, TypeError, ValueError):
            raise EmbeddingFailure("invalid_vector", "The provider returned an invalid embedding. Retry this attempt.") from None

    @staticmethod
    def _normalize(values, dimensions, provider):
        if (not values or (dimensions is not None and len(values) != dimensions)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or abs(value) > 1e30 for value in values)):
            raise EmbeddingFailure("invalid_vector", "The provider returned an invalid embedding. Retry this attempt.")
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            raise EmbeddingFailure("invalid_vector", "The provider returned an invalid embedding. Retry this attempt.")
        return [value / norm for value in values]

    @staticmethod
    def _is_size_error(response):
        try:
            message = str(response.json().get("error", {}).get("message", "")).lower()
        except (ValueError, AttributeError):
            message = ""
        return (any(term in message for term in ("token", "input size", "input length", "context length"))
                and any(term in message for term in ("exceed", "too long", "too large", "maximum", "limit")))
