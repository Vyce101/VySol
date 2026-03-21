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
        def get_active_key(self):
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
        "audit_ingestion_integrity",
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
    assert "Node B: descX descY" in context
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


def test_retrieve_builds_context_graph_snapshot_from_merged_nodes_and_sorted_edges(monkeypatch):
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

    assert context_graph["schema_version"] == "context_graph.v1"
    assert [node["label"] for node in context_graph["nodes"]] == ["2B", "9S"]
    assert context_graph["nodes"][0]["description"] == "Entry desc Graph desc three"
    assert context_graph["edges"] == [
        {
            "source": "9S",
            "target": "2B",
            "description": "earlier edge",
            "strength": 1,
            "source_book": 1,
            "source_chunk": 0,
        },
        {
            "source": "2B",
            "target": "9S",
            "description": "later edge",
            "strength": 1,
            "source_book": 1,
            "source_chunk": 5,
        },
    ]
    assert context_graph["nodes"][0]["connection_count"] == 1
    assert context_graph["nodes"][1]["neighbors"][0]["label"] == "2B"


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


def test_retrieve_blocks_when_node_vectors_are_missing(monkeypatch):
    _patch_retrieval_dependencies(
        monkeypatch,
        bfs_nodes=[],
        graph_nodes=[
            ("n1", {"display_name": "N1", "description": "d1"}),
        ],
        chunk_results=[{"id": "chunk-1", "document": "seed"}],
        node_results=[],
        total_chunks=1,
        node_vector_count=0,
    )

    engine = retrieval_engine.RetrievalEngine("world-1")

    with pytest.raises(RuntimeError) as exc:
        engine.retrieve("test query")

    assert "unique graph-node embeddings are missing" in str(exc.value)


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


def test_retrieve_surfaces_precise_blocking_issue_message(monkeypatch):
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

    with pytest.raises(RuntimeError) as exc:
        engine.retrieve("test query")

    assert "no chunk provenance" in str(exc.value)
