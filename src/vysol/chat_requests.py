"""Translate shared chat preferences into each provider's documented wire format."""

from __future__ import annotations

from urllib.parse import urlsplit


LEVEL_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max")
COMPATIBLE_FIELDS = {
    "temperature", "top_p", "frequency_penalty", "presence_penalty",
    "seed", "stop", "reasoning_effort", "verbosity",
}


def effective_level(preference: str, capabilities: dict, *, google: bool = False) -> str | None:
    prefix = "thinking" if google else "reasoning"
    levels = capabilities.get(f"{prefix}_levels")
    if levels is None or not levels:
        return None
    default = capabilities.get(f"{prefix}_default")
    fallback = default if default in levels else None if default in {"auto", "off"} else levels[-1]
    if preference == "off":
        return "off" if capabilities.get(f"{prefix}_off") else fallback
    if preference == "auto":
        return fallback
    if preference in levels:
        return preference
    if preference in LEVEL_ORDER:
        maximum = LEVEL_ORDER.index(preference)
        lower = [level for level in levels if level in LEVEL_ORDER and LEVEL_ORDER.index(level) <= maximum]
        if lower:
            return max(lower, key=LEVEL_ORDER.index)
    return fallback


def output_limit(preference: str | int, capabilities: dict) -> int | None:
    maximum = capabilities.get("output_limit")
    if not isinstance(maximum, int) or maximum < 1:
        return None
    if preference == "max":
        return maximum
    return min(preference, maximum) if isinstance(preference, int) and preference > 0 else maximum


def request_for(provider: str, model: str, prompt: str, secret: str, base_url: str | None,
                settings: dict, capabilities: dict) -> tuple[str, dict, dict]:
    """Return endpoint, headers, and payload; unknown optional capabilities stay omitted."""
    limit = output_limit(settings.get("output_limit", "max"), capabilities)
    preference = settings.get("reasoning", "auto")
    if provider == "google":
        thinking_budget = capabilities.get("thinking_budget")
        if isinstance(thinking_budget, dict):
            generation = {}
            if limit is not None:
                generation["maxOutputTokens"] = limit
            budget = settings.get("thinking_budget")
            if budget is not None:
                minimum = thinking_budget.get("minimum")
                maximum = thinking_budget.get("maximum")
                allow_zero = thinking_budget.get("allow_zero") is True
                if (isinstance(budget, bool) or not isinstance(budget, int)
                        or budget < 0 or not isinstance(minimum, int) or not isinstance(maximum, int)):
                    raise ValueError(f"Thinking Budget for {model} is invalid.")
                if budget == 0 and not allow_zero:
                    budget = None
                elif budget != 0:
                    budget = min(max(budget, minimum), maximum)
                if budget is not None:
                    generation["thinkingConfig"] = {"thinkingBudget": budget}
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
            if generation:
                payload["generationConfig"] = generation
            return ("https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{model}:streamGenerateContent?alt=sse",
                    {"x-goog-api-key": secret, "Content-Type": "application/json"}, payload)
        payload = {"model": model, "input": prompt, "stream": True, "store": False}
        generation = {}
        if limit is not None:
            generation["max_output_tokens"] = limit
        level = effective_level(preference, capabilities, google=True)
        if level and level != "off":
            generation["thinking_level"] = level
        if generation:
            payload["generation_config"] = generation
        return ("https://generativelanguage.googleapis.com/v1beta/interactions",
                {"x-goog-api-key": secret, "Content-Type": "application/json"}, payload)

    if provider == "openai":
        payload = {"model": model, "input": prompt, "stream": True, "store": False}
        if limit is not None:
            payload["max_output_tokens"] = limit
        level = effective_level(preference, capabilities)
        if level:
            payload["reasoning"] = {"effort": "none" if level == "off" else level}
        return ("https://api.openai.com/v1/responses",
                {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, payload)

    if provider == "anthropic":
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                   "max_tokens": limit or 4096, "stream": True}
        level = effective_level(preference, capabilities)
        if level == "off":
            payload["thinking"] = {"type": "disabled"}
        elif level:
            if capabilities.get("thinking_mode") == "manual":
                budgets = {"minimal": 1024, "low": 2048, "medium": 4096,
                           "high": 8192, "xhigh": 16384, "max": 32768}
                if payload["max_tokens"] < 2048:
                    raise ValueError("Raise Output Limit to at least 2048 tokens to use this model's Reasoning setting.")
                payload["thinking"] = {"type": "enabled", "budget_tokens": min(budgets[level], payload["max_tokens"] // 2)}
            else:
                payload["thinking"] = {"type": "adaptive"}
                payload["output_config"] = {"effort": level}
        return ("https://api.anthropic.com/v1/messages",
                {"x-api-key": secret, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, payload)

    if provider in {"deepseek", "openai_compatible"}:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True}
        if provider == "openai_compatible" and limit is None:
            requested = settings.get("output_limit")
            if isinstance(requested, int) and not isinstance(requested, bool) and requested > 0:
                limit = requested
        if limit is not None:
            payload["max_tokens"] = limit
        if provider == "deepseek":
            level = effective_level(preference, capabilities)
            if level:
                payload["reasoning_effort"] = "none" if level == "off" else level
            endpoint = "https://api.deepseek.com/chat/completions"
        else:
            for name, value in settings.get("compatible_overrides", {}).items():
                if name in COMPATIBLE_FIELDS and value is not None:
                    payload[name] = value
            endpoint = _compatible_endpoint(base_url)
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return endpoint, headers, payload
    raise ValueError("Unsupported AI provider.")


def _compatible_endpoint(base_url: str | None) -> str:
    if not base_url:
        raise ValueError("This compatible connection has no Base URL.")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("This compatible connection has an invalid Base URL.")
    return base_url.rstrip("/") + "/chat/completions"
