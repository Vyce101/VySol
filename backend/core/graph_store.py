"""NetworkX GEXF-backed graph store with atomic writes and node/edge upsert."""

from __future__ import annotations

from copy import deepcopy
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx

from .config import world_graph_path

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cast_node(attrs: dict) -> dict:
    """Cast GEXF string attributes back to proper Python types."""
    if "claims" in attrs and isinstance(attrs["claims"], str):
        try:
            attrs["claims"] = json.loads(attrs["claims"])
        except (json.JSONDecodeError, TypeError):
            attrs["claims"] = []
    if "source_chunks" in attrs and isinstance(attrs["source_chunks"], str):
        try:
            attrs["source_chunks"] = json.loads(attrs["source_chunks"])
        except (json.JSONDecodeError, TypeError):
            attrs["source_chunks"] = []
    return attrs


def _cast_edge(attrs: dict) -> dict:
    """Cast GEXF edge attributes to proper types."""
    for int_key in ("strength", "source_book", "source_chunk"):
        if int_key in attrs and isinstance(attrs[int_key], str):
            try:
                attrs[int_key] = int(attrs[int_key])
            except (ValueError, TypeError):
                pass
    return attrs


def _normalize_id(name: str) -> str:
    """Convert display name to lowercase_with_underscores."""
    return name.lower().replace(" ", "_").replace("-", "_")


class GraphStore:
    """Wrapper around NetworkX for GEXF-backed knowledge graphs."""

    def __init__(self, world_id: str):
        self.world_id = world_id
        self.path = world_graph_path(world_id)
        self.graph = self._load()

    def _load(self) -> nx.Graph:
        """Load GEXF or return empty graph."""
        if self.path.exists() and self.path.stat().st_size > 0:
            try:
                g = nx.read_gexf(str(self.path))
                # Cast attributes
                for nid in g.nodes:
                    g.nodes[nid].update(_cast_node(dict(g.nodes[nid])))
                if isinstance(g, nx.MultiDiGraph):
                    for u, v, k in g.edges(keys=True):
                        g.edges[u, v, k].update(_cast_edge(dict(g.edges[u, v, k])))
                else:
                    for u, v in g.edges():
                        g.edges[u, v].update(_cast_edge(dict(g.edges[u, v])))
                return g
            except Exception as e:
                logger.error(f"Failed to load GEXF for {self.world_id}: {e}")
                return nx.MultiDiGraph()
        return nx.MultiDiGraph()

    def _save(self) -> None:
        """Atomic write: .tmp.gexf → os.replace()."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Prepare graph for GEXF — serialize lists as JSON strings
        g_copy = self.graph.copy()
        for nid in g_copy.nodes:
            attrs = g_copy.nodes[nid]
            if "claims" in attrs and isinstance(attrs["claims"], list):
                attrs["claims"] = json.dumps(attrs["claims"])
            if "source_chunks" in attrs and isinstance(attrs["source_chunks"], list):
                attrs["source_chunks"] = json.dumps(attrs["source_chunks"])
        tmp = self.path.with_suffix(".tmp.gexf")
        nx.write_gexf(g_copy, str(tmp))
        os.replace(str(tmp), str(self.path))

    def upsert_node(
        self,
        node_id: str,
        display_name: str,
        description: str,
        source_chunk_id: str | None = None,
    ) -> str:
        """Upsert a node. Returns the permanent UUID node_id."""
        normalized = _normalize_id(node_id)

        # Find existing by normalized_id — DISABLED: User requested NO merging
        # existing_uuid = None
        # for nid, attrs in self.graph.nodes(data=True):
        #     if attrs.get("normalized_id") == normalized:
        #         existing_uuid = nid
        #         break

        # Always Create new
        perm_id = str(uuid.uuid4())
        self.graph.add_node(perm_id, **{
            "node_id": perm_id,
            "display_name": display_name,
            "normalized_id": normalized,
            "description": description,
            "claims": [],
            "source_chunks": [source_chunk_id] if source_chunk_id else [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        return perm_id

    def add_claims_to_node(self, normalized_id: str, claims: list[dict]) -> None:
        """Add claims to a node found by normalized_id."""
        for nid, attrs in self.graph.nodes(data=True):
            if attrs.get("normalized_id") == normalized_id:
                existing = attrs.get("claims", [])
                if isinstance(existing, str):
                    existing = json.loads(existing)
                for claim in claims:
                    claim["claim_id"] = claim.get("claim_id", str(uuid.uuid4()))
                    existing.append(claim)
                attrs["claims"] = existing
                attrs["updated_at"] = _now_iso()
                return
        logger.warning(f"Node with normalized_id '{normalized_id}' not found for claims")

    def upsert_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        description: str,
        strength: int,
        source_book: int,
        source_chunk: int,
    ) -> str | None:
        """Upsert an edge. Returns edge_id or None if nodes missing."""
        # Prefer direct graph UUIDs when provided, otherwise fall back to
        # normalized-name lookup for legacy callers.
        source_uuid = source_node_id if source_node_id in self.graph.nodes else self._resolve_normalized(source_node_id)
        target_uuid = target_node_id if target_node_id in self.graph.nodes else self._resolve_normalized(target_node_id)

        if not source_uuid:
            logger.warning(f"Edge skipped: source node '{source_node_id}' not found")
            return None
        if not target_uuid:
            logger.warning(f"Edge skipped: target node '{target_node_id}' not found")
            return None

        # Check for existing edge — DISABLED: User requested NO merging
        # if self.graph.has_edge(source_uuid, target_uuid):
        #     edge_data = self.graph.edges[source_uuid, target_uuid]
        #     # Increment strength
        #     old_strength = int(edge_data.get("strength", 1))
        #     edge_data["strength"] = min(10, old_strength + 1)
        #     return edge_data.get("edge_id")

        # New edge
        eid = str(uuid.uuid4())
        self.graph.add_edge(source_uuid, target_uuid, **{
            "edge_id": eid,
            "source_node_id": source_uuid,
            "target_node_id": target_uuid,
            "description": description,
            "strength": min(10, max(1, strength)),
            "source_book": source_book,
            "source_chunk": source_chunk,
            "created_at": _now_iso(),
        })
        return eid

    def _resolve_normalized(self, normalized_or_id: str) -> str | None:
        """Resolve a normalized_id to a permanent UUID."""
        normalized = _normalize_id(normalized_or_id)
        for nid, attrs in self.graph.nodes(data=True):
            if attrs.get("normalized_id") == normalized:
                return nid
        return None

    def save(self) -> None:
        """Public save — call after a batch of upserts."""
        self._save()

    def _iter_edge_rows(self):
        """Yield graph edges uniformly for simple and multi-edge graphs."""
        if isinstance(self.graph, nx.MultiDiGraph):
            for u, v, _key, attrs in self.graph.edges(keys=True, data=True):
                yield u, v, attrs
            return
        for u, v, attrs in self.graph.edges(data=True):
            yield u, v, attrs

    def _connected_neighbor_map(self) -> dict[str, dict[str, str]]:
        """
        Build a bidirectional neighbor map from real graph edges.

        Only counts endpoints that still exist, ignores self-loops, and
        deduplicates repeated edges between the same pair.
        """
        node_ids = set(self.graph.nodes())
        neighbors: dict[str, dict[str, str]] = {str(node_id): {} for node_id in node_ids}

        for raw_u, raw_v, attrs in self._iter_edge_rows():
            u = str(raw_u)
            v = str(raw_v)
            if u == v:
                continue
            if u not in node_ids or v not in node_ids:
                continue

            description = str(attrs.get("description", "") or "")
            if v not in neighbors[u]:
                neighbors[u][v] = description
            elif not neighbors[u][v] and description:
                neighbors[u][v] = description

            if u not in neighbors[v]:
                neighbors[v][u] = description
            elif not neighbors[v][u] and description:
                neighbors[v][u] = description

        return neighbors

    def get_all_data(self) -> dict:
        """Return nodes and edges in API-friendly format."""
        neighbor_map = self._connected_neighbor_map()
        nodes = []
        for nid, attrs in self.graph.nodes(data=True):
            claims = attrs.get("claims", [])
            if isinstance(claims, str):
                claims = json.loads(claims)
            source_chunks = attrs.get("source_chunks", [])
            if isinstance(source_chunks, str):
                source_chunks = json.loads(source_chunks)
            nodes.append({
                "id": nid,
                "label": attrs.get("display_name", nid),
                "description": attrs.get("description", ""),
                "claim_count": len(claims),
                "connection_count": len(neighbor_map.get(str(nid), {})),
                "source_chunks": source_chunks,
                "created_at": attrs.get("created_at", ""),
            })
        edges = []
        for u, v, attrs in self._iter_edge_rows():
            edges.append({
                "source": u,
                "target": v,
                "description": attrs.get("description", ""),
                "strength": int(attrs.get("strength", 1)),
                "source_book": attrs.get("source_book", 0),
                "source_chunk": attrs.get("source_chunk", 0),
                "created_at": attrs.get("created_at", ""),
            })
        return {"nodes": nodes, "edges": edges}

    def get_node(self, node_id: str) -> dict | None:
        """Get full node data by UUID."""
        if node_id not in self.graph.nodes:
            return None
        attrs = dict(self.graph.nodes[node_id])
        claims = attrs.get("claims", [])
        if isinstance(claims, str):
            claims = json.loads(claims)
        source_chunks = attrs.get("source_chunks", [])
        if isinstance(source_chunks, str):
            source_chunks = json.loads(source_chunks)

        neighbor_map = self._connected_neighbor_map()
        neighbors = []
        for neighbor, description in sorted(
            neighbor_map.get(str(node_id), {}).items(),
            key=lambda item: self.graph.nodes[item[0]].get("display_name", item[0]).lower(),
        ):
            n_attrs = self.graph.nodes[neighbor]
            neighbors.append({
                "id": neighbor,
                "label": n_attrs.get("display_name", neighbor),
                "description": description,
            })

        return {
            "id": node_id,
            "display_name": attrs.get("display_name", ""),
            "normalized_id": attrs.get("normalized_id", ""),
            "description": attrs.get("description", ""),
            "claims": claims,
            "source_chunks": source_chunks,
            "connection_count": len(neighbor_map.get(str(node_id), {})),
            "neighbors": neighbors,
            "created_at": attrs.get("created_at", ""),
            "updated_at": attrs.get("updated_at", ""),
        }

    def search_nodes(self, query: str) -> list[dict]:
        """Substring search on display_name."""
        q = query.lower()
        results = []
        for nid, attrs in self.graph.nodes(data=True):
            if q in attrs.get("display_name", "").lower():
                claims = attrs.get("claims", [])
                if isinstance(claims, str):
                    claims = json.loads(claims)
                results.append({
                    "id": nid,
                    "label": attrs.get("display_name", nid),
                    "claim_count": len(claims),
                })
        return results

    def get_node_count(self) -> int:
        return self.graph.number_of_nodes()

    def get_edge_count(self) -> int:
        return self.graph.number_of_edges()

    def clear(self) -> None:
        """Clear the graph and save an empty GEXF."""
        self.graph.clear()
        self._save()

    def snapshot_chunk_artifacts(self, chunk_id: str, source_book: int, source_chunk: int) -> dict:
        """Capture the current graph artifacts tied to a specific chunk."""
        snapshot_node_ids: set[str] = set()
        edges: list[dict] = []

        if isinstance(self.graph, nx.MultiDiGraph):
            for source, target, _key, attrs in self.graph.edges(keys=True, data=True):
                if int(attrs.get("source_book", -1)) != int(source_book) or int(attrs.get("source_chunk", -1)) != int(source_chunk):
                    continue
                snapshot_node_ids.add(str(source))
                snapshot_node_ids.add(str(target))
                edges.append(
                    {
                        "source": str(source),
                        "target": str(target),
                        "attrs": deepcopy(_cast_edge(dict(attrs))),
                    }
                )
        else:
            for source, target, attrs in self.graph.edges(data=True):
                if int(attrs.get("source_book", -1)) != int(source_book) or int(attrs.get("source_chunk", -1)) != int(source_chunk):
                    continue
                snapshot_node_ids.add(str(source))
                snapshot_node_ids.add(str(target))
                edges.append(
                    {
                        "source": str(source),
                        "target": str(target),
                        "attrs": deepcopy(_cast_edge(dict(attrs))),
                    }
                )

        nodes: list[dict] = []
        for node_id, attrs in self.graph.nodes(data=True):
            claims = attrs.get("claims", [])
            if isinstance(claims, str):
                try:
                    claims = json.loads(claims)
                except (json.JSONDecodeError, TypeError):
                    claims = []

            source_chunks = attrs.get("source_chunks", [])
            if isinstance(source_chunks, str):
                try:
                    source_chunks = json.loads(source_chunks)
                except (json.JSONDecodeError, TypeError):
                    source_chunks = []

            has_chunk_ref = chunk_id in {str(raw_chunk_id) for raw_chunk_id in (source_chunks or [])}
            has_chunk_claim = False
            for claim in claims:
                try:
                    if int(claim.get("source_book", -1)) == int(source_book) and int(claim.get("source_chunk", -1)) == int(source_chunk):
                        has_chunk_claim = True
                        break
                except (TypeError, ValueError, AttributeError):
                    continue

            node_id_str = str(node_id)
            if not has_chunk_ref and not has_chunk_claim and node_id_str not in snapshot_node_ids:
                continue

            nodes.append(
                {
                    "id": node_id_str,
                    "attrs": deepcopy(_cast_node(dict(attrs))),
                }
            )

        return {
            "nodes": sorted(nodes, key=lambda node: node["id"]),
            "edges": edges,
        }

    def restore_chunk_artifacts(self, snapshot: dict) -> None:
        """Restore a previously captured chunk artifact snapshot."""
        nodes = list(snapshot.get("nodes") or [])
        edges = list(snapshot.get("edges") or [])
        if not nodes and not edges:
            return

        for node in nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            attrs = deepcopy(_cast_node(dict(node.get("attrs") or {})))
            if node_id in self.graph.nodes:
                live_attrs = self.graph.nodes[node_id]
                live_attrs.clear()
                live_attrs.update(attrs)
            else:
                self.graph.add_node(node_id, **attrs)

        for edge in edges:
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if not source or not target or source not in self.graph.nodes or target not in self.graph.nodes:
                continue
            attrs = deepcopy(_cast_edge(dict(edge.get("attrs") or {})))
            edge_id = str(attrs.get("edge_id") or "").strip()
            if isinstance(self.graph, nx.MultiDiGraph) and edge_id:
                self.graph.add_edge(source, target, key=edge_id, **attrs)
            else:
                self.graph.add_edge(source, target, **attrs)

        self._save()

    def remove_chunk_artifacts(self, chunk_id: str, source_book: int, source_chunk: int) -> dict:
        """
        Remove graph artifacts tied to a specific chunk.

        Returns a small cleanup report for logging/debugging.
        """
        removed_nodes = 0
        removed_edges = 0
        removed_claims = 0

        # Remove chunk-scoped edges first.
        edge_keys_to_remove: list[tuple] = []
        if isinstance(self.graph, nx.MultiDiGraph):
            for u, v, k, attrs in self.graph.edges(keys=True, data=True):
                if int(attrs.get("source_book", -1)) == int(source_book) and int(attrs.get("source_chunk", -1)) == int(source_chunk):
                    edge_keys_to_remove.append((u, v, k))
        else:
            for u, v, attrs in self.graph.edges(data=True):
                if int(attrs.get("source_book", -1)) == int(source_book) and int(attrs.get("source_chunk", -1)) == int(source_chunk):
                    edge_keys_to_remove.append((u, v))

        for edge_key in edge_keys_to_remove:
            self.graph.remove_edge(*edge_key)
            removed_edges += 1

        # Remove chunk source references and chunk-scoped claims from nodes.
        nodes_to_remove: list[str] = []
        for nid, attrs in list(self.graph.nodes(data=True)):
            normalized_attrs = _cast_node(dict(attrs))
            source_chunks = [str(c) for c in normalized_attrs.get("source_chunks", [])]
            had_chunk = chunk_id in source_chunks

            claims = normalized_attrs.get("claims", [])

            filtered_claims = []
            removed_chunk_claim = False
            for claim in claims:
                try:
                    claim_book = int(claim.get("source_book", -1))
                    claim_chunk = int(claim.get("source_chunk", -1))
                except (TypeError, ValueError, AttributeError):
                    claim_book = -1
                    claim_chunk = -1
                if claim_book == int(source_book) and claim_chunk == int(source_chunk):
                    removed_claims += 1
                    removed_chunk_claim = True
                    continue
                filtered_claims.append(claim)

            if had_chunk:
                source_chunks = [c for c in source_chunks if c != chunk_id]
                normalized_attrs["source_chunks"] = source_chunks

            if len(filtered_claims) != len(claims):
                normalized_attrs["claims"] = filtered_claims

            # If this node is now orphaned for provenance, remove it.
            if (had_chunk or removed_chunk_claim) and not source_chunks and not filtered_claims:
                nodes_to_remove.append(nid)
                continue

            if had_chunk or removed_chunk_claim:
                normalized_attrs["updated_at"] = _now_iso()
                attrs.clear()
                attrs.update(normalized_attrs)

        for nid in nodes_to_remove:
            if nid in self.graph:
                self.graph.remove_node(nid)
                removed_nodes += 1

        if removed_nodes or removed_edges or removed_claims:
            self._save()

        return {
            "removed_nodes": removed_nodes,
            "removed_edges": removed_edges,
            "removed_claims": removed_claims,
        }

    def get_bfs_neighborhood(self, start_nodes: list[str], hops: int, max_nodes: int) -> list[dict]:
        """BFS from start_nodes for N hops. Return up to max_nodes unique nodes."""
        visited = set()
        queue = list(start_nodes)
        depth = {n: 0 for n in start_nodes}

        while queue and len(visited) < max_nodes:
            current = queue.pop(0)
            if current in visited:
                continue
            if current not in self.graph.nodes:
                continue
            visited.add(current)

            if depth.get(current, 0) < hops:
                for neighbor in self.graph.neighbors(current):
                    if neighbor not in visited:
                        queue.append(neighbor)
                        depth[neighbor] = depth.get(current, 0) + 1

        results = []
        for nid in visited:
            if nid in self.graph.nodes:
                node_data = self.get_node(nid)
                if node_data:
                    results.append(node_data)
        return results[:max_nodes]
