"""Hybrid retrieval: vector search + BFS graph walk → context assembly."""

from __future__ import annotations

import logging

from .config import load_settings
from .graph_store import GraphStore
from .ingestion_engine import audit_ingestion_integrity
from .key_manager import get_key_manager
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


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
        km = get_key_manager()
        api_key, _ = km.get_active_key()
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
            unique_edges = set()
            for edge in sorted(graph_edges, key=_edge_temporal_sort_key):
                s = edge.get("source", "?")
                t = edge.get("target", "?")
                desc = edge.get("description", "")
                book = edge.get("source_book", 0)
                chunk_id = edge.get("source_chunk", 0)
                temporal_prefix = f"[B{book}:C{chunk_id}] " if book or chunk_id else ""
                edge_str = f"{temporal_prefix}{s}, {desc}, {t}"
                if edge_str not in unique_edges:
                    unique_edges.add(edge_str)
                    edge_strs.append(edge_str)
            parts.append("# Graph Edges\n" + "\n".join(edge_strs))

        # RAG Chunks (scrubbed of B{X}:C{Y} tags and deduplicated)
        if rag_chunks:
            import re
            chunk_strs = []
            seen_chunks = set()
            for chunk in rag_chunks:
                doc = chunk.get("document", "")
                doc = re.sub(r"\[B\d+:C\d+\]\s*", "", doc).strip()
                if doc and doc not in seen_chunks:
                    seen_chunks.add(doc)
                    chunk_strs.append(doc)
            if chunk_strs:
                parts.append("# RAG Chunks\n" + "\n\n".join(chunk_strs))

        return "\n\n".join(parts)

    def _format_context_edge_line(self, edge: dict) -> str:
        s = edge.get("source", "?")
        t = edge.get("target", "?")
        desc = edge.get("description", "")
        book = edge.get("source_book", 0)
        chunk_id = edge.get("source_chunk", 0)
        temporal_prefix = f"[B{book}:C{chunk_id}] " if book or chunk_id else ""
        return f"{temporal_prefix}{s}, {desc}, {t}"

    def _merge_nodes_by_display_name(self, nodes: list[dict]) -> dict[str, dict]:
        unique_nodes: dict[str, dict] = {}
        for node in nodes:
            name = node.get("display_name", "Unknown")
            raw_desc = node.get("description", "").strip()
            desc_parts = [d.strip() for d in raw_desc.split('\n') if d.strip()]

            if name not in unique_nodes:
                unique_nodes[name] = {
                    "name": name,
                    "description_parts": [],
                    "entity_type": node.get("entity_type") or "Unknown",
                }

            merged_node = unique_nodes[name]
            if merged_node["entity_type"] in {"", "Unknown"} and node.get("entity_type"):
                merged_node["entity_type"] = node["entity_type"]

            for dp in desc_parts:
                if dp not in merged_node["description_parts"]:
                    merged_node["description_parts"].append(dp)

        return unique_nodes

    def _build_nodes_section(self, heading: str, nodes: list[dict]) -> str:
        unique_nodes = self._merge_nodes_by_display_name(nodes)

        if not unique_nodes:
            return ""

        node_strs = []
        for name, merged_node in unique_nodes.items():
            merged_desc = " ".join(merged_node["description_parts"])
            node_strs.append(f"{name}: {merged_desc}")
        return heading + "\n" + "\n".join(node_strs)

    def _build_context_graph_snapshot(
        self,
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
    ) -> dict:
        merged_nodes = self._merge_nodes_by_display_name([*entry_nodes, *graph_nodes])
        ordered_edges: list[dict] = []
        seen_edge_lines: set[str] = set()

        for edge in sorted(graph_edges, key=_edge_temporal_sort_key):
            edge_line = self._format_context_edge_line(edge)
            if edge_line in seen_edge_lines:
                continue

            seen_edge_lines.add(edge_line)
            source_name = edge.get("source", "?")
            target_name = edge.get("target", "?")
            description = edge.get("description", "")

            merged_nodes.setdefault(source_name, {
                "name": source_name,
                "description_parts": [],
                "entity_type": "Unknown",
            })
            merged_nodes.setdefault(target_name, {
                "name": target_name,
                "description_parts": [],
                "entity_type": "Unknown",
            })
            ordered_edges.append({
                "source": source_name,
                "target": target_name,
                "description": description,
                "strength": 1,
                "source_book": edge.get("source_book", 0),
                "source_chunk": edge.get("source_chunk", 0),
            })

        neighbor_map: dict[str, dict[str, str]] = {name: {} for name in merged_nodes}
        for edge in ordered_edges:
            source_name = edge["source"]
            target_name = edge["target"]
            description = edge.get("description", "") or ""

            if target_name not in neighbor_map[source_name]:
                neighbor_map[source_name][target_name] = description
            elif not neighbor_map[source_name][target_name] and description:
                neighbor_map[source_name][target_name] = description

            if source_name not in neighbor_map[target_name]:
                neighbor_map[target_name][source_name] = description
            elif not neighbor_map[target_name][source_name] and description:
                neighbor_map[target_name][source_name] = description

        serialized_nodes = []
        for name in sorted(merged_nodes, key=str.lower):
            merged_node = merged_nodes[name]
            neighbors = [
                {
                    "id": neighbor_name,
                    "label": neighbor_name,
                    "description": neighbor_description,
                }
                for neighbor_name, neighbor_description in sorted(
                    neighbor_map.get(name, {}).items(),
                    key=lambda item: item[0].lower(),
                )
            ]
            serialized_nodes.append({
                "id": name,
                "label": name,
                "description": " ".join(merged_node["description_parts"]),
                "entity_type": merged_node["entity_type"],
                "connection_count": len(neighbors),
                "neighbors": neighbors,
            })

        return {
            "schema_version": "context_graph.v1",
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
