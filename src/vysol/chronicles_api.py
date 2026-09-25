"""HTTP endpoints for Chronicle lists, chat history, shared settings, and streamed turns."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .chronicles import CHAT_MODEL_IDS, ChronicleService


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
        if value not in CHAT_MODEL_IDS:
            raise ValueError("Choose a supported chat model.")
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
