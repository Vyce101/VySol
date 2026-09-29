"""HTTP routes for Embedding Profiles and World vector bindings."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .creation_store import CreationConflict
from .embedding_profiles import EmbeddingProfileService
from .embeddings import EmbeddingFailure


class EmbeddingProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    key_id: UUID
    model: str = Field(min_length=1, max_length=200)
    dimensions: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Give the Embedding Profile a name.")
        return value.strip()

    @field_validator("model")
    @classmethod
    def model_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Choose an embedding model from the selected connection.")
        return value.strip()


class DefaultProfile(BaseModel):
    profile_id: UUID | None = None


class WorldEmbeddingProfile(BaseModel):
    profile_id: UUID


def embedding_profile_routes(service: EmbeddingProfileService):
    router = APIRouter(prefix="/api")

    @router.get("/embedding-profiles")
    def list_profiles():
        return service.list()

    @router.post("/embedding-profiles")
    def create_profile(value: EmbeddingProfileInput):
        try:
            return service.save(None, value.name, str(value.key_id), value.model, value.dimensions)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except CreationConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.put("/embedding-profiles/default")
    def set_default(value: DefaultProfile):
        try:
            return service.set_default(str(value.profile_id) if value.profile_id else None)
        except KeyError:
            raise HTTPException(404, "Embedding Profile not found.") from None

    @router.put("/embedding-profiles/{profile_id}")
    def update_profile(profile_id: UUID, value: EmbeddingProfileInput):
        try:
            return service.save(str(profile_id), value.name, str(value.key_id), value.model, value.dimensions)
        except KeyError:
            raise HTTPException(404, "Embedding Profile not found.") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except CreationConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/embedding-profiles/{profile_id}/preflight")
    def preflight(profile_id: UUID):
        try:
            return service.preflight(str(profile_id))
        except KeyError:
            raise HTTPException(404, "Embedding Profile not found.") from None
        except EmbeddingFailure as exc:
            raise HTTPException(502, str(exc)) from None
        except CreationConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.delete("/embedding-profiles/{profile_id}")
    def delete_profile(profile_id: UUID):
        try:
            return service.delete(str(profile_id))
        except KeyError:
            raise HTTPException(404, "Embedding Profile not found.") from None
        except CreationConflict as exc:
            raise HTTPException(409, str(exc)) from None

    @router.put("/worlds/{world_id}/embedding-profile")
    def rebind_world(world_id: UUID, value: WorldEmbeddingProfile):
        try:
            return service.rebind_world(str(world_id), str(value.profile_id))
        except FileNotFoundError:
            raise HTTPException(404, "World not found.") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except CreationConflict as exc:
            raise HTTPException(409, str(exc)) from None

    return router
