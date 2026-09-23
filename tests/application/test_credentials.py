import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vysol.credentials import FileCredentialVault
from vysol.server import create_app


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
