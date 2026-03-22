export type IngestProgressPhase = "extracting" | "embedding" | "aborting" | "idle";
export type IngestWaitState = "queued_for_extraction_slot" | "queued_for_embedding_slot" | "waiting_for_api_key";

export interface IngestStageCounters {
    expected_chunks?: number;
    extracted_chunks?: number;
    embedded_chunks?: number;
    current_unique_nodes?: number;
    embedded_unique_nodes?: number;
    failed_records?: number;
    sources_total?: number;
    sources_complete?: number;
    sources_partial_failure?: number;
}

export interface IngestProgressPayload {
    active_operation?: string;
    progress_phase?: IngestProgressPhase;
    completed_chunks_current_phase?: number;
    total_chunks_current_phase?: number;
    chunks_total?: number;
    chunk_index?: number;
    stage_counters?: IngestStageCounters;
    wait_state?: IngestWaitState | null;
    wait_label?: string | null;
    wait_retry_after_seconds?: number | null;
    active_agent?: string | null;
    progress_source_id?: string | null;
    progress_source_display_name?: string | null;
    progress_source_book_number?: number | null;
}

export interface StableIngestRow {
    key: string;
    label: string;
    completed: number;
    total: number;
    percent: number;
    infoTitle?: string;
}

export interface StableIngestProgress {
    operation: string;
    phase: IngestProgressPhase;
    expectedChunks: number;
    extractedChunks: number;
    embeddedChunks: number;
    currentUniqueNodes: number;
    embeddedUniqueNodes: number;
    completedWorkUnits: number;
    totalWorkUnits: number;
    overallPercent: number;
    rows: StableIngestRow[];
    waitState: IngestWaitState | null;
    waitLabel: string | null;
    waitRetryAfterSeconds: number | null;
    activeAgent: string | null;
    progressSourceId: string | null;
    progressSourceDisplayName: string | null;
    progressSourceBookNumber: number | null;
    isReembedAll: boolean;
    isAborting: boolean;
}

function asCount(value: unknown): number {
    const numeric = Number(value ?? 0);
    if (!Number.isFinite(numeric)) return 0;
    return Math.max(0, Math.trunc(numeric));
}

export function clampPercent(value: number): number {
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(100, value));
}

function rowPercent(completed: number, total: number): number {
    return total > 0 ? clampPercent((completed / total) * 100) : 0;
}

function fallbackExpectedChunks(payload: IngestProgressPayload): number {
    return Math.max(
        asCount(payload.stage_counters?.expected_chunks),
        asCount(payload.total_chunks_current_phase),
        asCount(payload.chunks_total),
    );
}

function fallbackExtractedChunks(payload: IngestProgressPayload, expectedChunks: number): number {
    const fromStageCounters = asCount(payload.stage_counters?.extracted_chunks);
    if (fromStageCounters > 0) return fromStageCounters;

    const phase = payload.progress_phase ?? "idle";
    const phaseCompleted = Math.max(
        asCount(payload.completed_chunks_current_phase),
        asCount(payload.chunk_index),
    );
    if (payload.active_operation === "reembed_all") {
        return expectedChunks;
    }
    if (phase === "extracting") {
        return phaseCompleted;
    }
    if (phase === "embedding" || phase === "aborting") {
        return expectedChunks > 0 ? expectedChunks : phaseCompleted;
    }
    return phaseCompleted;
}

function fallbackEmbeddedChunks(payload: IngestProgressPayload): number {
    const fromStageCounters = asCount(payload.stage_counters?.embedded_chunks);
    if (fromStageCounters > 0) return fromStageCounters;

    const phase = payload.progress_phase ?? "idle";
    const phaseCompleted = Math.max(
        asCount(payload.completed_chunks_current_phase),
        asCount(payload.chunk_index),
    );
    if (phase === "embedding" || phase === "aborting") {
        return phaseCompleted;
    }
    return 0;
}

function fallbackCurrentUniqueNodes(payload: IngestProgressPayload): number {
    return asCount(payload.stage_counters?.current_unique_nodes);
}

function fallbackEmbeddedUniqueNodes(payload: IngestProgressPayload): number {
    return asCount(payload.stage_counters?.embedded_unique_nodes);
}

export function resolveStableIngestProgress(payload?: IngestProgressPayload | null): StableIngestProgress {
    const operation = String(payload?.active_operation ?? "default");
    const phase = payload?.progress_phase ?? "idle";
    const expectedChunks = fallbackExpectedChunks(payload ?? {});
    const extractedChunks = Math.min(expectedChunks || Number.MAX_SAFE_INTEGER, fallbackExtractedChunks(payload ?? {}, expectedChunks));
    const embeddedChunks = Math.min(expectedChunks || Number.MAX_SAFE_INTEGER, fallbackEmbeddedChunks(payload ?? {}));
    const currentUniqueNodes = fallbackCurrentUniqueNodes(payload ?? {});
    const embeddedUniqueNodes = Math.min(
        currentUniqueNodes || Number.MAX_SAFE_INTEGER,
        fallbackEmbeddedUniqueNodes(payload ?? {}),
    );
    const isReembedAll = operation === "reembed_all";
    const isAborting = phase === "aborting";

    const completedWorkUnits = isReembedAll ? embeddedChunks : extractedChunks + embeddedChunks;
    const totalWorkUnits = isReembedAll ? expectedChunks : expectedChunks * 2;
    const overallPercent = totalWorkUnits > 0 ? clampPercent((completedWorkUnits / totalWorkUnits) * 100) : 0;

    const rows: StableIngestRow[] = isReembedAll
        ? [
            {
                key: "reembed",
                label: "Chunks Re-embedded",
                completed: embeddedChunks,
                total: expectedChunks,
                percent: rowPercent(embeddedChunks, expectedChunks),
            },
            {
                key: "unique-graph-nodes",
                label: "Unique Graph Nodes",
                completed: currentUniqueNodes,
                total: currentUniqueNodes,
                percent: currentUniqueNodes > 0 ? 100 : 0,
                infoTitle: "Shows the current unique nodes in the graph. This can change after entity resolution merges duplicate nodes.",
            },
            {
                key: "embedded-unique-nodes",
                label: "Embedded Unique Nodes",
                completed: embeddedUniqueNodes,
                total: currentUniqueNodes,
                percent: rowPercent(embeddedUniqueNodes, currentUniqueNodes),
                infoTitle: "Shows how many current unique graph nodes already have embeddings in the unique-node index. This count is tied to the current graph and can change when entity resolution refreshes node embeddings.",
            },
        ]
        : [
            {
                key: "extracted",
                label: "Chunks Extracted",
                completed: extractedChunks,
                total: expectedChunks,
                percent: rowPercent(extractedChunks, expectedChunks),
            },
            {
                key: "embedded",
                label: "Chunks Embedded",
                completed: embeddedChunks,
                total: expectedChunks,
                percent: rowPercent(embeddedChunks, expectedChunks),
            },
            {
                key: "unique-graph-nodes",
                label: "Unique Graph Nodes",
                completed: currentUniqueNodes,
                total: currentUniqueNodes,
                percent: currentUniqueNodes > 0 ? 100 : 0,
                infoTitle: "Shows the current unique nodes in the graph. This can change after entity resolution merges duplicate nodes.",
            },
            {
                key: "embedded-unique-nodes",
                label: "Embedded Unique Nodes",
                completed: embeddedUniqueNodes,
                total: currentUniqueNodes,
                percent: rowPercent(embeddedUniqueNodes, currentUniqueNodes),
                infoTitle: "Shows how many current unique graph nodes already have embeddings in the unique-node index. This count is tied to the current graph and can change when entity resolution refreshes node embeddings.",
            },
        ];

    return {
        operation,
        phase,
        expectedChunks,
        extractedChunks,
        embeddedChunks,
        currentUniqueNodes,
        embeddedUniqueNodes,
        completedWorkUnits,
        totalWorkUnits,
        overallPercent,
        rows,
        waitState: payload?.wait_state ?? null,
        waitLabel: payload?.wait_label ?? null,
        waitRetryAfterSeconds: payload?.wait_retry_after_seconds ?? null,
        activeAgent: payload?.active_agent ?? null,
        progressSourceId: payload?.progress_source_id ?? null,
        progressSourceDisplayName: payload?.progress_source_display_name ?? null,
        progressSourceBookNumber: payload?.progress_source_book_number ?? null,
        isReembedAll,
        isAborting,
    };
}

export function formatIngestAgentLabel(agent?: string | null): string | null {
    const normalized = String(agent ?? "").trim();
    if (!normalized) return null;
    return normalized
        .split("_")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

function formatRetryAfterSuffix(seconds?: number | null): string | null {
    if (!Number.isFinite(Number(seconds))) return null;
    return `(~${Math.max(1, Math.ceil(Number(seconds)))}s)`;
}

export function buildIngestActivityLabel(
    progress: StableIngestProgress,
    options?: { fallbackSourceDisplayName?: string | null },
): string | null {
    const pieces: string[] = [];
    if (typeof progress.progressSourceBookNumber === "number" && Number.isFinite(progress.progressSourceBookNumber)) {
        pieces.push(`Book ${progress.progressSourceBookNumber}`);
    }

    const sourceName = String(
        progress.progressSourceDisplayName
        ?? options?.fallbackSourceDisplayName
        ?? "",
    ).trim();
    if (sourceName) {
        pieces.push(sourceName);
    }

    let activity = "";
    if (progress.isAborting) {
        activity = "Stopping after current in-flight work finishes";
    } else if (progress.waitLabel) {
        const retryAfter = formatRetryAfterSuffix(progress.waitRetryAfterSeconds);
        activity = retryAfter ? `${progress.waitLabel} ${retryAfter}` : progress.waitLabel;
    } else {
        activity = formatIngestAgentLabel(progress.activeAgent) ?? "";
    }

    if (activity) {
        pieces.push(activity);
    }

    return pieces.length > 0 ? pieces.join(" • ") : null;
}
