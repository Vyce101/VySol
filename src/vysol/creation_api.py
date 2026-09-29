"""Local HTTP contracts for creation attempts and named provider credentials."""

from typing import Literal
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from .creation import Creation
from .chronicles import CHAT_MODELS
from .creation_store import CreationConflict
from .embeddings import MODEL, MODELS
from .provider_profiles import preview_chat_models
from .provider_catalog import ProviderCatalog


PROVIDERS = ("google", "openai", "anthropic", "deepseek", "openai_compatible")


class Configuration(BaseModel):
    model: Literal[MODEL] = MODEL
    size: int = Field(default=8000, ge=1, le=1_000_000)
    search: int = Field(default=1000, ge=0)

    @model_validator(mode="after")
    def boundaries(self):
        if self.search >= self.size:
            raise ValueError("Boundary search must be smaller than chunk size.")
        return self


class BookSelection(BaseModel):
    id: UUID
    filename: str
    size: int = Field(ge=0)


class Manifest(BaseModel):
    operation_id: UUID
    revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=200)
    embedding_profile_id: UUID | None = None
    key_id: UUID | None = None
    config: Configuration
    books: list[BookSelection] = Field(min_length=1, max_length=1000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Give your world a name.")
        return value.strip()

    @model_validator(mode="after")
    def unique_ids(self):
        if self.embedding_profile_id is None and self.key_id is None:
            raise ValueError("Choose an Embedding Profile before creating this World.")
        if len({book.id for book in self.books}) != len(self.books):
            raise ValueError("Each selected book must have its own identifier.")
        return self


class Revision(BaseModel):
    revision: int = Field(ge=0)


class Start(Revision):
    operation_id: UUID


class ProviderKey(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["google", "openai", "anthropic", "deepseek", "openai_compatible"] = "google"
    connection_id: UUID | None = None
    base_url: str | None = Field(default=None, max_length=500)
    secret: SecretStr | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Give the key a name.")
        return value.strip()


class ProviderConnection(BaseModel):
    provider: Literal["google", "openai", "anthropic", "deepseek", "openai_compatible"]


class ProviderConnectionState(BaseModel):
    enabled: bool


def creation_routes(creation: Creation, catalog_client=None):
    router = APIRouter(prefix="/api")
    catalog_service = ProviderCatalog(creation.store, creation.vault, creation.logger, client=catalog_client)
    creation.provider_catalog = catalog_service

    @router.get("/creation")
    def current():
        return creation.store.public(creation.store.get())

    @router.get("/creations")
    def all_current():
        return [creation.store.public(value) for value in creation.store.pending()]

    @router.get("/creation/{attempt_id}")
    def status(attempt_id: UUID):
        value = creation.store.get(str(attempt_id))
        if not value:
            raise HTTPException(404, "Creation attempt not found.")
        return creation.store.public(value)

    @router.put("/creation/{attempt_id}")
    def save(attempt_id: UUID, value: Manifest):
        return creation.save(str(attempt_id), value.model_dump(mode="json"))

    @router.put("/creation/{attempt_id}/books/{book_id}")
    async def upload(attempt_id: UUID, book_id: UUID, revision: int, operation_id: UUID, request: Request):
        content = bytearray()
        try:
            async for piece in request.stream():
                if len(content) + len(piece) > creation.limits.max_upload_bytes:
                    await run_in_threadpool(creation.upload_failed, str(attempt_id), str(book_id), revision,
                                            "This book exceeds the upload limit. Discard this attempt and start again with a smaller file.")
                    raise HTTPException(413, "This book exceeds the upload limit.")
                content.extend(piece)
        except ClientDisconnect:
            await run_in_threadpool(creation.upload_failed, str(attempt_id), str(book_id), revision,
                                    "The upload was interrupted. Resume to retry, or discard and start again if its file is unavailable.")
            raise HTTPException(409, "The upload was interrupted.") from None
        return await run_in_threadpool(creation.upload, str(attempt_id), str(book_id), revision,
                                       str(operation_id), unquote(request.headers.get("x-filename", "")), bytes(content))

    @router.post("/creation/{attempt_id}/start")
    def start(attempt_id: UUID, value: Start):
        return creation.start(str(attempt_id), value.revision, str(value.operation_id))

    @router.post("/creation/{attempt_id}/pause")
    def pause(attempt_id: UUID, value: Revision):
        return creation.pause(str(attempt_id), value.revision)

    @router.delete("/creation/{attempt_id}")
    def discard(attempt_id: UUID, revision: int):
        creation.discard(str(attempt_id), revision)
        return {"discarded": True}

    @router.get("/providers")
    def providers():
        defaults = creation.store.defaults()
        profile_list = creation.embedding_profiles.list()
        defaults["embedding_profile_id"] = (profile_list.get("last_used_profile_id")
                                               or profile_list.get("default_profile_id"))
        return {"keys": creation.store.keys(), "connections": creation.store.connections(),
                "models": MODELS, "chat_models": CHAT_MODELS,
                "preview_chat_models": preview_chat_models(), "defaults": defaults}

    @router.get("/providers/keys/{key_id}/models")
    def credential_models(key_id: UUID):
        key = str(key_id)
        if creation.store.credential(key) is None:
            raise HTTPException(404, "AI credential not found.")
        result = creation.store.catalog(key)
        return {**result, "stale": creation.store.needs_catalog_refresh(key)}

    @router.post("/providers/keys/{key_id}/models/refresh")
    def refresh_credential_models(key_id: UUID):
        try:
            return catalog_service.refresh(str(key_id))
        except KeyError:
            raise HTTPException(404, "AI credential not found.") from None

    @router.post("/providers/connections")
    def add_provider_connection(value: ProviderConnection):
        return creation.store.add_connection(value.provider)

    @router.put("/providers/connections/{connection_id}")
    def update_provider_connection(connection_id: UUID, value: ProviderConnectionState):
        try:
            return creation.store.update_connection(str(connection_id), value.enabled)
        except KeyError:
            raise HTTPException(404, "AI connection not found.") from None

    @router.get("/providers/keys/{key_id}/secret")
    def reveal_key(key_id: UUID):
        key = str(key_id)
        if not any(item["id"] == key for item in creation.store.keys()):
            raise HTTPException(404, "API key not found.")
        secret = creation.vault.read(key)
        if not secret:
            raise HTTPException(404, "Saved API key secret not found.")
        return JSONResponse({"secret": secret}, headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        })

    def ensure_key_mutable(key_id):
        if creation.store.credential_busy(key_id):
            raise CreationConflict("Pause world creation before changing its API credential.")

    @router.put("/providers/keys/{key_id}")
    def save_key(key_id: UUID, value: ProviderKey):
        key = str(key_id)
        with creation.guard:
            ensure_key_mutable(key)
            prior = creation.store.credential(key)
            fields = value.model_fields_set
            provider = value.provider
            if prior and "provider" not in fields:
                provider = prior["provider"]
            connection_id = str(value.connection_id) if value.connection_id else None
            if prior and provider != prior["provider"]:
                raise HTTPException(422, "An AI credential cannot be moved to another provider.")
            if connection_id and not any(
                connection["id"] == connection_id and connection["provider"] == provider
                for connection in creation.store.connections()
            ):
                raise HTTPException(422, "The selected provider connection does not match this credential.")

            base_url = prior.get("base_url") if prior else None
            if provider == "openai_compatible":
                if value.base_url is not None:
                    try:
                        normalized = normalize_base_url(value.base_url)
                    except ValueError as exc:
                        raise HTTPException(422, str(exc)) from None
                    if base_url and normalized != base_url:
                        raise HTTPException(422, "The Base URL cannot be changed after this credential is created.")
                    base_url = normalized
                if not base_url:
                    raise HTTPException(422, "Enter a Base URL for this compatible connection.")
            elif value.base_url is not None:
                raise HTTPException(422, "Base URL is only available for OpenAI-compatible connections.")

            if value.secret is not None:
                secret = value.secret.get_secret_value().strip()
                if not secret or len(secret.encode("utf-16-le")) > 2560:
                    raise HTTPException(422, "Enter a valid API key.")
                creation.vault.write(key, secret)
            elif not prior and provider != "openai_compatible":
                raise HTTPException(422, "Enter an API key.")
            with creation.store.connect() as db:
                try:
                    result = creation.store.save_key(
                        db, key, value.name, provider, connection_id, base_url,
                    )
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from None
        creation.logger.info("Provider credential saved provider=%s key_id=%s", provider, key)
        should_discover = ((prior is None and "provider" in value.model_fields_set)
                           or (prior is not None and value.secret is not None))
        if should_discover:
            catalog_result = catalog_service.refresh(key)
        else:
            catalog_result = creation.store.catalog(key)
        return {**result, **catalog_result}

    @router.delete("/providers/keys/{key_id}")
    def delete_key(key_id: UUID):
        key = str(key_id)
        with creation.guard:
            ensure_key_mutable(key)
            if creation.store.credential(key) is None:
                raise HTTPException(404, "AI credential not found.")
            if creation.store.credential_used(key):
                raise CreationConflict("Update any referenced Embedding Profiles to use another compatible credential and finish or discard saved creations before deleting this credential.")
            creation.vault.delete(key)
            with creation.store.connect() as db:
                db.execute("DELETE FROM provider_keys WHERE id=?", (key,))
        creation.logger.info("Provider credential deleted key_id=%s", key)
        return {"deleted": True}

    return router


def normalize_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Enter a valid HTTP or HTTPS Base URL without a key, query, or fragment.")
    try:
        parsed.port
    except ValueError:
        raise ValueError("Enter a valid HTTP or HTTPS Base URL.") from None
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
