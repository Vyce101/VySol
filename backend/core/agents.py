"""AI agents used by ingestion and entity resolution."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from google import genai
from google.genai import types
import httpx
from pydantic import BaseModel

from .config import (
    SLOT_ENTITY_CHOOSER,
    SLOT_ENTITY_COMBINER,
    SLOT_FLASH,
    get_provider_pool,
    load_prompt,
    load_settings,
    resolve_gemini_thinking_settings,
    resolve_groq_reasoning_effort,
    resolve_slot_provider,
)
from .key_manager import (
    AllKeysInCooldownError,
    RequestKeyPoolExhaustedError,
    classify_transient_provider_error,
    get_key_manager,
    jittered_delay,
)
from .openai_compatible_provider import (
    async_create_openai_compatible_chat_completion,
    async_create_openai_compatible_chat_completion_for_api_key,
)

logger = logging.getLogger(__name__)
TransientKeyStrategy = Literal["default", "fail_fast_no_cooldown"]


class AgentCallError(RuntimeError):
    """Structured provider/runtime failure for ingestion agents."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        safety_reason: str | None = None,
        blocked_prefixed_text: str | None = None,
        blocked_raw_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = str(kind or "provider_error")
        self.message = str(message or "")
        self.safety_reason = str(safety_reason) if safety_reason else None
        self.blocked_prefixed_text = blocked_prefixed_text
        self.blocked_raw_text = blocked_raw_text


def _agent_error_kind_for_transient(transient_kind: str | None) -> str:
    if transient_kind == "429":
        return "rate_limit"
    return "provider_error"


class NodeOut(BaseModel):
    node_id: str
    display_name: str
    description: str


class EdgeOut(BaseModel):
    source_node_id: str
    target_node_id: str
    description: str
    strength: int = 5


class EntityArchitectOutput(BaseModel):
    nodes: list[NodeOut] = []


class RelationshipArchitectOutput(BaseModel):
    edges: list[EdgeOut] = []


class GraphArchitectOutput(BaseModel):
    nodes: list[NodeOut] = []
    edges: list[EdgeOut] = []


class ClaimOut(BaseModel):
    node_id: str
    text: str
    source_book: int
    source_chunk: int
    sequence_id: int


class ClaimArchitectOutput(BaseModel):
    claims: list[ClaimOut] = []


class ScribeOutput(BaseModel):
    merged_nodes: list[NodeOut] = []
    merged_edges: list[EdgeOut] = []
    merged_claims: list[ClaimOut] = []


class EntityResolutionChooserOutput(BaseModel):
    chosen_ids: list[str] = []
    reasoning: str = ""


class EntityResolutionCombinerOutput(BaseModel):
    display_name: str
    description: str


def _agent_slot_for_prompt(prompt_key: str, slot_key: str | None = None) -> tuple[str | None, str | None]:
    if slot_key == "default_model_flash":
        return SLOT_FLASH, slot_key
    if slot_key == "default_model_entity_chooser":
        return SLOT_ENTITY_CHOOSER, slot_key
    if slot_key == "default_model_entity_combiner":
        return SLOT_ENTITY_COMBINER, slot_key

    mapping = {
        "entity_architect_prompt": (SLOT_FLASH, "default_model_flash"),
        "relationship_architect_prompt": (SLOT_FLASH, "default_model_flash"),
        "graph_architect_prompt": (SLOT_FLASH, "default_model_flash"),
        "claim_architect_prompt": (SLOT_FLASH, "default_model_flash"),
        "entity_resolution_chooser_prompt": (SLOT_ENTITY_CHOOSER, "default_model_entity_chooser"),
        "entity_resolution_combiner_prompt": (SLOT_ENTITY_COMBINER, "default_model_entity_combiner"),
    }
    return mapping.get(prompt_key, (None, slot_key))


def _output_model_for_prompt(prompt_key: str) -> type[BaseModel] | None:
    return {
        "entity_architect_prompt": EntityArchitectOutput,
        "relationship_architect_prompt": RelationshipArchitectOutput,
        "graph_architect_prompt": GraphArchitectOutput,
        "claim_architect_prompt": ClaimArchitectOutput,
        "entity_resolution_chooser_prompt": EntityResolutionChooserOutput,
        "entity_resolution_combiner_prompt": EntityResolutionCombinerOutput,
        "scribe_prompt": ScribeOutput,
    }.get(prompt_key)


def _message_content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(value or "")


def _get_provider_key_manager(provider: str):
    try:
        return get_key_manager(provider)
    except TypeError:
        return get_key_manager()


def _build_gemini_generate_config(
    *,
    settings: dict[str, Any],
    system_prompt: str,
    resolved_slot_key: str | None,
    model_name: str,
    temperature: float,
) -> types.GenerateContentConfig:
    disable_safety = settings.get(
        "gemini_disable_safety_filters",
        settings.get("disable_safety_filters", False),
    )

    safety_settings = None
    if disable_safety:
        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]

    config_kwargs: dict[str, Any] = {
        "system_instruction": system_prompt,
        "max_output_tokens": 8192,
        "temperature": temperature,
        "response_mime_type": "application/json",
        "safety_settings": safety_settings,
    }
    if resolved_slot_key:
        thinking_config = resolve_gemini_thinking_settings(
            settings,
            slot_key=resolved_slot_key,
            model_name=model_name,
        )
        if thinking_config:
            config_kwargs["thinking_config"] = types.ThinkingConfig(**thinking_config)

    return types.GenerateContentConfig(**config_kwargs)


def _parse_gemini_agent_response(response: Any, user_content: str) -> tuple[dict[str, Any], dict[str, int]]:
    if not response.candidates or not response.candidates[0].content:
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            reason = response.prompt_feedback.block_reason
            details = []
            if hasattr(response.prompt_feedback, "safety_ratings"):
                for rating in (response.prompt_feedback.safety_ratings or []):
                    if rating.probability != "NEGLIGIBLE":
                        details.append(f"{rating.category}: {rating.probability}")
            detail_str = f" ({', '.join(details)})" if details else ""
            reason_text = f"{reason}{detail_str}"
            raise AgentCallError(
                "safety_block",
                f"Provider safety block: {reason_text}",
                safety_reason=reason_text,
                blocked_prefixed_text=user_content,
            )
        raise AgentCallError("empty_response", "Provider returned an empty response.")

    text = response.text.strip()
    if text.startswith("```json"):
        text = text.replace("```json", "", 1).replace("```", "", 1).strip()
    elif text.startswith("```"):
        text = text.replace("```", "", 2).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentCallError("parse_error", f"Provider returned invalid JSON: {exc}") from exc

    usage = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = {
            "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
            "output_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
        }
    return parsed, usage


def _build_openai_compatible_agent_payload(
    *,
    settings: dict[str, Any],
    prompt_key: str,
    system_prompt: str,
    user_content: str,
    model_name: str,
    temperature: float,
    resolved_slot_key: str | None,
) -> dict[str, Any]:
    schema_model = _output_model_for_prompt(prompt_key)
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_completion_tokens": 8192,
    }
    if schema_model is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_model.__name__.lower(),
                "schema": schema_model.model_json_schema(),
            },
        }
    else:
        payload["response_format"] = {"type": "json_object"}

    if resolved_slot_key:
        reasoning_effort = resolve_groq_reasoning_effort(
            settings,
            slot_key=resolved_slot_key,
            model_name=model_name,
        )
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
    return payload


def _openai_compatible_json_schema_mode(payload: dict[str, Any]) -> bool:
    response_format = payload.get("response_format")
    if not isinstance(response_format, dict):
        return False
    return str(response_format.get("type") or "").strip().lower() == "json_schema"


def _build_openai_compatible_json_object_fallback_payload(payload: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(payload)
    response_format = payload.get("response_format")
    schema_payload = response_format.get("json_schema") if isinstance(response_format, dict) else None
    schema = schema_payload.get("schema") if isinstance(schema_payload, dict) else None
    fallback["response_format"] = {"type": "json_object"}

    messages = payload.get("messages") or []
    cloned_messages = [dict(message) for message in messages if isinstance(message, dict)]
    schema_instruction = "Return only a single valid JSON object. Do not include markdown fences or extra prose."
    if schema is not None:
        schema_instruction = (
            "Return only a single valid JSON object that satisfies this JSON schema: "
            f"{json.dumps(schema, separators=(',', ':'))}. "
            "Do not include markdown fences or extra prose."
        )
    if cloned_messages and cloned_messages[0].get("role") == "system":
        system_content = str(cloned_messages[0].get("content") or "").strip()
        cloned_messages[0]["content"] = f"{system_content}\n\n{schema_instruction}".strip()
    else:
        cloned_messages.insert(0, {"role": "system", "content": schema_instruction})
    fallback["messages"] = cloned_messages
    return fallback


def _build_openai_compatible_payload_variants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [payload]
    seen: set[str] = set()

    def add_variant(candidate: dict[str, Any]) -> None:
        key = json.dumps(candidate, sort_keys=True, default=str)
        if key in seen:
            return
        seen.add(key)
        variants.append(candidate)

    seen.add(json.dumps(payload, sort_keys=True, default=str))

    if _openai_compatible_json_schema_mode(payload):
        add_variant(_build_openai_compatible_json_object_fallback_payload(payload))

    if "reasoning_effort" in payload:
        without_reasoning = dict(payload)
        without_reasoning.pop("reasoning_effort", None)
        add_variant(without_reasoning)
        if _openai_compatible_json_schema_mode(payload):
            add_variant(_build_openai_compatible_json_object_fallback_payload(without_reasoning))

    return variants


async def _execute_openai_compatible_agent_request(
    provider: str,
    payload: dict[str, Any],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    last_http_error: httpx.HTTPStatusError | None = None
    variants = _build_openai_compatible_payload_variants(payload)

    for index, candidate in enumerate(variants):
        try:
            if api_key is not None:
                return await async_create_openai_compatible_chat_completion_for_api_key(
                    provider,
                    candidate,
                    api_key=api_key,
                    base_url=base_url,
                )
            return await async_create_openai_compatible_chat_completion(provider, candidate)
        except httpx.HTTPStatusError as exc:
            last_http_error = exc
            if exc.response.status_code != 400 or index == len(variants) - 1:
                raise
            continue

    if last_http_error is not None:
        raise last_http_error
    raise RuntimeError("OpenAI-compatible provider call did not execute.")


def _parse_openai_compatible_agent_response(response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    choice = ((response.get("choices") or [{}])[0]) if isinstance(response, dict) else {}
    message_payload = choice.get("message") or {}
    text = _message_content_to_text(message_payload.get("content")).strip()
    if not text:
        raise AgentCallError("empty_response", "Provider returned an empty response.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentCallError("parse_error", f"Provider returned invalid JSON: {exc}") from exc
    usage_payload = response.get("usage") or {}
    usage = {
        "input_tokens": int(usage_payload.get("prompt_tokens") or 0),
        "output_tokens": int(usage_payload.get("completion_tokens") or 0),
    }
    return parsed, usage


async def _call_agent_fail_fast_no_cooldown(
    *,
    provider: str,
    settings: dict[str, Any],
    prompt_key: str,
    user_content: str,
    model_name: str,
    temperature: float,
    system_prompt: str,
    resolved_slot_key: str | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    pool = get_provider_pool(provider)
    if not pool:
        raise AgentCallError("provider_error", f"No API keys configured for {provider}. Add keys in Key Library.")

    last_transient_error: Exception | None = None

    if provider == "gemini":
        config = _build_gemini_generate_config(
            settings=settings,
            system_prompt=system_prompt,
            resolved_slot_key=resolved_slot_key,
            model_name=model_name,
            temperature=temperature,
        )
        for entry in pool:
            api_key = str(entry.get("api_key") or "").strip()
            if not api_key:
                continue
            try:
                client = genai.Client(api_key=api_key)
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=user_content,
                    config=config,
                )
                return _parse_gemini_agent_response(response, user_content)
            except AgentCallError:
                raise
            except Exception as exc:
                transient_kind = classify_transient_provider_error(exc)
                if transient_kind:
                    last_transient_error = exc
                    continue
                raise AgentCallError("provider_error", f"Provider call failed: {exc}") from exc
    else:
        payload = _build_openai_compatible_agent_payload(
            settings=settings,
            prompt_key=prompt_key,
            system_prompt=system_prompt,
            user_content=user_content,
            model_name=model_name,
            temperature=temperature,
            resolved_slot_key=resolved_slot_key,
        )
        for entry in pool:
            api_key = str(entry.get("api_key") or "").strip()
            if not api_key:
                continue
            base_url = str(entry.get("base_url") or "").strip() or None
            try:
                response = await _execute_openai_compatible_agent_request(
                    provider,
                    payload,
                    api_key=api_key,
                    base_url=base_url,
                )
                return _parse_openai_compatible_agent_response(response)
            except AgentCallError:
                raise
            except Exception as exc:
                transient_kind = classify_transient_provider_error(exc)
                if transient_kind:
                    last_transient_error = exc
                    continue
                raise AgentCallError("provider_error", f"Provider call failed: {exc}") from exc

    if last_transient_error is not None:
        transient_kind = classify_transient_provider_error(last_transient_error)
        raise AgentCallError(
            _agent_error_kind_for_transient(transient_kind),
            str(last_transient_error),
        ) from last_transient_error
    raise AgentCallError("provider_error", f"No API keys configured for {provider}. Add keys in Key Library.")


async def _call_agent(
    prompt_key: str,
    user_content: str,
    model_name: str,
    temperature: float,
    max_retries: int = 3,
    extra_system_instruction: str | None = None,
    world_id: str | None = None,
    slot_key: str | None = None,
    transient_key_strategy: TransientKeyStrategy = "default",
) -> tuple[dict, dict]:
    """
    Call a structured-output agent with retry logic and key rotation.

    Returns (parsed_json_output, usage_metadata).
    Raises AgentCallError on classified provider/runtime failures.
    """
    settings = load_settings()
    slot_name, resolved_slot_key = _agent_slot_for_prompt(prompt_key, slot_key)
    provider = resolve_slot_provider(settings, slot_name) if slot_name else "gemini"

    system_prompt = load_prompt(prompt_key, world_id=world_id) if world_id is not None else load_prompt(prompt_key)
    if extra_system_instruction:
        system_prompt = f"{system_prompt.strip()}\n\n{extra_system_instruction.strip()}"
    if transient_key_strategy == "fail_fast_no_cooldown":
        return await _call_agent_fail_fast_no_cooldown(
            provider=provider,
            settings=settings,
            prompt_key=prompt_key,
            user_content=user_content,
            model_name=model_name,
            temperature=temperature,
            system_prompt=system_prompt,
            resolved_slot_key=resolved_slot_key,
        )
    backoff = [2, 4, 8]
    last_error: Exception | AgentCallError | None = None

    attempt = 0
    tried_key_indices: set[int] = set()

    while attempt < max_retries:
        key_idx: int | None = None
        try:
            if provider == "gemini":
                km = _get_provider_key_manager("gemini")
                if hasattr(km, "await_request_key"):
                    api_key, key_idx = await km.await_request_key(tried_key_indices)
                else:
                    api_key, key_idx = await km.await_active_key()
                client = genai.Client(api_key=api_key)
                config = _build_gemini_generate_config(
                    settings=settings,
                    system_prompt=system_prompt,
                    resolved_slot_key=resolved_slot_key,
                    model_name=model_name,
                    temperature=temperature,
                )

                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=user_content,
                    config=config,
                )
                return _parse_gemini_agent_response(response, user_content)

            payload = _build_openai_compatible_agent_payload(
                settings=settings,
                prompt_key=prompt_key,
                system_prompt=system_prompt,
                user_content=user_content,
                model_name=model_name,
                temperature=temperature,
                resolved_slot_key=resolved_slot_key,
            )
            response = await _execute_openai_compatible_agent_request(provider, payload)
            return _parse_openai_compatible_agent_response(response)

        except json.JSONDecodeError as e:
            logger.warning(f"Agent {prompt_key} attempt {attempt + 1}: JSON parse error - {e}")
            last_error = e
        except AgentCallError as e:
            if e.kind == "safety_block":
                raise e
            last_error = e
        except (AllKeysInCooldownError, RequestKeyPoolExhaustedError):
            raise
        except Exception as e:
            transient_kind = classify_transient_provider_error(e)
            if transient_kind and key_idx is not None:
                _get_provider_key_manager(provider).report_error(key_idx, transient_kind)
                logger.warning(
                    "Agent %s attempt %s: transient %s on key %s: %s",
                    prompt_key,
                    attempt + 1,
                    transient_kind,
                    key_idx,
                    e,
                )
                tried_key_indices.add(key_idx)
                await asyncio.sleep(jittered_delay(backoff[min(len(tried_key_indices) - 1, len(backoff) - 1)]))
                continue
            if transient_kind and key_idx is None:
                raise AgentCallError(
                    _agent_error_kind_for_transient(transient_kind),
                    str(e),
                ) from e
            else:
                logger.warning(f"Agent {prompt_key} attempt {attempt + 1}: {e}")
            last_error = e

        attempt += 1
        if attempt < max_retries:
            await asyncio.sleep(jittered_delay(backoff[min(attempt - 1, len(backoff) - 1)]))

    logger.error(f"Agent {prompt_key}: all {max_retries} retries failed. Last error: {last_error}")
    if isinstance(last_error, AgentCallError):
        raise last_error
    if isinstance(last_error, json.JSONDecodeError):
        raise AgentCallError(
            "parse_error",
            f"Provider returned invalid JSON after {max_retries} attempts: {last_error}",
        ) from last_error
    if last_error is not None:
        raise AgentCallError(
            "provider_error",
            f"Provider call failed after {max_retries} attempts: {last_error}",
        ) from last_error
    raise AgentCallError(
        "provider_error",
        f"Provider call failed after {max_retries} attempts.",
    )


class EntityArchitectAgent:
    """Extracts entities from a chunk."""

    async def run(self, prefixed_chunk_text: str) -> tuple[EntityArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-3.1-flash-lite-preview")

        parsed, usage = await _call_agent(
            prompt_key="entity_architect_prompt",
            user_content=prefixed_chunk_text,
            model_name=model,
            temperature=0.1,
        )

        if not parsed:
            return EntityArchitectOutput(nodes=[]), usage

        try:
            output = EntityArchitectOutput(**parsed)
        except Exception as e:
            logger.warning(f"EntityArchitect output parse failed: {e}")
            output = EntityArchitectOutput(nodes=[])

        return output, usage


class RelationshipArchitectAgent:
    """Extracts relationships given a chunk and extracted entities."""

    async def run(self, prefixed_chunk_text: str, entities: list[NodeOut]) -> tuple[RelationshipArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-3.1-flash-lite-preview")

        user_content = json.dumps(
            {
                "chunk_text": prefixed_chunk_text,
                "extracted_entities": [n.model_dump() for n in entities],
            }
        )

        parsed, usage = await _call_agent(
            prompt_key="relationship_architect_prompt",
            user_content=user_content,
            model_name=model,
            temperature=0.1,
        )

        if not parsed:
            return RelationshipArchitectOutput(edges=[]), usage

        try:
            output = RelationshipArchitectOutput(**parsed)
        except Exception as e:
            logger.warning(f"RelationshipArchitect output parse failed: {e}")
            output = RelationshipArchitectOutput(edges=[])

        return output, usage


class GraphArchitectAgent:
    """Extracts both nodes and edges in a single pass."""

    def __init__(self, *, world_id: str | None = None) -> None:
        self.world_id = world_id

    async def run(
        self,
        extraction_chunk_text: str,
        *,
        transient_key_strategy: TransientKeyStrategy = "default",
    ) -> tuple[GraphArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-3.1-flash-lite-preview")

        parsed, usage = await _call_agent(
            prompt_key="graph_architect_prompt",
            user_content=extraction_chunk_text,
            model_name=model,
            temperature=0.1,
            world_id=self.world_id,
            transient_key_strategy=transient_key_strategy,
        )

        if not parsed:
            return GraphArchitectOutput(nodes=[], edges=[]), usage

        try:
            output = GraphArchitectOutput(**parsed)
        except Exception as e:
            logger.warning(f"GraphArchitect output parse failed: {e}")
            output = GraphArchitectOutput(nodes=[], edges=[])

        return output, usage

    async def run_glean(
        self,
        extraction_chunk_text: str,
        previous_nodes: list[NodeOut],
        previous_edges: list[EdgeOut],
        *,
        transient_key_strategy: TransientKeyStrategy = "default",
    ) -> tuple[GraphArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-3.1-flash-lite-preview")

        user_content = extraction_chunk_text + "\n\n"
        user_content += "Here are the previously extracted entities for this same chunk:\n"
        user_content += json.dumps([n.model_dump() for n in previous_nodes], indent=2) + "\n"
        user_content += "Here are the previously extracted relationships for this same chunk:\n"
        user_content += json.dumps([e.model_dump() for e in previous_edges], indent=2) + "\n"

        parsed, usage = await _call_agent(
            prompt_key="graph_architect_prompt",
            user_content=user_content,
            model_name=model,
            temperature=0.1,
            extra_system_instruction=load_prompt("graph_architect_glean_prompt", world_id=self.world_id),
            world_id=self.world_id,
            transient_key_strategy=transient_key_strategy,
        )

        if not parsed:
            return GraphArchitectOutput(nodes=[], edges=[]), usage

        try:
            output = GraphArchitectOutput(**parsed)
        except Exception as e:
            logger.warning(f"GraphArchitect glean output parse failed: {e}")
            output = GraphArchitectOutput(nodes=[], edges=[])

        return output, usage


class ClaimArchitectAgent:
    """Extracts atomic factual claims from a chunk."""

    async def run(self, prefixed_chunk_text: str) -> tuple[ClaimArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-3.1-flash-lite-preview")

        parsed, usage = await _call_agent(
            prompt_key="claim_architect_prompt",
            user_content=prefixed_chunk_text,
            model_name=model,
            temperature=0.1,
        )

        if not parsed:
            return ClaimArchitectOutput(claims=[]), usage

        try:
            output = ClaimArchitectOutput(**parsed)
        except Exception as e:
            logger.warning(f"ClaimArchitect output parse failed: {e}")
            output = ClaimArchitectOutput(claims=[])

        return output, usage


class ScribeAgent:
    """Deduplicates and merges Graph + Claim outputs."""

    async def run(
        self,
        nodes: list[NodeOut],
        edges: list[EdgeOut],
        claim_output: ClaimArchitectOutput,
        chunk_text: str,
    ) -> tuple[ScribeOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_scribe", "gemini-2.5-pro-preview-05-06")

        user_content = json.dumps(
            {
                "graph_output": {
                    "nodes": [n.model_dump() for n in nodes],
                    "edges": [e.model_dump() for e in edges],
                },
                "claim_output": claim_output.model_dump(),
                "chunk_text": chunk_text,
            }
        )

        parsed, usage = await _call_agent(
            prompt_key="scribe_prompt",
            user_content=user_content,
            model_name=model,
            temperature=0.4,
        )

        if not parsed:
            return ScribeOutput(
                merged_nodes=[n.model_copy() for n in nodes],
                merged_edges=[e.model_copy() for e in edges],
                merged_claims=[c.model_copy() for c in claim_output.claims],
            ), usage

        try:
            output = ScribeOutput(**parsed)
        except Exception as e:
            logger.warning(f"Scribe output parse failed: {e}")
            output = ScribeOutput(
                merged_nodes=[n.model_copy() for n in nodes],
                merged_edges=[e.model_copy() for e in edges],
                merged_claims=[c.model_copy() for c in claim_output.claims],
            )

        return output, usage
