"""Shared text builders for unique graph-node embeddings."""

from __future__ import annotations

from typing import Any, Mapping


def build_unique_node_document(node: Mapping[str, Any]) -> str:
    """Return the canonical text used for one-vector-per-node embeddings."""
    display_name = str(node.get("display_name", "")).strip()
    description = str(node.get("description", "")).strip()
    if display_name and description:
        return f"{display_name}\n\n{description}"
    return display_name or description
