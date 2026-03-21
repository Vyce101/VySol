"use client";

import { useState, useEffect, useCallback, use } from "react";
import { Search, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import InteractiveGraphViewer, {
    GraphViewerNode,
    GraphViewerLink,
    GraphViewerNodeDetail,
} from "@/components/interactive-graph-viewer";

interface GraphNode extends GraphViewerNode {
    claim_count: number;
    source_chunks?: string[];
    created_at?: string;
}

interface GraphLink extends GraphViewerLink {
    strength: number;
}

interface NodeDetail extends GraphViewerNodeDetail {
    claims: Array<{ text: string; source_book: number; source_chunk: number }>;
}

export default function GraphPage({ params }: { params: Promise<{ worldId: string }> }) {
    const { worldId } = use(params);
    const [nodes, setNodes] = useState<GraphNode[]>([]);
    const [edges, setEdges] = useState<GraphLink[]>([]);
    const [searchQuery, setSearchQuery] = useState("");
    const [searchResults, setSearchResults] = useState<string[]>([]);

    const loadGraph = useCallback(async () => {
        try {
            const data = await apiFetch<{ nodes: GraphNode[]; edges: GraphLink[] }>(`/worlds/${worldId}/graph`);
            setNodes(data.nodes);
            setEdges(data.edges);
        } catch { /* ignore */ }
    }, [worldId]);

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        void loadGraph();
    }, [loadGraph]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const handleSearch = async (query: string) => {
        setSearchQuery(query);
        if (!query.trim()) {
            setSearchResults([]);
            return;
        }

        try {
            const results = await apiFetch<Array<{ id: string }>>(`/worlds/${worldId}/graph/search?q=${encodeURIComponent(query)}`);
            setSearchResults(results.map((result) => result.id));
        } catch {
            setSearchResults([]);
        }
    };

    return (
        <div style={{ flex: 1, display: "flex", minHeight: 0, minWidth: 0, height: "100%" }}>
            <InteractiveGraphViewer
                nodes={nodes}
                edges={edges}
                resolveNodeDetail={(node) => apiFetch<NodeDetail>(`/worlds/${worldId}/graph/node/${node.id}`)}
                searchResults={searchResults}
                searchOverlay={(
                    <>
                        <div style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            background: "var(--card)",
                            border: "1px solid var(--border)",
                            borderRadius: "var(--radius)",
                            padding: "6px 12px",
                        }}>
                            <Search size={14} style={{ color: "var(--text-muted)" }} />
                            <input
                                value={searchQuery}
                                onChange={(event) => void handleSearch(event.target.value)}
                                placeholder="Search nodes..."
                                style={{ border: "none", background: "transparent", color: "var(--text-primary)", fontSize: 13, width: 200, outline: "none", padding: 0 }}
                            />
                            {searchQuery && (
                                <button
                                    onClick={() => {
                                        setSearchQuery("");
                                        setSearchResults([]);
                                    }}
                                    style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}
                                >
                                    <X size={14} />
                                </button>
                            )}
                        </div>
                        {searchResults.length === 0 && searchQuery && (
                            <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>No matches found.</div>
                        )}
                    </>
                )}
                showRefreshButton
                onRefresh={() => {
                    void loadGraph();
                }}
                showColorToggle
            />
        </div>
    );
}
