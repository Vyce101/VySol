"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import type { MutableRefObject, ReactElement, ReactNode } from "react";
import { Maximize, ChevronRight, ChevronLeft } from "lucide-react";
import dynamic from "next/dynamic";
import type { ForceGraphMethods, ForceGraphProps, LinkObject, NodeObject } from "react-force-graph-2d";

export interface GraphViewerNeighbor {
    id: string;
    label: string;
    description: string;
}

export interface GraphViewerClaim {
    text: string;
    source_book: number;
    source_chunk: number;
}

export interface GraphViewerNode {
    id: string;
    label: string;
    description: string;
    entity_type?: string;
    is_entry_node?: boolean;
    claim_count?: number;
    connection_count: number;
    source_chunks?: string[];
    created_at?: string;
    neighbors?: GraphViewerNeighbor[];
    claims?: GraphViewerClaim[];
    x?: number;
    y?: number;
}

export interface GraphViewerLink {
    source: string;
    target: string;
    description: string;
    strength?: number;
    source_book?: number;
    source_chunk?: number;
    created_at?: string;
}

export interface GraphViewerNodeDetail {
    id: string;
    display_name: string;
    description: string;
    is_entry_node?: boolean;
    source_chunks?: string[];
    created_at?: string;
    connection_count?: number;
    claims?: GraphViewerClaim[];
    neighbors: GraphViewerNeighbor[];
}

type ForceGraphLinkData = Omit<GraphViewerLink, "source" | "target">;
type ForceGraphNode = NodeObject<GraphViewerNode>;
type ForceGraphLink = LinkObject<GraphViewerNode, ForceGraphLinkData>;
type ForceGraphHandle = ForceGraphMethods<GraphViewerNode, ForceGraphLinkData>;
type GraphEndpoint = ForceGraphLink["source"] | ForceGraphLink["target"];
type ForceGraphComponent = (props: ForceGraphProps<GraphViewerNode, ForceGraphLinkData> & {
    ref?: MutableRefObject<ForceGraphHandle | undefined>;
}) => ReactElement | null;

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as unknown as ForceGraphComponent;

const LINK_CURVATURE = 0.25;
const DEFAULT_LINK_WIDTH = 1.45;
const LINK_HOVER_PRECISION = 10;
const BASE_NODE_RADIUS = 6;
const NODE_RADIUS_CONNECTION_MULTIPLIER = 3.2;
const CHARGE_RADIUS_MULTIPLIER = 26;
const LINK_DISTANCE_RADIUS_MULTIPLIER = 1.45;
const HOVER_GLOW_BLUR = 10;
const HOVER_GLOW_EXPAND = 1.6;
const SELECTED_GLOW_BLUR = 15;
const SELECTED_GLOW_EXPAND = 2.4;

const getNodeRadius = (node: Pick<GraphViewerNode, "connection_count"> | null | undefined) =>
    Math.max(BASE_NODE_RADIUS, BASE_NODE_RADIUS + Math.sqrt(node?.connection_count || 0) * NODE_RADIUS_CONNECTION_MULTIPLIER);

const getNodePosition = (node: Pick<GraphViewerNode, "x" | "y">) => ({
    x: typeof node.x === "number" ? node.x : 0,
    y: typeof node.y === "number" ? node.y : 0,
});

const paintNodeCircle = (
    ctx: CanvasRenderingContext2D,
    node: Pick<GraphViewerNode, "x" | "y" | "connection_count">,
    fillStyle: string,
) => {
    const radius = getNodeRadius(node);
    const { x, y } = getNodePosition(node);

    ctx.beginPath();
    ctx.arc(x, y, radius, 0, 2 * Math.PI, false);
    ctx.fillStyle = fillStyle;
    ctx.fill();

    return { radius, x, y };
};

const paintNodeGlow = (
    ctx: CanvasRenderingContext2D,
    node: Pick<GraphViewerNode, "x" | "y" | "connection_count">,
    options: {
        opacity: number;
        blur: number;
        expand: number;
        fillAlpha: number;
        strokeAlpha: number;
        strokeWidth: number;
    },
) => {
    const radius = getNodeRadius(node);
    const { x, y } = getNodePosition(node);

    ctx.save();
    ctx.globalAlpha = options.opacity;
    ctx.shadowColor = `rgba(255, 255, 255, ${options.strokeAlpha})`;
    ctx.shadowBlur = options.blur;
    ctx.beginPath();
    ctx.arc(x, y, radius + options.expand, 0, 2 * Math.PI, false);
    ctx.fillStyle = `rgba(255, 255, 255, ${options.fillAlpha})`;
    ctx.fill();
    ctx.lineWidth = options.strokeWidth;
    ctx.strokeStyle = `rgba(255, 255, 255, ${options.strokeAlpha})`;
    ctx.stroke();
    ctx.restore();
};

const readThemeVar = (name: string, fallback: string) => {
    if (typeof window === "undefined") return fallback;
    const value = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
};

const escapeHtml = (value: string) =>
    value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");

const hasUsableGraphBounds = (bbox: { x: [number, number]; y: [number, number] } | undefined) => {
    if (!bbox) return false;

    const [minX, maxX] = bbox.x;
    const [minY, maxY] = bbox.y;
    if (![minX, maxX, minY, maxY].every((value) => Number.isFinite(value))) {
        return false;
    }

    return maxX > minX && maxY > minY;
};

const getGraphNodeId = (value: GraphEndpoint): string | null => {
    if (typeof value === "string") return value;
    if (typeof value === "number") return String(value);
    if (value && typeof value === "object") {
        if (typeof value.id === "string") return value.id;
        if (typeof value.id === "number") return String(value.id);
    }
    return null;
};

function getFallbackNodeDetail(node: GraphViewerNode): GraphViewerNodeDetail {
    return {
        id: node.id,
        display_name: node.label,
        description: node.description,
        is_entry_node: node.is_entry_node,
        source_chunks: node.source_chunks,
        created_at: node.created_at,
        connection_count: node.connection_count,
        claims: node.claims || [],
        neighbors: node.neighbors || [],
    };
}

function getEntryRolePresentation(node: { is_entry_node?: boolean } | null | undefined) {
    const isEntryNode = Boolean(node?.is_entry_node);
    return {
        label: isEntryNode ? "Entry Node" : "Expanded Node",
        background: isEntryNode ? "var(--primary-soft)" : "var(--status-info-soft-bg)",
        border: isEntryNode ? "var(--primary-soft-strong)" : "var(--status-info-soft-border)",
        color: isEntryNode ? "var(--primary-light)" : "var(--status-info-pill-fg)",
    };
}

export default function InteractiveGraphViewer(props: {
    nodes: GraphViewerNode[];
    edges: GraphViewerLink[];
    resolveNodeDetail?: (node: GraphViewerNode) => Promise<GraphViewerNodeDetail | null> | GraphViewerNodeDetail | null;
    searchResults?: string[];
    searchOverlay?: ReactNode;
    emptyStateTitle?: string;
    emptyStateSubtitle?: string;
    panelPlaceholderTitle?: string;
    panelPlaceholderSubtitle?: string;
    showRefreshButton?: boolean;
    onRefresh?: () => void | Promise<void>;
    showColorToggle?: boolean;
    useEntryRoleColors?: boolean;
    showFitButton?: boolean;
    fitButtonLabel?: string;
}) {
    const {
        nodes,
        edges,
        resolveNodeDetail,
        searchResults = [],
        searchOverlay,
        emptyStateTitle = "No graph data yet.",
        emptyStateSubtitle = "Ingest a source to populate the graph.",
        panelPlaceholderTitle = "Click a node to inspect",
        panelPlaceholderSubtitle = "See details, claims, and connections",
        showRefreshButton = false,
        onRefresh,
        showColorToggle = false,
        useEntryRoleColors = false,
        showFitButton = true,
        fitButtonLabel = "Fit View",
    } = props;

    const inspectorWidth = 320;
    const [selectedNode, setSelectedNode] = useState<GraphViewerNodeDetail | null>(null);
    const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
    const [panelOpen, setPanelOpen] = useState(true);
    const [colorBySource, setColorBySource] = useState(false);
    const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
    const [, setThemeMode] = useState("dark");
    const graphRef = useRef<ForceGraphHandle | undefined>(undefined);
    const containerRef = useRef<HTMLDivElement>(null);
    const resizeFrameRef = useRef<number | null>(null);
    const initialFitFrameRef = useRef<number | null>(null);
    const hasInitialFitRunRef = useRef(false);

    useEffect(() => {
        hasInitialFitRunRef.current = false;
    }, [nodes, edges]);

    const visibleSelectedNode = selectedNode && nodes.some((node) => node.id === selectedNode.id)
        ? selectedNode
        : null;
    const selectedNodeId = visibleSelectedNode?.id ?? null;
    const nodeLookup = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
    const graphData = useMemo<{ nodes: ForceGraphNode[]; links: ForceGraphLink[] }>(() => ({ nodes, links: edges }), [nodes, edges]);

    const measureContainer = useCallback(() => {
        const element = containerRef.current;
        if (!element) return;
        const rect = element.getBoundingClientRect();
        const nextWidth = Math.round(rect.width);
        const nextHeight = Math.round(rect.height);
        if (nextWidth <= 0 || nextHeight <= 0) return;
        setDimensions((current) => (
            current.width === nextWidth && current.height === nextHeight
                ? current
                : { width: nextWidth, height: nextHeight }
        ));
    }, []);

    const scheduleMeasurement = useCallback(() => {
        if (resizeFrameRef.current !== null) {
            window.cancelAnimationFrame(resizeFrameRef.current);
        }
        resizeFrameRef.current = window.requestAnimationFrame(() => {
            resizeFrameRef.current = null;
            measureContainer();
        });
    }, [measureContainer]);

    useEffect(() => {
        scheduleMeasurement();

        const observer = new ResizeObserver(() => {
            scheduleMeasurement();
        });
        const containerElement = containerRef.current;
        const parentElement = containerElement?.parentElement;
        if (containerElement) observer.observe(containerElement);
        if (parentElement) observer.observe(parentElement);

        window.addEventListener("resize", scheduleMeasurement);
        return () => {
            window.removeEventListener("resize", scheduleMeasurement);
            observer.disconnect();
            if (resizeFrameRef.current !== null) {
                window.cancelAnimationFrame(resizeFrameRef.current);
                resizeFrameRef.current = null;
            }
            if (initialFitFrameRef.current !== null) {
                window.cancelAnimationFrame(initialFitFrameRef.current);
                initialFitFrameRef.current = null;
            }
        };
    }, [scheduleMeasurement]);

    useEffect(() => {
        scheduleMeasurement();
    }, [nodes.length, panelOpen, scheduleMeasurement]);

    useEffect(() => {
        const syncTheme = () => {
            setThemeMode(document.documentElement.getAttribute("data-theme") || "dark");
        };
        syncTheme();
        const observer = new MutationObserver(syncTheme);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
        return () => observer.disconnect();
    }, []);

    const fitView = useCallback(() => {
        if (dimensions.width > 0) {
            graphRef.current?.zoomToFit(400, 40);
        }
    }, [dimensions.width]);

    const applyGraphLayout = useCallback(() => {
        if (!graphRef.current || nodes.length === 0 || dimensions.width <= 0 || dimensions.height <= 0) return false;
        const getLinkedNode = (value: GraphEndpoint) => {
            if (value && typeof value === "object") {
                return value;
            }

            const nodeId = getGraphNodeId(value);
            return nodeId ? nodeLookup.get(nodeId) : undefined;
        };

        const chargeForce = graphRef.current.d3Force("charge");
        chargeForce?.strength?.((rawNode: ForceGraphNode) => {
            const node = rawNode;
            return -240 - getNodeRadius(node) * CHARGE_RADIUS_MULTIPLIER;
        });
        chargeForce?.distanceMax?.(1200);

        const linkForce = graphRef.current.d3Force("link");
        linkForce?.distance?.((rawLink: ForceGraphLink) => {
            const link = rawLink;
            const sourceNode = getLinkedNode(link.source);
            const targetNode = getLinkedNode(link.target);
            return 120 + (getNodeRadius(sourceNode) + getNodeRadius(targetNode)) * LINK_DISTANCE_RADIUS_MULTIPLIER;
        });
        linkForce?.strength?.(0.07);

        graphRef.current.d3ReheatSimulation();
        return true;
    }, [dimensions.height, dimensions.width, nodeLookup, nodes.length]);

    const getSourceColor = useCallback((sourceStr?: string | number) => {
        if (!sourceStr) return readThemeVar("--graph-node", "#7c3aed");
        let bookNum = 0;
        if (typeof sourceStr === "string") {
            const match = sourceStr.match(/Book (\d+)/);
            if (match) bookNum = parseInt(match[1]);
        } else {
            bookNum = sourceStr;
        }

        if (bookNum === 0) return readThemeVar("--graph-node", "#7c3aed");

        const hue = (bookNum * 137.5) % 360;
        return `hsl(${hue}, 70%, 60%)`;
    }, []);

    const getNodeLabel = useCallback((value: GraphEndpoint) => {
        if (value && typeof value === "object") {
            const fallbackId = typeof value.id === "number" ? String(value.id) : value.id;
            return value.label || fallbackId || "Unknown";
        }

        const nodeId = getGraphNodeId(value);
        if (!nodeId) return "Unknown";

        return nodeLookup.get(nodeId)?.label || nodeId;
    }, [nodeLookup]);

    const getEdgeTemporalLabel = useCallback((link: ForceGraphLink) => {
        if (typeof link.source_book === "number" && typeof link.source_chunk === "number" && link.source_book > 0 && link.source_chunk >= 0) {
            return `Book ${link.source_book} > Chunk ${link.source_chunk}`;
        }
        return "Unknown origin";
    }, []);

    useEffect(() => {
        if (nodes.length === 0 || dimensions.width <= 0 || dimensions.height <= 0) {
            return;
        }

        if (initialFitFrameRef.current !== null) {
            window.cancelAnimationFrame(initialFitFrameRef.current);
        }

        let layoutApplied = false;
        const waitForGraph = () => {
            if (!graphRef.current) {
                initialFitFrameRef.current = window.requestAnimationFrame(waitForGraph);
                return;
            }

            if (!layoutApplied) {
                layoutApplied = applyGraphLayout();
            }

            if (!layoutApplied) {
                initialFitFrameRef.current = window.requestAnimationFrame(waitForGraph);
                return;
            }

            if (!hasInitialFitRunRef.current) {
                const bbox = graphRef.current.getGraphBbox();
                if (!hasUsableGraphBounds(bbox)) {
                    initialFitFrameRef.current = window.requestAnimationFrame(waitForGraph);
                    return;
                }

                initialFitFrameRef.current = null;
                graphRef.current.zoomToFit(400, 40);
                hasInitialFitRunRef.current = true;
            }
        };

        initialFitFrameRef.current = window.requestAnimationFrame(waitForGraph);

        return () => {
            if (initialFitFrameRef.current !== null) {
                window.cancelAnimationFrame(initialFitFrameRef.current);
                initialFitFrameRef.current = null;
            }
        };
    }, [applyGraphLayout, dimensions.height, dimensions.width, nodes.length]);

    const nodeCanvasObject = useCallback(
        (node: ForceGraphNode, ctx: CanvasRenderingContext2D) => {
            const primaryNodeColor = readThemeVar("--graph-node", "#7c3aed");
            const entryNodeColor = readThemeVar("--primary", "#7c3aed");
            const expandedNodeColor = readThemeVar("--status-info-pill-fg", "#60a5fa");
            const labelColor = readThemeVar("--graph-label", "rgba(255,255,255,0.9)");
            let color = primaryNodeColor;
            if (useEntryRoleColors) {
                color = node.is_entry_node ? entryNodeColor : expandedNodeColor;
            } else if (colorBySource && node.source_chunks && node.source_chunks.length > 0) {
                color = getSourceColor(node.source_chunks[0]);
            }
            const isSearching = searchResults.length > 0;
            const isMatch = searchResults.includes(node.id);
            const opacity = isSearching ? (isMatch ? 1 : 0.1) : 1;
            const isSelected = selectedNodeId === node.id;
            const isHovered = hoveredNodeId === node.id && !isSelected;

            if (isSelected) {
                paintNodeGlow(ctx, node, {
                    opacity,
                    blur: SELECTED_GLOW_BLUR,
                    expand: SELECTED_GLOW_EXPAND,
                    fillAlpha: 0.18,
                    strokeAlpha: 0.82,
                    strokeWidth: 1.8,
                });
            } else if (isHovered) {
                paintNodeGlow(ctx, node, {
                    opacity,
                    blur: HOVER_GLOW_BLUR,
                    expand: HOVER_GLOW_EXPAND,
                    fillAlpha: 0.11,
                    strokeAlpha: 0.58,
                    strokeWidth: 1.2,
                });
            }

            ctx.save();
            ctx.globalAlpha = opacity;
            const { radius, x, y } = paintNodeCircle(ctx, node, color);

            ctx.font = `${Math.max(3, radius * 0.6)}px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillStyle = labelColor;
            ctx.fillText(node.label, x, y + radius + 8);
            ctx.restore();
        },
        [colorBySource, getSourceColor, hoveredNodeId, searchResults, selectedNodeId, useEntryRoleColors]
    );

    const getLinkStrokeStyle = useCallback((link: ForceGraphLink) => {
        const isSearching = searchResults.length > 0;
        const sourceId = getGraphNodeId(link.source);
        const targetId = getGraphNodeId(link.target);
        const sourceMatch = sourceId ? searchResults.includes(sourceId) : false;
        const targetMatch = targetId ? searchResults.includes(targetId) : false;
        const opacity = isSearching ? (sourceMatch && targetMatch ? 0.6 : 0.05) : 0.4;

        if (!useEntryRoleColors && colorBySource && link.source_book) {
            const color = getSourceColor(link.source_book);
            return color.replace("hsl", "hsla").replace(")", `, ${opacity})`);
        }
        const graphLink = readThemeVar("--graph-link", "rgba(74, 74, 74, 0.4)");
        return graphLink.replace(/rgba?\(([^)]+)\)/, (_, values) => {
            const parts = values.split(",").map((value: string) => value.trim());
            if (parts.length >= 3) {
                return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${opacity})`;
            }
            return `rgba(74, 74, 74, ${opacity})`;
        });
    }, [colorBySource, getSourceColor, searchResults, useEntryRoleColors]);

    const resolveNodeClick = useCallback(async (node: ForceGraphNode) => {
        const nextDetail = resolveNodeDetail
            ? await Promise.resolve(resolveNodeDetail(node))
            : getFallbackNodeDetail(node);
        if (nextDetail) {
            setSelectedNode(nextDetail);
            setPanelOpen(true);
        }
    }, [resolveNodeDetail]);

    const handleNodeHover = useCallback((node: ForceGraphNode | null) => {
        setHoveredNodeId(node?.id ?? null);
    }, []);

    if (nodes.length === 0) {
        return (
            <div style={{ display: "flex", flex: 1, flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)" }}>
                <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>🕸️</div>
                <p style={{ fontSize: 16 }}>{emptyStateTitle}</p>
                <p style={{ fontSize: 13 }}>{emptyStateSubtitle}</p>
            </div>
        );
    }

    return (
        <div style={{ flex: 1, display: "flex", minHeight: 0, minWidth: 0, height: "100%", overflow: "hidden" }}>
            <div
                ref={containerRef}
                style={{ position: "relative", flex: 1, minWidth: 0, minHeight: 0, height: "100%", overflow: "visible", background: "var(--graph-bg)" }}
            >
                {dimensions.width > 0 && dimensions.height > 0 && (
                    <ForceGraph2D
                        ref={graphRef}
                        graphData={graphData}
                        nodeCanvasObject={nodeCanvasObject}
                        nodePointerAreaPaint={(node: ForceGraphNode, color: string, ctx: CanvasRenderingContext2D) => {
                            paintNodeCircle(ctx, node, color);
                        }}
                        d3AlphaDecay={0.02}
                        d3VelocityDecay={0.2}
                        warmupTicks={100}
                        cooldownTicks={220}
                        linkDirectionalArrowLength={10}
                        linkDirectionalArrowRelPos={1}
                        linkCurvature={LINK_CURVATURE}
                        linkWidth={DEFAULT_LINK_WIDTH}
                        linkHoverPrecision={LINK_HOVER_PRECISION}
                        linkColor={getLinkStrokeStyle}
                        onNodeClick={resolveNodeClick}
                        onNodeHover={handleNodeHover}
                        nodeId="id"
                        linkSource="source"
                        linkTarget="target"
                        backgroundColor={readThemeVar("--graph-bg", "#0f0f0f")}
                        width={dimensions.width}
                        height={dimensions.height}
                        nodeLabel={(node: ForceGraphNode) => {
                            const firstSource = node.source_chunks && node.source_chunks.length > 0 ? node.source_chunks[0] : null;
                            const createdAt = node.created_at ? new Date(node.created_at).toLocaleString() : null;
                            const connectionLine = `${node.connection_count || 0} connected nodes`;
                            const claimsLine = typeof node.claim_count === "number" ? `${node.claim_count} claims found` : null;
                            const rolePresentation = useEntryRoleColors ? getEntryRolePresentation(node) : null;
                            return `
                                <div style="background: var(--tooltip-bg); padding: 12px; border: 1px solid var(--tooltip-border); border-radius: 8px; color: var(--tooltip-text); max-width: 300px; box-shadow: 0 4px 20px var(--shadow-color);">
                                    <div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; border-bottom: 1px solid var(--tooltip-strong-border); padding-bottom: 4px; color: var(--primary-light);">${escapeHtml(node.label)}</div>
                                    ${rolePresentation ? `<div style="display: inline-flex; align-items: center; gap: 6px; margin-bottom: 8px; padding: 3px 8px; border-radius: 999px; background: ${rolePresentation.background}; border: 1px solid ${rolePresentation.border}; color: ${rolePresentation.color}; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;">${escapeHtml(rolePresentation.label)}</div>` : ""}
                                    <div style="font-size: 12px; line-height: 1.5; opacity: 0.9;">${escapeHtml(node.description || "No description available.")}</div>
                                    <div style="margin-top: 8px; font-size: 11px; color: var(--primary-light); font-weight: 600;">${escapeHtml(connectionLine)}</div>
                                    ${claimsLine ? `<div style="margin-top: 8px; font-size: 11px; color: var(--tooltip-subtle); font-style: italic;">${escapeHtml(claimsLine)}</div>` : ""}
                                    ${(firstSource || createdAt) ? `
                                        <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--tooltip-border); font-size: 10px; color: var(--tooltip-subtle);">
                                            ${firstSource ? `<div><strong style="color: var(--text-subtle);">First seen:</strong> ${escapeHtml(firstSource)}</div>` : ""}
                                            ${createdAt ? `<div><strong style="color: var(--text-subtle);">Created:</strong> ${escapeHtml(createdAt)}</div>` : ""}
                                        </div>
                                    ` : ""}
                                </div>
                            `;
                        }}
                        linkLabel={(link: ForceGraphLink) => {
                            const sourceName = escapeHtml(getNodeLabel(link.source));
                            const targetName = escapeHtml(getNodeLabel(link.target));
                            const description = escapeHtml((link.description || "").trim() || "No description available.");
                            const temporalLabel = escapeHtml(getEdgeTemporalLabel(link));
                            return `
                                <div style="background: var(--tooltip-bg); padding: 12px; border: 1px solid var(--tooltip-border); border-radius: 8px; color: var(--tooltip-text); max-width: 300px; box-shadow: 0 4px 20px var(--shadow-color);">
                                    <div style="font-size: 12px; line-height: 1.5; font-weight: 600; color: var(--text-subtle);">Source: ${sourceName}</div>
                                    <div style="margin-top: 6px; font-size: 12px; line-height: 1.5; opacity: 0.92;">${description}</div>
                                    <div style="margin-top: 6px; font-size: 11px; line-height: 1.5; color: var(--tooltip-subtle);">${temporalLabel}</div>
                                    <div style="margin-top: 6px; font-size: 12px; line-height: 1.5; font-weight: 600; color: var(--text-subtle);">Target: ${targetName}</div>
                                </div>
                            `;
                        }}
                    />
                )}

                {searchOverlay && (
                    <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10 }}>
                        {searchOverlay}
                    </div>
                )}

                {useEntryRoleColors && (
                    <div
                        style={{
                            position: "absolute",
                            top: 16,
                            left: 16,
                            zIndex: 10,
                            display: "flex",
                            gap: 8,
                            padding: "8px 10px",
                            background: "var(--card)",
                            border: "1px solid var(--border)",
                            borderRadius: "var(--radius)",
                            boxShadow: "0 8px 18px rgba(0,0,0,0.14)",
                        }}
                    >
                        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-primary)" }}>
                            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--primary)", flexShrink: 0 }} />
                            Entry Node
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-primary)" }}>
                            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--status-info-pill-fg)", flexShrink: 0 }} />
                            Expanded Node
                        </div>
                    </div>
                )}

                {(showColorToggle || showRefreshButton || showFitButton) && (
                    <div style={{ position: "absolute", top: 16, right: 16, zIndex: 10, display: "flex", gap: 8 }}>
                        {showColorToggle && (
                            <button
                                onClick={() => setColorBySource(!colorBySource)}
                                style={{
                                    background: colorBySource ? "var(--primary-soft-strong)" : "var(--card)",
                                    border: colorBySource ? "1px solid var(--primary)" : "1px solid var(--border)",
                                    borderRadius: "var(--radius)",
                                    padding: "8px 12px",
                                    cursor: "pointer",
                                    color: colorBySource ? "var(--primary-light)" : "var(--text-subtle)",
                                    fontSize: 13,
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 6,
                                }}
                            >
                                🎨 {colorBySource ? "Source Colors" : "Standard Colors"}
                            </button>
                        )}
                        {showRefreshButton && onRefresh && (
                            <button
                                onClick={onRefresh}
                                style={{
                                    background: "var(--card)",
                                    border: "1px solid var(--border)",
                                    borderRadius: "var(--radius)",
                                    padding: "8px 12px",
                                    cursor: "pointer",
                                    color: "var(--text-subtle)",
                                    fontSize: 13,
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 6,
                                }}
                            >
                                <Maximize size={14} style={{ transform: "rotate(45deg)" }} /> Refresh
                            </button>
                        )}
                        {showFitButton && (
                            <button
                                onClick={fitView}
                                style={{
                                    background: "var(--card)",
                                    border: "1px solid var(--border)",
                                    borderRadius: "var(--radius)",
                                    padding: "8px 12px",
                                    cursor: "pointer",
                                    color: "var(--text-subtle)",
                                    fontSize: 13,
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 6,
                                }}
                            >
                                <Maximize size={14} /> {fitButtonLabel}
                            </button>
                        )}
                    </div>
                )}

                <button
                    onClick={() => setPanelOpen(!panelOpen)}
                    style={{
                        position: "absolute",
                        right: 0,
                        top: "50%",
                        transform: "translateY(-50%)",
                        zIndex: 10,
                        background: "var(--card)",
                        border: "1px solid var(--border)",
                        borderRadius: "8px 0 0 8px",
                        padding: "8px 4px",
                        cursor: "pointer",
                        color: "var(--text-muted)",
                    }}
                >
                    {panelOpen ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
                </button>
            </div>

            {panelOpen && (
                <div style={{
                    width: inspectorWidth,
                    flexShrink: 0,
                    height: "100%",
                    minHeight: 0,
                    background: "var(--card)",
                    borderLeft: "1px solid var(--border)",
                    overflowY: "auto",
                    padding: 20,
                }}>
                    {visibleSelectedNode ? (
                        <>
                            <h3 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16, color: "var(--primary-light)" }}>{visibleSelectedNode.display_name}</h3>
                            {useEntryRoleColors && (
                                <div
                                    style={{
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: 6,
                                        padding: "4px 10px",
                                        borderRadius: 999,
                                        marginBottom: 14,
                                        background: getEntryRolePresentation(visibleSelectedNode).background,
                                        border: `1px solid ${getEntryRolePresentation(visibleSelectedNode).border}`,
                                        color: getEntryRolePresentation(visibleSelectedNode).color,
                                        fontSize: 11,
                                        fontWeight: 700,
                                        letterSpacing: "0.04em",
                                        textTransform: "uppercase",
                                    }}
                                >
                                    {getEntryRolePresentation(visibleSelectedNode).label}
                                </div>
                            )}
                            <div style={{ fontSize: 13, lineHeight: 1.6, color: "var(--text-primary)", marginBottom: 20, whiteSpace: "pre-wrap" }}>
                                {visibleSelectedNode.description}
                            </div>

                            {(visibleSelectedNode.source_chunks?.length || visibleSelectedNode.created_at) ? (
                                <div style={{ marginBottom: 20, padding: 12, background: "var(--primary-soft)", borderRadius: 8, border: "1px solid var(--primary-soft-strong)" }}>
                                    <div style={{ fontSize: 11, color: "var(--primary-light)", fontWeight: 600, textTransform: "uppercase", marginBottom: 8, letterSpacing: "0.05em" }}>Temporal Origin</div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                        {visibleSelectedNode.source_chunks && visibleSelectedNode.source_chunks.length > 0 && (
                                            <div>
                                                <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 2 }}>First Appearance</div>
                                                <div style={{ fontSize: 12, color: "var(--text-primary)" }}>{visibleSelectedNode.source_chunks[0]}</div>
                                            </div>
                                        )}
                                        {visibleSelectedNode.created_at && (
                                            <div>
                                                <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 2 }}>Extracted On</div>
                                                <div style={{ fontSize: 12, color: "var(--text-primary)" }}>{new Date(visibleSelectedNode.created_at).toLocaleString()}</div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ) : null}

                            {visibleSelectedNode.claims && visibleSelectedNode.claims.length > 0 && (
                                <details open style={{ marginBottom: 20 }}>
                                    <summary style={{ fontSize: 14, fontWeight: 600, cursor: "pointer", marginBottom: 8 }}>
                                        Claims ({visibleSelectedNode.claims.length})
                                    </summary>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                        {visibleSelectedNode.claims.map((claim, index) => (
                                            <div key={index} style={{
                                                padding: "8px 10px",
                                                background: "var(--background)",
                                                borderRadius: 8,
                                                fontSize: 12,
                                                lineHeight: 1.5,
                                                border: "1px solid var(--border)",
                                            }}>
                                                {claim.text}
                                                <span style={{
                                                    marginLeft: 6,
                                                    padding: "1px 5px",
                                                    borderRadius: 4,
                                                    background: "var(--status-info-pill-bg)",
                                                    color: "var(--status-info-pill-fg)",
                                                    fontSize: 10,
                                                    fontFamily: "monospace",
                                                }}>
                                                    B{claim.source_book}:C{claim.source_chunk}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </details>
                            )}

                            {visibleSelectedNode.neighbors.length > 0 && (
                                <details open>
                                    <summary style={{ fontSize: 14, fontWeight: 600, cursor: "pointer", marginBottom: 8 }}>
                                        Connected Nodes ({visibleSelectedNode.connection_count ?? visibleSelectedNode.neighbors.length})
                                    </summary>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                                        {visibleSelectedNode.neighbors.map((neighbor, index) => (
                                            <button
                                                key={index}
                                                onClick={() => {
                                                    const nextNode = nodes.find((node) => node.id === neighbor.id);
                                                    if (!nextNode) return;
                                                    const nextDetail = resolveNodeDetail
                                                        ? Promise.resolve(resolveNodeDetail(nextNode))
                                                        : Promise.resolve(getFallbackNodeDetail(nextNode));
                                                    nextDetail.then((value) => {
                                                        if (value) {
                                                            setSelectedNode(value);
                                                        }
                                                    });
                                                }}
                                                style={{
                                                    display: "flex",
                                                    alignItems: "center",
                                                    gap: 8,
                                                    padding: "8px 10px",
                                                    background: "var(--background)",
                                                    border: "1px solid var(--border)",
                                                    borderRadius: 8,
                                                    cursor: "pointer",
                                                    color: "var(--text-primary)",
                                                    fontSize: 12,
                                                    textAlign: "left",
                                                    width: "100%",
                                                }}
                                            >
                                                <span style={{
                                                    width: 8,
                                                    height: 8,
                                                    borderRadius: "50%",
                                                    flexShrink: 0,
                                                    background: "var(--primary)",
                                                }} />
                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                    <div style={{ fontWeight: 500 }}>{neighbor.label}</div>
                                                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{neighbor.description}</div>
                                                </div>
                                            </button>
                                        ))}
                                    </div>
                                </details>
                            )}
                        </>
                    ) : (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)", textAlign: "center" }}>
                            <p style={{ fontSize: 14 }}>{panelPlaceholderTitle}</p>
                            <p style={{ fontSize: 12, marginTop: 4 }}>{panelPlaceholderSubtitle}</p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
