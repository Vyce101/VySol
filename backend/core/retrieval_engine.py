"""Hybrid retrieval: vector search + BFS graph walk → context assembly."""

from __future__ import annotations

import logging

from .config import load_settings
from .graph_store import GraphStore
from .ingestion_engine import audit_ingestion_integrity
from .key_manager import get_key_manager
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


def _get_provider_key_manager(provider: str):
    try:
        return get_key_manager(provider)
    except TypeError:
        return get_key_manager()


def _edge_temporal_sort_key(edge: dict) -> tuple[int, int]:
    raw_book = edge.get("source_book", 0)
    raw_chunk = edge.get("source_chunk", 0)

    try:
        book = int(raw_book)
    except (TypeError, ValueError):
        book = 0

    try:
        chunk = int(raw_chunk)
    except (TypeError, ValueError):
        chunk = 0

    return book, chunk


def _chunk_temporal_sort_key(chunk: dict) -> tuple[int, int, int]:
    metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
    raw_book = metadata.get("book_number", 0)
    raw_chunk = metadata.get("chunk_index", 0)

    try:
        book = int(raw_book)
        chunk_index = int(raw_chunk)
        return 0, book, chunk_index
    except (TypeError, ValueError):
        return 1, 0, 0


def _normalize_context_text(value: str) -> str:
    return " ".join(part.strip() for part in str(value or "").splitlines() if part.strip())


class RetrievalEngine:
    """Performs GraphRAG retrieval: vector query → graph walk → context assembly."""

    def __init__(self, world_id: str):
        self.world_id = world_id
        self.graph_store = GraphStore(world_id)
        self.chunk_vector_store = VectorStore(world_id)
        self.unique_node_vector_store = VectorStore(world_id, collection_suffix="unique_nodes")

    def retrieve(self, query: str, settings_override: dict | None = None) -> dict:
        """
        Run full retrieval pipeline.

        Returns {
            "context_string": str,
            "rag_chunks": list[dict],
            "graph_nodes": list[dict],
            "graph_edges": list[dict],
        }
        """
        settings = load_settings()
        if settings_override:
            settings.update(settings_override)

        try:
            top_k = max(1, int(settings.get("retrieval_top_k_chunks", 5)))
        except (TypeError, ValueError):
            top_k = 5

        entry_k = settings.get("retrieval_entry_top_k_nodes")
        if entry_k is None:
            # Backward compatibility for earlier key naming.
            entry_k = settings.get("retrieval_entry_top_k_chunks")
        if entry_k is None:
            entry_k = top_k
        try:
            entry_k = max(1, int(entry_k))
        except (TypeError, ValueError):
            entry_k = top_k
        hops = settings.get("retrieval_graph_hops", 2)
        max_nodes = settings.get("retrieval_max_nodes", 50)

        total_graph_nodes = self.graph_store.get_node_count()
        force_all = total_graph_nodes > 0 and entry_k >= total_graph_nodes

        # Step 1: Embed query once and validate retrieval health.
        embedding_provider = getattr(self.chunk_vector_store, "embedding_provider", "gemini")
        km = _get_provider_key_manager(embedding_provider)
        api_key, _ = km.wait_for_available_key()
        query_embedding = self.chunk_vector_store.embed_text(query, api_key)
        chunk_vector_count = self.chunk_vector_store.count()
        unique_node_vector_count = self.unique_node_vector_store.count()
        health_summary = audit_ingestion_integrity(
            self.world_id,
            synthesize_failures=False,
            persist=False,
        )
        self._validate_retrieval_health(health_summary)

        # Step 2: Chunk vector query for evidence/RAG excerpts.
        query_n_results = max(top_k, chunk_vector_count) if chunk_vector_count > 0 else top_k
        vector_results = self.chunk_vector_store.query_by_embedding(
            query_embedding,
            n_results=query_n_results,
        )
        rag_results = vector_results[:top_k]

        # Step 3: Node vector query for graph entry points.
        node_query_n_results = max(0, unique_node_vector_count)
        node_results = (
            self.unique_node_vector_store.query_by_embedding(
                query_embedding,
                n_results=node_query_n_results,
            )
            if node_query_n_results > 0
            else []
        )
        entry_nodes = self._entry_nodes_from_query_results(
            node_results=node_results,
            requested=entry_k,
        )
        matched_node_ids = {node.get("id", "") for node in entry_nodes if node.get("id")}

        # Step 4: Graph node selection
        graph_nodes = []
        if force_all:
            graph_nodes = self._all_graph_nodes()
        elif matched_node_ids:
            graph_nodes = self.graph_store.get_bfs_neighborhood(
                start_nodes=sorted(matched_node_ids),
                hops=hops,
                max_nodes=max_nodes,
            )

        # Step 5: Collect relationships
        graph_edges = []
        node_ids = {n.get("id", "") for n in graph_nodes}
        for u, v, attrs in self.graph_store.graph.edges(data=True):
            if u in node_ids and v in node_ids:
                u_node = self.graph_store.get_node(u) or {}
                v_node = self.graph_store.get_node(v) or {}
                u_name = u_node.get("display_name", u)
                v_name = v_node.get("display_name", v)
                graph_edges.append({
                    "source_id": u,
                    "target_id": v,
                    "source_label": u_name,
                    "target_label": v_name,
                    "source": u_name,
                    "target": v_name,
                    "label": attrs.get("label", ""),
                    "description": attrs.get("description", ""),
                    "source_book": attrs.get("source_book", 0),
                    "source_chunk": attrs.get("source_chunk", 0),
                })

        # Step 6: Assemble context string
        context = self._assemble_context(rag_results, entry_nodes, graph_nodes, graph_edges)
        context_graph = self._build_context_graph_snapshot(entry_nodes, graph_nodes, graph_edges)

        serialized_nodes = []
        for node in graph_nodes:
            node_id = node.get("id", "")
            display_name = node.get("display_name") or node_id or "Unknown"
            entity_type = node.get("entity_type") or "Unknown"
            serialized_nodes.append({
                "id": node_id,
                "display_name": display_name,
                "entity_type": entity_type,
            })

        return {
            "context_string": context,
            "rag_chunks": rag_results,
            "graph_nodes": serialized_nodes,
            "graph_edges": graph_edges,
            "context_graph": context_graph,
            "retrieval_meta": {
                "requested_entry_nodes": entry_k,
                "selected_entry_nodes": len(entry_nodes),
                "total_graph_nodes": total_graph_nodes,
                "force_all_nodes": force_all,
                "ranked_entry_candidates": len(node_results),
                "entry_backfill_count": 0,
                "vector_results_count": len(vector_results),
                "query_n_results": query_n_results,
                "node_query_results_count": len(node_results),
                "node_query_n_results": node_query_n_results,
                "chunk_vector_count": chunk_vector_count,
                "node_vector_count": unique_node_vector_count,
                "unique_node_vector_count": unique_node_vector_count,
                "entry_index_kind": "unique_nodes",
                "node_seeded_retrieval_used": True,
                "retrieval_blocked": False,
            },
        }

    def _validate_retrieval_health(
        self,
        health_summary: dict,
    ) -> None:
        world = health_summary.get("world", {}) if isinstance(health_summary, dict) else {}
        expected_chunks = max(0, int(world.get("expected_chunks", 0) or 0))
        embedded_chunks = max(0, int(world.get("embedded_chunks", 0) or 0))
        expected_node_vectors = max(0, int(world.get("expected_node_vectors", 0) or 0))
        embedded_node_vectors = max(0, int(world.get("embedded_node_vectors", 0) or 0))
        if expected_chunks > 0 and embedded_chunks <= 0:
            raise RuntimeError(
                "This world's chunk embeddings are missing. Use Re-embed All or Rechunk And Re-ingest to rebuild chunk and unique node vectors."
            )
        if expected_chunks > 0 and embedded_chunks < expected_chunks:
            raise RuntimeError(
                "This world's chunk embeddings are incomplete. Use Re-embed All or Rechunk And Re-ingest to rebuild chunk and unique node vectors."
            )
        blocking_issues = health_summary.get("blocking_issues", []) if isinstance(health_summary, dict) else []
        if blocking_issues:
            first_issue = blocking_issues[0]
            raise RuntimeError(
                str(first_issue.get("message") or "This world's graph/vector state requires Rechunk And Re-ingest.")
            )
        if expected_node_vectors > 0 and embedded_node_vectors <= 0:
            raise RuntimeError(
                "This world's unique graph-node embeddings are missing. Run Re-embed All to rebuild chunk and unique node vectors."
            )
        if expected_node_vectors > 0 and embedded_node_vectors < expected_node_vectors:
            raise RuntimeError(
                "This world's unique graph-node embeddings are incomplete. Run Re-embed All to rebuild chunk and unique node vectors."
            )

    def _assemble_context(
        self,
        rag_chunks: list[dict],
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
    ) -> str:
        parts = []
        entry_nodes_section = self._build_nodes_section("# Entry Nodes", entry_nodes)
        if entry_nodes_section:
            parts.append(entry_nodes_section)

        entry_node_ids = {str(node.get("id", "")) for node in entry_nodes if node.get("id")}
        graph_nodes_only = [
            node
            for node in graph_nodes
            if str(node.get("id", "")) not in entry_node_ids
        ]

        graph_nodes_section = self._build_nodes_section("# Graph Nodes", graph_nodes_only)
        if graph_nodes_section:
            parts.append(graph_nodes_section)

        # Edges
        if graph_edges:
            edge_strs = []
            unique_edges: set[tuple[str, str, str, int, int]] = set()
            for edge in sorted(graph_edges, key=_edge_temporal_sort_key):
                edge_identity = (
                    str(edge.get("source_id", edge.get("source", ""))),
                    str(edge.get("target_id", edge.get("target", ""))),
                    str(edge.get("description", "")),
                    int(edge.get("source_book", 0) or 0),
                    int(edge.get("source_chunk", 0) or 0),
                )
                if edge_identity in unique_edges:
                    continue

                unique_edges.add(edge_identity)
                edge_strs.append(self._format_context_edge_line(edge))
            parts.append("# Graph Edges\n" + "\n".join(edge_strs))

        # RAG Chunks
        if rag_chunks:
            chunk_strs = []
            seen_chunk_ids: set[str] = set()
            ordered_chunks = sorted(
                enumerate(rag_chunks),
                key=lambda item: (_chunk_temporal_sort_key(item[1]), item[0]),
            )
            for _, chunk in ordered_chunks:
                chunk_id = str(chunk.get("id", "") or "")
                if not chunk_id or chunk_id in seen_chunk_ids:
                    continue

                seen_chunk_ids.add(chunk_id)
                doc = chunk.get("document", "")
                if doc:
                    chunk_strs.append(doc)
            if chunk_strs:
                parts.append("# RAG Chunks\n" + "\n\n".join(chunk_strs))

        return "\n\n".join(parts)

    def _format_context_edge_line(self, edge: dict) -> str:
        s = edge.get("source_label") or edge.get("source", "?")
        t = edge.get("target_label") or edge.get("target", "?")
        desc = _normalize_context_text(edge.get("description", ""))
        book = edge.get("source_book", 0)
        chunk_id = edge.get("source_chunk", 0)
        temporal_prefix = f"[B{book}:C{chunk_id}] " if book or chunk_id else ""
        return f"{temporal_prefix}{s}, {desc}, {t}"

    def _build_nodes_section(self, heading: str, nodes: list[dict]) -> str:
        node_lines: list[str] = []
        seen_node_ids: set[str] = set()
        for node in nodes:
            node_id = str(node.get("id", "") or "")
            if not node_id or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            display_name = str(node.get("display_name") or node_id or "Unknown")
            description = _normalize_context_text(node.get("description", ""))
            node_lines.append(f"{display_name}: {description}")

        if not node_lines:
            return ""

        return heading + "\n" + "\n".join(node_lines)

    def _build_context_graph_snapshot(
        self,
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
    ) -> dict:
        entry_node_ids = {str(node.get("id", "")) for node in entry_nodes if node.get("id")}
        snapshot_nodes_by_id: dict[str, dict] = {}
        for node in [*entry_nodes, *graph_nodes]:
            node_id = str(node.get("id", "") or "")
            if not node_id:
                continue
            snapshot_nodes_by_id.setdefault(node_id, {
                "id": node_id,
                "label": str(node.get("display_name") or node_id or "Unknown"),
                "description": _normalize_context_text(node.get("description", "")),
                "entity_type": node.get("entity_type") or "Unknown",
                "is_entry_node": node_id in entry_node_ids,
            })

        ordered_edges: list[dict] = []
        seen_edges: set[tuple[str, str, str, int, int]] = set()

        for edge in sorted(graph_edges, key=_edge_temporal_sort_key):
            source_id = str(edge.get("source_id", "") or "")
            target_id = str(edge.get("target_id", "") or "")
            edge_identity = (
                source_id,
                target_id,
                str(edge.get("description", "")),
                int(edge.get("source_book", 0) or 0),
                int(edge.get("source_chunk", 0) or 0),
            )
            if edge_identity in seen_edges:
                continue

            seen_edges.add(edge_identity)
            source_name = str(edge.get("source_label") or edge.get("source") or source_id or "Unknown")
            target_name = str(edge.get("target_label") or edge.get("target") or target_id or "Unknown")
            snapshot_nodes_by_id.setdefault(source_id, {
                "id": source_id,
                "label": source_name,
                "description": "",
                "entity_type": "Unknown",
                "is_entry_node": source_id in entry_node_ids,
            })
            snapshot_nodes_by_id.setdefault(target_id, {
                "id": target_id,
                "label": target_name,
                "description": "",
                "entity_type": "Unknown",
                "is_entry_node": target_id in entry_node_ids,
            })
            ordered_edges.append({
                "source": source_id,
                "target": target_id,
                "description": _normalize_context_text(edge.get("description", "")),
                "strength": 1,
                "source_book": edge.get("source_book", 0),
                "source_chunk": edge.get("source_chunk", 0),
            })

        neighbor_map: dict[str, dict[str, str]] = {node_id: {} for node_id in snapshot_nodes_by_id}
        for edge in ordered_edges:
            source_id = edge["source"]
            target_id = edge["target"]
            description = edge.get("description", "") or ""

            if target_id not in neighbor_map[source_id]:
                neighbor_map[source_id][target_id] = description
            elif not neighbor_map[source_id][target_id] and description:
                neighbor_map[source_id][target_id] = description

            if source_id not in neighbor_map[target_id]:
                neighbor_map[target_id][source_id] = description
            elif not neighbor_map[target_id][source_id] and description:
                neighbor_map[target_id][source_id] = description

        serialized_nodes = []
        for node_id in sorted(snapshot_nodes_by_id, key=lambda value: ((snapshot_nodes_by_id[value].get("label") or value).lower(), value.lower())):
            snapshot_node = snapshot_nodes_by_id[node_id]
            neighbors = [
                {
                    "id": neighbor_id,
                    "label": snapshot_nodes_by_id.get(neighbor_id, {}).get("label", neighbor_id),
                    "description": neighbor_description,
                }
                for neighbor_id, neighbor_description in sorted(
                    neighbor_map.get(node_id, {}).items(),
                    key=lambda item: (
                        snapshot_nodes_by_id.get(item[0], {}).get("label", item[0]).lower(),
                        item[0].lower(),
                    ),
                )
            ]
            serialized_nodes.append({
                "id": node_id,
                "label": snapshot_node["label"],
                "description": snapshot_node["description"],
                "entity_type": snapshot_node["entity_type"],
                "is_entry_node": snapshot_node["is_entry_node"],
                "connection_count": len(neighbors),
                "neighbors": neighbors,
            })

        return {
            "schema_version": "context_graph.v2",
            "nodes": serialized_nodes,
            "edges": ordered_edges,
        }

    def _node_record(self, node_id: str, attrs: dict) -> dict:
        return {
            "id": node_id,
            "display_name": attrs.get("display_name", node_id),
            "description": attrs.get("description", ""),
            "entity_type": attrs.get("entity_type", "Unknown"),
        }

    def _entry_nodes_from_query_results(self, node_results: list[dict], requested: int) -> list[dict]:
        if requested <= 0:
            return []

        ranked: list[dict] = []
        seen: set[str] = set()
        for result in node_results:
            metadata = result.get("metadata", {}) or {}
            node_id = str(metadata.get("node_id") or result.get("id", ""))
            if not node_id or node_id in seen or node_id not in self.graph_store.graph.nodes():
                continue
            node_data = self.graph_store.get_node(node_id)
            if not node_data:
                continue
            seen.add(node_id)
            ranked.append(self._node_record(node_id, node_data))
            if len(ranked) >= requested:
                break
        return ranked

    def _all_graph_nodes(self) -> list[dict]:
        output: list[dict] = []
        for nid in sorted(self.graph_store.graph.nodes()):
            node_data = self.graph_store.get_node(nid)
            if node_data:
                output.append(node_data)
        return output
