"""Discover and cache the models available to one saved provider credential."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

import httpx

from .creation_store import CreationStore
from .provider_profiles import profile_for


DEFAULT_ENDPOINTS = {
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "deepseek": "https://api.deepseek.com/models",
}


class CatalogError(Exception):
    """A safe, user-facing model discovery failure."""


class ProviderCatalog:
    def __init__(self, store: CreationStore, vault, logger: logging.Logger | None = None,
                 client: httpx.Client | None = None):
        self.store = store
        self.vault = vault
        self.logger = logger or logging.getLogger("vysol.provider_catalog")
        self.client = client or httpx.Client(timeout=20.0, follow_redirects=False)
        self._owns_client = client is None
        self._refresh_lock = threading.Lock()
        self._background_thread: threading.Thread | None = None
        self._last_background_attempt: dict[str, float] = {}
        self._retry_after_seconds = 15 * 60

    def close(self) -> None:
        thread = self._background_thread
        if thread and thread.is_alive():
            thread.join(timeout=25)
        if thread and thread.is_alive():
            self.logger.warning("Provider model refresh still running during shutdown")
            return
        if self._owns_client:
            self.client.close()

    def refresh(self, key_id: str) -> dict:
        credential = self.store.credential(key_id)
        if credential is None:
            raise KeyError(key_id)
        if not credential.get("enabled"):
            return self._failed(key_id, credential["provider"],
                                CatalogError("Enable this AI connection before refreshing its models."))

        secret = self.vault.read(key_id) or ""
        provider = credential["provider"]
        if provider != "openai_compatible" and not secret:
            return self._failed(key_id, provider, CatalogError("Add an API key before refreshing models."))
        if provider == "openai_compatible" and not credential.get("base_url"):
            return self._failed(key_id, provider, CatalogError("Add a Base URL before refreshing models."))

        try:
            models = self._fetch_models(credential, secret)
            result = self.store.save_catalog(key_id, models)
            self.logger.info("Provider models refreshed provider=%s key_id=%s count=%d",
                             provider, key_id, len(models))
            return {**result, "stale": False}
        except (CatalogError, httpx.HTTPError, ValueError, sqlite3.IntegrityError) as exc:
            if self.store.credential(key_id) is None:
                return self.store.catalog(key_id)
            safe_error = exc if isinstance(exc, CatalogError) else CatalogError(
                "Could not reach this provider. Check the connection and try again.")
            return self._failed(key_id, provider, safe_error)

    def refresh_stale(self) -> None:
        for credential in self.store.keys():
            key_id = credential["id"]
            if not credential.get("enabled"):
                continue
            if not credential.get("base_url") and credential.get("provider") == "openai_compatible":
                continue
            if credential["provider"] != "openai_compatible" and not self.vault.read(key_id):
                continue
            if self.store.needs_catalog_refresh(key_id):
                last_attempt = self._last_background_attempt.get(key_id)
                if last_attempt is not None and time.monotonic() - last_attempt < self._retry_after_seconds:
                    continue
                self._last_background_attempt[key_id] = time.monotonic()
                try:
                    self.refresh(key_id)
                except KeyError:
                    continue

    def refresh_stale_background(self) -> None:
        with self._refresh_lock:
            if self._background_thread and self._background_thread.is_alive():
                return
            self._background_thread = threading.Thread(
                target=self.refresh_stale, name="provider-model-refresh", daemon=True)
            self._background_thread.start()

    def _failed(self, key_id: str, provider: str, error: CatalogError) -> dict:
        try:
            result = self.store.fail_catalog_refresh(key_id, str(error))
        except sqlite3.IntegrityError:
            if self.store.credential(key_id) is None:
                return self.store.catalog(key_id)
            raise
        self.logger.warning("Provider model refresh failed provider=%s key_id=%s reason=%s",
                            provider, key_id, str(error))
        return {**result, "stale": self.store.needs_catalog_refresh(key_id)}

    def _fetch_models(self, credential: dict, secret: str) -> list[dict]:
        provider = credential["provider"]
        if provider == "google":
            raw_models = self._google_models(secret)
        elif provider == "openai":
            raw_models = self._openai_models(DEFAULT_ENDPOINTS[provider], secret, provider)
        elif provider == "anthropic":
            raw_models = self._anthropic_models(secret)
        elif provider == "deepseek":
            raw_models = self._openai_models(DEFAULT_ENDPOINTS[provider], secret, provider)
        elif provider == "openai_compatible":
            endpoint = credential["base_url"].rstrip("/") + "/models"
            raw_models = self._openai_models(endpoint, secret, provider)
        else:
            raise CatalogError("This provider is not supported.")

        models = []
        seen = set()
        for raw in raw_models:
            model_id = raw.get("id")
            if not isinstance(model_id, str) or not model_id.strip() or model_id in seen:
                continue
            seen.add(model_id)
            models.append(profile_for(provider, model_id, raw))
        return models

    def _google_models(self, secret: str) -> list[dict]:
        models = []
        page_token = None
        while True:
            params = {"pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            response = self.client.get(
                DEFAULT_ENDPOINTS["google"], params=params,
                headers={"x-goog-api-key": secret},
            )
            self._check_response(response)
            payload = self._json(response)
            rows = payload.get("models")
            if not isinstance(rows, list):
                raise CatalogError("This provider returned an invalid model list.")
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                methods = raw.get("supportedGenerationMethods")
                if not isinstance(methods, list):
                    continue
                methods = {method for method in methods if isinstance(method, str)}
                if not ({"generateContent", "embedContent"} & methods):
                    continue
                model_id = raw.get("baseModelId") or raw.get("name")
                if isinstance(model_id, str) and model_id.startswith("models/"):
                    model_id = model_id.removeprefix("models/")
                if isinstance(model_id, str):
                    models.append({**raw, "id": model_id})
            page_token = payload.get("nextPageToken")
            if not page_token:
                return models

    def _anthropic_models(self, secret: str) -> list[dict]:
        models = []
        after_id = None
        while True:
            params = {"limit": 1000}
            if after_id:
                params["after_id"] = after_id
            response = self.client.get(
                DEFAULT_ENDPOINTS["anthropic"], params=params,
                headers={"x-api-key": secret, "anthropic-version": "2023-06-01"},
            )
            self._check_response(response)
            payload = self._json(response)
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise CatalogError("This provider returned an invalid model list.")
            models.extend(row for row in rows if isinstance(row, dict))
            if not payload.get("has_more"):
                return models
            after_id = payload.get("last_id")
            if not isinstance(after_id, str) or not after_id:
                raise CatalogError("This provider returned an incomplete model list.")

    def _openai_models(self, endpoint: str, secret: str, provider: str) -> list[dict]:
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        models = []
        after = None
        while True:
            params = {"after": after} if after else None
            response = self.client.get(endpoint, headers=headers, params=params)
            self._check_response(response, provider)
            payload = self._json(response)
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise CatalogError("This provider returned an invalid model list.")
            models.extend(row for row in rows if isinstance(row, dict))
            if not payload.get("has_more"):
                return models
            last = next((row.get("id") for row in reversed(rows)
                         if isinstance(row, dict) and isinstance(row.get("id"), str)), None)
            if not last or last == after:
                raise CatalogError("This provider returned an incomplete model list.")
            after = last

    @staticmethod
    def _check_response(response: httpx.Response, provider: str | None = None) -> None:
        if response.is_success:
            return
        if response.status_code in {401, 403}:
            if provider == "openai_compatible":
                raise CatalogError("This server requires a key or rejected the key.")
            raise CatalogError("The API key was rejected. Check it and try again.")
        if response.status_code == 404:
            raise CatalogError("The model list endpoint was not found. Check the Base URL.")
        if response.status_code == 429:
            raise CatalogError("The provider is temporarily limiting requests. Try again shortly.")
        raise CatalogError(f"Model refresh failed (HTTP {response.status_code}).")

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            raise CatalogError("This provider returned an invalid response.") from None
        if not isinstance(payload, dict):
            raise CatalogError("This provider returned an invalid response.")
        return payload
