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


def test_stream_chat_blocks_when_context_exceeds_character_limit(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "A" * 120,
                "graph_nodes": [{"id": "a", "display_name": "A", "entity_type": "Unknown"}],
                "retrieval_meta": {"context_characters": 120},
                "context_graph": None,
            }

    class DummyClient:
        def __init__(self, api_key: str):
            raise AssertionError("Gemini client should not be created when context limit blocks the request.")

    monkeypatch.setattr(chat_engine, "RetrievalEngine", DummyRetriever)
    monkeypatch.setattr(chat_engine, "load_prompt", lambda key: "BASE SYSTEM")
    monkeypatch.setattr(
        chat_engine,
        "load_settings",
        lambda: {
            "chat_provider": "gemini",
            "default_model_chat": "gemini-test-model",
            "chat_history_messages": 10,
            "retrieval_context_char_limit": 100,
        },
    )
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)

    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello")))

    assert events[0]["token"].startswith("I did not send your prompt to the AI because the retrieved context was 120 characters")
    assert events[-1]["event"] == "done"
    assert events[-1]["context_meta"]["retrieval"]["retrieval_blocked"] is True
    assert events[-1]["context_meta"]["retrieval"]["block_reason"] == "context_limit_exceeded"


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
        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
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
        {
            "role": "model",
            "content": "older model",
            "gemini_parts": [{"text": "hidden thought", "thought": True}],
        },
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
    assert all("gemini_parts" not in message for message in captured["messages_payload"])
    assert done["context_meta"]["schema_version"] == "model_context.v1"
    assert done["context_meta"]["provider"] == "intenserp"
    assert done["context_meta"]["model"] == "glm-chat-test"
    assert done["context_meta"]["retrieval"]["requested_entry_nodes"] == 7
    assert done["context_meta"]["visualization"]["context_graph"]["schema_version"] == "context_graph.v1"
    assert "context_meta" not in done["context_payload"]
    assert "visualization" not in done["context_payload"]
    assert "captured_at" in done["context_meta"]


def test_stream_chat_groq_ignores_stale_reasoning_for_known_unsupported_models(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    captured: dict[str, object] = {}

    def fake_stream(provider: str, payload: dict, **kwargs):
        captured["provider"] = provider
        captured["payload"] = payload
        yield {"choices": [{"delta": {"content": "hello"}}]}

    monkeypatch.setattr(chat_engine, "RetrievalEngine", DummyRetriever)
    monkeypatch.setattr(chat_engine, "load_prompt", lambda key: "BASE SYSTEM")
    monkeypatch.setattr(
        chat_engine,
        "load_settings",
        lambda: {
            "default_model_chat": "llama-3.3-70b-versatile",
            "default_model_chat_groq_reasoning_effort": "high",
            "groq_chat_include_reasoning": False,
            "chat_history_messages": 10,
        },
    )
    monkeypatch.setattr(chat_engine, "resolve_slot_provider", lambda settings, slot: "groq")
    monkeypatch.setattr(chat_engine, "stream_openai_compatible_chat", fake_stream)

    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello")))

    assert captured["provider"] == "groq"
    assert "reasoning_effort" not in captured["payload"]
    assert events[-1]["event"] == "done"


def test_stream_chat_groq_preserves_reasoning_for_unknown_models(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    captured: dict[str, object] = {}

    def fake_stream(provider: str, payload: dict, **kwargs):
        captured["payload"] = payload
        yield {"choices": [{"delta": {"content": "hello"}}]}

    monkeypatch.setattr(chat_engine, "RetrievalEngine", DummyRetriever)
    monkeypatch.setattr(chat_engine, "load_prompt", lambda key: "BASE SYSTEM")
    monkeypatch.setattr(
        chat_engine,
        "load_settings",
        lambda: {
            "default_model_chat": "custom/groq-model",
            "default_model_chat_groq_reasoning_effort": "medium",
            "groq_chat_include_reasoning": False,
            "chat_history_messages": 10,
        },
    )
    monkeypatch.setattr(chat_engine, "resolve_slot_provider", lambda settings, slot: "groq")
    monkeypatch.setattr(chat_engine, "stream_openai_compatible_chat", fake_stream)

    list(chat_engine.stream_chat("world-123", "hello"))

    assert captured["payload"]["reasoning_effort"] == "medium"


def test_gemini_part_roundtrip_preserves_structured_function_call():
    part = types.Part(function_call=types.FunctionCall(name="lookup", args={"q": "x"}))

    serialized = chat_engine._serialize_gemini_part(part)

    assert serialized == {"function_call": {"name": "lookup", "args": {"q": "x"}}}

    rebuilt = chat_engine._build_gemini_sdk_parts("", [serialized])[0]

    assert rebuilt.function_call is not None
    assert rebuilt.function_call.name == "lookup"
    assert rebuilt.function_call.args == {"q": "x"}


def test_stream_chat_gemini_retries_transient_failure_before_first_token(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    class DummyKM:
        def __init__(self):
            self.calls = 0
            self.reported: list[tuple[int, str]] = []

        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
            keys = [("k1", 0), ("k2", 1)]
            key = keys[min(self.calls, len(keys) - 1)]
            self.calls += 1
            return key

        def report_error(self, key_index: int, error_type: str) -> None:
            self.reported.append((key_index, error_type))

    class FailingResponse:
        def __iter__(self):
            raise RuntimeError("request timed out")
            yield  # pragma: no cover

    class SuccessfulResponse:
        def __iter__(self):
            class Chunk:
                text = "hello"

            yield Chunk()

    class DummyModels:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def generate_content_stream(self, *, model, contents, config):
            if self.api_key == "k1":
                return FailingResponse()
            return SuccessfulResponse()

    class DummyClient:
        def __init__(self, api_key: str):
            self.models = DummyModels(api_key)

    dummy_km = DummyKM()

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
    monkeypatch.setattr(chat_engine, "get_key_manager", lambda: dummy_km)
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)
    monkeypatch.setattr(chat_engine.time, "sleep", lambda seconds: None)

    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello")))

    assert [event.get("token") for event in events if "token" in event] == ["hello"]
    assert events[-1]["event"] == "done"
    assert dummy_km.reported == [(0, "timeout")]


def test_stream_chat_gemini_generic_429_retries_same_key_without_cooldown(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    class DummyKM:
        def __init__(self):
            self.wait_calls = 0
            self.reported: list[tuple[int, str]] = []

        def wait_for_request_key(self, used_indices=None):
            self.wait_calls += 1
            return ("k1", 0)

        def report_error(self, key_index: int, error_type: str) -> None:
            self.reported.append((key_index, error_type))

    class FailingResponse:
        def __iter__(self):
            raise RuntimeError("429 Too Many Requests")
            yield  # pragma: no cover

    class SuccessfulResponse:
        def __iter__(self):
            class Chunk:
                text = "hello"

            yield Chunk()

    class DummyModels:
        def __init__(self):
            self.calls = 0

        def generate_content_stream(self, *, model, contents, config):
            self.calls += 1
            if self.calls == 1:
                return FailingResponse()
            return SuccessfulResponse()

    class DummyClient:
        models_instance = DummyModels()

        def __init__(self, api_key: str):
            self.models = self.models_instance

    dummy_km = DummyKM()

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
    monkeypatch.setattr(chat_engine, "get_key_manager", lambda: dummy_km)
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)
    monkeypatch.setattr(chat_engine.time, "sleep", lambda seconds: None)

    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello")))

    assert [event.get("token") for event in events if "token" in event] == ["hello"]
    assert events[-1]["event"] == "done"
    assert dummy_km.wait_calls == 1
    assert dummy_km.reported == []


def test_stream_chat_gemini_explicit_key_quota_429_cools_down_and_rotates(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    class DummyKM:
        def __init__(self):
            self.wait_calls = 0
            self.reported: list[tuple[int, str]] = []

        def wait_for_request_key(self, used_indices=None):
            keys = [("k1", 0), ("k2", 1)]
            key = keys[min(self.wait_calls, len(keys) - 1)]
            self.wait_calls += 1
            return key

        def report_error(self, key_index: int, error_type: str) -> None:
            self.reported.append((key_index, error_type))

    class FailingResponse:
        def __iter__(self):
            raise RuntimeError("429 API key quota exceeded")
            yield  # pragma: no cover

    class SuccessfulResponse:
        def __iter__(self):
            class Chunk:
                text = "hello"

            yield Chunk()

    class DummyModels:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def generate_content_stream(self, *, model, contents, config):
            if self.api_key == "k1":
                return FailingResponse()
            return SuccessfulResponse()

    class DummyClient:
        def __init__(self, api_key: str):
            self.models = DummyModels(api_key)

    dummy_km = DummyKM()

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
    monkeypatch.setattr(chat_engine, "get_key_manager", lambda: dummy_km)
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)
    monkeypatch.setattr(chat_engine.time, "sleep", lambda seconds: None)

    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello")))

    assert [event.get("token") for event in events if "token" in event] == ["hello"]
    assert events[-1]["event"] == "done"
    assert dummy_km.wait_calls == 2
    assert dummy_km.reported == [(0, "429")]


def test_stream_chat_gemini_does_not_retry_after_first_token(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    class DummyKM:
        def __init__(self):
            self.calls = 0
            self.reported: list[tuple[int, str]] = []

        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
            keys = [("k1", 0), ("k2", 1)]
            key = keys[min(self.calls, len(keys) - 1)]
            self.calls += 1
            return key

        def report_error(self, key_index: int, error_type: str) -> None:
            self.reported.append((key_index, error_type))

    class PartialFailureResponse:
        def __iter__(self):
            class Chunk:
                text = "hello"

            yield Chunk()
            raise RuntimeError("request timed out")

    class DummyModels:
        def __init__(self, api_key: str):
            self.api_key = api_key

        def generate_content_stream(self, *, model, contents, config):
            return PartialFailureResponse()

    class DummyClient:
        def __init__(self, api_key: str):
            self.models = DummyModels(api_key)

    dummy_km = DummyKM()

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
    monkeypatch.setattr(chat_engine, "get_key_manager", lambda: dummy_km)
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)

    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello")))

    assert events[0]["token"] == "hello"
    assert events[-1]["event"] == "error"
    assert dummy_km.calls == 1
    assert dummy_km.reported == []


def test_stream_chat_gemini_emits_thought_tokens_and_applies_thinking_config(monkeypatch):
    class DummyRetriever:
        def __init__(self, world_id: str):
            self.world_id = world_id

        def retrieve(self, query: str, settings_override=None):
            return {
                "context_string": "",
                "graph_nodes": [],
                "retrieval_meta": {},
                "context_graph": None,
            }

    class DummyKM:
        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
            return ("test-key", 0)

    captured = {}

    class DummyContent:
        def __init__(self, parts):
            self.parts = parts

    class DummyCandidate:
        def __init__(self, parts):
            self.content = DummyContent(parts)

    class DummyChunk:
        def __init__(self, parts):
            self.candidates = [DummyCandidate(parts)]
            self.text = None

    class DummyModels:
        def generate_content_stream(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["thinking_config"] = config.thinking_config
            return [
                DummyChunk([
                    types.Part(text="Thought 1", thought=True, thought_signature=b"sig"),
                    types.Part(text="Answer 1", thought=False),
                ]),
            ]

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
            "default_model_chat": "gemini-3-flash",
            "default_model_chat_thinking_level": "minimal",
            "gemini_chat_send_thinking": True,
            "chat_history_messages": 10,
        },
    )
    monkeypatch.setattr(chat_engine, "get_key_manager", lambda: DummyKM())
    monkeypatch.setattr(chat_engine.genai, "Client", DummyClient)

    history = [{
        "role": "model",
        "content": "older model",
        "gemini_parts": [{"text": "prior thought", "thought": True}, {"text": "prior answer", "thought": False}],
    }]
    events = _parse_sse_events(list(chat_engine.stream_chat("world-123", "hello", history=history)))

    assert [event.get("thought_token") for event in events if "thought_token" in event] == ["Thought 1"]
    assert [event.get("token") for event in events if "token" in event] == ["Answer 1"]
    done = [event for event in events if event.get("event") == "done"][0]
    assert done["thought_text"] == "Thought 1"
    assert done["gemini_parts"] == [
        {"text": "Thought 1", "thought": True, "thought_signature": {"__kind__": "bytes", "base64": "c2ln"}},
        {"text": "Answer 1", "thought": False},
    ]
    assert isinstance(captured["contents"][0], types.ModelContent)
    assert len(captured["contents"][0].parts) == 2
    assert captured["contents"][0].parts[0].text == "prior thought"
    assert captured["contents"][0].parts[0].thought is True
    assert captured["contents"][0].parts[1].text == "prior answer"
    thinking_level = getattr(captured["thinking_config"].thinking_level, "value", captured["thinking_config"].thinking_level)
    assert thinking_level == "MINIMAL"
    assert captured["thinking_config"].include_thoughts is True
