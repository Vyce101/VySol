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
