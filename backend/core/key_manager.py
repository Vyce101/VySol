"""API key rotation manager with FAIL_OVER and ROUND_ROBIN modes."""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time

logger = logging.getLogger(__name__)


class AllKeysInCooldownError(RuntimeError):
    """Raised when every configured API key is temporarily cooling down."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(f"All API keys are in cooldown. Retry in {self.retry_after_seconds:.0f} seconds.")


class RequestKeyPoolExhaustedError(RuntimeError):
    """Raised when a single request has already tried every currently available key."""


_RATE_LIMIT_COOLDOWN_SECONDS = 65.0
_SERVER_ERROR_COOLDOWN_SECONDS = 10.0
_TRANSIENT_COOLDOWN_SECONDS = 15.0
_COOLDOWN_SECONDS_BY_ERROR = {
    "429": _RATE_LIMIT_COOLDOWN_SECONDS,
    "500": _SERVER_ERROR_COOLDOWN_SECONDS,
    "timeout": _TRANSIENT_COOLDOWN_SECONDS,
    "temporary_unavailable": _TRANSIENT_COOLDOWN_SECONDS,
}


def jittered_delay(base_seconds: float, *, jitter_seconds: float = 0.25) -> float:
    """Add a small jitter so concurrent workers do not all resume at once."""
    normalized_base = max(0.0, float(base_seconds))
    normalized_jitter = max(0.0, float(jitter_seconds))
    return normalized_base + (random.uniform(0.0, normalized_jitter) if normalized_jitter > 0 else 0.0)


def classify_transient_provider_error(exc: Exception | str) -> str | None:
    """Return a cooldown code for transient provider/runtime failures."""
    message = str(exc or "").lower()

    if (
        "429" in message
        or "resource has been exhausted" in message
        or "resource_exhausted" in message
        or "rate limit" in message
    ):
        return "429"

    if "500" in message or "internal server error" in message or "internal" in message:
        return "500"

    if (
        isinstance(exc, TimeoutError)
        or "timeout" in message
        or "timed out" in message
        or "deadline exceeded" in message
        or "readtimeout" in message
        or "connecttimeout" in message
        or "request timed out" in message
    ):
        return "timeout"

    if (
        "connecterror" in message
        or "connection error" in message
        or "connection reset" in message
        or "connection aborted" in message
        or "service unavailable" in message
        or "temporarily unavailable" in message
        or "remoteprotocolerror" in message
        or "503" in message
        or "overloaded" in message
    ):
        return "temporary_unavailable"

    return None


class KeyManager:
    """Manages multiple API keys with rotation and cooldown."""

    def __init__(self, api_keys: list[str] | None = None, mode: str = "FAIL_OVER", provider: str = "gemini"):
        from .config import get_provider_pool, load_settings

        self.provider = provider
        if api_keys is None:
            settings = load_settings()
            api_keys = [
                str(entry.get("api_key") or "")
                for entry in get_provider_pool(provider)
                if str(entry.get("api_key") or "").strip()
            ]
            mode = settings.get("key_rotation_mode", "FAIL_OVER")

        self.api_keys: list[str] = api_keys
        self.mode: str = mode
        self._current_index: int = 0
        self._cooldown_map: dict[int, float] = {}
        self._call_count: int = 0
        self._lock = threading.RLock()

    @property
    def key_count(self) -> int:
        return len(self.api_keys)

    def _is_in_cooldown_unlocked(self, index: int) -> bool:
        if index not in self._cooldown_map:
            return False
        if time.time() >= self._cooldown_map[index]:
            del self._cooldown_map[index]
            return False
        return True

    def _cooldown_remaining_unlocked(self, index: int) -> float:
        if index not in self._cooldown_map:
            return 0.0
        remaining = self._cooldown_map[index] - time.time()
        return max(0.0, remaining)

    def _all_keys_cooling_down_error_unlocked(self, key_count: int) -> AllKeysInCooldownError:
        min_wait = min(self._cooldown_remaining_unlocked(i) for i in range(key_count))
        return AllKeysInCooldownError(min_wait)

    def _next_available_index_unlocked(self, *, exclude_indices: set[int] | None = None) -> int | None:
        excluded = exclude_indices or set()
        key_count = len(self.api_keys)

        if self.mode == "ROUND_ROBIN":
            for offset in range(key_count):
                idx = (self._current_index + offset) % key_count
                if idx in excluded or self._is_in_cooldown_unlocked(idx):
                    continue
                self._call_count += 1
                self._current_index = (idx + 1) % key_count
                return idx
            return None

        for offset in range(key_count):
            idx = (self._current_index + offset) % key_count
            if idx in excluded or self._is_in_cooldown_unlocked(idx):
                continue
            self._current_index = idx
            return idx
        return None

    def get_active_key(self) -> tuple[str, int]:
        """Return (key, index). Raises AllKeysInCooldownError if all keys are cooling down."""
        with self._lock:
            if not self.api_keys:
                raise RuntimeError(f"No API keys configured for {self.provider}. Add keys in Key Library.")

            key_count = len(self.api_keys)

            if self.mode == "ROUND_ROBIN":
                self._call_count += 1
                for _ in range(key_count):
                    idx = self._current_index % key_count
                    self._current_index = (self._current_index + 1) % key_count
                    if not self._is_in_cooldown_unlocked(idx):
                        return self.api_keys[idx], idx
                raise self._all_keys_cooling_down_error_unlocked(key_count)

            for offset in range(key_count):
                idx = (self._current_index + offset) % key_count
                if not self._is_in_cooldown_unlocked(idx):
                    self._current_index = idx
                    return self.api_keys[idx], idx
            raise self._all_keys_cooling_down_error_unlocked(key_count)

    def get_request_key(self, tried_indices: set[int] | None = None) -> tuple[str, int]:
        """Return the next available key for one logical request, excluding already-tried indices."""
        with self._lock:
            if not self.api_keys:
                raise RuntimeError(f"No API keys configured for {self.provider}. Add keys in Key Library.")

            excluded = set(tried_indices or ())
            idx = self._next_available_index_unlocked(exclude_indices=excluded)
            if idx is not None:
                return self.api_keys[idx], idx

            remaining = [index for index in range(len(self.api_keys)) if index not in excluded]
            if not remaining:
                raise RequestKeyPoolExhaustedError(
                    f"Every configured key for {self.provider} has already been tried for this request."
                )

            min_wait = min(self._cooldown_remaining_unlocked(index) for index in remaining)
            raise AllKeysInCooldownError(min_wait)

    def wait_for_available_key(self, *, jitter_seconds: float = 0.25) -> tuple[str, int]:
        """Block until a key is available, sleeping through cooldown windows."""
        while True:
            try:
                return self.get_active_key()
            except AllKeysInCooldownError as exc:
                time.sleep(jittered_delay(exc.retry_after_seconds, jitter_seconds=jitter_seconds))

    def wait_for_request_key(
        self,
        tried_indices: set[int] | None = None,
        *,
        jitter_seconds: float = 0.25,
    ) -> tuple[str, int]:
        """Wait for the first available key, then only rotate across untried keys for this request."""
        excluded = set(tried_indices or ())
        while True:
            try:
                return self.get_request_key(excluded)
            except AllKeysInCooldownError as exc:
                if excluded:
                    raise
                time.sleep(jittered_delay(exc.retry_after_seconds, jitter_seconds=jitter_seconds))

    async def await_active_key(self, *, jitter_seconds: float = 0.25) -> tuple[str, int]:
        """Async variant of wait_for_available_key()."""
        while True:
            try:
                return self.get_active_key()
            except AllKeysInCooldownError as exc:
                await asyncio.sleep(jittered_delay(exc.retry_after_seconds, jitter_seconds=jitter_seconds))

    async def await_request_key(
        self,
        tried_indices: set[int] | None = None,
        *,
        jitter_seconds: float = 0.25,
    ) -> tuple[str, int]:
        """Async variant of wait_for_request_key()."""
        excluded = set(tried_indices or ())
        while True:
            try:
                return self.get_request_key(excluded)
            except AllKeysInCooldownError as exc:
                if excluded:
                    raise
                await asyncio.sleep(jittered_delay(exc.retry_after_seconds, jitter_seconds=jitter_seconds))

    def report_error(self, key_index: int, error_type: str) -> None:
        """Report an error for a key and apply any configured cooldown."""
        cooldown_seconds = _COOLDOWN_SECONDS_BY_ERROR.get(str(error_type or ""))
        if cooldown_seconds is None:
            return

        with self._lock:
            self._cooldown_map[key_index] = time.time() + cooldown_seconds

        logger.warning(
            "Key index %s entered %ss cooldown due to %s",
            key_index,
            int(cooldown_seconds),
            error_type,
        )


_key_managers: dict[str, KeyManager] = {}
_key_manager: KeyManager | None = None


def get_key_manager(provider: str = "gemini", force_reload: bool = False) -> KeyManager:
    """Get or create the provider-specific KeyManager singleton."""
    global _key_managers, _key_manager
    if provider == "gemini" and _key_manager is None:
        _key_managers.pop("gemini", None)
    if force_reload or provider not in _key_managers:
        _key_managers[provider] = KeyManager(provider=provider)
        if provider == "gemini":
            _key_manager = _key_managers[provider]
    return _key_managers[provider]
