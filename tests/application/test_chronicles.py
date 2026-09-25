import json
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx

from vysol.embeddings import DIMENSIONS
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


class RetrievalEmbeddings:
    def embed(self, text, secret, stop, logger):
        values = [0.0] * DIMENSIONS
        if text == "cccc":
            values[1] = 1
        else:
            values[0] = 1
        return values

    def embed_query(self, text, secret, stop, logger):
        values = [0.0] * DIMENSIONS
        values[1] = 1
        return values


class WaitingSSEStream(httpx.SyncByteStream):
    def __init__(self):
        self.ready = threading.Event()
        self.release = threading.Event()

    def __iter__(self):
        yield (b'event: step.delta\ndata: {"event_type":"step.delta","index":0,'
               b'"delta":{"type":"thought_summary","content":{"text":"Thinking"}}}\n\n')
        self.ready.set()
        self.release.wait(10)
        yield b'event: interaction.completed\ndata: {"event_type":"interaction.completed"}\n\n'

    def close(self):
        self.release.set()


class ResumableSSEStream(httpx.SyncByteStream):
    def __init__(self):
        self.ready = threading.Event()
        self.release = threading.Event()

    def __iter__(self):
        yield (b'event: step.delta\ndata: {"event_type":"step.delta","index":0,'
               b'"delta":{"type":"text","text":"First"}}\n\n')
        self.ready.set()
        self.release.wait(10)
        yield (b'event: step.delta\ndata: {"event_type":"step.delta","index":0,'
               b'"delta":{"type":"text","text":" message"}}\n\n'
               b'event: interaction.completed\ndata: {"event_type":"interaction.completed"}\n\n')

    def close(self):
        self.release.set()


def stream_response(request):
    events = [
        ("step.start", {"event_type": "step.start", "index": 0,
                        "step": {"type": "thought", "summary": [{"type": "text", "text": "Plan."}]}}),
        ("step.delta", {"event_type": "step.delta", "index": 0,
                         "delta": {"type": "thought_summary", "content": {"type": "text", "text": " More."}}}),
        ("step.start", {"event_type": "step.start", "index": 1,
                        "step": {"type": "model_output", "content": [{"type": "text", "text": "Hello"}]}}),
        ("step.delta", {"event_type": "step.delta", "index": 1, "delta": {"type": "text", "text": " there."}}),
        ("interaction.completed", {"event_type": "interaction.completed"}),
    ]
    body = "".join(f"event: {kind}\ndata: {json.dumps(value)}\n\n" for kind, value in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def prepare_app(tmp_path, *, handler=stream_response):
    vault = MemoryVault()
    requests = []

    def handle(request):
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    app = create_app(tmp_path, vault=vault, embedder=RetrievalEmbeddings(), chat_client=client)
    return app, vault, client, requests


def make_ready_world(client):
    key_id = str(uuid4())
    saved = client.put(f"/api/providers/keys/{key_id}", json={"name": "World key", "secret": "test-secret"})
    assert saved.status_code == 200, saved.text
    attempt_id = str(uuid4())
    book_id = str(uuid4())
    manifest = {
        "operation_id": str(uuid4()), "revision": 0, "name": "North",
        "key_id": key_id, "config": {"model": "gemini-embedding-2", "size": 4, "search": 0},
        "books": [{"id": book_id, "filename": "Source.txt", "size": 12}],
    }
    attempt = client.put(f"/api/creation/{attempt_id}", json=manifest).json()
    uploaded = client.put(
        f"/api/creation/{attempt_id}/books/{book_id}",
        params={"revision": attempt["revision"], "operation_id": str(uuid4())},
        headers={"X-Filename": "Source.txt"}, content=b"aaaabbbbcccc")
    assert uploaded.status_code == 200, uploaded.text
    attempt = uploaded.json()
    started = client.post(f"/api/creation/{attempt_id}/start",
                          json={"revision": attempt["revision"], "operation_id": str(uuid4())})
    assert started.status_code == 200, started.text
    thread = client.app.state.creation.threads[attempt_id]
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert client.get(f"/api/worlds/{attempt_id}").json()["state"] == "complete"
    return attempt_id


def add_key_and_world_setting(client):
    key_id = str(uuid4())
    assert client.put(f"/api/providers/keys/{key_id}", json={
        "name": "Chronicle key", "secret": "chat-secret",
    }).status_code == 200
    settings = client.get("/api/chronicle-settings").json()
    settings["key_id"] = key_id
    assert client.put("/api/chronicle-settings", json=settings).status_code == 200
    return key_id


def test_chronicle_rows_shared_settings_duplicate_titles_and_pending_world(tmp_path):
    app, _, chat_client, _ = prepare_app(tmp_path)
    with TestClient(app) as client:
        world_id = str(uuid4())
        client.app.state.creation.worlds.create(world_id, "Unfinished")
        first = client.post(f"/api/worlds/{world_id}/chronicles")
        second = client.post(f"/api/worlds/{world_id}/chronicles")
        assert first.status_code == second.status_code == 201
        assert first.json()["title"] == second.json()["title"] == "New Chronicle"
        assert first.json()["message_count"] == 0
        assert first.json()["preview"] == "No messages yet"
        assert first.json()["not_started"] is True
        assert client.patch(f"/api/chronicles/{first.json()['id']}", json={"title": "New Chronicle"}).status_code == 200
        assert len(client.get(f"/api/worlds/{world_id}/chronicles").json()) == 2

        settings = client.get("/api/chronicle-settings").json()
        assert settings["model"] == "gemini-3.8-flash"
        assert settings["key_id"] == ""
        assert settings["chunk_count"] == 3
        assert settings["minimum_similarity"] == 0.6
        assert settings["chunk_overlap"] == 150
        assert settings["streaming_speed"] == 50
        assert settings["sections"] == {"ai": True, "retrieval": True, "response": True, "section_tags": True}
        settings["chunk_count"] = 7
        assert client.put("/api/chronicle-settings", json=settings).status_code == 200
        assert client.get("/api/chronicle-settings").json()["chunk_count"] == 7
        assert client.get("/api/providers").json()["chat_models"] == [
            {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash", "provider": "google", "series": "Flash"},
            {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash-Lite", "provider": "google", "series": "Flash Lite"},
            {"id": "gemma-4-31b-it", "name": "Gemma 4 31B IT", "provider": "google", "series": "Gemma"},
        ]
        assert client.delete(f"/api/chronicles/{first.json()['id']}").json() == {"deleted": True}
        assert client.get(f"/api/chronicles/{first.json()['id']}").status_code == 404
    chat_client.close()


def test_chat_retrieves_world_chunks_with_source_character_overlap_streams_and_replays_idempotently(tmp_path):
    app, _, chat_client, requests = prepare_app(tmp_path)
    with TestClient(app) as client:
        world_id = make_ready_world(client)
        add_key_and_world_setting(client)
        settings = client.get("/api/chronicle-settings").json()
        settings.update(chunk_count=1, chunk_overlap=8, minimum_similarity=0.6)
        assert client.put("/api/chronicle-settings", json=settings).status_code == 200
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        request_id = str(uuid4())
        response = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                               json={"request_id": request_id, "text": "What happened?"})
        assert response.status_code == 200, response.text
        assert "event: user_message" in response.text
        assert "event: thinking_delta" in response.text
        assert "event: answer_delta" in response.text
        assert "event: completed" in response.text
        assert '"text": "Plan. More."' in response.text
        assert '"text": "Hello there."' in response.text

        payload = json.loads(requests[0].content)
        assert payload["model"] == "gemini-3.8-flash"
        assert payload["store"] is False
        assert "system_instruction" not in payload
        assert "<chat_history>" in payload["input"] and "</chat_history>" in payload["input"]
        assert "<rag_chunks>" in payload["input"] and "</rag_chunks>" in payload["input"]
        assert "Source.txt | chars 0-12" in payload["input"]
        assert "aaaabbbbcccc" in payload["input"]

        retry = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                            json={"request_id": request_id, "text": "What happened?"})
        assert retry.status_code == 200 and "event: completed" in retry.text
        assert len(requests) == 1
        collision = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                                json={"request_id": request_id, "text": "Different input"})
        assert collision.status_code == 409

        messages = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()
        assert [(message["role"], message["text"]) for message in messages] == [
            ("user", "What happened?"), ("assistant", "Hello there."),
        ]
        assert messages[1]["thinking"] == "Plan. More."
        assert messages[1]["status"] == "complete"
        row = client.get(f"/api/worlds/{world_id}/chronicles").json()[0]
        assert row["message_count"] == 2
        assert row["preview"] == "Hello there."
        assert row["not_started"] is False
    chat_client.close()


def test_unembedded_world_rejects_chat_without_creating_a_message(tmp_path):
    app, _, chat_client, requests = prepare_app(tmp_path)
    with TestClient(app) as client:
        world_id = str(uuid4())
        client.app.state.creation.worlds.create(world_id, "Empty")
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        response = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                               json={"request_id": str(uuid4()), "text": "Hello"})
        assert response.status_code == 409
        assert "finishes processing" in response.json()["detail"]
        assert client.get(f"/api/chronicles/{chronicle['id']}/messages").json() == []
        assert requests == []
    chat_client.close()


def test_failed_generation_keeps_partial_output_for_retry(tmp_path):
    def fail_after_partial(request):
        body = "".join([
            "event: step.delta\ndata: {\"event_type\":\"step.delta\",\"delta\":{\"type\":\"text\",\"text\":\"Partial\"}}\n\n",
            "event: interaction.failed\ndata: {\"event_type\":\"interaction.failed\"}\n\n",
        ])
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    app, _, chat_client, _ = prepare_app(tmp_path, handler=fail_after_partial)
    with TestClient(app) as client:
        world_id = make_ready_world(client)
        add_key_and_world_setting(client)
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        result = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                             json={"request_id": str(uuid4()), "text": "Continue"})
        assert result.status_code == 200
        assert "event: error" in result.text
        assert "Partial" in result.text
        answer = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()[1]
        assert answer["text"] == "Partial"
        assert answer["status"] == "partial"
    chat_client.close()


def test_empty_failed_generation_keeps_user_message_without_counting_an_empty_reply(tmp_path):
    def fail_without_output(request):
        body = "event: interaction.failed\ndata: {\"event_type\":\"interaction.failed\"}\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    app, _, chat_client, _ = prepare_app(tmp_path, handler=fail_without_output)
    with TestClient(app) as client:
        world_id = make_ready_world(client)
        add_key_and_world_setting(client)
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        result = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                             json={"request_id": str(uuid4()), "text": "Continue"})
        assert result.status_code == 200
        assert '"assistant": null' in result.text
        messages = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()
        assert [(message["role"], message["text"]) for message in messages] == [("user", "Continue")]
        row = client.get(f"/api/worlds/{world_id}/chronicles").json()[0]
        assert row["message_count"] == 1
        assert row["preview"] == "Continue"
    chat_client.close()


def test_stop_waits_for_thinking_only_partial_to_be_saved_and_prevents_a_second_active_turn(tmp_path):
    provider_stream = WaitingSSEStream()

    def wait_for_stop(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=provider_stream)

    app, _, chat_client, _ = prepare_app(tmp_path, handler=wait_for_stop)
    with TestClient(app) as client:
        world_id = make_ready_world(client)
        add_key_and_world_setting(client)
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        request_id = str(uuid4())
        client.app.state.chronicles.start_generation(chronicle["id"], request_id, "Continue")
        assert provider_stream.ready.wait(5)

        duplicate_turn = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                                     json={"request_id": str(uuid4()), "text": "Another turn"})
        assert duplicate_turn.status_code == 409

        stopped = client.post(f"/api/chronicles/{chronicle['id']}/generations/{request_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["stopped"] is True
        assert stopped.json()["status"] == "stopped"
        assert stopped.json()["message"]["thinking"] == "Thinking"
        assert stopped.json()["message"]["text"] == ""

        messages = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()
        assert len(messages) == 2
        assert messages[-1]["status"] == "stopped"
        assert messages[-1]["thinking"] == "Thinking"
    chat_client.close()


def test_stream_consumer_disconnect_does_not_cancel_generation_and_active_message_exposes_request_id(tmp_path):
    provider_stream = ResumableSSEStream()

    def continue_after_disconnect(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=provider_stream)

    app, _, chat_client, _ = prepare_app(tmp_path, handler=continue_after_disconnect)
    with TestClient(app) as client:
        world_id = make_ready_world(client)
        add_key_and_world_setting(client)
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        request_id = str(uuid4())
        begun = client.app.state.chronicles.start_generation(chronicle["id"], request_id, "Keep going")
        stream = client.app.state.chronicles.stream_events(chronicle["id"], request_id, begun["user_message"])
        assert next(stream).startswith("event: user_message")
        assert provider_stream.ready.wait(5)

        active = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()
        assert active[-1]["status"] == "streaming"
        assert active[-1]["request_id"] == request_id
        assert active[-1]["streaming_speed"] == 50
        stream.close()
        assert client.app.state.chronicles.stops[(chronicle["id"], request_id)].is_set() is False

        provider_stream.release.set()
        thread = client.app.state.chronicles.threads[(chronicle["id"], request_id)]
        thread.join(timeout=5)
        assert not thread.is_alive()
        messages = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()
        assert messages[-1]["text"] == "First message"
        assert messages[-1]["status"] == "complete"
    chat_client.close()


def test_discarding_an_unfinished_world_deletes_its_chronicles(tmp_path):
    app, _, chat_client, _ = prepare_app(tmp_path)
    with TestClient(app) as client:
        key_id = str(uuid4())
        client.put(f"/api/providers/keys/{key_id}", json={"name": "Build key", "secret": "secret"})
        attempt_id = str(uuid4())
        manifest = {
            "operation_id": str(uuid4()), "revision": 0, "name": "In progress",
            "key_id": key_id, "config": {"model": "gemini-embedding-2", "size": 8000, "search": 1000},
            "books": [{"id": str(uuid4()), "filename": "Book.txt", "size": 4}],
        }
        attempt = client.put(f"/api/creation/{attempt_id}", json=manifest).json()
        chronicle = client.post(f"/api/worlds/{attempt_id}/chronicles").json()
        assert client.get(f"/api/worlds/{attempt_id}/chronicles").json()[0]["id"] == chronicle["id"]
        discarded = client.delete(f"/api/creation/{attempt_id}?revision={attempt['revision']}")
        assert discarded.status_code == 200
        with client.app.state.chronicles.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM chronicles WHERE world_id=?", (attempt_id,)).fetchone()[0] == 0
    chat_client.close()


def test_upstream_eof_without_completed_event_preserves_partial_output_as_failure(tmp_path):
    def end_early(request):
        body = "event: step.delta\ndata: {\"event_type\":\"step.delta\",\"index\":0,\"delta\":{\"type\":\"text\",\"text\":\"Partial\"}}\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    app, _, chat_client, _ = prepare_app(tmp_path, handler=end_early)
    with TestClient(app) as client:
        world_id = make_ready_world(client)
        add_key_and_world_setting(client)
        chronicle = client.post(f"/api/worlds/{world_id}/chronicles").json()
        result = client.post(f"/api/chronicles/{chronicle['id']}/messages/stream",
                             json={"request_id": str(uuid4()), "text": "Continue"})
        assert "event: error" in result.text
        assert "provider_incomplete" in result.text
        answer = client.get(f"/api/chronicles/{chronicle['id']}/messages").json()[1]
        assert answer["text"] == "Partial"
        assert answer["status"] == "partial"
    chat_client.close()
