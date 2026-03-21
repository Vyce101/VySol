"""API key rotation manager with FAIL_OVER and ROUND_ROBIN modes."""

import os
import time
import logging

logger = logging.getLogger(__name__)


class KeyManager:
    """Manages multiple API keys with rotation and cooldown."""

    def __init__(self, api_keys: list[str] | None = None, mode: str = "FAIL_OVER"):
        from .config import get_enabled_api_keys, load_settings

        if api_keys is None:
            settings = load_settings()
            api_keys = get_enabled_api_keys(settings)
            mode = settings.get("key_rotation_mode", "FAIL_OVER")

        # Fallback to env var
        if not api_keys:
            env_key = os.environ.get("GEMINI_API_KEY", "")
            if env_key and env_key != "your_key_here":
                api_keys = [env_key]

        self.api_keys: list[str] = api_keys
        self.mode: str = mode  # "FAIL_OVER" or "ROUND_ROBIN"
        self._current_index: int = 0
        self._cooldown_map: dict[int, float] = {}  # index → time when cooldown expires
        self._call_count: int = 0

    @property
    def key_count(self) -> int:
        return len(self.api_keys)

    def _is_in_cooldown(self, index: int) -> bool:
        if index not in self._cooldown_map:
            return False
        if time.time() >= self._cooldown_map[index]:
            del self._cooldown_map[index]
            return False
        return True

    def _cooldown_remaining(self, index: int) -> float:
        if index not in self._cooldown_map:
            return 0.0
        remaining = self._cooldown_map[index] - time.time()
        return max(0.0, remaining)

    def get_active_key(self) -> tuple[str, int]:
        """Return (key, index). Raises RuntimeError if all keys are in cooldown."""
        if not self.api_keys:
            raise RuntimeError("No API keys configured. Add keys in Settings or set GEMINI_API_KEY env var.")

        n = len(self.api_keys)

        if self.mode == "ROUND_ROBIN":
            self._call_count += 1
            start = self._current_index
            for _ in range(n):
                idx = self._current_index % n
                self._current_index = (self._current_index + 1) % n
                if not self._is_in_cooldown(idx):
                    return self.api_keys[idx], idx
            # All in cooldown
            min_wait = min(self._cooldown_remaining(i) for i in range(n))
            raise RuntimeError(f"All API keys are in cooldown. Retry in {min_wait:.0f} seconds.")

        else:  # FAIL_OVER
            for i in range(n):
                idx = (self._current_index + i) % n
                if not self._is_in_cooldown(idx):
                    self._current_index = idx
                    return self.api_keys[idx], idx
            min_wait = min(self._cooldown_remaining(i) for i in range(n))
            raise RuntimeError(f"All API keys are in cooldown. Retry in {min_wait:.0f} seconds.")

    def report_error(self, key_index: int, error_type: str) -> None:
        """Report an error for a key. 429 errors trigger 65s cooldown."""
        if error_type == "429":
            self._cooldown_map[key_index] = time.time() + 65
            logger.warning(f"Key index {key_index} rate-limited — cooldown until {self._cooldown_map[key_index]:.0f}")
        elif error_type == "500":
            self._cooldown_map[key_index] = time.time() + 10
            logger.warning(f"Key index {key_index} server error — short cooldown")
        # Other errors: no cooldown, just move on

    def advance_index(self) -> None:
        """Advance to next key index (for FAIL_OVER on error)."""
        if self.api_keys:
            self._current_index = (self._current_index + 1) % len(self.api_keys)


# Module-level singleton — reinitialised when settings change
_key_manager: KeyManager | None = None


def get_key_manager(force_reload: bool = False) -> KeyManager:
    """Get or create the global KeyManager singleton."""
    global _key_manager
    if _key_manager is None or force_reload:
        _key_manager = KeyManager()
    return _key_manager
