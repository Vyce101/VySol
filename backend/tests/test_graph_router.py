import asyncio
from pathlib import Path

import networkx as nx

from core.graph_store import GraphStore, clear_active_ingest_graph_session, create_active_ingest_graph_session
from routers import graph as graph_router


def test_graph_routes_use_active_ingest_session(monkeypatch):
    world_id = "world-graph-session"
    monkeypatch.setattr(graph_router, "world_meta_path", lambda _world_id: Path(__file__))

    graph = nx.MultiDiGraph()
    graph.add_node(
        "node-a",
        node_id="node-a",
        display_name="Alpha Node",
        normalized_id="alpha_node",
        description="Alpha description",
        claims=[],
        source_chunks=["chunk_world-graph-session_source-a_0"],
        created_at="2026-03-25T00:00:00+00:00",
        updated_at="2026-03-25T00:00:00+00:00",
    )
    graph.add_node(
        "node-b",
        node_id="node-b",
        display_name="Beta Node",
        normalized_id="beta_node",
        description="Beta description",
        claims=[],
        source_chunks=["chunk_world-graph-session_source-a_0"],
        created_at="2026-03-25T00:00:00+00:00",
        updated_at="2026-03-25T00:00:00+00:00",
    )
    graph.add_edge(
        "node-a",
        "node-b",
        key="edge-a-b",
        edge_id="edge-a-b",
        source_node_id="node-a",
        target_node_id="node-b",
        description="Alpha supports Beta",
        strength=7,
        source_book=1,
        source_chunk=0,
        created_at="2026-03-25T00:00:00+00:00",
    )
    store = GraphStore.from_graph(world_id, graph)
    create_active_ingest_graph_session(world_id, store, read_cache=store.build_read_cache())

    monkeypatch.setattr(
        graph_router,
        "GraphStore",
        lambda _world_id: (_ for _ in ()).throw(AssertionError("active graph session should bypass disk GraphStore loads")),
    )

    try:
        payload = asyncio.run(graph_router.get_graph(world_id))
        node = asyncio.run(graph_router.get_node(world_id, "node-a"))
        results = asyncio.run(graph_router.search_graph(world_id, "alpha"))
    finally:
        clear_active_ingest_graph_session(world_id)

    assert len(payload["nodes"]) == 2
    assert len(payload["edges"]) == 1
    assert node["display_name"] == "Alpha Node"
    assert node["neighbors"][0]["id"] == "node-b"
    assert results == [{"id": "node-a", "label": "Alpha Node", "claim_count": 0}]
