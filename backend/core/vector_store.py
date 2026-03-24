"""ChromaDB PersistentClient wrapper for vector storage and retrieval."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from uuid import uuid4

import chromadb
from google import genai

from .atomic_json import dump_json_atomic
from .config import (
    get_world_embedding_model,
    get_world_embedding_provider,
    load_settings,
    resolve_slot_provider,
    set_world_embedding_model,
    set_world_ingest_settings,
    world_chroma_dir,
)
from .key_manager import classify_transient_provider_error, get_key_manager, jittered_delay

logger = logging.getLogger(__name__)


def _get_provider_key_manager(provider: str):
    try:
        return get_key_manager(provider)
    except TypeError:
        return get_key_manager()


class VectorStoreReadError(RuntimeError):
    """Raised when a vector collection could not be read safely."""


class VectorStore:
    """Wraps ChromaDB PersistentClient for a single world."""

    def __init__(
        self,
        world_id: str,
        embedding_model: str | None = None,
        embedding_provider: str | None = None,
        collection_suffix: str | None = None,
        *,
        collection_name_override: str | None = None,
        manage_manifest: bool = True,
    ):
        self.world_id = world_id
        self.embedding_provider = embedding_provider or get_world_embedding_provider(world_id)
        self.embedding_model = embedding_model or get_world_embedding_model(world_id)
        self.collection_suffix = collection_suffix
        self.manage_manifest = manage_manifest
        self.collection_key = str(collection_suffix or "chunks")
        self.collection_kind = self._infer_collection_kind(self.collection_key)
        chroma_path = str(world_chroma_dir(world_id))
        self.client = chromadb.PersistentClient(path=chroma_path)
        self._embed_clients: dict[str, genai.Client] = {}
        base_name = f"world_{world_id.replace('-', '_')}"
        collection_name = (
            str(collection_name_override)
            if collection_name_override
            else (f"{base_name}_{collection_suffix}" if collection_suffix else base_name)
        )
        self.collection_name = collection_name
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def _infer_collection_kind(self, collection_key: str) -> str:
        if collection_key == "nodes":
            return "node"
        if collection_key == "unique_nodes":
            return "unique node"
        if collection_key == "entities":
            return "entity"
        return "chunk"

    def _manifest_path(self) -> Path:
        return Path(world_chroma_dir(self.world_id)) / "collections_manifest.json"

    def _load_manifest(self) -> dict:
        path = self._manifest_path()
        if not path.exists():
            return {"collections": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"collections": {}}
        if not isinstance(data, dict):
            return {"collections": {}}
        collections = data.get("collections")
        if not isinstance(collections, dict):
            data["collections"] = {}
        return data

    def _save_manifest(self, manifest: dict) -> None:
        path = self._manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        dump_json_atomic(path, manifest)

    def _get_manifest_entry(self) -> dict:
        manifest = self._load_manifest()
        entry = manifest.get("collections", {}).get(self.collection_key, {})
        return entry if isinstance(entry, dict) else {}

    def recorded_embedding_model(self) -> str | None:
        entry = self._get_manifest_entry()
        model = entry.get("embedding_model")
        return str(model) if model else None

    def recorded_embedding_provider(self) -> str | None:
        entry = self._get_manifest_entry()
        provider = entry.get("embedding_provider")
        return str(provider) if provider else None

    def _set_recorded_embedding_model(self, embedding_model: str) -> None:
        if not self.manage_manifest:
            return
        manifest = self._load_manifest()
        collections = manifest.setdefault("collections", {})
        collections[self.collection_key] = {
            "embedding_provider": str(self.embedding_provider),
            "embedding_model": str(embedding_model),
            "collection_name": self.collection_name,
        }
        self._save_manifest(manifest)

    def _clear_recorded_embedding_model(self) -> None:
        if not self.manage_manifest:
            return
        manifest = self._load_manifest()
        collections = manifest.setdefault("collections", {})
        if self.collection_key in collections:
            del collections[self.collection_key]
            self._save_manifest(manifest)

    def _rebuild_required_message(self) -> str:
        return (
            f"This world's {self.collection_kind} embeddings were built with a different embedding model or provider. "
            "Use Re-embed All or Rechunk And Re-ingest to rebuild chunk and node vectors with the current embedding backend."
        )

    def _ensure_collection_model_matches(self) -> None:
        recorded_provider = self.recorded_embedding_provider()
        recorded_model = self.recorded_embedding_model()
        if recorded_provider and recorded_provider != self.embedding_provider:
            raise RuntimeError(self._rebuild_required_message())
        if recorded_model and recorded_model != self.embedding_model:
            raise RuntimeError(self._rebuild_required_message())

    def _get_embed_client(self, api_key: str) -> genai.Client:
        client = self._embed_clients.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            self._embed_clients[api_key] = client
        return client

    def _candidate_embedding_models(self) -> list[str]:
        if self.embedding_provider != "gemini":
            return [self.embedding_model]
        settings_model = load_settings().get("embedding_model")

        candidates: list[str] = [self.embedding_model]
        if settings_model and settings_model not in candidates:
            candidates.append(settings_model)

        # Compatibility aliases for older model IDs.
        if self.embedding_model == "models/text-embedding-004":
            for alias in ("gemini-embedding-001", "models/gemini-embedding-001"):
                if alias not in candidates:
                    candidates.append(alias)
        return candidates

    def _record_effective_embedding_model(self, candidates: list[str], model_name: str) -> None:
        if model_name != self.embedding_model:
            self.embedding_model = model_name
            set_world_ingest_settings(
                self.world_id,
                {
                    "embedding_provider": self.embedding_provider,
                    "embedding_model": model_name,
                },
                lock=False,
                touch=False,
            )
            logger.warning(
                "Switched embedding model for world %s from %s to %s",
                self.world_id,
                candidates[0],
                model_name,
            )

    def _lookup_key_index(self, api_key: str, used_indices: set[int]) -> int | None:
        key_manager = _get_provider_key_manager(self.embedding_provider)
        for index, configured_key in enumerate(key_manager.api_keys):
            if configured_key == api_key and index not in used_indices:
                return index
        return None

    def embed_texts(self, texts: list[str], api_key: str) -> list[list[float]]:
        """Embed one or more texts using the configured embedding provider."""
        if not texts:
            return []
        if self.embedding_provider != "gemini":
            raise RuntimeError(
                f"{self.embedding_provider} is selected for embeddings, but this build only supports Gemini embeddings right now."
            )

        candidates = self._candidate_embedding_models()
        last_error: Exception | None = None
        key_manager = _get_provider_key_manager(self.embedding_provider)
        current_api_key = api_key
        current_key_index = self._lookup_key_index(current_api_key, set())
        used_key_indices: set[int] = set()
        max_key_attempts = max(3, key_manager.key_count * 2)

        for attempt in range(max_key_attempts):
            client = self._get_embed_client(current_api_key)
            rotate_key = False

            for model_name in candidates:
                try:
                    payload: str | list[str] = texts if len(texts) > 1 else texts[0]
                    result = client.models.embed_content(model=model_name, contents=payload)
                    embeddings = [list(item.values) for item in (result.embeddings or [])]
                    if len(embeddings) != len(texts):
                        raise RuntimeError(
                            f"Embedding API returned {len(embeddings)} embeddings for {len(texts)} texts."
                        )
                    self._record_effective_embedding_model(candidates, model_name)
                    return embeddings
                except Exception as e:
                    last_error = e
                    message = str(e).lower()
                    transient_kind = classify_transient_provider_error(e)

                    if transient_kind and current_key_index is not None:
                        used_key_indices.add(current_key_index)
                        key_manager.report_error(current_key_index, transient_kind)
                        current_api_key, current_key_index = key_manager.wait_for_available_key()
                        rotate_key = True
                        break

                    if ("not found" in message or "not supported" in message) and model_name != candidates[-1]:
                        continue
                    rotate_key = False
                    break

            if rotate_key:
                if attempt < max_key_attempts - 1:
                    time.sleep(jittered_delay(0.5))
                continue
            break

        if last_error:
            raise last_error
        raise RuntimeError("Embedding generation failed with no model candidates.")

    def embed_text(self, text: str, api_key: str) -> list[float]:
        """Embed a single text using Google's embedding model."""
        return self.embed_texts([text], api_key=api_key)[0]

    def upsert_document(
        self,
        document_id: str,
        text: str,
        metadata: dict,
        api_key: str,
    ) -> None:
        """Embed and upsert a single document. Idempotent."""
        embedding = self.embed_text(text, api_key)
        self.upsert_document_embedding(
            document_id=document_id,
            text=text,
            metadata=metadata,
            embedding=embedding,
        )

    def upsert_document_embedding(
        self,
        *,
        document_id: str,
        text: str,
        metadata: dict,
        embedding: list[float],
    ) -> None:
        """Upsert a single document with a precomputed embedding."""
        self.collection.upsert(
            ids=[document_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )
        self._set_recorded_embedding_model(self.embedding_model)

    def upsert_documents_embeddings(
        self,
        *,
        document_ids: list[str],
        texts: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """Upsert multiple documents with precomputed embeddings."""
        if not document_ids:
            return
        if not (len(document_ids) == len(texts) == len(metadatas) == len(embeddings)):
            raise ValueError("Document ids, texts, metadatas, and embeddings must have matching lengths.")
        self.collection.upsert(
            ids=document_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        self._set_recorded_embedding_model(self.embedding_model)

    def upsert_chunk(
        self,
        chunk_id: str,
        prefixed_text: str,
        metadata: dict,
        api_key: str,
    ) -> None:
        """Embed and upsert a single chunk. Idempotent."""
        self.upsert_document(chunk_id, prefixed_text, metadata, api_key)

    def upsert_node(
        self,
        node_id: str,
        node_text: str,
        metadata: dict,
        api_key: str,
    ) -> None:
        """Embed and upsert a single node. Idempotent."""
        self.upsert_document(node_id, node_text, metadata, api_key)

    def query_by_embedding(self, query_embedding: list[float], n_results: int = 5) -> list[dict]:
        """Query the collection using a precomputed embedding."""
        self._ensure_collection_model_matches()
        collection_count = self.collection.count()
        if collection_count <= 0:
            return []

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results, collection_count),
            )
        except Exception as e:
            message = str(e).lower()
            if "dimension" in message:
                raise RuntimeError(self._rebuild_required_message()) from e
            raise
        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            output.append({
                "id": doc_id,
                "document": results["documents"][0][i] if results.get("documents") else "",
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                "distance": results["distances"][0][i] if results.get("distances") else 0.0,
            })
        return output

    def query(self, query_text: str, api_key: str, n_results: int = 5) -> list[dict]:
        """Query the collection with text. Returns list of results."""
        embedding = self.embed_text(query_text, api_key)
        return self.query_by_embedding(embedding, n_results=n_results)

    def drop_collection(self) -> None:
        """Delete and recreate the collection."""
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        self._clear_recorded_embedding_model()

    def delete_collection(self) -> None:
        """Delete the collection without recreating it."""
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        self._clear_recorded_embedding_model()

    def create_staging_store(self) -> VectorStore:
        """Create a temporary collection for staged rebuilds."""
        staging_name = f"{self.collection_name}__staging_{uuid4().hex}"
        return VectorStore(
            self.world_id,
            embedding_model=self.embedding_model,
            embedding_provider=self.embedding_provider,
            collection_suffix=self.collection_suffix,
            collection_name_override=staging_name,
            manage_manifest=False,
        )

    def swap_staged_collection(self, staged_store: VectorStore) -> None:
        """Swap a fully built staging collection into the live collection name."""
        backup_name = f"{self.collection_name}__backup_{uuid4().hex}"
        live_name = self.collection_name
        staged_name = staged_store.collection_name

        self.collection.modify(name=backup_name)
        self.collection_name = backup_name
        self.collection = self.client.get_or_create_collection(name=backup_name)

        try:
            staged_store.collection.modify(name=live_name)
            staged_store.collection_name = live_name
            staged_store.collection = staged_store.client.get_or_create_collection(name=live_name)
        except Exception:
            self.collection.modify(name=live_name)
            self.collection_name = live_name
            self.collection = self.client.get_or_create_collection(name=live_name)
            raise

        self.collection_name = live_name
        self.collection = self.client.get_or_create_collection(name=live_name)
        self._set_recorded_embedding_model(staged_store.embedding_model)

        try:
            self.client.delete_collection(name=backup_name)
        except Exception:
            pass

    def count(self) -> int:
        return self.collection.count()

    def get_all_records(self, *, include_documents: bool = False, raise_on_error: bool = False) -> list[dict]:
        """Return all stored ids with optional documents and metadata."""
        include: list[str] = ["metadatas"]
        if include_documents:
            include.append("documents")
        try:
            data = self.collection.get(include=include)
        except Exception as exc:
            if raise_on_error:
                raise VectorStoreReadError(
                    f"Unable to read collection '{self.collection_name}'."
                ) from exc
            return []

        ids = data.get("ids") or []
        metas = data.get("metadatas") or []
        docs = data.get("documents") or []
        output: list[dict] = []
        for i, record_id in enumerate(ids):
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            row = {"id": str(record_id), "metadata": meta}
            if include_documents:
                row["document"] = docs[i] if i < len(docs) else ""
            output.append(row)
        return output

    def get_all_chunk_records(self, *, raise_on_error: bool = False) -> list[dict]:
        """Return all chunk ids with metadata for ingestion audits/retries."""
        return self.get_all_records(include_documents=False, raise_on_error=raise_on_error)

    def get_records_by_ids(
        self,
        document_ids: list[str],
        *,
        include_documents: bool = False,
        include_embeddings: bool = False,
        raise_on_error: bool = False,
    ) -> list[dict]:
        """Return specific stored ids with optional documents and embeddings."""
        normalized_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
        if not normalized_ids:
            return []

        include: list[str] = ["metadatas"]
        if include_documents:
            include.append("documents")
        if include_embeddings:
            include.append("embeddings")

        try:
            data = self.collection.get(ids=normalized_ids, include=include)
        except Exception as exc:
            if raise_on_error:
                raise VectorStoreReadError(
                    f"Unable to read collection '{self.collection_name}'."
                ) from exc
            return []

        ids = data.get("ids")
        metas = data.get("metadatas")
        docs = data.get("documents")
        embeddings = data.get("embeddings")
        if ids is None:
            ids = []
        if metas is None:
            metas = []
        if docs is None:
            docs = []
        if embeddings is None:
            embeddings = []
        output: list[dict] = []
        for i, record_id in enumerate(ids):
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            row = {"id": str(record_id), "metadata": meta}
            if include_documents:
                row["document"] = docs[i] if i < len(docs) else ""
            if include_embeddings:
                raw_embedding = embeddings[i] if i < len(embeddings) else []
                row["embedding"] = list(raw_embedding) if raw_embedding is not None else []
            output.append(row)
        return output

    def upsert_records(self, records: list[dict]) -> None:
        """Upsert precomputed document records including embeddings."""
        document_ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        embeddings: list[list[float]] = []

        for record in records:
            document_id = str(record.get("id") or "").strip()
            if not document_id:
                continue
            document_ids.append(document_id)
            documents.append(str(record.get("document") or ""))
            metadata = record.get("metadata")
            metadatas.append(metadata if isinstance(metadata, dict) else {})
            raw_embedding = record.get("embedding") or []
            embeddings.append(list(raw_embedding))

        if not document_ids:
            return

        self.collection.upsert(
            ids=document_ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        self._set_recorded_embedding_model(self.embedding_model)

    def has_chunk(self, chunk_id: str) -> bool:
        """Check whether a specific chunk id exists in the vector collection."""
        return self.has_document(chunk_id)

    def has_document(self, document_id: str) -> bool:
        """Check whether a specific document id exists in the vector collection."""
        try:
            data = self.collection.get(ids=[document_id], include=[])
            ids = data.get("ids") or []
            return bool(ids)
        except Exception:
            return False

    def delete_document(self, document_id: str) -> None:
        """Delete a single document by id if it exists."""
        self.delete_documents([document_id])

    def delete_documents(self, document_ids: list[str]) -> None:
        """Delete one or more documents by id."""
        normalized_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
        if not normalized_ids:
            return
        self.collection.delete(ids=normalized_ids)
