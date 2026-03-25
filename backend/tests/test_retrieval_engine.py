import pytest

from core import retrieval_engine


def _patch_retrieval_dependencies(
    monkeypatch,
    *,
    bfs_nodes: list[dict],
    graph_nodes: list[tuple[str, dict]] | None = None,
    edge_rows: list[tuple[str, str, dict]] | None = None,
    chunk_results: list[dict] | None = None,
    node_results: list[dict] | None = None,
    settings: dict | None = None,
    total_chunks: int = 1,
    chunk_vector_count: int | None = None,
    node_vector_count: int | None = None,
    health_summary: dict | None = None,
) -> dict:
    telemetry: dict = {}

    class DummyGraph:
        def __init__(self):
            self._nodes = graph_nodes or [
                ("uuid-1", {"display_name": "Node One", "description": "Node one"}),
            ]
            self._edges = edge_rows or []

        def nodes(self, data=False):
            if data:
                return list(self._nodes)
            return [nid for nid, _ in self._nodes]

        def edges(self, data=False):
            if data:
                return list(self._edges)
            return [(u, v) for u, v, _ in self._edges]

    class DummyGraphStore:
        def __init__(self, world_id: str):
            self.world_id = world_id
            self.graph = DummyGraph()
            self._node_lookup = {nid: attrs for nid, attrs in self.graph.nodes(data=True)}

        def get_bfs_neighborhood(self, start_nodes: list[str], hops: int, max_nodes: int) -> list[dict]:
            telemetry["bfs_start_nodes"] = list(start_nodes)
            telemetry["bfs_hops"] = hops
            telemetry["bfs_max_nodes"] = max_nodes
            return list(bfs_nodes)

        def get_node_count(self) -> int:
            return len(self.graph.nodes())

        def get_node(self, node_id: str) -> dict | None:
            attrs = self._node_lookup.get(node_id)
            if not attrs:
                return None
            return {
                "id": node_id,
                "display_name": attrs.get("display_name", node_id),
                "description": attrs.get("description", ""),
                "entity_type": attrs.get("entity_type", "Unknown"),
            }

    class DummyVectorStore:
        def __init__(self, world_id: str, collection_suffix: str | None = None, embedding_model: str | None = None):
            self.world_id = world_id
            self.collection_suffix = collection_suffix

        def embed_text(self, query: str, api_key: str) -> list[float]:
            telemetry["embedded_query"] = query
            return [0.1, 0.2, 0.3]

        def query_by_embedding(self, query_embedding: list[float], n_results: int) -> list[dict]:
            if self.collection_suffix == "unique_nodes":
                telemetry["node_query_n_results"] = n_results
                return list(node_results or [])
            telemetry["chunk_query_n_results"] = n_results
            return list(chunk_results or [])

        def count(self) -> int:
            if self.collection_suffix == "unique_nodes":
                if node_vector_count is not None:
                    return node_vector_count
                return len(graph_nodes or [])
            if chunk_vector_count is not None:
                return chunk_vector_count
            return len(chunk_results or [])

    class DummyKeyManager:
        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
            return "test-key", 0

    monkeypatch.setattr(retrieval_engine, "GraphStore", DummyGraphStore)
    monkeypatch.setattr(retrieval_engine, "VectorStore", DummyVectorStore)
    monkeypatch.setattr(retrieval_engine, "get_key_manager", lambda: DummyKeyManager())
    monkeypatch.setattr(
        retrieval_engine,
        "load_settings",
        lambda: settings
        or {
            "retrieval_top_k_chunks": 5,
            "retrieval_entry_top_k_nodes": 2,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )
    resolved_chunk_vectors = chunk_vector_count if chunk_vector_count is not None else len(chunk_results or [])
    resolved_node_vectors = node_vector_count if node_vector_count is not None else len(graph_nodes or [])
    monkeypatch.setattr(
        retrieval_engine,
        "get_ingestion_audit_snapshot",
        lambda world_id, synthesize_failures=False, persist=False: health_summary
        or {
            "world": {
                "expected_chunks": total_chunks,
                "embedded_chunks": resolved_chunk_vectors,
                "expected_node_vectors": len(graph_nodes or []),
                "embedded_node_vectors": resolved_node_vectors,
            },
            "blocking_issues": [],
        },
    )
    return telemetry


def test_retrieve_defaults_missing_entity_type_to_unknown(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "node-1", "display_name": "Rudeus Greyrat", "description": "A mage"},
        ],
        graph_nodes=[
            ("node-1", {"display_name": "Rudeus Greyrat", "description": "A mage"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "Chunk one"}],
        node_results=[{"id": "node-1"}],
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("Who is Rudeus?")

    assert result["graph_nodes"] == [
        {
            "id": "node-1",
            "display_name": "Rudeus Greyrat",
            "entity_type": "Unknown",
        }
    ]


def test_retrieve_preserves_existing_entity_type(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {
                "id": "node-2",
                "display_name": "Roxy Migurdia",
                "entity_type": "Person",
                "description": "Water mage",
            },
        ],
        graph_nodes=[
            ("node-2", {"display_name": "Roxy Migurdia", "entity_type": "Person", "description": "Water mage"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "Chunk one"}],
        node_results=[{"id": "node-2"}],
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("Who is Roxy?")

    assert result["graph_nodes"] == [
        {
            "id": "node-2",
            "display_name": "Roxy Migurdia",
            "entity_type": "Person",
        }
    ]


def test_retrieve_uses_node_vectors_for_entry_nodes_not_chunk_provenance(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "uuid-entry", "display_name": "Entry Node", "description": "Entry desc"},
        ],
        graph_nodes=[
            ("uuid-rag", {"display_name": "RAG Node", "description": "Rag desc"}),
            ("uuid-entry", {"display_name": "Entry Node", "description": "Entry desc"}),
        ],
        chunk_results=[
            {"id": "chunk-rag", "document": "rag chunk"},
        ],
        node_results=[
            {"id": "uuid-entry", "document": "entry node"},
        ],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert telemetry["bfs_start_nodes"] == ["uuid-entry"]
    assert [chunk["id"] for chunk in result["rag_chunks"]] == ["chunk-rag"]
    assert result["retrieval_meta"]["node_seeded_retrieval_used"] is True


def test_retrieve_uses_active_ingest_graph_session_without_loading_graph_from_disk(monkeypatch):
    class DummyGraph:
        def __init__(self):
            self._nodes = [("node-1", {"display_name": "Active Node", "description": "Session graph node"})]

        def nodes(self, data=False):
            if data:
                return list(self._nodes)
            return [node_id for node_id, _attrs in self._nodes]

        def edges(self, data=False):
            return []

    class DummySessionGraphStore:
        def __init__(self):
            self.graph = DummyGraph()

        def get_bfs_neighborhood(self, start_nodes: list[str], hops: int, max_nodes: int) -> list[dict]:
            return [{"id": "node-1", "display_name": "Active Node", "description": "Session graph node"}]

        def get_node_count(self) -> int:
            return 1

        def get_node(self, node_id: str) -> dict | None:
            if node_id != "node-1":
                return None
            return {
                "id": "node-1",
                "display_name": "Active Node",
                "description": "Session graph node",
                "entity_type": "Unknown",
            }

    class DummyVectorStore:
        def __init__(self, world_id: str, collection_suffix: str | None = None, embedding_model: str | None = None):
            self.collection_suffix = collection_suffix

        def embed_text(self, query: str, api_key: str) -> list[float]:
            return [0.1, 0.2]

        def query_by_embedding(self, query_embedding: list[float], n_results: int) -> list[dict]:
            if self.collection_suffix == "unique_nodes":
                return [{"id": "node-1"}]
            return [{"id": "chunk-1", "document": "chunk doc", "metadata": {"book_number": 1, "chunk_index": 0}}]

        def count(self) -> int:
            return 1

    class DummyKeyManager:
        def wait_for_available_key(self, *, jitter_seconds: float = 0.25):
            return "test-key", 0

    session_store = DummySessionGraphStore()
    monkeypatch.setattr(
        retrieval_engine,
        "get_active_ingest_graph_session",
        lambda world_id: type("Session", (), {"committed_store": session_store})(),
    )
    monkeypatch.setattr(
        retrieval_engine,
        "GraphStore",
        lambda world_id: (_ for _ in ()).throw(AssertionError("active ingest retrieval should not reload GraphStore from disk")),
    )
    monkeypatch.setattr(retrieval_engine, "VectorStore", DummyVectorStore)
    monkeypatch.setattr(retrieval_engine, "get_key_manager", lambda: DummyKeyManager())
    monkeypatch.setattr(
        retrieval_engine,
        "load_settings",
        lambda: {
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 1,
            "retrieval_max_nodes": 10,
        },
    )
    monkeypatch.setattr(
        retrieval_engine,
        "get_ingestion_audit_snapshot",
        lambda world_id, synthesize_failures=False, persist=False: {
            "world": {
                "expected_chunks": 1,
                "embedded_chunks": 1,
                "expected_node_vectors": 1,
                "embedded_node_vectors": 1,
            },
            "blocking_issues": [],
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert result["graph_nodes"] == [
        {
            "id": "node-1",
            "display_name": "Active Node",
            "entity_type": "Unknown",
        }
    ]


def test_retrieve_queries_full_unique_node_index_before_selecting_entry_nodes(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "uuid-entry-a", "display_name": "Entry A", "description": "A"},
            {"id": "uuid-entry-b", "display_name": "Entry B", "description": "B"},
        ],
        graph_nodes=[
            ("uuid-entry-a", {"display_name": "Entry A", "description": "A"}),
            ("uuid-entry-b", {"display_name": "Entry B", "description": "B"}),
            ("uuid-entry-c", {"display_name": "Entry C", "description": "C"}),
        ],
        chunk_results=[{"id": "chunk-rag", "document": "rag chunk"}],
        node_results=[
            {"id": "uuid-entry-a"},
            {"id": "uuid-entry-b"},
            {"id": "uuid-entry-c"},
        ],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 2,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
        node_vector_count=3,
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert telemetry["node_query_n_results"] == 3
    assert result["retrieval_meta"]["entry_index_kind"] == "unique_nodes"
    assert result["retrieval_meta"]["selected_entry_nodes"] == 2


def test_retrieve_uses_node_id_metadata_for_chunk_scoped_node_vectors(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "uuid-entry", "display_name": "Entry Node", "description": "Entry desc"},
        ],
        graph_nodes=[
            ("uuid-entry", {"display_name": "Entry Node", "description": "Entry desc"}),
        ],
        chunk_results=[{"id": "chunk-rag", "document": "rag chunk"}],
        node_results=[
            {
                "id": "chunk_world-1_source-a_0::node::uuid-entry",
                "metadata": {"node_id": "uuid-entry"},
                "document": "entry node",
            }
        ],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    entry_nodes = engine._entry_nodes_from_query_results(
        [
            {
                "id": "chunk_world-1_source-a_0::node::uuid-entry",
                "metadata": {"node_id": "uuid-entry"},
                "document": "entry node",
            }
        ],
        requested=1,
    )

    assert [node["id"] for node in entry_nodes] == ["uuid-entry"]


def test_retrieve_context_keeps_graph_dedup_and_edge_dedup(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "g1", "display_name": "Node A", "description": "descA\ndescA\ndescB"},
            {"id": "g2", "display_name": "Node A", "description": "descB\ndescC"},
            {"id": "g3", "display_name": "Node B", "description": "descX\ndescX"},
            {"id": "g4", "display_name": "Node B", "description": "descY"},
        ],
        graph_nodes=[
            ("g1", {"display_name": "Node A", "description": "entryA\nentryA"}),
            ("g2", {"display_name": "Node A", "description": "entryB"}),
            ("g3", {"display_name": "Node B", "description": "graphB1"}),
            ("g4", {"display_name": "Node B", "description": "graphB2"}),
        ],
        edge_rows=[
            ("g3", "g4", {"label": "", "description": "knows", "source_book": 1, "source_chunk": 2}),
            ("g3", "g4", {"label": "", "description": "knows", "source_book": 1, "source_chunk": 2}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "same rag chunk"}],
        node_results=[{"id": "g1"}],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context = result["context_string"]

    assert "# Entry Nodes" in context
    assert context.index("# Entry Nodes") < context.index("# Graph Nodes")
    assert "Node A: entryA" in context
    assert "Node A: descB descC" in context
    assert "Node B: descX descX" in context
    assert "Node B: descY" in context
    assert context.count("[B1:C2] Node B, knows, Node B") == 1


def test_retrieve_context_sorts_graph_edges_by_book_then_chunk(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "g1", "display_name": "Node One", "description": "desc1"},
            {"id": "g2", "display_name": "Node Two", "description": "desc2"},
            {"id": "g3", "display_name": "Node Three", "description": "desc3"},
        ],
        graph_nodes=[
            ("g1", {"display_name": "Node One", "description": "desc1"}),
            ("g2", {"display_name": "Node Two", "description": "desc2"}),
            ("g3", {"display_name": "Node Three", "description": "desc3"}),
        ],
        edge_rows=[
            ("g1", "g2", {"label": "", "description": "late in book one", "source_book": 1, "source_chunk": 57}),
            ("g2", "g3", {"label": "", "description": "early in book two", "source_book": 2, "source_chunk": 0}),
            ("g3", "g1", {"label": "", "description": "early in book one", "source_book": 1, "source_chunk": 0}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "g1"}],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context = result["context_string"]

    first_edge = "[B1:C0] Node Three, early in book one, Node One"
    second_edge = "[B1:C57] Node One, late in book one, Node Two"
    third_edge = "[B2:C0] Node Two, early in book two, Node Three"

    assert first_edge in context
    assert second_edge in context
    assert third_edge in context
    assert context.index(first_edge) < context.index(second_edge)
    assert context.index(second_edge) < context.index(third_edge)


def test_retrieve_preserves_chunk_tags_and_sorts_rag_chunks_by_book_then_chunk(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "g1", "display_name": "Node One", "description": "desc1"},
        ],
        graph_nodes=[
            ("g1", {"display_name": "Node One", "description": "desc1"}),
        ],
        chunk_results=[
            {
                "id": "chunk-b2-c0",
                "document": "[B2:C0] Later chunk",
                "metadata": {"book_number": 2, "chunk_index": 0},
            },
            {
                "id": "chunk-b1-c7",
                "document": "[B1:C7] Earlier chunk in same book",
                "metadata": {"book_number": 1, "chunk_index": 7},
            },
            {
                "id": "chunk-b1-c0",
                "document": "[B1:C0] Earliest chunk",
                "metadata": {"book_number": 1, "chunk_index": 0},
            },
        ],
        node_results=[{"id": "g1"}],
        settings={
            "retrieval_top_k_chunks": 3,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context = result["context_string"]

    first_chunk = "[B1:C0] Earliest chunk"
    second_chunk = "[B1:C7] Earlier chunk in same book"
    third_chunk = "[B2:C0] Later chunk"

    assert first_chunk in context
    assert second_chunk in context
    assert third_chunk in context
    assert context.index(first_chunk) < context.index(second_chunk)
    assert context.index(second_chunk) < context.index(third_chunk)


def test_retrieve_rag_chunks_dedup_only_by_chunk_id(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "g1", "display_name": "Node One", "description": "desc1"},
        ],
        graph_nodes=[
            ("g1", {"display_name": "Node One", "description": "desc1"}),
        ],
        chunk_results=[
            {
                "id": "chunk-a",
                "document": "[B1:C0] Shared text",
                "metadata": {"book_number": 1, "chunk_index": 0},
            },
            {
                "id": "chunk-a",
                "document": "[B1:C0] Shared text",
                "metadata": {"book_number": 1, "chunk_index": 0},
            },
            {
                "id": "chunk-b",
                "document": "[B1:C1] Shared text",
                "metadata": {"book_number": 1, "chunk_index": 1},
            },
        ],
        node_results=[{"id": "g1"}],
        settings={
            "retrieval_top_k_chunks": 3,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context = result["context_string"]

    assert context.count("[B1:C0] Shared text") == 1
    assert context.count("[B1:C1] Shared text") == 1


def test_retrieve_builds_context_graph_snapshot_from_real_nodes_and_sorted_edges(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "entry-1", "display_name": "2B", "description": "Entry desc"},
            {"id": "g2", "display_name": "9S", "description": "Graph desc one\nGraph desc two"},
            {"id": "g3", "display_name": "2B", "description": "Graph desc three"},
        ],
        graph_nodes=[
            ("entry-1", {"display_name": "2B", "description": "Entry desc"}),
            ("g2", {"display_name": "9S", "description": "Graph desc one\nGraph desc two"}),
            ("g3", {"display_name": "2B", "description": "Graph desc three"}),
        ],
        edge_rows=[
            ("entry-1", "g2", {"label": "", "description": "later edge", "source_book": 1, "source_chunk": 5}),
            ("g2", "g3", {"label": "", "description": "earlier edge", "source_book": 1, "source_chunk": 0}),
            ("g2", "g3", {"label": "", "description": "earlier edge", "source_book": 1, "source_chunk": 0}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "entry-1"}],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context_graph = result["context_graph"]

    assert context_graph["schema_version"] == "context_graph.v2"
    assert [(node["id"], node["label"], node["is_entry_node"]) for node in context_graph["nodes"]] == [
        ("entry-1", "2B", True),
        ("g3", "2B", False),
        ("g2", "9S", False),
    ]
    assert context_graph["nodes"][0]["description"] == "Entry desc"
    assert context_graph["nodes"][1]["description"] == "Graph desc three"
    assert context_graph["edges"] == [
        {
            "source": "g2",
            "target": "g3",
            "description": "earlier edge",
            "strength": 1,
            "source_book": 1,
            "source_chunk": 0,
        },
        {
            "source": "entry-1",
            "target": "g2",
            "description": "later edge",
            "strength": 1,
            "source_book": 1,
            "source_chunk": 5,
        },
    ]
    assert context_graph["nodes"][0]["connection_count"] == 1
    assert context_graph["nodes"][0]["neighbors"][0]["id"] == "g2"
    assert context_graph["nodes"][1]["neighbors"][0]["label"] == "9S"


def test_retrieve_preserves_duplicate_display_names_in_model_context(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "entry-1", "display_name": "Command", "description": "Entry version"},
            {"id": "graph-2", "display_name": "Command", "description": "Expanded version"},
        ],
        graph_nodes=[
            ("entry-1", {"display_name": "Command", "description": "Entry version"}),
            ("graph-2", {"display_name": "Command", "description": "Expanded version"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "entry-1"}],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context = result["context_string"]

    assert context.count("Command: Entry version") == 1
    assert context.count("Command: Expanded version") == 1
    assert result["context_graph"]["nodes"] == [
        {
            "id": "entry-1",
            "label": "Command",
            "description": "Entry version",
            "entity_type": "Unknown",
            "is_entry_node": True,
            "connection_count": 0,
            "neighbors": [],
        },
        {
            "id": "graph-2",
            "label": "Command",
            "description": "Expanded version",
            "entity_type": "Unknown",
            "is_entry_node": False,
            "connection_count": 0,
            "neighbors": [],
        },
    ]


def test_retrieve_entry_nodes_are_excluded_from_graph_nodes_section(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "g1", "display_name": "Entry X", "description": "desc"},
        ],
        graph_nodes=[
            ("g1", {"display_name": "Entry X", "description": "entrydesc"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "g1"}],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")
    context = result["context_string"]

    assert "# Entry Nodes" in context
    assert "Entry X: entrydesc" in context
    assert "# Graph Nodes" not in context


def test_retrieve_force_all_when_entry_nodes_at_or_above_total(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "n1", "display_name": "N1", "description": "d1"},
        ],
        graph_nodes=[
            ("n1", {"display_name": "N1", "description": "d1"}),
            ("n2", {"display_name": "N2", "description": "d2"}),
            ("n3", {"display_name": "N3", "description": "d3"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 999,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 1,
        },
        total_chunks=1,
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert "bfs_start_nodes" not in telemetry
    assert len(result["graph_nodes"]) == 3
    assert result["retrieval_meta"]["force_all_nodes"] is True


def test_retrieve_falls_back_to_chunk_only_when_node_vectors_are_missing(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[],
        graph_nodes=[
            ("n1", {"display_name": "N1", "description": "d1"}),
            ("n2", {"display_name": "N2", "description": "d2"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[],
        total_chunks=1,
        node_vector_count=0,
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert result["rag_chunks"] == [{"id": "chunk-1", "document": "seed"}]
    assert result["graph_nodes"] == []
    assert telemetry.get("node_query_n_results") is None
    assert result["retrieval_meta"]["node_seeded_retrieval_used"] is False
    assert result["retrieval_meta"]["node_index_usable"] is False


def test_retrieve_falls_back_to_chunk_only_when_unique_node_store_is_unreadable(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[],
        graph_nodes=[
            ("n1", {"display_name": "N1", "description": "d1"}),
            ("n2", {"display_name": "N2", "description": "d2"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[],
        total_chunks=1,
        node_vector_count=1,
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
        health_summary={
            "world": {
                "expected_chunks": 1,
                "embedded_chunks": 1,
                "expected_node_vectors": 1,
                "embedded_node_vectors": 1,
            },
            "blocking_issues": [
                {
                    "code": "unique_node_vector_store_unreadable",
                    "message": "Could not read the unique-node index while auditing this world.",
                }
            ],
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert result["rag_chunks"] == [{"id": "chunk-1", "document": "seed"}]
    assert result["graph_nodes"] == []
    assert telemetry.get("node_query_n_results") is None
    assert result["retrieval_meta"]["node_seeded_retrieval_used"] is False
    assert result["retrieval_meta"]["node_index_usable"] is False


def test_retrieve_uses_partial_node_index_when_some_node_vectors_exist(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "n1", "display_name": "N1", "description": "d1"},
            {"id": "n2", "display_name": "N2", "description": "d2"},
        ],
        graph_nodes=[
            ("n1", {"display_name": "N1", "description": "d1"}),
            ("n2", {"display_name": "N2", "description": "d2"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "n1"}],
        total_chunks=1,
        node_vector_count=1,
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
        health_summary={
            "world": {
                "expected_chunks": 1,
                "embedded_chunks": 1,
                "expected_node_vectors": 2,
                "embedded_node_vectors": 1,
            },
            "blocking_issues": [],
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert telemetry["node_query_n_results"] == 1
    assert telemetry["bfs_start_nodes"] == ["n1"]
    assert [node["id"] for node in result["graph_nodes"]] == ["n1", "n2"]
    assert result["retrieval_meta"]["node_seeded_retrieval_used"] is True
    assert result["retrieval_meta"]["node_index_usable"] is True
    assert result["retrieval_meta"]["node_index_complete"] is False


def test_retrieve_allows_partial_chunk_vectors_without_blocking_chat(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[],
        graph_nodes=[
            ("n1", {"display_name": "N1", "description": "d1"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[],
        total_chunks=3,
        chunk_vector_count=1,
        node_vector_count=0,
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert result["rag_chunks"] == [{"id": "chunk-1", "document": "seed"}]
    assert result["retrieval_meta"]["chunk_index_usable"] is True
    assert result["retrieval_meta"]["chunk_index_complete"] is False
    assert result["retrieval_meta"]["retrieval_blocked"] is False


def test_retrieve_allows_graph_only_fallback_when_chunk_vectors_are_missing(monkeypatch):
    telemetry = _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "n1", "display_name": "Node One", "description": "d1"},
        ],
        graph_nodes=[
            ("n1", {"display_name": "Node One", "description": "d1"}),
        ],
        chunk_results=[],
        node_results=[{"id": "n1"}],
        total_chunks=3,
        chunk_vector_count=0,
        node_vector_count=1,
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert result["rag_chunks"] == []
    assert [node["id"] for node in result["graph_nodes"]] == ["n1"]
    assert result["retrieval_meta"]["chunk_index_usable"] is True
    assert result["retrieval_meta"]["chunk_index_complete"] is False
    assert result["retrieval_meta"]["node_seeded_retrieval_used"] is True


def test_retrieve_uses_shared_health_summary_instead_of_raw_node_counts(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[
            {"id": "n1", "display_name": "Node One", "description": "d1"},
        ],
        graph_nodes=[
            ("n1", {"display_name": "Node One", "description": "d1"}),
            ("orphan", {"display_name": "Orphan Node", "description": "legacy"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[{"id": "n1"}],
        node_vector_count=1,
        settings={
            "retrieval_top_k_chunks": 1,
            "retrieval_entry_top_k_nodes": 1,
            "retrieval_graph_hops": 2,
            "retrieval_max_nodes": 20,
        },
        health_summary={
            "world": {
                "expected_chunks": 1,
                "embedded_chunks": 1,
                "expected_node_vectors": 1,
                "embedded_node_vectors": 1,
            },
            "blocking_issues": [],
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert [node["id"] for node in result["graph_nodes"]] == ["n1"]


def test_retrieve_keeps_nonvector_blockers_as_passive_metadata(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[],
        graph_nodes=[
            ("n1", {"display_name": "Node One", "description": "d1"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[],
        health_summary={
            "world": {
                "expected_chunks": 1,
                "embedded_chunks": 1,
                "expected_node_vectors": 1,
                "embedded_node_vectors": 1,
            },
            "blocking_issues": [
                {
                    "code": "graph_nodes_missing_chunk_provenance",
                    "message": "Some graph nodes have no chunk provenance, so Re-embed All cannot rebuild all node vectors. Use Rechunk And Re-ingest to rebuild the graph and vectors together.",
                    "count": 1,
                }
            ],
        },
    )

    engine = retrieval_engine.RetrievalEngine("world-1")
    result = engine.retrieve("test query")

    assert result["rag_chunks"] == [{"id": "chunk-1", "document": "seed"}]
    assert result["retrieval_meta"]["passive_blockers"] == [
        {
            "code": "graph_nodes_missing_chunk_provenance",
            "message": "Some graph nodes have no chunk provenance, so Re-embed All cannot rebuild all node vectors. Use Rechunk And Re-ingest to rebuild the graph and vectors together.",
            "count": 1,
        }
    ]
