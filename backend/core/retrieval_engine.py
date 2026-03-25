"""Hybrid retrieval: vector search + BFS graph walk → context assembly."""

from __future__ import annotations

import logging

from .config import load_settings
from .graph_store import GraphStore, get_active_ingest_graph_session
from .ingestion_engine import get_ingestion_audit_snapshot
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


def _safe_vector_count(store: VectorStore, *, label: str, world_id: str) -> int:
    try:
        return max(0, int(store.count() or 0))
    except Exception:
        logger.warning("Could not count %s vectors for world %s during retrieval.", label, world_id, exc_info=True)
        return 0


class RetrievalEngine:
    """Performs GraphRAG retrieval: vector query → graph walk → context assembly."""

    def __init__(self, world_id: str):
        self.world_id = world_id
        active_graph_session = get_active_ingest_graph_session(world_id)
        self.graph_store = active_graph_session.committed_store if active_graph_session is not None else GraphStore(world_id)
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
        try:
            max_nodes = max(1, int(max_nodes))
        except (TypeError, ValueError):
            max_nodes = 50
        max_neighbors_per_node = settings.get("retrieval_max_neighbors_per_node", 15)
        try:
            max_neighbors_per_node = max(1, int(max_neighbors_per_node))
        except (TypeError, ValueError):
            max_neighbors_per_node = 15
        max_node_description_chars = settings.get("retrieval_max_node_description_chars", 0)
        try:
            max_node_description_chars = max(0, int(max_node_description_chars))
        except (TypeError, ValueError):
            max_node_description_chars = 0

        total_graph_nodes = self.graph_store.get_node_count()
        force_all = total_graph_nodes > 0 and entry_k >= total_graph_nodes

        # Step 1: Embed query once and validate retrieval health.
        embedding_provider = getattr(self.chunk_vector_store, "embedding_provider", "gemini")
        km = _get_provider_key_manager(embedding_provider)
        api_key, _ = km.wait_for_available_key()
        query_embedding = self.chunk_vector_store.embed_text(query, api_key)
        chunk_vector_count = _safe_vector_count(self.chunk_vector_store, label="chunk", world_id=self.world_id)
        unique_node_vector_count = _safe_vector_count(
            self.unique_node_vector_store,
            label="unique-node",
            world_id=self.world_id,
        )
        health_summary = get_ingestion_audit_snapshot(
            self.world_id,
            synthesize_failures=False,
            persist=False,
        )
        retrieval_health = self._validate_retrieval_health(health_summary)
        chunk_index_usable = bool(retrieval_health.get("chunk_index_usable"))
        chunk_index_complete = bool(retrieval_health.get("chunk_index_complete"))
        node_index_usable = bool(retrieval_health.get("node_index_usable")) and unique_node_vector_count > 0
        node_index_complete = bool(retrieval_health.get("node_index_complete"))
        passive_blockers = list(retrieval_health.get("passive_blockers") or [])

        # Step 2: Chunk vector query for evidence/RAG excerpts.
        query_n_results = max(top_k, chunk_vector_count) if chunk_vector_count > 0 else top_k
        vector_results: list[dict] = []
        if chunk_index_usable and chunk_vector_count > 0:
            try:
                vector_results = self.chunk_vector_store.query_by_embedding(
                    query_embedding,
                    n_results=query_n_results,
                )
            except Exception:
                chunk_index_usable = False
                passive_blockers.append({
                    "code": "chunk_vector_query_failed",
                    "message": "Could not query the chunk vector store during retrieval.",
                })
                logger.warning("Chunk retrieval fell back after chunk vector query failed for world %s.", self.world_id, exc_info=True)
        rag_results = vector_results[:top_k]

        # Step 3: Node vector query for graph entry points.
        node_query_n_results = max(0, unique_node_vector_count) if node_index_usable else 0
        node_results: list[dict] = []
        if node_query_n_results > 0:
            try:
                node_results = self.unique_node_vector_store.query_by_embedding(
                    query_embedding,
                    n_results=node_query_n_results,
                )
            except Exception:
                node_index_usable = False
                node_query_n_results = 0
                passive_blockers.append({
                    "code": "unique_node_vector_query_failed",
                    "message": "Could not query the unique-node vector store during retrieval.",
                })
                logger.warning("Node-seeded retrieval fell back after unique-node query failed for world %s.", self.world_id, exc_info=True)
        entry_nodes = self._entry_nodes_from_query_results(
            node_results=node_results,
            requested=entry_k,
        )
        node_similarity_map = self._node_similarity_map_from_query_results(node_results)
        matched_node_ids = [
            str(node.get("id") or "").strip()
            for node in entry_nodes
            if str(node.get("id") or "").strip()
        ]

        # Step 4: Graph node selection
        candidate_graph_nodes: list[dict] = []
        if matched_node_ids:
            candidate_graph_nodes = self.graph_store.get_ranked_neighborhood_candidates(
                start_nodes=matched_node_ids,
                hops=hops,
                node_similarity_map=node_similarity_map,
            )
        entry_nodes, graph_nodes = self._select_context_graph_nodes(
            entry_nodes=entry_nodes,
            candidate_graph_nodes=candidate_graph_nodes,
            max_nodes=max_nodes,
        )

        # Step 5: Collect relationships
        graph_edges = self._select_context_graph_edges(
            graph_nodes=graph_nodes,
            candidate_graph_nodes=candidate_graph_nodes,
            node_similarity_map=node_similarity_map,
            max_neighbors_per_node=max_neighbors_per_node,
        )

        # Step 6: Assemble context string
        node_descriptions, truncated_node_descriptions = self._prepare_context_node_descriptions(
            entry_nodes=entry_nodes,
            graph_nodes=graph_nodes,
            max_node_description_chars=max_node_description_chars,
        )
        context = self._assemble_context(
            rag_results,
            entry_nodes,
            graph_nodes,
            graph_edges,
            node_descriptions=node_descriptions,
        )
        context_characters = len(context)
        context_section_character_counts = self._context_character_counts(
            rag_chunks=rag_results,
            entry_nodes=entry_nodes,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            node_descriptions=node_descriptions,
        )
        context_graph = self._build_context_graph_snapshot(
            entry_nodes,
            graph_nodes,
            graph_edges,
            node_descriptions=node_descriptions,
        )

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
                "graph_candidate_nodes": len(candidate_graph_nodes),
                "selected_graph_nodes": len(graph_nodes),
                "graph_edge_count": len(graph_edges),
                "max_neighbors_per_node": max_neighbors_per_node,
                "ranked_entry_candidates": len(node_results),
                "entry_backfill_count": 0,
                "vector_results_count": len(vector_results),
                "query_n_results": query_n_results,
                "node_query_results_count": len(node_results),
                "node_query_n_results": node_query_n_results,
                "chunk_vector_count": chunk_vector_count,
                "chunk_index_usable": chunk_index_usable,
                "chunk_index_complete": chunk_index_complete,
                "node_vector_count": unique_node_vector_count,
                "unique_node_vector_count": unique_node_vector_count,
                "entry_index_kind": "unique_nodes",
                "node_seeded_retrieval_used": node_query_n_results > 0,
                "node_index_usable": node_index_usable,
                "node_index_complete": node_index_complete,
                "passive_blockers": passive_blockers,
                "retrieval_blocked": False,
                "context_characters": context_characters,
                "node_description_char_limit": max_node_description_chars,
                "truncated_node_descriptions": truncated_node_descriptions,
                **context_section_character_counts,
            },
        }

    def _validate_retrieval_health(
        self,
        health_summary: dict,
    ) -> dict[str, object]:
        world = health_summary.get("world", {}) if isinstance(health_summary, dict) else {}
        expected_chunks = max(0, int(world.get("expected_chunks", 0) or 0))
        embedded_chunks = max(0, int(world.get("embedded_chunks", 0) or 0))
        expected_node_vectors = max(0, int(world.get("expected_node_vectors", 0) or 0))
        embedded_node_vectors = max(0, int(world.get("embedded_node_vectors", 0) or 0))
        chunk_index_usable = True
        chunk_index_complete = not (expected_chunks > 0 and embedded_chunks < expected_chunks)
        node_index_usable = True
        node_index_complete = not (expected_node_vectors > 0 and embedded_node_vectors < expected_node_vectors)
        passive_blockers: list[dict] = []
        blocking_issues = health_summary.get("blocking_issues", []) if isinstance(health_summary, dict) else []
        if blocking_issues:
            for issue in blocking_issues:
                if not isinstance(issue, dict):
                    passive_blockers.append({"message": str(issue)})
                    continue
                issue_code = str(issue.get("code") or "").strip().lower()
                if issue_code == "unique_node_vector_store_unreadable":
                    node_index_usable = False
                    continue
                if issue_code == "chunk_vector_store_unreadable":
                    chunk_index_usable = False
                    continue
                passive_blockers.append(issue)
        return {
            "chunk_index_usable": chunk_index_usable,
            "chunk_index_complete": chunk_index_complete,
            "node_index_usable": node_index_usable,
            "node_index_complete": node_index_complete,
            "passive_blockers": passive_blockers,
        }

    def _node_similarity_map_from_query_results(self, node_results: list[dict]) -> dict[str, float]:
        ranked_scores: dict[str, float] = {}
        for index, result in enumerate(node_results):
            metadata = result.get("metadata", {}) or {}
            node_id = str(metadata.get("node_id") or result.get("id", "")).strip()
            if not node_id or node_id not in self.graph_store.graph.nodes():
                continue
            raw_distance = result.get("distance")
            try:
                score = float(raw_distance)
            except (TypeError, ValueError):
                # Keep deterministic rank ordering even in tests or legacy payloads
                # that do not include an explicit distance.
                score = float(index) * 0.000001
            previous = ranked_scores.get(node_id)
            if previous is None or score < previous:
                ranked_scores[node_id] = score
        return ranked_scores

    def _assemble_context(
        self,
        rag_chunks: list[dict],
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
        *,
        node_descriptions: dict[str, str] | None = None,
    ) -> str:
        sections = self._build_context_sections(
            rag_chunks=rag_chunks,
            entry_nodes=entry_nodes,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            node_descriptions=node_descriptions,
        )
        return "\n\n".join(section_text for _key, section_text in sections)

    def _context_character_counts(
        self,
        *,
        rag_chunks: list[dict],
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
        node_descriptions: dict[str, str] | None = None,
    ) -> dict[str, int]:
        counts = {
            "entry_node_characters": 0,
            "graph_node_characters": 0,
            "graph_edge_characters": 0,
            "rag_chunk_characters": 0,
        }
        ordered_sections = self._build_context_sections(
            rag_chunks=rag_chunks,
            entry_nodes=entry_nodes,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            node_descriptions=node_descriptions,
        )
        for index, (key, section_text) in enumerate(ordered_sections):
            counts[key] = len(section_text) + (2 if index > 0 else 0)
        return counts

    def _build_context_sections(
        self,
        *,
        rag_chunks: list[dict],
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
        node_descriptions: dict[str, str] | None = None,
    ) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []

        entry_nodes_section = self._build_nodes_section(
            "# Entry Nodes",
            entry_nodes,
            node_descriptions=node_descriptions,
        )
        if entry_nodes_section:
            sections.append(("entry_node_characters", entry_nodes_section))

        entry_node_ids = {str(node.get("id", "")) for node in entry_nodes if node.get("id")}
        graph_nodes_only = [
            node
            for node in graph_nodes
            if str(node.get("id", "")) not in entry_node_ids
        ]
        graph_nodes_section = self._build_nodes_section(
            "# Graph Nodes",
            graph_nodes_only,
            node_descriptions=node_descriptions,
        )
        if graph_nodes_section:
            sections.append(("graph_node_characters", graph_nodes_section))

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
            if edge_strs:
                sections.append(("graph_edge_characters", "# Graph Edges\n" + "\n".join(edge_strs)))

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
                sections.append(("rag_chunk_characters", "# RAG Chunks\n" + "\n\n".join(chunk_strs)))

        return sections

    def _format_context_edge_line(self, edge: dict) -> str:
        s = edge.get("source_label") or edge.get("source", "?")
        t = edge.get("target_label") or edge.get("target", "?")
        desc = _normalize_context_text(edge.get("description", ""))
        book = edge.get("source_book", 0)
        chunk_id = edge.get("source_chunk", 0)
        temporal_prefix = f"[B{book}:C{chunk_id}] " if book or chunk_id else ""
        return f"{temporal_prefix}{s}, {desc}, {t}"

    def _build_nodes_section(
        self,
        heading: str,
        nodes: list[dict],
        *,
        node_descriptions: dict[str, str] | None = None,
    ) -> str:
        node_lines: list[str] = []
        seen_node_ids: set[str] = set()
        for node in nodes:
            node_id = str(node.get("id", "") or "")
            if not node_id or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            display_name = str(node.get("display_name") or node_id or "Unknown")
            description = self._get_context_node_description(node, node_descriptions=node_descriptions)
            node_lines.append(f"{display_name}: {description}")

        if not node_lines:
            return ""

        return heading + "\n" + "\n".join(node_lines)

    def _build_context_graph_snapshot(
        self,
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        graph_edges: list[dict],
        *,
        node_descriptions: dict[str, str] | None = None,
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
                "description": self._get_context_node_description(node, node_descriptions=node_descriptions),
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

    def _prepare_context_node_descriptions(
        self,
        *,
        entry_nodes: list[dict],
        graph_nodes: list[dict],
        max_node_description_chars: int,
    ) -> tuple[dict[str, str], int]:
        node_descriptions: dict[str, str] = {}
        truncated_count = 0

        for node in [*entry_nodes, *graph_nodes]:
            node_id = str(node.get("id", "") or "")
            if not node_id or node_id in node_descriptions:
                continue
            description, truncated = self._truncate_node_description(
                node.get("description", ""),
                max_node_description_chars=max_node_description_chars,
            )
            node_descriptions[node_id] = description
            if truncated:
                truncated_count += 1

        return node_descriptions, truncated_count

    def _get_context_node_description(
        self,
        node: dict,
        *,
        node_descriptions: dict[str, str] | None = None,
    ) -> str:
        node_id = str(node.get("id", "") or "")
        if node_descriptions and node_id in node_descriptions:
            return node_descriptions[node_id]
        description, _ = self._truncate_node_description(
            node.get("description", ""),
            max_node_description_chars=0,
        )
        return description

    def _truncate_node_description(
        self,
        description: str,
        *,
        max_node_description_chars: int,
    ) -> tuple[str, bool]:
        normalized = _normalize_context_text(description)
        if max_node_description_chars <= 0 or len(normalized) <= max_node_description_chars:
            return normalized, False
        if max_node_description_chars <= 3:
            return normalized[:max_node_description_chars], True
        return normalized[: max_node_description_chars - 3] + "...", True

    def _selected_node_rank_map(self, candidate_graph_nodes: list[dict]) -> dict[str, int]:
        candidate_rank_map: dict[str, int] = {}
        for index, node in enumerate(candidate_graph_nodes):
            node_id = str(node.get("id", "") or "")
            if not node_id or node_id in candidate_rank_map:
                continue
            candidate_rank_map[node_id] = index
        return candidate_rank_map

    def _neighbor_rank_key(
        self,
        node_id: str,
        *,
        node_similarity_map: dict[str, float],
        candidate_rank_map: dict[str, int],
    ) -> tuple[int, float, int, str, str]:
        node_data = self.graph_store.get_node(node_id) or {}
        label = str(node_data.get("display_name") or node_id or "Unknown").strip().lower()
        if node_id in node_similarity_map:
            return (0, float(node_similarity_map[node_id]), candidate_rank_map.get(node_id, 0), label, node_id.lower())
        if node_id in candidate_rank_map:
            return (1, float(candidate_rank_map[node_id]), candidate_rank_map[node_id], label, node_id.lower())
        return (2, float("inf"), 0, label, node_id.lower())

    def _select_context_graph_edges(
        self,
        *,
        graph_nodes: list[dict],
        candidate_graph_nodes: list[dict],
        node_similarity_map: dict[str, float],
        max_neighbors_per_node: int,
    ) -> list[dict]:
        try:
            normalized_max_neighbors = max(1, int(max_neighbors_per_node))
        except (TypeError, ValueError):
            normalized_max_neighbors = 1

        selected_node_ids = {
            str(node.get("id", "") or "")
            for node in graph_nodes
            if str(node.get("id", "") or "")
        }
        if not selected_node_ids:
            return []

        candidate_rank_map = self._selected_node_rank_map(candidate_graph_nodes)
        node_adjacency: dict[str, set[str]] = {node_id: set() for node_id in selected_node_ids}
        candidate_edges: list[dict] = []

        for u, v, attrs in self.graph_store.graph.edges(data=True):
            source_id = str(u or "")
            target_id = str(v or "")
            if source_id not in selected_node_ids or target_id not in selected_node_ids:
                continue

            node_adjacency.setdefault(source_id, set()).add(target_id)
            node_adjacency.setdefault(target_id, set()).add(source_id)

            source_node = self.graph_store.get_node(source_id) or {}
            target_node = self.graph_store.get_node(target_id) or {}
            source_name = source_node.get("display_name", source_id)
            target_name = target_node.get("display_name", target_id)
            candidate_edges.append({
                "source_id": source_id,
                "target_id": target_id,
                "source_label": source_name,
                "target_label": target_name,
                "source": source_name,
                "target": target_name,
                "label": attrs.get("label", ""),
                "description": attrs.get("description", ""),
                "source_book": attrs.get("source_book", 0),
                "source_chunk": attrs.get("source_chunk", 0),
            })

        retained_neighbors_by_node: dict[str, set[str]] = {}
        for node_id, neighbor_ids in node_adjacency.items():
            ranked_neighbor_ids = sorted(
                neighbor_ids,
                key=lambda neighbor_id: self._neighbor_rank_key(
                    neighbor_id,
                    node_similarity_map=node_similarity_map,
                    candidate_rank_map=candidate_rank_map,
                ),
            )
            retained_neighbors_by_node[node_id] = set(ranked_neighbor_ids[:normalized_max_neighbors])

        retained_edges: list[dict] = []
        for edge in candidate_edges:
            source_id = str(edge.get("source_id", "") or "")
            target_id = str(edge.get("target_id", "") or "")
            if (
                target_id in retained_neighbors_by_node.get(source_id, set())
                and source_id in retained_neighbors_by_node.get(target_id, set())
            ):
                retained_edges.append(edge)

        return retained_edges

    def _select_context_graph_nodes(
        self,
        *,
        entry_nodes: list[dict],
        candidate_graph_nodes: list[dict],
        max_nodes: int,
    ) -> tuple[list[dict], list[dict]]:
        try:
            normalized_max_nodes = max(1, int(max_nodes))
        except (TypeError, ValueError):
            normalized_max_nodes = 1

        ranked_nodes_by_id: dict[str, dict] = {}
        ranked_candidate_ids: list[str] = []
        for node in candidate_graph_nodes:
            node_id = str(node.get("id", "") or "")
            if not node_id or node_id in ranked_nodes_by_id:
                continue
            ranked_nodes_by_id[node_id] = node
            ranked_candidate_ids.append(node_id)

        ranked_entry_ids: list[str] = []
        for node in entry_nodes:
            node_id = str(node.get("id", "") or "")
            if not node_id or node_id not in ranked_nodes_by_id or node_id in ranked_entry_ids:
                continue
            ranked_entry_ids.append(node_id)

        selected_ids: list[str] = []
        for node_id in ranked_entry_ids:
            if len(selected_ids) >= normalized_max_nodes:
                break
            selected_ids.append(node_id)

        for node_id in ranked_candidate_ids:
            if len(selected_ids) >= normalized_max_nodes:
                break
            if node_id in selected_ids:
                continue
            selected_ids.append(node_id)

        selected_id_set = set(selected_ids)
        selected_entry_nodes = [
            node
            for node in entry_nodes
            if str(node.get("id", "") or "") in selected_id_set
        ]
        selected_graph_nodes = [ranked_nodes_by_id[node_id] for node_id in selected_ids if node_id in ranked_nodes_by_id]
        return selected_entry_nodes, selected_graph_nodes

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
