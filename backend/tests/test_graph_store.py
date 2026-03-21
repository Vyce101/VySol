from pathlib import Path
import shutil
import uuid

from core import graph_store


def _make_store(monkeypatch) -> graph_store.GraphStore:
    scratch_root = Path(__file__).resolve().parent / "_graph_store_tmp"
    scratch_root.mkdir(parents=True, exist_ok=True)
    graph_path = scratch_root / f"{uuid.uuid4()}.gexf"
    monkeypatch.setattr(graph_store, "world_graph_path", lambda world_id: graph_path)
    return graph_store.GraphStore("world-1")


def test_get_all_data_counts_bidirectional_unique_neighbors(monkeypatch):
    store = _make_store(monkeypatch)
    store.graph.add_node("a", display_name="A", description="", claims=[], source_chunks=[])
    store.graph.add_node("b", display_name="B", description="", claims=[], source_chunks=[])
    store.graph.add_node("c", display_name="C", description="", claims=[], source_chunks=[])
    store.graph.add_edge("a", "b", description="a to b", strength=1)
    store.graph.add_edge("c", "a", description="c to a", strength=1)

    data = store.get_all_data()
    counts = {node["id"]: node["connection_count"] for node in data["nodes"]}

    assert counts["a"] == 2
    assert counts["b"] == 1
    assert counts["c"] == 1


def test_get_all_data_deduplicates_parallel_edges(monkeypatch):
    store = _make_store(monkeypatch)
    store.graph.add_node("a", display_name="A", description="", claims=[], source_chunks=[])
    store.graph.add_node("b", display_name="B", description="", claims=[], source_chunks=[])
    store.graph.add_edge("a", "b", description="first", strength=1)
    store.graph.add_edge("a", "b", description="second", strength=2)
    store.graph.add_edge("b", "a", description="third", strength=3)

    data = store.get_all_data()
    counts = {node["id"]: node["connection_count"] for node in data["nodes"]}

    assert counts["a"] == 1
    assert counts["b"] == 1


def test_get_all_data_ignores_self_loops(monkeypatch):
    store = _make_store(monkeypatch)
    store.graph.add_node("solo", display_name="Solo", description="", claims=[], source_chunks=[])
    store.graph.add_edge("solo", "solo", description="loop", strength=1)

    data = store.get_all_data()

    assert data["nodes"][0]["connection_count"] == 0


def test_get_all_data_ignores_edges_with_missing_endpoints(monkeypatch):
    store = _make_store(monkeypatch)
    store.graph.add_node("a", display_name="A", description="", claims=[], source_chunks=[])
    store.graph.add_node("b", display_name="B", description="", claims=[], source_chunks=[])
    monkeypatch.setattr(
        store,
        "_iter_edge_rows",
        lambda: iter(
            [
                ("a", "b", {"description": "real", "strength": 1}),
                ("a", "ghost", {"description": "broken", "strength": 1}),
            ]
        ),
    )

    data = store.get_all_data()
    counts = {node["id"]: node["connection_count"] for node in data["nodes"]}

    assert counts["a"] == 1
    assert counts["b"] == 1


def test_get_node_neighbors_are_bidirectional_and_deduplicated(monkeypatch):
    store = _make_store(monkeypatch)
    store.graph.add_node("a", display_name="A", description="", claims=[], source_chunks=[])
    store.graph.add_node("b", display_name="B", description="", claims=[], source_chunks=[])
    store.graph.add_node("c", display_name="C", description="", claims=[], source_chunks=[])
    store.graph.add_edge("a", "b", description="first link", strength=1)
    store.graph.add_edge("b", "a", description="return link", strength=1)
    store.graph.add_edge("c", "a", description="incoming link", strength=1)

    node = store.get_node("a")

    assert node is not None
    assert node["connection_count"] == 2
    assert [neighbor["id"] for neighbor in node["neighbors"]] == ["b", "c"]
    assert {neighbor["description"] for neighbor in node["neighbors"]} == {"first link", "incoming link"}


def test_upsert_edge_prefers_direct_node_ids_over_normalized_lookup(monkeypatch):
    store = _make_store(monkeypatch)
    old_2b = store.upsert_node("2B", "2B", "Old 2B")
    new_2b = store.upsert_node("2B", "2B", "New 2B")
    scanner = store.upsert_node("9S", "9S", "Scanner")

    edge_id = store.upsert_edge(new_2b, scanner, "Partners with", 7, 1, 0)

    assert edge_id is not None
    matching_edges = [
        attrs
        for source, target, attrs in store._iter_edge_rows()
        if source == new_2b and target == scanner
    ]
    assert len(matching_edges) == 1
    assert matching_edges[0]["source_node_id"] == new_2b
    assert all(source != old_2b for source, _, _ in store._iter_edge_rows())


def teardown_module(module):
    scratch_root = Path(__file__).resolve().parent / "_graph_store_tmp"
    if scratch_root.exists():
        shutil.rmtree(scratch_root, ignore_errors=True)
