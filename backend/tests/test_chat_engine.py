import json

from core import chat_engine
from google.genai import types


def _parse_sse_events(chunks: list[str]) -> list[dict]:
    events = []
    for chunk in chunks:
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:].strip()))
    return events


def test_stream_chat_turns_setup_failures_into_error_events(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            raise RuntimeError("dimension mismatch")

    monkeypatch.setattr(chat_engine, "RetrievalEngine", DummyRetriever)

    chunks = list(chat_engine.stream_chat("world-123", "hello"))

    assert len(chunks) == 1
    assert chunks[0].startswith("data: ")

    payload = json.loads(chunks[0][6:].strip())
    assert payload["event"] == "error"
    assert "dimension mismatch" in payload["message"]


def test_stream_chat_gemini_emits_exact_context_payload_and_separate_meta(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": (
                    "# Entry Nodes\nA: entry desc\n\n"
                    "# Graph Nodes\nA: node desc\n\n"
                    "# Graph Edges\n[B1:C2] A, knows, B\n\n"
                    "# RAG Chunks\nChunk text"
                ),
                "graph_nodes": [{"id": "a", "display_name": "A", "entity_type": "Unknown"}],
                "context_graph": {
                    "schema_version": "context_graph.v1",
                    "nodes": [{"id": "A", "label": "A", "description": "entry desc", "connection_count": 1, "neighbors": []}],
                    "edges": [{"source": "A", "target": "B", "description": "knows", "strength": 1, "source_book": 1, "source_chunk": 2}],
                },
                "retrieval_meta": {
                    "requested_entry_nodes": 5,
                    "selected_entry_nodes": 3,
                    "force_all_nodes": False,
                },
            }

    class DummyKM:
        def get_active_key(self):
            return ("test-key", "key-1")

    captured = {}

    class DummyModels:
        def generate_content_stream(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["system_instruction"] = config.system_instruction

            class Chunk:
                text = "hello"

            return [Chunk()]

    class DummyClient:
        def __init__(self, api_key: str):
            self.models = DummyModels()

    monkeypatch.setattr(chat_engine, "RetrievalEngine", DummyRetriever)
    monkeypatch.setattr(chat_engine, "load_prompt", lambda key: "BASE SYSTEM")
    monkeypatch.setattr(
        chat_engine,
        "load_settings",
        lambda: {
            "chat_provider": "gemini",
            "default_model_chat": "gemini-test-model",
            "chat_history_messages": 10,
        },
    )
    monkeypatch.setattr(chat_engine, "get_key_manager", lambda: DummyKM())
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)

    history = [
        {"role": "user", "content": "older user"},
        {"role": "model", "content": "older model"},
    ]
    chunks = list(chat_engine.stream_chat("world-123", "latest user", history=history))
    events = _parse_sse_events(chunks)
    done = [e for e in events if e.get("event") == "done"][0]

    assert done["nodes_used"] == [{"id": "a", "display_name": "A", "entity_type": "Unknown"}]
    assert done["context_payload"] == {
        "system_instruction": captured["system_instruction"],
        "contents": [
            {"role": "user", "parts": ["older user"]},
            {"role": "model", "parts": ["older model"]},
            {"role": "user", "parts": ["latest user"]},
        ],
    }
    assert len(captured["contents"]) == 3
    assert isinstance(captured["contents"][0], types.UserContent)
    assert isinstance(captured["contents"][1], types.ModelContent)
    assert isinstance(captured["contents"][2], types.UserContent)
    assert captured["contents"][0].role == "user"
    assert captured["contents"][1].role == "model"
    assert captured["contents"][2].role == "user"
    assert captured["contents"][0].parts[0].text == "older user"
    assert captured["contents"][1].parts[0].text == "older model"
    assert captured["contents"][2].parts[0].text == "latest user"
    assert all(not isinstance(part, str) for content in captured["contents"] for part in content.parts)
    assert "# Entry Nodes" in done["context_payload"]["system_instruction"]
    assert "# Graph Nodes" in done["context_payload"]["system_instruction"]
    assert "# Graph Edges" in done["context_payload"]["system_instruction"]
    assert "# RAG Chunks" in done["context_payload"]["system_instruction"]
    assert "# Chat History" in done["context_payload"]["system_instruction"]
    assert done["context_payload"]["system_instruction"].index("# Entry Nodes") < done["context_payload"]["system_instruction"].index("# Graph Nodes")
    assert done["context_meta"]["schema_version"] == "model_context.v1"
    assert done["context_meta"]["provider"] == "gemini"
    assert done["context_meta"]["model"] == "gemini-test-model"
    assert done["context_meta"]["retrieval"]["requested_entry_nodes"] == 5
    assert done["context_meta"]["visualization"]["context_graph"]["schema_version"] == "context_graph.v1"
    assert "context_meta" not in done["context_payload"]
    assert "visualization" not in done["context_payload"]
    assert "captured_at" in done["context_meta"]


def test_stream_chat_intenserp_emits_exact_context_payload_and_separate_meta(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "# Entry Nodes\nA: entry desc\n\n# Graph Nodes\nA: node desc",
                "graph_nodes": [{"id": "a", "display_name": "A", "entity_type": "Unknown"}],
                "context_graph": {
                    "schema_version": "context_graph.v1",
                    "nodes": [{"id": "A", "label": "A", "description": "entry desc", "connection_count": 0, "neighbors": []}],
                    "edges": [],
                },
                "retrieval_meta": {
                    "requested_entry_nodes": 7,
                    "selected_entry_nodes": 4,
                    "force_all_nodes": False,
                },
            }

    captured = {}

    def fake_stream_intenserp_chat(*, messages_payload, nodes_used, settings):
        captured["messages_payload"] = messages_payload
        captured["nodes_used"] = nodes_used
        captured["settings"] = settings
        yield f"data: {json.dumps({'token': 'x'})}\n\n"
        yield f"data: {json.dumps({'event': 'done', 'nodes_used': nodes_used})}\n\n"

    monkeypatch.setattr(chat_engine, "RetrievalEngine", DummyRetriever)
    monkeypatch.setattr(chat_engine, "load_prompt", lambda key: "BASE SYSTEM")
    monkeypatch.setattr(
        chat_engine,
        "load_settings",
        lambda: {
            "chat_provider": "intenserp",
            "intenserp_model_id": "glm-chat-test",
            "chat_history_messages": 10,
        },
    )
    monkeypatch.setattr(chat_engine, "stream_intenserp_chat", fake_stream_intenserp_chat)

    history = [
        {"role": "user", "content": "older user"},
        {"role": "model", "content": "older model"},
    ]
    chunks = list(chat_engine.stream_chat("world-123", "latest user", history=history))
    events = _parse_sse_events(chunks)
    done = [e for e in events if e.get("event") == "done"][0]

    assert done["context_payload"] == {"messages": captured["messages_payload"]}
    assert done["context_payload"]["messages"] == [
        {"role": "system", "content": "BASE SYSTEM\n\n# Entry Nodes\nA: entry desc\n\n# Graph Nodes\nA: node desc\n\n# Chat History"},
        {"role": "user", "content": "older user"},
        {"role": "assistant", "content": "older model"},
        {"role": "user", "content": "latest user"},
    ]
    assert done["context_meta"]["schema_version"] == "model_context.v1"
    assert done["context_meta"]["provider"] == "intenserp"
    assert done["context_meta"]["model"] == "glm-chat-test"
    assert done["context_meta"]["retrieval"]["requested_entry_nodes"] == 7
    assert done["context_meta"]["visualization"]["context_graph"]["schema_version"] == "context_graph.v1"
    assert "context_meta" not in done["context_payload"]
    assert "visualization" not in done["context_payload"]
    assert "captured_at" in done["context_meta"]
