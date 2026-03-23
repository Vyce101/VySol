"use client";

import { useEffect, useRef, useState } from "react";
import {
    AlertTriangle,
    CheckCircle,
    Info,
    Loader2,
    Play,
    RotateCcw,
    XCircle,
} from "lucide-react";
import {
    abortEntityResolution,
    getEntityResolutionCurrent,
    getEntityResolutionStatus,
    startEntityResolution,
    streamEntityResolutionEvents,
    type EntityResolutionEvent,
    type EntityResolutionMode,
    type EntityResolutionRunMode,
    type EntityResolutionStatus,
} from "@/lib/api";

interface EntityResolutionPanelProps {
    worldId: string;
    canResolve: boolean;
    allComplete: boolean;
    isIngesting: boolean;
    disabledReason?: string | null;
}

interface ResolutionLogRow {
    id: string;
    event: EntityResolutionEvent;
    summary: string;
    timestamp: string;
}

function isActiveStatus(value?: string) {
    const normalized = value?.trim().toLowerCase();
    return normalized === "in_progress" || normalized === "running" || normalized === "active" || normalized === "processing";
}

function isTerminalStatus(value?: string) {
    const normalized = value?.trim().toLowerCase();
    return normalized === "complete" || normalized === "completed" || normalized === "aborted" || normalized === "error" || normalized === "failed";
}

function formatCount(value: number | undefined | null) {
    return value === undefined || value === null ? "-" : value.toLocaleString();
}

function formatTitle(value?: string) {
    if (!value) return "Update";
    return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function summarizeEvent(event: EntityResolutionEvent) {
    if (typeof event.message === "string" && event.message.trim()) {
        return event.message.trim();
    }
    if (typeof event.reason === "string" && event.reason.trim()) {
        return event.reason.trim();
    }
    if (typeof event.phase === "string" && event.phase.trim()) {
        return `Phase: ${formatTitle(event.phase)}`;
    }
    if (typeof event.status === "string" && event.status.trim()) {
        return `Status: ${formatTitle(event.status)}`;
    }

    const anchor = event.current_anchor as { display_name?: string } | undefined;
    const anchorLabel = typeof event.current_anchor_label === "string" && event.current_anchor_label.trim()
        ? event.current_anchor_label.trim()
        : "Current Anchor";
    if (anchor?.display_name) {
        return `${anchorLabel}: ${anchor.display_name}`;
    }

    const candidates = event.current_candidates as unknown[] | undefined;
    if (Array.isArray(candidates)) {
        return `${candidates.length} candidate${candidates.length === 1 ? "" : "s"} ready`;
    }

    return "Resolution update received";
}

function statusBadge(status?: string, phase?: string) {
    const normalized = status?.trim().toLowerCase();
    const normalizedPhase = phase?.trim().toLowerCase();
    if (isActiveStatus(normalized)) {
        if (normalizedPhase === "aborting") {
            return { bg: "var(--status-pending-bg)", fg: "var(--status-pending-fg)", label: "Aborting" };
        }
        return { bg: "var(--status-progress-bg)", fg: "var(--status-progress-fg)", label: "Running" };
    }
    if (normalized === "complete" || normalized === "completed") {
        return { bg: "var(--status-success-bg)", fg: "var(--status-success-fg)", label: "Complete" };
    }
    if (normalized === "aborted") {
        return { bg: "var(--status-pending-bg)", fg: "var(--status-pending-fg)", label: "Aborted" };
    }
    if (normalized === "error" || normalized === "failed") {
        return { bg: "var(--status-error-bg)", fg: "var(--status-error-fg)", label: "Error" };
    }
    return { bg: "var(--background-tertiary)", fg: "var(--text-subtle)", label: "Idle" };
}

function isRequestResolutionMode(value: unknown): value is EntityResolutionMode {
    return value === "exact_only" || value === "exact_then_ai";
}

function formatResolutionMode(mode?: string) {
    if (mode === "exact_only") {
        return "Exact Only";
    }
    if (mode === "ai_only") {
        return "Chooser/Combiner Only (Legacy)";
    }
    return "Exact + Chooser/Combiner";
}

function isCompletedStatus(value?: string) {
    const normalized = value?.trim().toLowerCase();
    return normalized === "complete" || normalized === "completed";
}

function normalizeResolutionText(value: unknown): string | null {
    const normalized = typeof value === "string" ? value.trim() : "";
    return normalized ? normalized : null;
}

function getResolutionFailureMessage(payload: {
    event?: unknown;
    status?: unknown;
    message?: unknown;
    reason?: unknown;
}): string | null {
    const event = typeof payload.event === "string" ? payload.event.trim().toLowerCase() : undefined;
    const status = typeof payload.status === "string" ? payload.status.trim().toLowerCase() : undefined;
    if (event !== "error" && status !== "error" && status !== "failed") {
        return null;
    }
    return normalizeResolutionText(payload.message)
        ?? normalizeResolutionText(payload.reason)
        ?? "Entity resolution failed.";
}

function getResolutionStatusDetail(payload: {
    message?: unknown;
    reason?: unknown;
}, failureMessage?: string | null): string | null {
    if (failureMessage) return null;
    return normalizeResolutionText(payload.message) ?? normalizeResolutionText(payload.reason);
}

export default function EntityResolutionPanel({
    worldId,
    canResolve,
    allComplete,
    isIngesting,
    disabledReason,
}: EntityResolutionPanelProps) {
    const [open, setOpen] = useState(false);
    const [topK, setTopK] = useState(50);
    const [embeddingBatchSize, setEmbeddingBatchSize] = useState(32);
    const [embeddingCooldownSeconds, setEmbeddingCooldownSeconds] = useState(0);
    const [resolutionMode, setResolutionMode] = useState<EntityResolutionMode>("exact_only");
    const [status, setStatus] = useState<EntityResolutionStatus | null>(null);
    const [logs, setLogs] = useState<ResolutionLogRow[]>([]);
    const [running, setRunning] = useState(false);
    const [streamState, setStreamState] = useState<"idle" | "connecting" | "streaming">("idle");
    const [busy, setBusy] = useState(false);
    const [failureMessage, setFailureMessage] = useState<string | null>(null);
    const [statusDetail, setStatusDetail] = useState<string | null>(null);
    const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
    const eventSourceRef = useRef<EventSource | null>(null);
    const statusRef = useRef<(EntityResolutionStatus & Partial<EntityResolutionEvent>) | null>(null);
    const logIdRef = useRef(0);

    function closeStream() {
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        setStreamState("idle");
    }

    function syncStatusMessages(next: Partial<EntityResolutionStatus & EntityResolutionEvent>) {
        const nextFailureMessage = getResolutionFailureMessage(next);
        setFailureMessage(nextFailureMessage);
        setStatusDetail(getResolutionStatusDetail(next, nextFailureMessage));
    }

    function applyStatus(next: EntityResolutionStatus) {
        statusRef.current = next;
        setStatus(next);
        setRunning(isActiveStatus(next.status));
        setLastSyncedAt(new Date().toISOString());
        syncStatusMessages(next);
        if (typeof next.top_k === "number") {
            setTopK(next.top_k);
        }
        if (typeof next.embedding_batch_size === "number") {
            setEmbeddingBatchSize(Math.max(1, Math.trunc(next.embedding_batch_size)));
        }
        if (typeof next.embedding_cooldown_seconds === "number") {
            setEmbeddingCooldownSeconds(Math.max(0, next.embedding_cooldown_seconds));
        }
        if (isRequestResolutionMode(next.resolution_mode)) {
            setResolutionMode(next.resolution_mode);
        }
    }

    function pushEvent(event: EntityResolutionEvent) {
        setStreamState("streaming");
        const nextStatus = { ...(statusRef.current || {}), ...event };
        statusRef.current = nextStatus;
        setStatus(nextStatus);
        setRunning(!isTerminalStatus(event.status) && !isTerminalStatus(event.event));
        syncStatusMessages(nextStatus);
        setLogs((prev) => {
            logIdRef.current += 1;
            const nextRow: ResolutionLogRow = {
                id: `entity-resolution-log-${logIdRef.current}`,
                event,
                summary: summarizeEvent(event),
                timestamp: new Date().toISOString(),
            };
            return [...prev.slice(-49), nextRow];
        });
    }

    function openStream() {
        closeStream();
        setStreamState("connecting");
        setFailureMessage(null);
        eventSourceRef.current = streamEntityResolutionEvents(
            worldId,
            pushEvent,
            () => {
                closeStream();
                void loadSnapshot(false);
            },
            (streamError) => {
                closeStream();
                void loadSnapshot(false).then((synced) => {
                    if (!synced) {
                        setFailureMessage((previous) => previous ?? streamError.message);
                        setStatusDetail(null);
                    }
                });
            }
        );
    }

    async function loadSnapshot(allowReconnect = true): Promise<boolean> {
        try {
            const live = await getEntityResolutionStatus(worldId);
            applyStatus(live);
            if (isActiveStatus(live.status) && allowReconnect) {
                openStream();
            } else {
                closeStream();
            }
            return true;
        } catch {
            try {
                const snapshot = await getEntityResolutionCurrent(worldId);
                applyStatus(snapshot);
                if (isActiveStatus(snapshot.status) && allowReconnect) {
                    openStream();
                } else {
                    closeStream();
                }
                return true;
            } catch (snapshotError) {
                closeStream();
                statusRef.current = null;
                setStatus(null);
                setRunning(false);
                setLastSyncedAt(new Date().toISOString());
                setFailureMessage(snapshotError instanceof Error ? snapshotError.message : "Entity-resolution status is not available yet.");
                setStatusDetail(null);
                return false;
            }
        }
    }
    useEffect(() => {
        void loadSnapshot(true);
        return () => closeStream();
        // We intentionally only bind to world changes so live SSE can continue across re-renders.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [worldId]);

    const gateMessage = running
        ? status?.phase === "aborting"
            ? "Entity resolution is stopping after the current in-flight work finishes."
            : "Entity resolution is running and can be monitored here."
        : disabledReason
            ? disabledReason
            : isIngesting
                ? "Wait for ingestion to finish before starting entity resolution."
                : canResolve
                    ? "Ready for post-ingestion entity resolution."
                    : !allComplete
                        ? "Finish ingestion or retry failed chunks before resolving entities."
                        : "Entity resolution is currently unavailable for this world.";

    const triggerLabel = running ? "Monitor Entities" : "Resolve Entities";
    const triggerDisabled = !running && !canResolve;
    const abortRequested = running && status?.phase === "aborting";
    const badge = statusBadge(status?.status || (running ? "running" : "idle"), status?.phase);
    const lastUsedResolutionMode = status?.resolution_mode as EntityResolutionRunMode | undefined;
    const currentAnchorLabel = typeof status?.current_anchor_label === "string" && status.current_anchor_label.trim()
        ? status.current_anchor_label.trim()
        : "Current Anchor";
    const showExactOnlyOutcomeLabels = isCompletedStatus(status?.status) && lastUsedResolutionMode === "exact_only";
    const unresolvedMetricTooltip = showExactOnlyOutcomeLabels
        ? "These entities were checked during exact normalization, but no exact normalized match was found."
        : undefined;
    const newNodesValue = typeof status?.new_nodes_since_last_completed_resolution === "number"
        ? formatCount(status.new_nodes_since_last_completed_resolution)
        : "Unavailable";
    const summaryMetrics = [
        {
            key: "processed",
            label: showExactOnlyOutcomeLabels ? "Exact Matches" : "Processed",
            value: formatCount(status?.resolved_entities as number | undefined),
            tooltip: undefined,
        },
        {
            key: "remaining",
            label: showExactOnlyOutcomeLabels ? "Left Unchanged" : "Remaining",
            value: formatCount(status?.unresolved_entities as number | undefined),
            tooltip: unresolvedMetricTooltip,
        },
        {
            key: "new_nodes",
            label: "New Nodes",
            value: newNodesValue,
            tooltip: undefined,
        },
    ];
    const lastTopKValue = lastUsedResolutionMode === undefined
        ? "Not run yet"
        : lastUsedResolutionMode === "exact_only"
            ? "Not Used"
            : typeof status?.top_k === "number"
                ? formatCount(status.top_k)
                : "Not run yet";
    const lastEmbeddingBatchValue = typeof status?.embedding_batch_size === "number"
        ? formatCount(Math.max(1, Math.trunc(status.embedding_batch_size)))
        : "Not run yet";
    const lastEmbeddingDelayValue = typeof status?.embedding_cooldown_seconds === "number"
        ? `${Math.max(0, status.embedding_cooldown_seconds).toFixed(2)}s`
        : "Not run yet";
    const summaryDetails = [
        {
            key: "phase",
            label: "Phase",
            value: formatTitle((status?.phase as string | undefined) || "waiting"),
        },
        {
            key: "mode",
            label: "Last Used Mode",
            value: lastUsedResolutionMode ? formatResolutionMode(lastUsedResolutionMode) : "Not run yet",
        },
        {
            key: "top_k",
            label: "Last Top K",
            value: lastTopKValue,
        },
        {
            key: "embed_batch",
            label: "Last Embedding Batch",
            value: lastEmbeddingBatchValue,
        },
        {
            key: "embed_delay",
            label: "Last Embedding Delay",
            value: lastEmbeddingDelayValue,
        },
    ];
    const eventRows = [...logs].reverse();

    const handleStart = async () => {
        setBusy(true);
        setFailureMessage(null);
        setLogs([]);
        try {
            await startEntityResolution(worldId, {
                top_k: topK,
                resolution_mode: resolutionMode,
                embedding_batch_size: embeddingBatchSize,
                embedding_cooldown_seconds: embeddingCooldownSeconds,
            });
            setOpen(true);
            await loadSnapshot(true);
        } catch (startError) {
            setFailureMessage(startError instanceof Error ? startError.message : "Unable to start entity resolution.");
            setStatusDetail(null);
            setRunning(false);
        } finally {
            setBusy(false);
        }
    };

    const handleAbort = async () => {
        setBusy(true);
        setFailureMessage(null);
        try {
            await abortEntityResolution(worldId);
            await loadSnapshot(true);
        } catch (abortError) {
            setFailureMessage(abortError instanceof Error ? abortError.message : "Unable to abort entity resolution.");
            setStatusDetail(null);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button
                    onClick={() => setOpen(true)}
                    disabled={triggerDisabled}
                    style={{
                        ...buttonStyle,
                        width: "100%",
                        background: running ? "var(--primary-soft-strong)" : "var(--primary)",
                        color: running ? "var(--primary-light)" : "var(--primary-contrast)",
                        opacity: triggerDisabled ? 0.45 : 1,
                    }}
                >
                    {running ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Play size={14} />}
                    {triggerLabel}
                </button>
                {triggerDisabled && (
                    <span
                        title={gateMessage}
                        aria-label={gateMessage}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            width: 28,
                            height: 28,
                            borderRadius: 9999,
                            border: "1px solid var(--border)",
                            color: "var(--text-subtle)",
                            flexShrink: 0,
                            cursor: "help",
                        }}
                    >
                        <Info size={14} />
                    </span>
                )}
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.45 }}>
                {running ? gateMessage : "Use the button above to open the entity-resolution workspace."}
            </div>

            {open && (
                <div
                    role="dialog"
                    aria-modal="true"
                    style={{
                        position: "fixed",
                        inset: 0,
                        zIndex: 1000,
                        background: "var(--overlay-strong)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        padding: 20,
                    }}
                >
                    <div
                        style={{
                            width: "100%",
                            maxWidth: 1100,
                            maxHeight: "92vh",
                            overflow: "hidden",
                            display: "flex",
                            flexDirection: "column",
                            background: "var(--background)",
                            border: "1px solid var(--border)",
                            borderRadius: "var(--radius)",
                            boxShadow: "0 24px 48px var(--shadow-color)",
                        }}
                    >
                        <div
                            style={{
                                display: "flex",
                                alignItems: "flex-start",
                                justifyContent: "space-between",
                                gap: 16,
                                padding: "18px 20px",
                                borderBottom: "1px solid var(--border)",
                            }}
                        >
                            <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                                    <h3 style={{ fontSize: 18, fontWeight: 700 }}>Entity Resolution</h3>
                                    <span
                                        style={{
                                            padding: "3px 10px",
                                            borderRadius: 9999,
                                            fontSize: 11,
                                            fontWeight: 700,
                                            background: badge.bg,
                                            color: badge.fg,
                                        }}
                                    >
                                        {badge.label}
                                    </span>
                                </div>
                                <p style={{ fontSize: 13, color: "var(--text-muted)", maxWidth: 820, lineHeight: 1.5 }}>
                                    Run either an exact-only normalization pass or continue into chooser/combiner review after exact matches are merged. Temporal edges stay intact.
                                </p>
                            </div>
                            <button
                                onClick={() => setOpen(false)}
                                style={{
                                    background: "none",
                                    border: "none",
                                    color: "var(--text-muted)",
                                    cursor: "pointer",
                                    padding: 4,
                                    flexShrink: 0,
                                }}
                            >
                                <XCircle size={20} />
                            </button>
                        </div>

                        <div
                            style={{
                                flex: 1,
                                overflowY: "auto",
                                padding: 20,
                                display: "flex",
                                flexDirection: "column",
                                gap: 16,
                            }}
                        >
                            <div
                                style={{
                                    display: "flex",
                                    flexWrap: "wrap",
                                    gap: 16,
                                    alignItems: "stretch",
                                }}
                            >
                                <div style={{ ...panelStyle, flex: "1.35 1 460px", minWidth: 0, display: "flex", flexDirection: "column" }}>
                                    <div style={panelHeaderStyle}>Controls</div>
                                    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
                                        <div style={{ display: "grid", gap: 12, marginTop: 8 }}>
                                            <label style={controlLabelStyle}>
                                                <span style={controlTextStyle}>Resolution mode</span>
                                                <select
                                                    value={resolutionMode}
                                                    onChange={(e) => setResolutionMode(e.target.value as EntityResolutionMode)}
                                                    disabled={busy || running}
                                                    style={controlInputStyle}
                                                >
                                                    <option value="exact_only">Exact only</option>
                                                    <option value="exact_then_ai">Exact + chooser/combiner</option>
                                                </select>
                                            </label>
                                            <label style={controlLabelStyle}>
                                                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                                    <span style={controlTextStyle}>Top K candidates</span>
                                                    <span
                                                        title={resolutionMode === "exact_only"
                                                            ? "Exact-only runs skip candidate search, so Top K is not used."
                                                            : "Used for candidate search before chooser/combiner review."}
                                                        aria-label={resolutionMode === "exact_only"
                                                            ? "Exact-only runs skip candidate search, so Top K is not used."
                                                            : "Used for candidate search before chooser/combiner review."}
                                                        style={summaryInfoIconStyle}
                                                    >
                                                        <Info size={12} />
                                                    </span>
                                                </span>
                                                <input
                                                    type="number"
                                                    min={1}
                                                    max={250}
                                                    value={topK}
                                                    onChange={(e) => setTopK(Number(e.target.value) || 1)}
                                                    disabled={busy || running || resolutionMode === "exact_only"}
                                                    style={controlInputStyle}
                                                />
                                            </label>
                                            <label style={controlLabelStyle}>
                                                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                                    <span style={controlTextStyle}>Embedding batch size</span>
                                                    <span
                                                        title="Applies to unique-node re-embedding during entity resolution, including exact-only runs."
                                                        aria-label="Applies to unique-node re-embedding during entity resolution, including exact-only runs."
                                                        style={summaryInfoIconStyle}
                                                    >
                                                        <Info size={12} />
                                                    </span>
                                                </span>
                                                <input
                                                    type="number"
                                                    min={1}
                                                    max={1000}
                                                    value={embeddingBatchSize}
                                                    onChange={(e) => setEmbeddingBatchSize(Math.max(1, Number(e.target.value) || 1))}
                                                    disabled={busy || running}
                                                    style={controlInputStyle}
                                                />
                                            </label>
                                            <label style={controlLabelStyle}>
                                                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                                    <span style={controlTextStyle}>Embedding delay (seconds)</span>
                                                    <span
                                                        title="Wait time between unique-node embedding batches. This does not affect chooser or combiner model calls."
                                                        aria-label="Wait time between unique-node embedding batches. This does not affect chooser or combiner model calls."
                                                        style={summaryInfoIconStyle}
                                                    >
                                                        <Info size={12} />
                                                    </span>
                                                </span>
                                                <input
                                                    type="number"
                                                    min={0}
                                                    step={0.1}
                                                    value={embeddingCooldownSeconds}
                                                    onChange={(e) => setEmbeddingCooldownSeconds(Math.max(0, Number(e.target.value) || 0))}
                                                    disabled={busy || running}
                                                    style={controlInputStyle}
                                                />
                                            </label>
                                        </div>

                                        <div style={{ marginTop: "auto", paddingTop: 20 }}>
                                            <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                                Entity resolution uses its own per-run embedding batch and delay controls here. These settings do not change ingest or Re-embed All behavior.
                                            </div>

                                            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 16 }}>
                                                {!running ? (
                                                    <button
                                                        onClick={() => void handleStart()}
                                                        disabled={!canResolve || busy}
                                                        style={{
                                                            ...buttonStyle,
                                                            background: "var(--primary)",
                                                            color: "var(--primary-contrast)",
                                                            opacity: !canResolve || busy ? 0.45 : 1,
                                                        }}
                                                    >
                                                        {busy ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Play size={14} />}
                                                        Start Resolution
                                                    </button>
                                                ) : (
                                                    <button
                                                        onClick={() => void handleAbort()}
                                                        disabled={busy || abortRequested}
                                                        style={{
                                                            ...buttonStyle,
                                                            background: "var(--status-error-bg)",
                                                            color: "var(--status-error-fg)",
                                                            opacity: busy || abortRequested ? 0.45 : 1,
                                                        }}
                                                    >
                                                        {busy ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <AlertTriangle size={14} />}
                                                        {abortRequested ? "Aborting..." : "Abort Run"}
                                                    </button>
                                                )}

                                                <button
                                                    onClick={() => void loadSnapshot(true)}
                                                    disabled={busy}
                                                    style={{
                                                        ...buttonStyle,
                                                        background: "var(--card)",
                                                        color: "var(--text-primary)",
                                                        opacity: busy ? 0.45 : 1,
                                                    }}
                                                >
                                                    <RotateCcw size={14} />
                                                    Refresh Status
                                                </button>
                                            </div>

                                            {statusDetail && (
                                                <div
                                                    style={{
                                                        marginTop: 14,
                                                        padding: "10px 12px",
                                                        borderRadius: 10,
                                                        border: "1px solid var(--border)",
                                                        background: "var(--background)",
                                                        color: "var(--text-primary)",
                                                        fontSize: 13,
                                                        lineHeight: 1.5,
                                                    }}
                                                >
                                                    {statusDetail}
                                                </div>
                                            )}

                                            {failureMessage && (
                                                <div
                                                    style={{
                                                        marginTop: 14,
                                                        padding: "10px 12px",
                                                        borderRadius: 10,
                                                        border: "1px solid var(--status-error-soft-border)",
                                                        background: "var(--status-error-soft-bg)",
                                                        color: "var(--status-error-fg)",
                                                        fontSize: 13,
                                                        lineHeight: 1.5,
                                                    }}
                                                >
                                                    {failureMessage}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div style={{ ...panelStyle, flex: "0.85 1 320px", minWidth: 0, maxWidth: "100%", display: "flex", flexDirection: "column" }}>
                                    <div style={panelHeaderStyle}>Last Run Summary</div>
                                    <div style={{ ...summarySurfaceStyle, flex: 1 }}>
                                        <div style={summaryMetricGridStyle}>
                                            {summaryMetrics.map((metric) => (
                                                <div key={metric.key} style={{ minWidth: 0 }}>
                                                    <div style={summaryMetricLabelRowStyle}>
                                                        <span style={summaryLabelStyle}>{metric.label}</span>
                                                        {metric.tooltip && (
                                                            <span
                                                                title={metric.tooltip}
                                                                aria-label={metric.tooltip}
                                                                style={summaryInfoIconStyle}
                                                            >
                                                                <Info size={12} />
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div style={summaryMetricValueStyle}>{metric.value}</div>
                                                </div>
                                            ))}
                                        </div>
                                        <div style={summaryDividerStyle} />
                                        <div style={summaryDetailsGridStyle}>
                                            {summaryDetails.map((detail) => (
                                                <div key={detail.key} style={{ minWidth: 0 }}>
                                                    <div style={summaryDetailLabelStyle}>{detail.label}</div>
                                                    <div style={summaryDetailValueStyle}>{detail.value}</div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {status?.current_anchor && (
                                <div style={panelStyle}>
                                    <div style={panelHeaderStyle}>{currentAnchorLabel}</div>
                                    <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                                        {(status.current_anchor as { display_name?: string }).display_name || "Unnamed entity"}
                                    </div>
                                    {(status.current_anchor as { description?: string }).description && (
                                        <div style={{ fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                            {(status.current_anchor as { description?: string }).description}
                                        </div>
                                    )}
                                </div>
                            )}

                            {status?.current_candidates && Array.isArray(status.current_candidates) && status.current_candidates.length > 0 && (
                                <div style={panelStyle}>
                                    <div style={panelHeaderStyle}>Top Candidates</div>
                                    <div style={{ display: "grid", gap: 10 }}>
                                        {(status.current_candidates as Array<{ node_id?: string; display_name?: string; description?: string; score?: number }>).slice(0, 6).map((candidate, index) => (
                                            <div
                                                key={`${candidate.node_id || index}`}
                                                style={{
                                                    border: "1px solid var(--border)",
                                                    borderRadius: 10,
                                                    padding: 12,
                                                    background: "var(--card)",
                                                }}
                                            >
                                                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 6 }}>
                                                    <div style={{ fontSize: 14, fontWeight: 600 }}>
                                                        {candidate.display_name || candidate.node_id || `Candidate ${index + 1}`}
                                                    </div>
                                                    {candidate.score !== undefined && (
                                                        <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "monospace" }}>
                                                            {candidate.score.toFixed(3)}
                                                        </div>
                                                    )}
                                                </div>
                                                {candidate.description && (
                                                    <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                                        {candidate.description}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div style={panelStyle}>
                                <div style={panelHeaderStyle}>Live Events</div>
                                <div style={{ marginTop: 6, fontSize: 12, color: "var(--text-muted)" }}>
                                    {streamState === "connecting" && "Connecting to live updates..."}
                                    {streamState === "streaming" && "Receiving live SSE updates."}
                                    {streamState === "idle" && "Live updates will appear here when the resolver is active."}
                                    {lastSyncedAt && ` Last synced ${new Date(lastSyncedAt).toLocaleTimeString()}.`}
                                </div>

                                <div
                                    style={{
                                        marginTop: 12,
                                        maxHeight: 320,
                                        overflowY: "auto",
                                        border: "1px solid var(--border)",
                                        borderRadius: 10,
                                        background: "var(--background)",
                                    }}
                                >
                                    {eventRows.length === 0 ? (
                                        <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>
                                            No events yet.
                                        </div>
                                    ) : (
                                        eventRows.map((row) => {
                                            const rawType = row.event.event || row.event.phase || row.event.status || "update";
                                            const normalizedType = formatTitle(typeof rawType === "string" ? rawType : "update");
                                            const isError = rawType === "error" || rawType === "failed";
                                            const isDone = rawType === "complete" || rawType === "completed" || rawType === "aborted";
                                            return (
                                                <div
                                                    key={row.id}
                                                    style={{
                                                        padding: 12,
                                                        borderBottom: "1px solid var(--border)",
                                                        display: "flex",
                                                        gap: 10,
                                                        alignItems: "flex-start",
                                                    }}
                                                >
                                                    <div style={{ marginTop: 1, color: isError ? "var(--status-error-fg)" : isDone ? "var(--status-success-fg)" : "var(--text-muted)" }}>
                                                        {isError ? (
                                                            <XCircle size={14} />
                                                        ) : isDone ? (
                                                            <CheckCircle size={14} />
                                                        ) : (
                                                            <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
                                                        )}
                                                    </div>
                                                    <div style={{ flex: 1, minWidth: 0 }}>
                                                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 3 }}>
                                                            <div style={{ fontSize: 13, fontWeight: 600 }}>{normalizedType}</div>
                                                            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                                                                {new Date(row.timestamp).toLocaleTimeString()}
                                                            </div>
                                                        </div>
                                                        <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                                            {row.summary}
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })
                                    )}
                                </div>
                            </div>

                            <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5, display: "flex", gap: 8 }}>
                                <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                                <span>
                                    Assumption: the backend exposes `start`, `status`, `events`, `abort`, and `current` under `/worlds/{worldId}/entity-resolution`. If the event payload shape changes, this panel will still render the generic message and the latest status snapshot.
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

const buttonStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    padding: "8px 16px",
    borderRadius: "var(--radius)",
    border: "none",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    transition: "opacity 0.2s",
};

const panelStyle: React.CSSProperties = {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: 16,
    background: "var(--card)",
};

const panelHeaderStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    marginBottom: 10,
    fontSize: 14,
    fontWeight: 700,
};

const summaryLabelStyle: React.CSSProperties = {
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "var(--text-muted)",
};

const summarySurfaceStyle: React.CSSProperties = {
    border: "1px solid var(--border)",
    borderRadius: 12,
    padding: 16,
    background: "var(--background)",
};

const summaryMetricGridStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    gap: 16,
};

const summaryMetricLabelRowStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
};

const summaryMetricValueStyle: React.CSSProperties = {
    fontSize: 28,
    fontWeight: 700,
    lineHeight: 1.1,
};

const summaryInfoIconStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    color: "var(--text-muted)",
    cursor: "help",
};

const summaryDividerStyle: React.CSSProperties = {
    height: 1,
    background: "var(--border)",
    margin: "18px 0",
};

const summaryDetailsGridStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 14,
};

const summaryDetailLabelStyle: React.CSSProperties = {
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "var(--text-muted)",
    marginBottom: 6,
};

const summaryDetailValueStyle: React.CSSProperties = {
    fontSize: 14,
    fontWeight: 600,
    color: "var(--text-primary)",
};

const controlLabelStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    fontSize: 13,
};

const controlTextStyle: React.CSSProperties = {
    fontWeight: 600,
    color: "var(--text-primary)",
};

const controlInputStyle: React.CSSProperties = {
    width: "100%",
    maxWidth: 240,
};
