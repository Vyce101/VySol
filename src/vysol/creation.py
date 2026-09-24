"""Resumable per-world creation workers, publishing only complete immutable worlds."""

import hashlib
import json
import logging
from pathlib import Path
import shutil
import threading
from uuid import UUID

from filelock import FileLock

from .books import ImportLimits, Upload
from .books.models import ImportFailure
from .books.storage import validate_upload, safe_directory, CONVERTER_VERSION
from .books.text import decode_text
from .books.epub import extract_epub
from .books.chunking import split_text
from .creation_store import CreationStore, CreationConflict, now
from .embeddings import GeminiEmbeddings, EmbeddingFailure, InputTooLarge, ProcessingPaused
from .worlds import WorldStore, atomic_json


BUSY = {"running", "pausing"}


class Creation:
    def __init__(self, root: Path, vault, embedder=None, limits=None):
        self.root = root
        self.store = CreationStore(root)
        self.worlds = WorldStore(root)
        self.vault = vault
        self.embedder = embedder or GeminiEmbeddings()
        self.limits = limits or ImportLimits()
        self.guard = threading.RLock()
        self.stops = {}
        self.threads = {}
        self.discarding = set()
        # Keep the most recently started worker available to older callers.
        self.stop = threading.Event()
        self.thread = None
        self.lease = FileLock(root / "locks" / "creation-worker.lock", timeout=0)
        self.logger = logging.getLogger("vysol.creation")

    def start_service(self, logger):
        self.lease.acquire()
        self.logger = logger
        try:
            for value in self.store.pending():
                if self.reconcile(value):
                    continue
                if value["state"] in BUSY:
                    self.store.update(value["id"], state="paused", message="Processing paused when VySol stopped.")
                    logger.info("Creation recovered as paused attempt_id=%s", value["id"])
        except BaseException:
            self.lease.release()
            raise

    def close(self):
        with self.guard:
            stops = list(self.stops.values())
            threads = list(self.threads.values())
            for stop in stops:
                stop.set()
        for thread in threads:
            thread.join()
        self.lease.release()

    def directory(self, attempt_id: str) -> Path:
        UUID(attempt_id)
        return safe_directory(self.root, "creations", attempt_id)

    def book_directory(self, attempt_id: str, book_id: str) -> Path:
        UUID(book_id)
        return safe_directory(self.root, "creations", attempt_id, "books", book_id)

    def require(self, attempt_id, revision=None, editable=False, db=None):
        if attempt_id in self.discarding:
            raise CreationConflict("The previous attempt is being discarded. Try again shortly.")
        value = self.store.get(attempt_id, db=db)
        if value is None:
            raise CreationConflict("This creation attempt no longer exists.")
        if value["state"] == "complete":
            raise CreationConflict("This world is accepted. Its books and order are fixed.")
        if revision is not None and value["revision"] != revision:
            raise CreationConflict("This attempt changed. Reload its saved progress before continuing.")
        if editable and value["state"] in BUSY:
            raise CreationConflict("Pause processing before changing this attempt.")
        return value

    def save(self, attempt_id: str, manifest: dict):
        with self.guard, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self.store.get(attempt_id, db=db)
            payload = dict(manifest)
            command_id = payload.pop("operation_id")
            if existing:
                if not self.store.command(db, attempt_id, command_id, payload):
                    return self.store.public(existing)
                raise CreationConflict("Submitted attempts cannot be edited. Discard this attempt and start again.")
            if manifest["revision"] != 0:
                raise CreationConflict("This creation attempt no longer exists.")
            if not self.store.enabled_key(manifest["key_id"], db=db):
                raise CreationConflict("Choose a saved API key from an enabled connection before creating a world.")
            value = {"id": attempt_id, "created_at": now(), "revision": 0, "state": "paused", "books": []}
            self.store.put(db, value)
            self.store.command(db, attempt_id, command_id, payload)
            books = []
            comparisons = set()
            for position, incoming in enumerate(manifest["books"], 1):
                comparison, _ = validate_upload(Upload(incoming["filename"], b""))
                if comparison in comparisons:
                    raise CreationConflict("Two selected books have the same name. Remove or rename one.")
                comparisons.add(comparison)
                books.append({**incoming, "position": position, "uploaded": False, "state": "waiting", "message": ""})
            value.update(name=manifest["name"], config=manifest["config"], key_id=manifest["key_id"],
                         books=books, state="paused", phase="uploading", message="", revision=value["revision"] + 1)
            self.store.put(db, value)
        return self.store.public(value)

    def upload(self, attempt_id, book_id, revision, operation_id, filename, content):
        digest = hashlib.sha256(content).hexdigest()
        with self.guard, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.require(attempt_id, editable=True, db=db)
            if not self.store.command(db, attempt_id, operation_id,
                                      {"book": book_id, "filename": filename, "digest": digest, "revision": revision}):
                return self.store.public(value)
            self.require(attempt_id, revision, True, db)
            book = next((b for b in value["books"] if b["id"] == book_id), None)
            if not book or filename != book["filename"]:
                raise CreationConflict("This file does not match the selected book.")
            if book["uploaded"]:
                if book["digest"] != digest:
                    raise CreationConflict("Submitted books cannot be replaced. Discard this attempt and start again.")
                return self.store.public(value)
            validate_upload(Upload(filename, content))
            if len(content) > self.limits.max_upload_bytes:
                raise CreationConflict("This book exceeds the upload limit.")
            folder = self.book_directory(attempt_id, book_id)
            temporary = folder / "upload.tmp"
            temporary.write_bytes(content)
            temporary.replace(folder / "source")
            db.execute("DELETE FROM chunks WHERE world_id=? AND book_id=?", (attempt_id, book_id))
            book.update(uploaded=True, digest=digest, size=len(content), state="uploaded", message="", chunked=False)
            value["revision"] += 1
            self.store.put(db, value)
        return self.store.public(value)

    def upload_failed(self, attempt_id, book_id, revision, message):
        with self.guard, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.store.get(attempt_id, db=db)
            if not value or value["state"] in BUSY or value["state"] == "complete" or value["revision"] != revision:
                return
            book = next((book for book in value["books"] if book["id"] == book_id), None)
            if not book or book["uploaded"]:
                return
            book.update(state="failed", message=message)
            value.update(state="failed", message="Some uploads need attention. Resume to retry available files, or discard and start again.")
            self.store.put(db, value)
        self.logger.warning("Book upload failed attempt_id=%s book_id=%s", attempt_id, book_id)

    def start(self, attempt_id, revision, operation_id):
        with self.guard:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = self.store.get(attempt_id, db=db)
                if not existing:
                    raise CreationConflict("This attempt no longer exists.")
                if not self.store.command(db, attempt_id, operation_id, {"action": "start", "revision": revision}):
                    return self.store.public(existing)
                value = self.require(attempt_id, revision, True, db)
                active_thread = self.threads.get(attempt_id)
                if active_thread and active_thread.is_alive():
                    raise CreationConflict("This world is still stopping. Try again shortly.")
                if not all(b["uploaded"] for b in value["books"]):
                    raise CreationConflict("Some uploads are missing. Discard this attempt and start again if the files are no longer available.")
                if not any(key["id"] == value["key_id"] for key in self.store.keys()) or not self.vault.read(value["key_id"]):
                    raise CreationConflict("The selected API key is unavailable. Restore its secret in Providers, or discard this attempt and start again.")
                value.update(state="running", message="", revision=value["revision"] + 1)
                self.store.put(db, value)
                db.execute("INSERT INTO preferences VALUES('processing',?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                           (json.dumps({"model": value["config"]["model"], "key_id": value["key_id"]}),))
            stop = threading.Event()
            thread = threading.Thread(target=self.run, args=(attempt_id, stop),
                                      name=f"world-creation-{attempt_id[:8]}", daemon=True)
            self.stops[attempt_id] = stop
            self.threads[attempt_id] = thread
            self.stop = stop
            self.thread = thread
            thread.start()
        self.logger.info("Creation started attempt_id=%s", attempt_id)
        return self.store.public(value)

    def pause(self, attempt_id, revision):
        with self.guard:
            value = self.require(attempt_id, revision)
            if value["state"] in BUSY:
                self.store.update(attempt_id, state="pausing", revision=value["revision"] + 1)
                stop = self.stops.get(attempt_id)
                if stop:
                    stop.set()
            return self.store.public(self.store.get(attempt_id))

    def discard(self, attempt_id, revision):
        with self.guard:
            self.require(attempt_id, revision)
            self.discarding.add(attempt_id)
            stop = self.stops.get(attempt_id)
            if stop:
                stop.set()
            thread = self.threads.get(attempt_id)
        try:
            if thread:
                thread.join()
            with self.guard:
                value = self.store.get(attempt_id)
                if self.reconcile(value):
                    raise CreationConflict("Creation completed before discard. The accepted world was retained.")
                folder = self.directory(attempt_id).resolve()
                expected = (self.root / "creations").resolve()
                if not folder.is_relative_to(expected) or folder == expected:
                    raise OSError("Invalid creation path.")
                shutil.rmtree(folder)
                with self.store.connect() as db:
                    db.execute("DELETE FROM attempts WHERE id=?", (attempt_id,))
        finally:
            with self.guard:
                self.discarding.discard(attempt_id)
                self.stops.pop(attempt_id, None)
                self.threads.pop(attempt_id, None)
        self.logger.info("Creation discarded attempt_id=%s", attempt_id)

    def check_stop(self, stop):
        if stop.is_set():
            raise ProcessingPaused()

    def reconcile(self, value):
        try:
            world = self.worlds.get(value["id"])
        except FileNotFoundError:
            return False
        if world.get("creation_id") != value["id"]:
            raise CreationConflict("The world destination is already occupied.")
        self.store.update(value["id"], state="complete", phase="complete", message="Your world is ready.")
        return True

    def run(self, attempt_id, stop):
        current_book = None
        try:
            value = self.store.get(attempt_id)
            if self.reconcile(value):
                return
            failed = False
            self.store.update(attempt_id, phase="preparing")
            for book in value["books"]:
                self.check_stop(stop)
                current_book = book["id"]
                try:
                    folder = self.book_directory(attempt_id, current_book)
                    content = (folder / "source").read_bytes()
                    if hashlib.sha256(content).hexdigest() != book["digest"]:
                        raise EmbeddingFailure("source_changed", "The saved upload changed. Discard this attempt and start again with a corrected book.")
                    if book.get("chunked"):
                        continue
                    self.store.update_book(attempt_id, current_book, state="converting", message="")
                    text = decode_text(content) if book["filename"].lower().endswith(".txt") else extract_epub(content, self.limits)
                    if not text.strip():
                        raise EmbeddingFailure("empty_book", "This book contains no readable text. Discard this attempt and start again with a readable book.")
                    (folder / "text").write_bytes(text.encode("utf-8"))
                    self.store.update_book(attempt_id, current_book, state="chunking")
                    # A terminated split is safe to repeat; chunk IDs are deterministic.
                    self.store.add_chunks(attempt_id, current_book,
                                          split_text(text, value["config"]["size"], value["config"]["search"]), value["config"])
                    self.store.update_book(attempt_id, current_book, state="prepared", chunked=True,
                                           text_digest=hashlib.sha256(text.encode("utf-8")).hexdigest())
                except (ImportFailure, EmbeddingFailure) as exc:
                    failed = True
                    self.store.update_book(attempt_id, current_book, state="failed", message=str(exc))
                    self.logger.warning("Book preparation failed attempt_id=%s book_id=%s", attempt_id, current_book)
            if failed:
                raise EmbeddingFailure("preparation_failed", "Some books need attention. No books have been accepted.")
            self.store.update(attempt_id, phase="embedding")
            secret = self.vault.read(value["key_id"])
            if not secret:
                raise EmbeddingFailure("credentials", "The selected API key is missing. Restore it in Providers, or discard this attempt and start again.")
            for book in value["books"]:
                current_book = book["id"]
                self.check_stop(stop)
                self.store.update_book(attempt_id, current_book, state="embedding", message="")
                while chunk := self.store.pending_chunk(attempt_id, current_book):
                    self.check_stop(stop)
                    try:
                        vector = self.embedder.embed(chunk["text"], secret, stop, self.logger)
                        self.store.save_vector(chunk["id"], vector)
                    except InputTooLarge:
                        size = len(chunk["text"]) // 2
                        if size < 1:
                            raise EmbeddingFailure("input_limit", "Google rejected even the smallest text slice. Retry later.") from None
                        self.store.add_chunks(attempt_id, current_book,
                                              split_text(chunk["text"], size, min(value["config"]["search"], size - 1),
                                                         offset=chunk["start"]), value["config"], replace_id=chunk["id"])
                        self.logger.warning("Oversized chunk split attempt_id=%s book_id=%s", attempt_id, current_book)
                self.store.update_book(attempt_id, current_book, state="done")
            self.check_stop(stop)
            current_book = None
            self.publish(self.store.get(attempt_id), stop)
            self.logger.info("World creation succeeded attempt_id=%s", attempt_id)
        except ProcessingPaused:
            self.store.update(attempt_id, state="paused", message="Progress saved. Resume when you are ready.")
            self.logger.info("Creation paused attempt_id=%s", attempt_id)
        except Exception as exc:
            # A published world wins even if the final checkpoint failed.
            try:
                if self.reconcile(self.store.get(attempt_id)):
                    return
                message = str(exc) if isinstance(exc, EmbeddingFailure) else "Processing could not finish. Your saved progress is retained; try again."
                if current_book and not (isinstance(exc, EmbeddingFailure) and exc.code == "preparation_failed"):
                    self.store.update_book(attempt_id, current_book, state="failed", message=message)
                self.store.update(attempt_id, state="failed", message=message)
            finally:
                self.logger.error("Creation failed attempt_id=%s type=%s", attempt_id, type(exc).__name__)
        finally:
            with self.guard:
                if self.threads.get(attempt_id) is threading.current_thread():
                    self.threads.pop(attempt_id, None)
                    self.stops.pop(attempt_id, None)

    def publish(self, value, stop):
        with self.guard:
            self.check_stop(stop)
            self.store.update(value["id"], phase="publishing")
            prepared = self.directory(value["id"]) / "world"
            prepared.mkdir(exist_ok=True)
            world_books = prepared / "books"
            world_books.mkdir(exist_ok=True)
            # Recreate the prepared directory after an interrupted publication.
            for old in world_books.iterdir():
                if old.is_dir() and old.resolve().is_relative_to(prepared.resolve()):
                    shutil.rmtree(old)
            for book in value["books"]:
                self.check_stop(stop)
                comparison, text_name = validate_upload(Upload(book["filename"], b""))
                source = self.book_directory(value["id"], book["id"])
                self.verify_book(value["id"], book, source)
                destination = world_books / hashlib.sha256(comparison.encode()).hexdigest()
                (destination / "original").mkdir(parents=True)
                (destination / "text").mkdir()
                shutil.copyfile(source / "source", destination / "original" / book["filename"])
                shutil.copyfile(source / "text", destination / "text" / text_name)
                atomic_json(destination / "metadata.json", {"book_id": book["id"], "world_id": value["id"],
                            "original_filename": book["filename"], "text_filename": text_name,
                            "comparison_name": comparison, "position": book["position"],
                            "converter_version": CONVERTER_VERSION, "source_digest": book["digest"],
                            "text_digest": book["text_digest"]})
            atomic_json(prepared / "world.json", {"id": value["id"], "name": value["name"],
                        "created_at": now(), "last_used_at": None, "artwork": "frostwake",
                        "creation_id": value["id"], "sources_locked": True, "processing": value["config"]})
            destination = self.worlds.directory(value["id"])
            destination.parent.mkdir(exist_ok=True)
            prepared.rename(destination)
            self.store.update(value["id"], state="complete", phase="complete", message="Your world is ready.")

    def verify_book(self, attempt_id, book, folder):
        """Verify that published files and every vector refer to the same complete text."""
        for filename, expected in (("source", book["digest"]), ("text", book["text_digest"])):
            with (folder / filename).open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                    raise EmbeddingFailure("source_changed", "A saved book changed on disk. Discard this attempt and start again.")
        digest, cursor, count = hashlib.sha256(), 0, 0
        with self.store.connect() as db:
            for chunk in db.execute("SELECT * FROM chunks WHERE world_id=? AND book_id=? ORDER BY start", (attempt_id, book["id"])):
                if chunk["start"] != cursor or chunk["end"] - cursor != len(chunk["text"]) or chunk["vector"] is None:
                    raise EmbeddingFailure("incomplete_chunks", "This book's processing is incomplete. Discard this attempt and start again.")
                digest.update(chunk["text"].encode("utf-8"))
                cursor, count = chunk["end"], count + 1
        if not count or digest.hexdigest() != book["text_digest"]:
            raise EmbeddingFailure("incomplete_chunks", "The saved chunks do not match this book. Discard this attempt and start again.")
