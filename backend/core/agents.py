"""AI agents used by ingestion and entity resolution."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import load_prompt, load_settings
from .key_manager import get_key_manager

logger = logging.getLogger(__name__)


# ── Output models ──────────────────────────────────────────────────────

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


# ── Agent call helper ──────────────────────────────────────────────────

async def _call_agent(
    prompt_key: str,
    user_content: str,
    model_name: str,
    temperature: float,
    max_retries: int = 3,
) -> tuple[dict, dict]:
    """
    Call a Gemini agent with retry logic and key rotation.

    Returns (parsed_json_output, usage_metadata).
    Raises RuntimeError on rate_limit/safety_block.
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

    system_prompt = load_prompt(prompt_key)
    backoff = [2, 4, 8]
    last_error = None

    for attempt in range(max_retries):
        try:
            api_key, key_idx = km.get_active_key()
            client = genai.Client(api_key=api_key)

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=8192,
                temperature=temperature,
                response_mime_type="application/json",
                safety_settings=safety_settings,
            )

            response = await client.aio.models.generate_content(
                model=model_name,
                contents=user_content,
                config=config,
            )

            # Check for safety blocks
            if not response.candidates or not response.candidates[0].content:
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    reason = response.prompt_feedback.block_reason
                    details = []
                    if hasattr(response.prompt_feedback, "safety_ratings"):
                        for rating in response.prompt_feedback.safety_ratings:
                            if rating.probability != "NEGLIGIBLE":
                                details.append(f"{rating.category}: {rating.probability}")
                    detail_str = f" ({', '.join(details)})" if details else ""
                    error_msg = f"safety_block|{reason}{detail_str}|{user_content}"
                    raise RuntimeError(error_msg)
                raise RuntimeError("empty_response")

            # Parse JSON
            text = response.text.strip()
            # Remove MD code blocks if present
            if text.startswith("```json"):
                text = text.replace("```json", "", 1).replace("```", "", 1).strip()
            elif text.startswith("```"):
                text = text.replace("```", "", 2).strip()

            parsed = json.loads(text)

            # Extract token usage
            usage = {}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = {
                    "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                    "output_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                }

            return parsed, usage

        except json.JSONDecodeError as e:
            logger.warning(f"Agent {prompt_key} attempt {attempt+1}: JSON parse error — {e}")
            last_error = e
        except RuntimeError as e:
            error_str = str(e)
            if "safety_block" in error_str:
                raise e
            last_error = e
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "Resource has been exhausted" in error_str:
                km.report_error(key_idx, "429")
                if attempt < max_retries - 1:
                    logger.warning(f"Agent {prompt_key} attempt {attempt+1}: 429 rate limit. Backoff {backoff[attempt]}s")
                    await asyncio.sleep(backoff[attempt])
                    continue
                raise RuntimeError("rate_limit")
            elif "500" in error_str:
                km.report_error(key_idx, "500")
            else:
                logger.warning(f"Agent {prompt_key} attempt {attempt+1}: {e}")
            last_error = e
            km.advance_index()

        if attempt < max_retries - 1:
            await asyncio.sleep(backoff[attempt])

    logger.error(f"Agent {prompt_key}: all {max_retries} retries failed. Last error: {last_error}")
    return {}, {}


# ── Agent classes ──────────────────────────────────────────────────────

class EntityArchitectAgent:
    """Extracts entities from a chunk."""

    async def run(self, prefixed_chunk_text: str) -> tuple[EntityArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-flash-lite-latest")

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
        model = settings.get("default_model_flash", "gemini-flash-lite-latest")

        # Combine the chunk text and the extracted entities so it knows what it can use
        user_content = json.dumps({
            "chunk_text": prefixed_chunk_text,
            "extracted_entities": [n.model_dump() for n in entities]
        })

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

    async def run(self, prefixed_chunk_text: str) -> tuple[GraphArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-flash-lite-latest")

        parsed, usage = await _call_agent(
            prompt_key="graph_architect_prompt",
            user_content=prefixed_chunk_text,
            model_name=model,
            temperature=0.1,
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
        prefixed_chunk_text: str,
        previous_nodes: list[NodeOut],
        previous_edges: list[EdgeOut]
    ) -> tuple[GraphArchitectOutput, dict]:
        settings = load_settings()
        model = settings.get("default_model_flash", "gemini-flash-lite-latest")

        # Append glean instructions to the user prompt
        user_content = prefixed_chunk_text + "\n\n"
        user_content += "MANY entities and relationships have been missed, continue with the extraction.\n"
        user_content += "Here are the previously extracted entities:\n"
        user_content += json.dumps([n.model_dump() for n in previous_nodes], indent=2) + "\n"
        user_content += "Here are the previously extracted relationships:\n"
        user_content += json.dumps([e.model_dump() for e in previous_edges], indent=2) + "\n"
        user_content += "NEVER repeat the same entities and relationships from the previous answers.\n"

        parsed, usage = await _call_agent(
            prompt_key="graph_architect_prompt",
            user_content=user_content,
            model_name=model,
            temperature=0.1,
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
        model = settings.get("default_model_flash", "gemini-flash-lite-latest")

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

        user_content = json.dumps({
            "graph_output": {
                "nodes": [n.model_dump() for n in nodes],
                "edges": [e.model_dump() for e in edges]
            },
            "claim_output": claim_output.model_dump(),
            "chunk_text": chunk_text,
        })

        parsed, usage = await _call_agent(
            prompt_key="scribe_prompt",
            user_content=user_content,
            model_name=model,
            temperature=0.4,
        )

        if not parsed:
            # Fallback: pass through unmerged
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
