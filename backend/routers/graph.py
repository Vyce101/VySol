"""Graph endpoints — full data, node detail, search."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from core.config import world_meta_path
from core.graph_store import GraphStore, get_active_ingest_graph_session

router = APIRouter()


@router.get("/{world_id}/graph")
async def get_graph(world_id: str):
    if not world_meta_path(world_id).exists():
        raise HTTPException(status_code=404, detail="World not found")
    active_session = get_active_ingest_graph_session(world_id)
    if active_session is not None:
        return active_session.get_all_data()
    gs = await asyncio.to_thread(GraphStore, world_id)
    return await asyncio.to_thread(gs.get_all_data)


@router.get("/{world_id}/graph/node/{node_id}")
async def get_node(world_id: str, node_id: str):
    if not world_meta_path(world_id).exists():
        raise HTTPException(status_code=404, detail="World not found")
    active_session = get_active_ingest_graph_session(world_id)
    if active_session is not None:
        node = active_session.get_node(node_id)
    else:
        gs = await asyncio.to_thread(GraphStore, world_id)
        node = await asyncio.to_thread(gs.get_node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.get("/{world_id}/graph/search")
async def search_graph(world_id: str, q: str = ""):
    if not world_meta_path(world_id).exists():
        raise HTTPException(status_code=404, detail="World not found")
    active_session = get_active_ingest_graph_session(world_id)
    if active_session is not None:
        return active_session.search_nodes(q)
    gs = await asyncio.to_thread(GraphStore, world_id)
    return await asyncio.to_thread(gs.search_nodes, q)
