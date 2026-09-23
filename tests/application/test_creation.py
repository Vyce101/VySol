import json
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from vysol.books import import_books, Upload, ImportLimits
from vysol.embeddings import DIMENSIONS, EmbeddingFailure, InputTooLarge, ProcessingPaused
from vysol.server import create_app


class MemoryVault:
    def __init__(self):
        self.values = {}

    def read(self, key):
        return self.values.get(key)

    def write(self, key, secret):
        self.values[key] = secret

    def delete(self, key):
        self.values.pop(key, None)


class Embeddings:
    def __init__(self):
        self.calls = []
        self.fail_after = None
        self.max_size = None

    def embed(self, text, secret, stop, logger):
        if self.max_size and len(text) > self.max_size:
            raise InputTooLarge()
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise EmbeddingFailure("provider_unavailable", "Try again later.")
        self.calls.append(text)
        return [1.0] + [0.0] * (DIMENSIONS - 1)


@pytest.fixture
def setup(tmp_path):
    vault, embeddings = MemoryVault(), Embeddings()
    with TestClient(create_app(tmp_path, vault=vault, embedder=embeddings)) as client:
        yield client, vault, embeddings


def manifest(client, files=None, *, size=8000, search=1000):
    key = str(uuid4())
    assert client.put(f"/api/providers/keys/{key}", json={"name": "Test key", "secret": "synthetic-secret"}).status_code == 200
    files = files or [("First.txt", b"First story"), ("Second.txt", b"Second story")]
    value = {"operation_id": str(uuid4()), "revision": 0, "name": "Test world", "key_id": key,
             "config": {"model": "gemini-embedding-2", "size": size, "search": search},
             "books": [{"id": str(uuid4()), "filename": name, "size": len(content)} for name, content in files]}
    attempt_id = str(uuid4())
    response = client.put(f"/api/creation/{attempt_id}", json=value)
    assert response.status_code == 200, response.text
    return response.json(), value, files


def upload_all(client, attempt, files):
    for book, (name, content) in zip(attempt["books"], files):
        result = client.put(f"/api/creation/{attempt['id']}/books/{book['id']}",
                            params={"revision": attempt["revision"], "operation_id": str(uuid4())},
                            headers={"X-Filename": name}, content=content)
        assert result.status_code == 200, result.text
        attempt = result.json()
    return attempt


def run(client, attempt):
    result = client.post(f"/api/creation/{attempt['id']}/start",
                         json={"revision": attempt["revision"], "operation_id": str(uuid4())})
    assert result.status_code == 200, result.text
    client.app.state.creation.thread.join(timeout=5)
    assert not client.app.state.creation.thread.is_alive()
    return client.get(f"/api/creation/{attempt['id']}").json()


def test_atomic_creation_order_source_lock_and_vectors(setup, tmp_path):
    client, _, embeddings = setup
    attempt, body, files = manifest(client)
    assert client.get("/api/worlds").json() == []
    attempt = upload_all(client, attempt, files)
    assert client.get("/api/worlds").json() == []
    attempt = run(client, attempt)
    assert attempt["state"] == "complete", attempt
    assert client.get("/api/creation").json() is None
    worlds = client.get("/api/worlds").json()
    assert len(worlds) == 1 and worlds[0]["sources_locked"]
    books = client.get(f"/api/worlds/{attempt['id']}/books").json()
    assert [b["position"] for b in books] == [1, 2]
    assert [b["filename"] for b in books] == ["First.txt", "Second.txt"]
    assert embeddings.calls == ["First story", "Second story"]
    manager = client.app.state.creation
    with manager.store.connect() as db:
        vectors = db.execute("SELECT * FROM chunks").fetchall()
        assert len(vectors) == 2
        assert all(len(row["vector"]) == DIMENSIONS * 4 for row in vectors)
    body.update(operation_id=str(uuid4()), revision=attempt["revision"])
    assert client.put(f"/api/creation/{attempt['id']}", json=body).status_code == 409
    outcome = import_books(attempt["id"], [Upload("Third.txt", b"Third")], data_dir=tmp_path)[0]
    assert outcome.error is not None


def test_bad_book_prevents_all_embedding_and_requires_a_new_attempt(setup):
    client, _, embeddings = setup
    attempt, body, files = manifest(client, [("Good.txt", b"Good"), ("Bad.txt", b"\xff")])
    attempt = run(client, upload_all(client, attempt, files))
    assert attempt["state"] == "failed"
    assert attempt["books"][1]["state"] == "failed"
    assert not embeddings.calls
    assert client.get("/api/worlds").json() == []
    body.update(revision=attempt["revision"], operation_id=str(uuid4()))
    body["books"][1]["id"] = str(uuid4())
    assert client.put(f"/api/creation/{attempt['id']}", json=body).status_code == 409
    assert client.delete(f"/api/creation/{attempt['id']}?revision={attempt['revision']}").status_code == 200
    fresh, _, files = manifest(client, [("Good.txt", b"Good"), ("Corrected.txt", b"Corrected")])
    assert run(client, upload_all(client, fresh, files))["state"] == "complete"


def test_retry_reuses_embeddings_without_changing_the_manifest(setup):
    client, _, embeddings = setup
    attempt, body, files = manifest(client)
    embeddings.fail_after = 1
    attempt = run(client, upload_all(client, attempt, files))
    assert attempt["state"] == "failed" and attempt["chunks_done"] == 1
    body.update(books=list(reversed(body["books"])), operation_id=str(uuid4()), revision=attempt["revision"])
    assert client.put(f"/api/creation/{attempt['id']}", json=body).status_code == 409
    embeddings.fail_after = None
    assert run(client, attempt)["state"] == "complete"
    assert embeddings.calls == ["First story", "Second story"]
    assert client.get(f"/api/worlds/{attempt['id']}/books").json()[0]["filename"] == "First.txt"


def test_oversized_chunks_split_losslessly(setup):
    client, _, embeddings = setup
    embeddings.max_size = 4
    attempt, _, files = manifest(client, [("Long.txt", "αβγδε🌕\r\nabcdef".encode())])
    attempt = run(client, upload_all(client, attempt, files))
    assert attempt["state"] == "complete"
    assert "".join(embeddings.calls) == files[0][1].decode()
    assert all(len(text) <= 4 for text in embeddings.calls)


def test_manifest_idempotency_stale_revision_and_single_attempt(setup):
    client, _, _ = setup
    attempt, body, _ = manifest(client)
    replay = client.put(f"/api/creation/{attempt['id']}", json=body).json()
    assert replay["revision"] == attempt["revision"]
    body["operation_id"] = str(uuid4())
    assert client.put(f"/api/creation/{attempt['id']}", json=body).status_code == 409
    assert client.put(f"/api/creation/{uuid4()}", json=body).status_code == 409
    assert client.delete(f"/api/creation/{attempt['id']}?revision={attempt['revision']}").status_code == 200
    assert client.get("/api/creation").json() is None


def test_credentials_never_return_or_persist_in_sqlite(setup, tmp_path, capsys):
    client, vault, _ = setup
    attempt, _, _ = manifest(client)
    response = client.get("/api/providers")
    assert "synthetic-secret" not in response.text
    assert "synthetic-secret".encode() not in (tmp_path / "processing.sqlite3").read_bytes()
    key = attempt["key_id"]
    assert vault.read(key) == "synthetic-secret"
    result = client.put(f"/api/providers/keys/{key}", json={"name": "Renamed"})
    assert result.status_code == 200 and vault.read(key) == "synthetic-secret"
    bad = client.put(f"/api/providers/keys/{key}", json={"name": "", "secret": "private-value"})
    assert bad.status_code == 422 and "private-value" not in bad.text
    assert client.delete(f"/api/providers/keys/{key}").status_code == 200
    assert vault.read(key) is None
    captured = capsys.readouterr()
    logs = (tmp_path / "logs" / "imports.log").read_text(encoding="utf-8")
    for secret in ("synthetic-secret", "private-value"):
        assert secret not in logs + captured.out + captured.err


def test_restart_pauses_and_preserves_embeddings(tmp_path):
    vault, embeddings = MemoryVault(), Embeddings()
    with TestClient(create_app(tmp_path, vault=vault, embedder=embeddings)) as client:
        attempt, _, files = manifest(client)
        embeddings.fail_after = 1
        attempt = run(client, upload_all(client, attempt, files))
        client.app.state.creation.store.update(attempt["id"], state="running")
    with TestClient(create_app(tmp_path, vault=vault, embedder=embeddings)) as client:
        attempt = client.get("/api/creation").json()
        assert attempt["state"] == "paused" and attempt["chunks_done"] == 1
        assert len(embeddings.calls) == 1
        embeddings.fail_after = None
        assert run(client, attempt)["state"] == "complete"


def test_missing_upload_and_empty_manifest_are_rejected(setup):
    client, _, _ = setup
    attempt, body, _ = manifest(client)
    assert client.post(f"/api/creation/{attempt['id']}/start", json={"revision": attempt["revision"], "operation_id": str(uuid4())}).status_code == 409
    body["books"] = []
    assert client.put(f"/api/creation/{attempt['id']}", json=body).status_code == 422


def test_pause_blocks_edits_and_key_mutations_until_worker_stops(setup):
    client, _, embeddings = setup
    entered = threading.Event()
    def blocking(text, secret, stop, logger):
        entered.set()
        assert stop.wait(5)
        raise ProcessingPaused()
    embeddings.embed = blocking
    attempt, body, files = manifest(client)
    attempt = upload_all(client, attempt, files)
    request = {"revision": attempt["revision"], "operation_id": str(uuid4())}
    started = client.post(f"/api/creation/{attempt['id']}/start", json=request).json()
    assert entered.wait(5)
    assert client.post(f"/api/creation/{attempt['id']}/start", json=request).status_code == 200
    assert client.put(f"/api/providers/keys/{attempt['key_id']}", json={"name": "Changed"}).status_code == 409
    assert client.delete(f"/api/providers/keys/{attempt['key_id']}").status_code == 409
    body.update(revision=started["revision"], operation_id=str(uuid4()))
    assert client.put(f"/api/creation/{attempt['id']}", json=body).status_code == 409
    assert client.post(f"/api/creation/{attempt['id']}/pause", json={"revision": started["revision"]}).status_code == 200
    client.app.state.creation.thread.join(5)
    assert client.get("/api/creation").json()["state"] == "paused"
    assert client.put(f"/api/providers/keys/{attempt['key_id']}", json={"name": "Changed"}).status_code == 200


def test_concurrent_attempts_and_stale_uploads(setup):
    from concurrent.futures import ThreadPoolExecutor
    client, _, _ = setup
    attempt, body, files = manifest(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.put(f"/api/creation/{attempt['id']}", json=body), range(2)))
    assert all(result.status_code == 200 for result in results)
    updated = results[0].json()
    assert updated["revision"] == attempt["revision"]
    book = updated["books"][0]
    url = f"/api/creation/{attempt['id']}/books/{book['id']}"
    params = {"revision": updated["revision"], "operation_id": str(uuid4())}
    first = client.put(url, params=params, content=files[0][1], headers={"X-Filename": book["filename"]})
    assert first.status_code == 200
    assert client.put(url, params=params, content=files[0][1], headers={"X-Filename": book["filename"]}).json()["revision"] == first.json()["revision"]
    assert client.put(url, params=params, content=b"Different", headers={"X-Filename": book["filename"]}).status_code == 409


@pytest.mark.parametrize("change", ["name", "config", "key_id", "books"])
def test_submitted_manifest_is_fixed_even_while_paused(setup, change):
    client, _, _ = setup
    attempt, body, _ = manifest(client)
    body.update(revision=attempt["revision"], operation_id=str(uuid4()))
    if change == "name":
        body["name"] = "New name"
    elif change == "config":
        body["config"].update(size=5, search=1)
    elif change == "key_id":
        body["key_id"] = str(uuid4())
    else:
        body["books"].reverse()
    result = client.put(f"/api/creation/{attempt['id']}", json=body)
    assert result.status_code == 409 and "cannot be edited" in result.text
    assert client.get("/api/creation").json()["revision"] == attempt["revision"]


def test_interrupted_final_checkpoint_reconciles_published_world(setup, monkeypatch):
    client, _, embeddings = setup
    manager = client.app.state.creation
    attempt, _, files = manifest(client)
    original = manager.store.update
    failed = []
    def update(attempt_id, **changes):
        if changes.get("state") == "complete" and not failed:
            failed.append(True)
            raise OSError("checkpoint interrupted")
        return original(attempt_id, **changes)
    monkeypatch.setattr(manager.store, "update", update)
    attempt = run(client, upload_all(client, attempt, files))
    assert failed and attempt["state"] == "complete"
    assert len(client.get("/api/worlds").json()) == 1
    assert len(embeddings.calls) == 2


def test_failure_before_publication_is_invisible_and_retry_reuses_vectors(setup, monkeypatch):
    client, _, embeddings = setup
    manager = client.app.state.creation
    attempt, _, files = manifest(client)
    original = manager.publish
    def fail(value):
        raise OSError("publication interrupted")
    monkeypatch.setattr(manager, "publish", fail)
    attempt = run(client, upload_all(client, attempt, files))
    assert attempt["state"] == "failed" and not client.get("/api/worlds").json()
    monkeypatch.setattr(manager, "publish", original)
    assert run(client, attempt)["state"] == "complete"
    assert len(embeddings.calls) == 2


def test_upload_size_limit_preserves_attempt(tmp_path):
    with TestClient(create_app(tmp_path, vault=MemoryVault(), embedder=Embeddings(), limits=ImportLimits(max_upload_bytes=3))) as client:
        attempt, _, _ = manifest(client, [("Book.txt", b"Text")])
        response = client.put(f"/api/creation/{attempt['id']}/books/{attempt['books'][0]['id']}",
                              params={"revision": attempt["revision"], "operation_id": str(uuid4())},
                              headers={"X-Filename": "Book.txt"}, content=iter([b"ab", b"cd"]))
        assert response.status_code == 413
        assert not client.get("/api/creation").json()["books"][0]["uploaded"]


def test_missing_secret_blocks_resume_without_losing_uploads(setup):
    client, vault, embeddings = setup
    attempt, _, files = manifest(client)
    attempt = upload_all(client, attempt, files)
    vault.delete(attempt["key_id"])
    response = client.post(f"/api/creation/{attempt['id']}/start",
                           json={"revision": attempt["revision"], "operation_id": str(uuid4())})
    assert response.status_code == 409 and "API key" in response.text
    assert all(book["uploaded"] for book in client.get("/api/creation").json()["books"])
    assert not embeddings.calls


def test_changed_working_text_cannot_publish_with_stale_vectors(setup, monkeypatch):
    client, _, _ = setup
    manager = client.app.state.creation
    attempt, _, files = manifest(client)
    original = manager.publish
    def corrupt(value):
        (manager.book_directory(value["id"], value["books"][0]["id"]) / "text").write_bytes(b"Changed text")
        original(value)
    monkeypatch.setattr(manager, "publish", corrupt)
    result = run(client, upload_all(client, attempt, files))
    assert result["state"] == "failed" and "changed on disk" in result["message"]
    assert client.get("/api/worlds").json() == []


def test_discard_waits_for_worker_and_preserves_other_worlds(setup, tmp_path):
    client, _, embeddings = setup
    manager = client.app.state.creation
    legacy = manager.worlds.create(str(uuid4()), "Existing world")
    entered = threading.Event()
    def blocking(text, secret, stop, logger):
        entered.set()
        assert stop.wait(5)
        raise ProcessingPaused()
    embeddings.embed = blocking
    attempt, _, files = manifest(client)
    attempt = upload_all(client, attempt, files)
    started = client.post(f"/api/creation/{attempt['id']}/start",
                          json={"revision": attempt["revision"], "operation_id": str(uuid4())}).json()
    assert entered.wait(5)
    assert client.delete(f"/api/creation/{attempt['id']}?revision={started['revision']}").status_code == 200
    assert not manager.thread.is_alive()
    assert not (tmp_path / "creations" / attempt["id"]).exists()
    assert client.get("/api/worlds").json()[0]["id"] == legacy["id"]
    with manager.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
