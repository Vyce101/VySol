"""HTTP endpoints for Chronicle lists, chat history, shared settings, and streamed turns."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .chronicles import ChronicleService


class NewMessage(BaseModel):
    request_id: UUID
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Enter a message before sending.")
        return value


class RenameChronicle(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Give this Chronicle a name.")
        return value.strip()


class ChronicleSettings(BaseModel):
    model: str = "gemini-3.8-flash"
    key_id: str = ""
    output_limit: int | Literal["max"] = "max"
    reasoning: str = "auto"
    thinking_budget: int | None = Field(default=None, ge=0, le=32768)
    compatible_overrides: dict[str, int | float | str | list[str] | None] = Field(default_factory=dict)
    chunk_count: int = Field(default=3, ge=1, le=50)
    minimum_similarity: float = Field(default=0.60, ge=0, le=1)
    chunk_overlap: int = Field(default=150, ge=0, le=100_000)
    streaming_speed: int = Field(default=50, ge=0, le=100)
    chat_history_prefix: str = Field(default="<chat_history>", max_length=2000)
    chat_history_suffix: str = Field(default="</chat_history>", max_length=2000)
    rag_chunks_prefix: str = Field(default="<rag_chunks>", max_length=2000)
    rag_chunks_suffix: str = Field(default="</rag_chunks>", max_length=2000)
    sections: dict[Literal["ai", "retrieval", "response", "section_tags"], bool] = Field(
        default_factory=lambda: {"ai": True, "retrieval": True, "response": True, "section_tags": True})

    @field_validator("model")
    @classmethod
    def supported_model(cls, value):
        if not value or len(value) > 200:
            raise ValueError("Choose a chat model.")
        return value

    @field_validator("output_limit")
    @classmethod
    def valid_output_limit(cls, value):
        if isinstance(value, int) and (value < 1 or value > 1_000_000):
            raise ValueError("Output Limit must be a positive number.")
        return value

    @field_validator("reasoning")
    @classmethod
    def valid_reasoning(cls, value):
        if value not in {"auto", "off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Choose a supported Reasoning value.")
        return value

    @field_validator("compatible_overrides")
    @classmethod
    def valid_compatible_overrides(cls, value):
        numeric = {"temperature": (0, 2), "top_p": (0, 1),
                   "frequency_penalty": (-2, 2), "presence_penalty": (-2, 2)}
        allowed = set(numeric) | {"seed", "stop", "reasoning_effort", "verbosity"}
        if set(value) - allowed:
            raise ValueError("Choose a supported Advanced Setting.")
        for name, entry in value.items():
            if entry is None:
                continue
            if name in numeric:
                low, high = numeric[name]
                if isinstance(entry, bool) or not isinstance(entry, (int, float)) or not low <= entry <= high or (name == "top_p" and entry == 0):
                    raise ValueError(f"Enter a valid {name} value.")
            elif name == "seed" and (isinstance(entry, bool) or not isinstance(entry, int) or not 0 <= entry <= 2_147_483_647):
                raise ValueError("Enter a valid Seed.")
            elif name == "stop" and (not isinstance(entry, list) or len(entry) > 16 or
                                      any(not isinstance(item, str) or not item or len(item) > 200 for item in entry)):
                raise ValueError("Enter valid Stop Sequences.")
            elif name == "reasoning_effort" and (not isinstance(entry, str) or entry not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}):
                raise ValueError("Choose a valid Reasoning Effort.")
            elif name == "verbosity" and (not isinstance(entry, str) or entry not in {"low", "medium", "high"}):
                raise ValueError("Choose a valid Verbosity.")
        return value

    @field_validator("key_id")
    @classmethod
    def valid_key_id(cls, value):
        if value and len(value) > 64:
            raise ValueError("Choose a saved API key.")
        if value:
            UUID(value)
        return value


def chronicle_routes(service: ChronicleService):
    router = APIRouter(prefix="/api")

    @router.get("/worlds/{world_id}/chronicles")
    def list_chronicles(world_id: UUID):
        try:
            return service.list_chronicles(str(world_id))
        except KeyError:
            raise HTTPException(404, "World not found.") from None

    @router.post("/worlds/{world_id}/chronicles", status_code=201)
    def create_chronicle(world_id: UUID):
        try:
            return service.create_chronicle(str(world_id))
        except KeyError:
            raise HTTPException(404, "World not found.") from None

    @router.get("/chronicles/{chronicle_id}")
    def get_chronicle(chronicle_id: UUID):
        try:
            return service.chronicle(str(chronicle_id))
        except KeyError:
            raise HTTPException(404, "Chronicle not found.") from None

    @router.patch("/chronicles/{chronicle_id}")
    def rename_chronicle(chronicle_id: UUID, value: RenameChronicle):
        try:
            return service.store.rename(str(chronicle_id), value.title)
        except KeyError:
            raise HTTPException(404, "Chronicle not found.") from None

    @router.delete("/chronicles/{chronicle_id}")
    def delete_chronicle(chronicle_id: UUID):
        try:
            service.delete_chronicle(str(chronicle_id))
        except KeyError:
            raise HTTPException(404, "Chronicle not found.") from None
        return {"deleted": True}

    @router.get("/chronicles/{chronicle_id}/messages")
    def messages(chronicle_id: UUID):
        try:
            return service.messages(str(chronicle_id))
        except KeyError:
            raise HTTPException(404, "Chronicle not found.") from None

    @router.post("/chronicles/{chronicle_id}/messages/stream")
    def stream_message(chronicle_id: UUID, value: NewMessage):
        try:
            result = service.start_generation(str(chronicle_id), str(value.request_id), value.text)
        except KeyError:
            raise HTTPException(404, "Chronicle not found.") from None
        return StreamingResponse(service.stream_events(str(chronicle_id), str(value.request_id), result["user_message"]),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.post("/chronicles/{chronicle_id}/generations/{request_id}/stop")
    def stop_generation(chronicle_id: UUID, request_id: UUID):
        try:
            return service.stop_generation(str(chronicle_id), str(request_id))
        except KeyError:
            raise HTTPException(404, "Generation not found.") from None

    @router.get("/chronicle-settings")
    def get_settings():
        return service.store.settings()

    @router.put("/chronicle-settings")
    def save_settings(value: ChronicleSettings):
        return service.store.save_settings(value.model_dump())

    return router
