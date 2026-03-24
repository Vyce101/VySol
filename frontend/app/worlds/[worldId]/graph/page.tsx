"use client";

import type { ReactNode } from "react";
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
    const [isInitialLoadPending, setIsInitialLoadPending] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const loadGraph = useCallback(async () => {
        try {
            setLoadError(null);
            const data = await apiFetch<{ nodes: GraphNode[]; edges: GraphLink[] }>(`/worlds/${worldId}/graph`);
            setNodes(data.nodes);
            setEdges(data.edges);
        } catch (error: unknown) {
            setLoadError((error as Error).message || "Could not load graph.");
        } finally {
            setIsInitialLoadPending(false);
        }
    }, [worldId]);

    useEffect(() => {
        void loadGraph();
    }, [loadGraph]);

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

    if (isInitialLoadPending) {
        return <GraphState title="Loading graph..." subtitle="Pulling the latest graph snapshot for this world." />;
    }

    if (loadError && nodes.length === 0 && edges.length === 0) {
        return (
            <GraphState
                title="Could not load graph"
                subtitle={loadError}
                action={(
                    <button
                        onClick={() => {
                            setIsInitialLoadPending(true);
                            void loadGraph();
                        }}
                        style={{
                            border: "1px solid var(--border)",
                            borderRadius: "var(--radius)",
                            background: "var(--background-secondary)",
                            color: "var(--text-primary)",
                            padding: "10px 14px",
                            cursor: "pointer",
                            fontWeight: 600,
                        }}
                    >
                        Retry
                    </button>
                )}
            />
        );
    }

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

function GraphState({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) {
    return (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
            <div
                style={{
                    maxWidth: 420,
                    width: "100%",
                    display: "grid",
                    gap: 14,
                    padding: 24,
                    borderRadius: 18,
                    border: "1px solid var(--border)",
                    background: "linear-gradient(180deg, var(--overlay) 0%, var(--card) 100%)",
                    boxShadow: "0 12px 28px color-mix(in srgb, var(--shadow-color) 50%, transparent)",
                }}
            >
                <div style={{ display: "grid", gap: 6 }}>
                    <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: "var(--text-primary)" }}>{title}</h2>
                    <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: "var(--text-subtle)" }}>{subtitle}</p>
                </div>
                {action ?? null}
            </div>
        </div>
    );
}
