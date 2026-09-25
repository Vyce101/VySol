from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from vysol.books import Upload, import_books
from vysol.server import create_app
from vysol.worlds import WorldStore, atomic_json


def set_world_times(store, world_id, *, created_at, last_used_at=None):
    value = store.get(world_id)
    value["created_at"] = created_at
    if last_used_at is None:
        value.pop("last_used_at", None)
    else:
        value["last_used_at"] = last_used_at
    atomic_json(store.directory(world_id) / "world.json", value)


def test_worlds_order_by_creation_then_latest_chronicle_message(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        store = WorldStore(tmp_path)
        older = str(uuid4())
        newer = str(uuid4())
        store.create(older, "Older World")
        store.create(newer, "Newer World")
        set_world_times(store, older, created_at="2020-01-01T00:00:00+00:00",
                        last_used_at="2021-01-01T00:00:00+00:00")
        set_world_times(store, newer, created_at="2022-01-01T00:00:00+00:00")

        assert [world["id"] for world in client.get("/api/worlds").json()] == [newer, older]

        chronicle = client.app.state.chronicles.store.create(older)
        request_id = str(uuid4())
        client.app.state.chronicles.store.begin_generation(
            chronicle["id"], request_id, "What happened?", {},
        )
        client.app.state.chronicles.store.append(chronicle["id"], request_id, "text", "The answer.")

        worlds = client.get("/api/worlds").json()
        assert [world["id"] for world in worlds] == [older, newer]
        assert worlds[0]["last_used_at"] > "2022-01-01T00:00:00+00:00"


def test_book_addition_updates_world_activity_and_old_metadata_still_sorts(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        store = WorldStore(tmp_path)
        older = str(uuid4())
        newer = str(uuid4())
        store.create(older, "Older World")
        store.create(newer, "Newer World")
        set_world_times(store, older, created_at="2020-01-01T00:00:00+00:00")
        set_world_times(store, newer, created_at="2022-01-01T00:00:00+00:00")

        result = import_books(older, [Upload("Added.txt", b"New source")], data_dir=tmp_path)[0]
        assert result.book is not None

        worlds = client.get("/api/worlds").json()
        assert [world["id"] for world in worlds] == [older, newer]
        assert worlds[0]["last_used_at"] is not None
        assert datetime.fromisoformat(worlds[0]["last_used_at"]) <= datetime.now(timezone.utc)


def test_pending_world_activity_does_not_add_it_to_accepted_world_list(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        key_id = str(uuid4())
        assert client.put(f"/api/providers/keys/{key_id}", json={
            "name": "Build key", "secret": "synthetic-secret",
        }).status_code == 200
        pending_id = str(uuid4())
        body = {
            "operation_id": str(uuid4()), "revision": 0, "name": "Pending World",
            "key_id": key_id,
            "config": {"model": "gemini-embedding-2", "size": 8000, "search": 1000},
            "books": [{"id": str(uuid4()), "filename": "Book.txt", "size": 4}],
        }
        assert client.put(f"/api/creation/{pending_id}", json=body).status_code == 200
        chronicle = client.post(f"/api/worlds/{pending_id}/chronicles").json()
        client.app.state.chronicles.store.begin_generation(
            chronicle["id"], str(uuid4()), "Pending message", {},
        )

        assert client.get(f"/api/worlds/{pending_id}").json()["last_used_at"] is not None
        assert client.get("/api/worlds").json() == []


def test_pending_creation_edits_move_the_attempt_to_the_front(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        key_id = str(uuid4())
        assert client.put(f"/api/providers/keys/{key_id}", json={
            "name": "Build key", "secret": "synthetic-secret",
        }).status_code == 200

        def save_attempt(name):
            attempt_id = str(uuid4())
            book_id = str(uuid4())
            body = {
                "operation_id": str(uuid4()), "revision": 0, "name": name,
                "key_id": key_id,
                "config": {"model": "gemini-embedding-2", "size": 8000, "search": 1000},
                "books": [{"id": book_id, "filename": "Book.txt", "size": 4}],
            }
            response = client.put(f"/api/creation/{attempt_id}", json=body)
            assert response.status_code == 200, response.text
            return response.json()

        older = save_attempt("Older pending world")
        newer = save_attempt("Newer pending world")
        assert client.get("/api/creations").json()[0]["id"] == newer["id"]

        uploaded = client.put(
            f"/api/creation/{older['id']}/books/{older['books'][0]['id']}",
            params={"revision": older["revision"], "operation_id": str(uuid4())},
            headers={"X-Filename": "Book.txt"}, content=b"Book",
        )
        assert uploaded.status_code == 200, uploaded.text
        assert client.get("/api/creations").json()[0]["id"] == older["id"]
