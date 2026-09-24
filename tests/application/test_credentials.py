import subprocess
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vysol.credentials import FileCredentialVault
from vysol.embeddings import DIMENSIONS
from vysol.server import create_app


class TestEmbeddings:
    def embed(self, text, secret, stop, logger):
        return [1.0] + [0.0] * (DIMENSIONS - 1)


def test_file_credentials_persist_and_stay_scoped(tmp_path):
    key = str(uuid4())
    vault = FileCredentialVault(tmp_path)
    assert vault.read(key) is None
    vault.write(key, "synthetic-test-value")
    assert FileCredentialVault(tmp_path).read(key) == "synthetic-test-value"
    assert FileCredentialVault(tmp_path / "other").read(key) is None
    vault.write(key, "replacement-test-value")
    assert vault.read(key) == "replacement-test-value"
    vault.delete(key)
    assert vault.read(key) is None


def test_custom_runtime_credentials_and_temporary_files_are_ignored(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    root = tmp_path / "custom-runtime"
    key = str(uuid4())
    FileCredentialVault(root).write(key, "synthetic-test-value")
    temporary = root / "credentials" / ".key-example.tmp"
    temporary.write_text("synthetic", encoding="utf-8")
    for name in (key + ".key", temporary.name):
        result = subprocess.run(["git", "check-ignore", "--quiet", f"custom-runtime/credentials/{name}"], cwd=tmp_path)
        assert result.returncode == 0


def test_interrupted_replacement_preserves_saved_secret(tmp_path, monkeypatch):
    vault, key = FileCredentialVault(tmp_path), str(uuid4())
    vault.write(key, "original-synthetic")
    def fail(*args):
        raise OSError("Replacement interrupted")
    monkeypatch.setattr(type(tmp_path), "replace", fail)
    with pytest.raises(OSError):
        vault.write(key, "new-synthetic")
    assert vault.read(key) == "original-synthetic"
    assert not list((tmp_path / "credentials").glob("*.tmp"))


def test_key_id_cannot_escape_credential_directory(tmp_path):
    with pytest.raises(ValueError):
        FileCredentialVault(tmp_path).write("../outside", "synthetic")
    assert not (tmp_path / "credentials").exists()


def test_api_uses_local_files_across_restarts_without_returning_secrets(tmp_path):
    key, secret = str(uuid4()), "synthetic-persistent-secret"
    with TestClient(create_app(tmp_path)) as client:
        result = client.put(f"/api/providers/keys/{key}", json={"name": "Local key", "secret": secret})
        assert result.status_code == 200 and secret not in result.text
    assert (tmp_path / "credentials" / f"{key}.key").read_text(encoding="utf-8") == secret
    with TestClient(create_app(tmp_path)) as client:
        result = client.get("/api/providers")
        assert result.json()["keys"][0]["name"] == "Local key"
        assert secret not in result.text
        assert client.app.state.creation.vault.read(key) == secret
        assert client.delete(f"/api/providers/keys/{key}").status_code == 200
    assert not (tmp_path / "credentials" / f"{key}.key").exists()


def test_provider_connections_are_idempotent_and_credential_numbers_reuse_gaps(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        connection = client.post("/api/providers/connections", json={"provider": "google"})
        repeated = client.post("/api/providers/connections", json={"provider": "google"})
        assert connection.status_code == repeated.status_code == 200
        connection = connection.json()
        assert repeated.json()["id"] == connection["id"]

        first_id, second_id, third_id = (str(uuid4()) for _ in range(3))
        first = client.put(f"/api/providers/keys/{first_id}", json={
            "name": "Zulu", "connection_id": connection["id"], "secret": "synthetic-first-secret",
        })
        second = client.put(f"/api/providers/keys/{second_id}", json={
            "name": "Alpha", "connection_id": connection["id"], "secret": "synthetic-second-secret",
        })
        assert first.json()["sequence"] == 1
        assert second.json()["sequence"] == 2

        assert client.delete(f"/api/providers/keys/{first_id}").status_code == 200
        third = client.put(f"/api/providers/keys/{third_id}", json={
            "name": "Beta", "connection_id": connection["id"], "secret": "synthetic-third-secret",
        })
        assert third.json()["sequence"] == 1

        providers = client.get("/api/providers").json()
        assert len(providers["connections"]) == 1
        group = providers["connections"][0]
        assert group["id"] == connection["id"]
        assert [(item["name"], item["sequence"]) for item in group["credentials"]] == [
            ("Alpha", 2), ("Beta", 1),
        ]
        assert "synthetic" not in client.get("/api/providers").text

        assert client.delete(f"/api/providers/keys/{second_id}").status_code == 200
        assert client.delete(f"/api/providers/keys/{third_id}").status_code == 200
        empty_group = client.get("/api/providers").json()["connections"][0]
        assert empty_group["credentials"] == []
        assert empty_group["next_sequence"] == 1
        assert client.post("/api/providers/connections", json={"provider": "google"}).json()["next_sequence"] == 1
        fourth = client.put(f"/api/providers/keys/{uuid4()}", json={
            "name": "Next credential", "connection_id": connection["id"],
            "secret": "synthetic-fourth-secret",
        })
        assert fourth.json()["sequence"] == 1

        invalid_id = str(uuid4())
        invalid = client.put(f"/api/providers/keys/{invalid_id}", json={
            "name": "Wrong connection", "connection_id": str(uuid4()), "secret": "must-not-be-saved",
        })
        assert invalid.status_code == 422
        assert not (tmp_path / "credentials" / f"{invalid_id}.key").exists()
        assert client.post("/api/providers/connections", json={"provider": "openai"}).status_code == 422


def test_existing_provider_keys_migrate_in_rowid_order(tmp_path):
    first_id, second_id = str(uuid4()), str(uuid4())
    with sqlite3.connect(tmp_path / "processing.sqlite3") as db:
        db.execute("CREATE TABLE provider_keys(id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL)")
        db.execute("INSERT INTO provider_keys VALUES(?,?,?)", (first_id, "Zulu", "google"))
        db.execute("INSERT INTO provider_keys VALUES(?,?,?)", (second_id, "Alpha", "google"))

    with TestClient(create_app(tmp_path)) as client:
        result = client.get("/api/providers").json()
        sequences = {key["id"]: key["sequence"] for key in result["keys"]}
        assert sequences == {first_id: 1, second_id: 2}
        group = result["connections"][0]
        assert {key["id"] for key in group["credentials"]} == {first_id, second_id}
        assert all(key["connection_id"] == group["id"] for key in result["keys"])

        assert client.delete(f"/api/providers/keys/{first_id}").status_code == 200
        third_id = str(uuid4())
        created = client.put(f"/api/providers/keys/{third_id}", json={
            "name": "Next", "secret": "synthetic-next-secret",
        })
        assert created.status_code == 200 and created.json()["sequence"] == 1


def test_saved_key_reveal_is_explicit_and_uncached(tmp_path):
    key_id, secret = str(uuid4()), "synthetic-visible-only-on-request"
    with TestClient(create_app(tmp_path)) as client:
        assert client.put(f"/api/providers/keys/{key_id}", json={
            "name": "Reveal key", "secret": secret,
        }).status_code == 200
        listed = client.get("/api/providers")
        assert secret not in listed.text

        revealed = client.get(f"/api/providers/keys/{key_id}/secret")
        assert revealed.status_code == 200
        assert revealed.json() == {"secret": secret}
        assert revealed.headers["cache-control"] == "no-store, max-age=0"
        assert revealed.headers["pragma"] == "no-cache"
        assert client.get(f"/api/providers/keys/{uuid4()}/secret").status_code == 404


def test_disabled_connection_hides_new_key_use_without_breaking_saved_attempts(tmp_path):
    with TestClient(create_app(tmp_path, embedder=TestEmbeddings())) as client:
        key_id, book_id, attempt_id = str(uuid4()), str(uuid4()), str(uuid4())
        assert client.put(f"/api/providers/keys/{key_id}", json={
            "name": "In use", "secret": "synthetic-enabled-key",
        }).status_code == 200
        body = {
            "operation_id": str(uuid4()), "revision": 0, "name": "Saved attempt", "key_id": key_id,
            "config": {"model": "gemini-embedding-2", "size": 8000, "search": 1000},
            "books": [{"id": book_id, "filename": "Book.txt", "size": 13}],
        }
        attempt_response = client.put(f"/api/creation/{attempt_id}", json=body)
        assert attempt_response.status_code == 200
        attempt = attempt_response.json()
        uploaded = client.put(f"/api/creation/{attempt_id}/books/{book_id}",
                              params={"revision": attempt["revision"], "operation_id": str(uuid4())},
                              headers={"X-Filename": "Book.txt"}, content=b"Saved attempt")
        assert uploaded.status_code == 200
        attempt = uploaded.json()
        providers = client.get("/api/providers").json()
        connection = providers["connections"][0]
        assert connection["enabled"] is True

        disabled = client.put(f"/api/providers/connections/{connection['id']}", json={"enabled": False})
        assert disabled.status_code == 200 and disabled.json()["enabled"] is False
        assert len(disabled.json()["credentials"]) == 1
        assert client.get("/api/providers").json()["connections"][0]["enabled"] is False

        new_body = {**body, "operation_id": str(uuid4())}
        assert client.put(f"/api/creation/{uuid4()}", json=new_body).status_code == 409
        started = client.post(f"/api/creation/{attempt['id']}/start", json={
            "revision": attempt["revision"], "operation_id": str(uuid4()),
        })
        assert started.status_code == 200
        client.app.state.creation.thread.join(timeout=5)
        assert client.get(f"/api/creation/{attempt['id']}").json()["state"] == "complete"
