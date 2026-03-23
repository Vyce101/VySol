"""AI agents used by ingestion and entity resolution."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import load_prompt, load_settings, resolve_gemini_thinking_settings
from .key_manager import classify_transient_provider_error, get_key_manager, jittered_delay

logger = logging.getLogger(__name__)


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


async def _call_agent(
    prompt_key: str,
    user_content: str,
    model_name: str,
    temperature: float,
    max_retries: int = 3,
    extra_system_instruction: str | None = None,
    world_id: str | None = None,
    slot_key: str | None = None,
) -> tuple[dict, dict]:
    """
    Call a Gemini agent with retry logic and key rotation.

    Returns (parsed_json_output, usage_metadata).
    Raises AgentCallError on classified provider/runtime failures.
    """
    km = get_key_manager()
    settings = load_settings()
    disable_safety = settings.get("disable_safety_filters", False)

    safety_settings = None
    if disable_safety:
        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]

    system_prompt = load_prompt(prompt_key, world_id=world_id)
    if extra_system_instruction:
        system_prompt = f"{system_prompt.strip()}\n\n{extra_system_instruction.strip()}"
    backoff = [2, 4, 8]
    last_error: Exception | AgentCallError | None = None

    for attempt in range(max_retries):
        key_idx: int | None = None
        try:
            api_key, key_idx = await km.await_active_key()
            client = genai.Client(api_key=api_key)

            resolved_slot_key = slot_key
            if resolved_slot_key is None:
                resolved_slot_key = {
                    "entity_architect_prompt": "default_model_flash",
                    "relationship_architect_prompt": "default_model_flash",
                    "graph_architect_prompt": "default_model_flash",
                    "claim_architect_prompt": "default_model_flash",
                    "entity_resolution_chooser_prompt": "default_model_entity_chooser",
                    "entity_resolution_combiner_prompt": "default_model_entity_combiner",
                }.get(prompt_key)

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

            config = types.GenerateContentConfig(**config_kwargs)

            response = await client.aio.models.generate_content(
                model=model_name,
                contents=user_content,
                config=config,
            )

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

            parsed = json.loads(text)

            usage = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = {
                    "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                    "output_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                }

            return parsed, usage

        except json.JSONDecodeError as e:
            logger.warning(f"Agent {prompt_key} attempt {attempt + 1}: JSON parse error - {e}")
            last_error = e
        except AgentCallError as e:
            if e.kind == "safety_block":
                raise e
            last_error = e
        except Exception as e:
            transient_kind = classify_transient_provider_error(e)
            if transient_kind and key_idx is not None:
                km.report_error(key_idx, transient_kind)
                logger.warning(
                    "Agent %s attempt %s: transient %s on key %s: %s",
                    prompt_key,
                    attempt + 1,
                    transient_kind,
                    key_idx,
                    e,
                )
                if transient_kind == "429" and attempt >= max_retries - 1:
                    raise AgentCallError("rate_limit", "Provider rate limit encountered.")
            else:
                logger.warning(f"Agent {prompt_key} attempt {attempt + 1}: {e}")
            last_error = e

        if attempt < max_retries - 1:
            await asyncio.sleep(jittered_delay(backoff[attempt]))

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

    async def run(self, extraction_chunk_text: str) -> tuple[GraphArchitectOutput, dict]:
        settings = load_settings()
    model = settings.get("default_model_flash", "gemini-3.1-flash-lite-preview")

        parsed, usage = await _call_agent(
            prompt_key="graph_architect_prompt",
            user_content=extraction_chunk_text,
            model_name=model,
            temperature=0.1,
            world_id=self.world_id,
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
