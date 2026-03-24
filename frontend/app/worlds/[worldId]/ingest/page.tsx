"use client";

import { useState, useEffect, useRef, use } from "react";
import { Upload, FileText, Trash2, ChevronDown, ChevronUp, CheckCircle, XCircle, Loader2, Settings2, Info } from "lucide-react";
import EntityResolutionPanel from "@/components/EntityResolutionPanel";
import WorldReingestSetupContent, {
    WorldIngestSetupForm,
    buildIngestSetupSubmission,
    createWorldIngestSetupDraft,
    type ReingestSetupSubmission,
    type WorldIngestSetupDraft,
} from "@/components/WorldReingestSetupContent";
import { apiFetch, apiUpload, apiStreamGet } from "@/lib/api";
import { buildIngestActivityLabel, resolveStableIngestProgress } from "@/lib/ingest-progress";
import {
    formatEmbeddingProviderLabel,
    formatPromptSourceLabel,
    WORLD_INGEST_PROMPT_FIELDS,
    type WorldIngestConfigResponse,
    type WorldIngestPromptKey,
    type WorldIngestSettings,
    type WorldPromptState,
} from "@/lib/world-ingest";

interface Source {
    source_id: string;
    original_filename: string;
    vault_filename: string;
    book_number: number;
    display_name: string;
    status: string;
    chunk_count: number;
    ingested_at: string | null;
    failed_chunks?: number[];
    extracted_chunks?: number[];
    embedded_chunks?: number[];
    stage_failures?: StageFailure[];
}

interface StageFailure {
    stage: "extraction" | "embedding";
    chunk_index: number;
    chunk_id: string;
    source_id: string;
    book_number: number;
    error_type: string;
    error_message: string;
    attempt_count: number;
    last_attempt_at: string;
    display_name?: string;
}

interface StageCounters {
    expected_chunks: number;
    extracted_chunks: number;
    embedded_chunks: number;
    current_unique_nodes: number;
    embedded_unique_nodes: number;
    failed_records: number;
    blocking_issues: number;
    sources_total: number;
    sources_complete: number;
    sources_partial_failure: number;
    synthesized_failures: number;
}

interface BlockingIssue {
    code: string;
    stage: string;
    scope: string;
    message: string;
}

interface Checkpoint {
    can_resume: boolean;
    chunk_index: number;
    chunks_total: number;
    reason: string | null;
    stage_counters?: StageCounters;
    failures?: StageFailure[];
    blocking_issues?: BlockingIssue[];
    safety_review_summary?: SafetyReviewSummary;
    active_ingestion_run?: boolean;
    progress_phase?: "extracting" | "chunk_embedding" | "unique_node_rebuild" | "audit_finalization" | "aborting" | "idle";
    progress_scope?: "source" | "world";
    completed_chunks_current_phase?: number;
    total_chunks_current_phase?: number;
    completed_work_units?: number;
    total_work_units?: number;
    overall_percent?: number;
    progress_percent?: number;
    active_operation?: string;
    wait_state?: "queued_for_extraction_slot" | "queued_for_embedding_slot" | "waiting_for_api_key" | null;
    wait_stage?: "extracting" | "embedding" | null;
    wait_label?: string | null;
    wait_retry_after_seconds?: number | null;
    progress_source_id?: string | null;
    progress_source_display_name?: string | null;
    progress_source_book_number?: number | null;
}

interface ReembedEligibility {
    can_reembed_all: boolean;
    reason_code: string;
    message: string;
    ignored_pending_sources_count: number;
    requires_full_rebuild: boolean;
    eligible_source_ids: string[];
    eligible_sources_count: number;
}

interface WorldResponse {
    world_name?: string;
    ingestion_status?: string;
    ingest_settings?: WorldIngestSettings;
    active_ingestion_run?: boolean;
    reembed_eligibility?: ReembedEligibility;
    safety_review_summary?: SafetyReviewSummary;
}

interface LogEntry {
    event?: string;
    status?: string;
    ingestion_status?: string;
    active_ingestion_run?: boolean;
    chunk_index?: number;
    chunks_total?: number;
    source_id?: string;
    active_agent?: string;
    agent?: string;
    node_count?: number;
    edge_count?: number;
    claim_count?: number;
    chunk_vector_count?: number;
    node_vector_count?: number;
    safety_reason?: string;
    review_id?: string;
    safety_review_summary?: SafetyReviewSummary;
    chunk_text?: string;
    error_type?: string;
    message?: string;
    book_number?: number;
    progress_phase?: "extracting" | "chunk_embedding" | "unique_node_rebuild" | "audit_finalization" | "aborting" | "idle";
    progress_scope?: "source" | "world";
    completed_chunks_current_phase?: number;
    total_chunks_current_phase?: number;
    completed_work_units?: number;
    total_work_units?: number;
    overall_percent?: number;
    progress_percent?: number;
    active_operation?: string;
    stage_counters?: StageCounters;
    wait_state?: "queued_for_extraction_slot" | "queued_for_embedding_slot" | "waiting_for_api_key" | null;
    wait_stage?: "extracting" | "embedding" | null;
    wait_label?: string | null;
    wait_retry_after_seconds?: number | null;
    wait_duration_seconds?: number;
    progress_source_id?: string | null;
    progress_source_display_name?: string | null;
    progress_source_book_number?: number | null;
}

interface ProgressState {
    phase: "extracting" | "chunk_embedding" | "unique_node_rebuild" | "audit_finalization" | "aborting" | "idle";
    progressScope: "source" | "world";
    operation: string;
    activeAgent: string | null;
    stageCounters: StageCounters;
    completedWorkUnits: number | null;
    totalWorkUnits: number | null;
    overallPercent: number | null;
    waitState: "queued_for_extraction_slot" | "queued_for_embedding_slot" | "waiting_for_api_key" | null;
    waitLabel: string | null;
    waitRetryAfterSeconds: number | null;
    progressSourceId: string | null;
    progressSourceDisplayName: string | null;
    progressSourceBookNumber: number | null;
}

interface SafetyReviewSummary {
    total_reviews: number;
    unresolved_reviews: number;
    resolved_reviews: number;
    active_override_reviews: number;
    blocked_reviews: number;
    draft_reviews: number;
    testing_reviews: number;
    unresolved_chunk_ids?: string[];
    blocks_rebuild: boolean;
    blocking_message?: string | null;
}

interface SafetyReviewItem {
    review_id: string;
    world_id?: string;
    source_id: string;
    book_number: number;
    chunk_index: number;
    chunk_id: string;
    status: "blocked" | "draft" | "testing" | "resolved";
    original_error_kind?: string;
    original_safety_reason: string;
    original_raw_text: string;
    original_prefixed_text: string;
    overlap_raw_text?: string;
    draft_raw_text: string;
    last_test_outcome: "not_tested" | "still_safety_blocked" | "transient_failure" | "other_failure" | "passed";
    last_test_error_kind?: string | null;
    last_test_error_message?: string | null;
    last_tested_at?: string | null;
    test_attempt_count?: number;
    has_active_override: boolean;
    active_override_raw_text: string;
    review_origin?: string;
    display_name: string;
    source_status?: string;
    prefix_label: string;
}

interface SafetyReviewResponse {
    reviews: SafetyReviewItem[];
    summary: SafetyReviewSummary;
}

interface RetryResponse {
    status: string;
    world_id: string;
    retry_stage: "extraction" | "embedding" | "all";
    source_id?: string | null;
    skipped_safety_review_chunks?: number;
    retry_notice?: string | null;
}

interface ManualRescueResponse {
    reviews: SafetyReviewItem[];
    safety_review_summary: SafetyReviewSummary;
    checkpoint: Checkpoint;
}

interface ResetSafetyReviewResponse {
    reset_details?: {
        warning?: string | null;
    };
}

type RightPanelView = "progress" | "safety_queue";

interface RuntimeSnapshot {
    world: WorldResponse;
    checkpoint: Checkpoint;
}

type RuntimeSnapshotLoadResult =
    | { ok: true; snapshot: RuntimeSnapshot }
    | { ok: false; error: Error };

const RUNTIME_SYNC_STALE_MESSAGE = "Live status refresh failed; showing last known state.";

function normalizeRuntimeSyncError(error: unknown): Error {
    if (error instanceof Error) {
        return error;
    }
    return new Error(RUNTIME_SYNC_STALE_MESSAGE);
}

function buildRuntimeSyncMessage(error: unknown): string {
    const normalized = normalizeRuntimeSyncError(error);
    const detail = normalized.message.trim();
    if (!detail || detail === RUNTIME_SYNC_STALE_MESSAGE) {
        return RUNTIME_SYNC_STALE_MESSAGE;
    }
    return `${RUNTIME_SYNC_STALE_MESSAGE} ${detail}`;
}

function isTerminalIngestStreamPayload(data: Record<string, unknown>): boolean {
    const event = typeof data.event === "string" ? data.event : undefined;
    if (event === "complete" || event === "aborted") {
        return true;
    }

    const ingestionStatus = typeof data.ingestion_status === "string" ? data.ingestion_status : undefined;
    if (ingestionStatus && ingestionStatus !== "in_progress") {
        return true;
    }

    const status = typeof data.status === "string" ? data.status : undefined;
    return Boolean(status && ["complete", "aborted", "error", "partial_failure"].includes(status));
}

function formatAgentLabel(agent?: string | null): string | null {
    const normalized = String(agent ?? "").trim();
    if (!normalized) return null;
    return normalized.replace(/_/g, " ");
}

function formatWaitReason(waitLabel?: string | null): string {
    const normalized = String(waitLabel ?? "").trim();
    if (!normalized) return "for work to resume";
    if (normalized.startsWith("Queued ")) {
        return normalized.replace("Queued ", "for ");
    }
    if (normalized.startsWith("Waiting ")) {
        return normalized.replace("Waiting ", "for ");
    }
    return normalized;
}

export default function IngestPage({ params }: { params: Promise<{ worldId: string }> }) {
    const { worldId } = use(params);
    const initialProgress: ProgressState = {
        phase: "idle",
        progressScope: "source",
        operation: "default",
        activeAgent: null,
        stageCounters: {
            expected_chunks: 0,
            extracted_chunks: 0,
            embedded_chunks: 0,
            current_unique_nodes: 0,
            embedded_unique_nodes: 0,
            failed_records: 0,
            blocking_issues: 0,
            sources_total: 0,
            sources_complete: 0,
            sources_partial_failure: 0,
            synthesized_failures: 0,
        },
        completedWorkUnits: null,
        totalWorkUnits: null,
        overallPercent: null,
        waitState: null,
        waitLabel: null,
        waitRetryAfterSeconds: null,
        progressSourceId: null,
        progressSourceDisplayName: null,
        progressSourceBookNumber: null,
    };
    const [sources, setSources] = useState<Source[]>([]);
    const [checkpoint, setCheckpoint] = useState<Checkpoint | null>(null);
    const [ingesting, setIngesting] = useState(false);
    const [abortRequestPending, setAbortRequestPending] = useState(false);
    const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
    const [progress, setProgress] = useState(initialProgress);
    const [showLog, setShowLog] = useState(true);
    const [showSettings, setShowSettings] = useState(false);
    const [showPrompts, setShowPrompts] = useState(false);
    const [isBooksExpanded, setIsBooksExpanded] = useState(false);
    const [isReingestModalOpen, setIsReingestModalOpen] = useState(false);
    const [activeRightPanel, setActiveRightPanel] = useState<RightPanelView>("progress");
    const [dragOver, setDragOver] = useState(false);
    const logEndRef = useRef<HTMLDivElement>(null);
    const fileRef = useRef<HTMLInputElement>(null);
    const esRef = useRef<EventSource | null>(null);
    const initialIngestDraftWorldIdRef = useRef<string | null>(null);
    const initialIngestDraftDirtyRef = useRef(false);

    // Read-only world ingest config state
    const [worldName, setWorldName] = useState("World");
    const [savedIngestSettings, setSavedIngestSettings] = useState<WorldIngestSettings | null>(null);
    const [reembedEligibility, setReembedEligibility] = useState<ReembedEligibility | null>(null);
    const [prompts, setPrompts] = useState<Record<string, WorldPromptState>>({} as Record<string, WorldPromptState>);
    const [initialIngestDraft, setInitialIngestDraft] = useState<WorldIngestSetupDraft | null>(null);
    const [initialIngestDraftDirty, setInitialIngestDraftDirty] = useState(false);
    const [hasActiveChunkOverrides, setHasActiveChunkOverrides] = useState(false);
    const [activeChunkOverrideCount, setActiveChunkOverrideCount] = useState(0);
    const [reuseActiveChunkOverrides, setReuseActiveChunkOverrides] = useState(true);
    const [blockedChunkData, setBlockedChunkData] = useState<{ text: string; reason: string } | null>(null);
    const [safetyReviews, setSafetyReviews] = useState<SafetyReviewItem[]>([]);
    const [safetyReviewSummary, setSafetyReviewSummary] = useState<SafetyReviewSummary | null>(null);
    const [safetyReviewLoadError, setSafetyReviewLoadError] = useState<string | null>(null);
    const [reviewDrafts, setReviewDrafts] = useState<Record<string, string>>({});
    const [savingReviewIds, setSavingReviewIds] = useState<Record<string, boolean>>({});
    const [testingReviewIds, setTestingReviewIds] = useState<Record<string, boolean>>({});
    const [resettingReviewIds, setResettingReviewIds] = useState<Record<string, boolean>>({});
    const [retryNotice, setRetryNotice] = useState<string | null>(null);
    const [pendingFocusReviewId, setPendingFocusReviewId] = useState<string | null>(null);
    const [isRescuingCollapsedFailures, setIsRescuingCollapsedFailures] = useState(false);
    const [statusSyncError, setStatusSyncError] = useState<string | null>(null);
    const [statusIsStale, setStatusIsStale] = useState(false);
    const [lastSuccessfulRuntimeSyncAt, setLastSuccessfulRuntimeSyncAt] = useState<string | null>(null);

    const resetProgress = () => setProgress(initialProgress);
    const isTerminalIngestionStatus = (status?: string | null) => Boolean(status && status !== "in_progress");
    const clearRuntimeSyncWarning = () => {
        setStatusIsStale(false);
        setStatusSyncError(null);
    };
    const markRuntimeSnapshotSuccess = () => {
        clearRuntimeSyncWarning();
        setLastSuccessfulRuntimeSyncAt(new Date().toISOString());
    };
    const markRuntimeSnapshotFailure = (error: unknown) => {
        setStatusIsStale(true);
        setStatusSyncError(buildRuntimeSyncMessage(error));
    };
    const mergeStageCounters = (previous: StageCounters, incoming?: StageCounters): StageCounters => {
        if (!incoming) return previous;
        return {
            expected_chunks: Math.max(Number(previous.expected_chunks ?? 0), Number(incoming.expected_chunks ?? 0)),
            extracted_chunks: Math.max(Number(previous.extracted_chunks ?? 0), Number(incoming.extracted_chunks ?? 0)),
            embedded_chunks: Math.max(Number(previous.embedded_chunks ?? 0), Number(incoming.embedded_chunks ?? 0)),
            current_unique_nodes: Number(incoming.current_unique_nodes ?? previous.current_unique_nodes ?? 0),
            embedded_unique_nodes: Number(incoming.embedded_unique_nodes ?? previous.embedded_unique_nodes ?? 0),
            failed_records: Number(incoming.failed_records ?? previous.failed_records ?? 0),
            blocking_issues: Number(incoming.blocking_issues ?? previous.blocking_issues ?? 0),
            sources_total: Math.max(Number(previous.sources_total ?? 0), Number(incoming.sources_total ?? 0)),
            sources_complete: Math.max(Number(previous.sources_complete ?? 0), Number(incoming.sources_complete ?? 0)),
            sources_partial_failure: Math.max(Number(previous.sources_partial_failure ?? 0), Number(incoming.sources_partial_failure ?? 0)),
            synthesized_failures: Math.max(Number(previous.synthesized_failures ?? 0), Number(incoming.synthesized_failures ?? 0)),
        };
    };

    useEffect(() => {
        initialIngestDraftDirtyRef.current = initialIngestDraftDirty;
    }, [initialIngestDraftDirty]);

    useEffect(() => {
        setWorldName("World");
        setInitialIngestDraft(null);
        setInitialIngestDraftDirty(false);
        initialIngestDraftWorldIdRef.current = null;
        initialIngestDraftDirtyRef.current = false;
        setSafetyReviews([]);
        setSafetyReviewSummary(null);
        setSafetyReviewLoadError(null);
        setReviewDrafts({});
    }, [worldId]);

    const syncSafetyReviewState = (reviews: SafetyReviewItem[], summary?: SafetyReviewSummary | null) => {
        setSafetyReviews(reviews);
        setSafetyReviewSummary(summary ?? null);
        setSafetyReviewLoadError(null);
        setReviewDrafts((prev) => {
            const next: Record<string, string> = {};
            for (const review of reviews) {
                next[review.review_id] = prev[review.review_id]
                    ?? review.draft_raw_text
                    ?? review.active_override_raw_text
                    ?? review.original_raw_text;
            }
            return next;
        });
    };

    const focusSafetyReview = (reviewId: string) => {
        const card = document.getElementById(`safety-review-${reviewId}`);
        const textarea = document.getElementById(`safety-review-textarea-${reviewId}`) as HTMLTextAreaElement | null;
        card?.scrollIntoView({ behavior: "smooth", block: "center" });
        window.setTimeout(() => {
            textarea?.focus();
            if (textarea) {
                const end = textarea.value.length;
                textarea.setSelectionRange(end, end);
            }
        }, 120);
    };

    const syncProgressFromPayload = (payload?: Partial<Checkpoint & LogEntry>) => {
        if (!payload) return;
        setProgress((prev) => {
            const liveRun = payload.active_ingestion_run === true || payload.ingestion_status === "in_progress";
            const nextStageCounters = payload.stage_counters
                ? (liveRun ? mergeStageCounters(prev.stageCounters, payload.stage_counters) : payload.stage_counters)
                : prev.stageCounters;
            const hasProgressSourceId = Object.prototype.hasOwnProperty.call(payload, "progress_source_id");
            const hasProgressSourceDisplayName = Object.prototype.hasOwnProperty.call(payload, "progress_source_display_name");
            const hasProgressSourceBookNumber = Object.prototype.hasOwnProperty.call(payload, "progress_source_book_number");
            return {
                phase: payload.progress_phase || prev.phase,
                progressScope: payload.progress_scope || prev.progressScope,
                operation: payload.active_operation || prev.operation,
                activeAgent: payload.active_agent || payload.agent || prev.activeAgent,
                stageCounters: nextStageCounters,
                completedWorkUnits: payload.completed_work_units ?? prev.completedWorkUnits,
                totalWorkUnits: payload.total_work_units ?? prev.totalWorkUnits,
                overallPercent: payload.overall_percent ?? prev.overallPercent,
                waitState: payload.wait_state ?? null,
                waitLabel: payload.wait_label ?? null,
                waitRetryAfterSeconds: payload.wait_retry_after_seconds ?? null,
                progressSourceId: hasProgressSourceId ? (payload.progress_source_id ?? null) : (payload.source_id ?? prev.progressSourceId),
                progressSourceDisplayName: hasProgressSourceDisplayName ? (payload.progress_source_display_name ?? null) : prev.progressSourceDisplayName,
                progressSourceBookNumber: hasProgressSourceBookNumber ? (payload.progress_source_book_number ?? null) : (payload.book_number ?? prev.progressSourceBookNumber),
            };
        });
    };

    const applyWorldData = (data: WorldResponse) => {
        setWorldName(data.world_name || "World");
        setReembedEligibility(data.reembed_eligibility ?? null);
        setSafetyReviewSummary(data.safety_review_summary ?? null);
    };

    const applySourcesData = (data: Source[]) => {
        setSources(data);
    };

    const applyCheckpointData = (data: Checkpoint) => {
        setCheckpoint(data);
        syncProgressFromPayload(data);
        if (data.safety_review_summary) {
            setSafetyReviewSummary(data.safety_review_summary);
        }
    };

    const applyRuntimeSnapshot = (
        snapshot: RuntimeSnapshot,
        options?: { reconnectStream?: boolean }
    ) => {
        applyWorldData(snapshot.world);
        applyCheckpointData(snapshot.checkpoint);

        const liveRun = snapshot.world.ingestion_status === "in_progress" && snapshot.world.active_ingestion_run === true;
        const aborting = snapshot.checkpoint.progress_phase === "aborting";
        const terminal = !liveRun && isTerminalIngestionStatus(snapshot.world.ingestion_status);

        if (aborting || terminal || !liveRun) {
            setAbortRequestPending(false);
        }

        if (liveRun) {
            setIngesting(true);
            if (options?.reconnectStream) {
                connectToSSE();
            }
            return;
        }

        esRef.current?.close();
        setIngesting(false);
    };

    async function fetchRuntimeSnapshot(): Promise<RuntimeSnapshot> {
        const [world, checkpoint] = await Promise.all([
            apiFetch<WorldResponse>(`/worlds/${worldId}`),
            apiFetch<Checkpoint>(`/worlds/${worldId}/ingest/checkpoint`),
        ]);
        return { world, checkpoint };
    }

    async function loadRuntimeSnapshot(reconnectStream = false): Promise<RuntimeSnapshotLoadResult> {
        try {
            const snapshot = await fetchRuntimeSnapshot();
            applyRuntimeSnapshot(snapshot, { reconnectStream });
            markRuntimeSnapshotSuccess();
            return { ok: true, snapshot };
        } catch (error) {
            const normalized = normalizeRuntimeSyncError(error);
            markRuntimeSnapshotFailure(normalized);
            return { ok: false, error: normalized };
        }
    }

    async function refreshRuntimeView(options?: {
        reconnectStream?: boolean;
        refreshSources?: boolean;
        refreshSafetyReviews?: boolean;
    }) {
        const runtimeResult = await loadRuntimeSnapshot(Boolean(options?.reconnectStream));
        const tasks: Array<Promise<unknown>> = [];
        if (options?.refreshSources) {
            tasks.push(loadSources());
        }
        if (options?.refreshSafetyReviews) {
            tasks.push(loadSafetyReviews({ markStaleOnError: true }));
        }
        await Promise.all(tasks);
        return runtimeResult;
    }

    const applyIngestConfigData = (data: WorldIngestConfigResponse) => {
        setSavedIngestSettings(data.ingest_settings);
        setPrompts(data.prompts as Record<string, WorldPromptState>);
        setHasActiveChunkOverrides(Boolean(data.has_active_chunk_overrides));
        setActiveChunkOverrideCount(Number(data.active_chunk_override_count ?? 0));
        setReuseActiveChunkOverrides((prev) => (data.has_active_chunk_overrides ? prev : true));
        const nextInitialDraft = createWorldIngestSetupDraft(data);
        const shouldResetInitialDraft = initialIngestDraftWorldIdRef.current !== worldId || !initialIngestDraftDirtyRef.current;
        if (shouldResetInitialDraft) {
            initialIngestDraftWorldIdRef.current = worldId;
            initialIngestDraftDirtyRef.current = false;
            setInitialIngestDraftDirty(false);
            setInitialIngestDraft(nextInitialDraft);
        }
    };

    async function loadWorld(options?: { throwOnError?: boolean; markStaleOnError?: boolean }) {
        try {
            const data = await apiFetch<WorldResponse>(`/worlds/${worldId}`);
            applyWorldData(data);
            return data;
        } catch (error) {
            if (options?.markStaleOnError) {
                markRuntimeSnapshotFailure(error);
            }
            if (options?.throwOnError) {
                throw error;
            }
        }
        return null;
    }

    async function loadSources() {
        try {
            const data = await apiFetch<Source[]>(`/worlds/${worldId}/sources`);
            applySourcesData(data);
        } catch { /* ignore */ }
    }

    async function loadCheckpoint(options?: { throwOnError?: boolean; markStaleOnError?: boolean }) {
        try {
            const data = await apiFetch<Checkpoint>(`/worlds/${worldId}/ingest/checkpoint`);
            applyCheckpointData(data);
            if (data.progress_phase === "aborting" || data.active_ingestion_run === false) {
                setAbortRequestPending(false);
            }
            return data;
        } catch (error) {
            if (options?.markStaleOnError) {
                markRuntimeSnapshotFailure(error);
            }
            if (options?.throwOnError) {
                throw error;
            }
        }
        return null;
    }

    async function loadIngestConfig(options?: { throwOnError?: boolean; markStaleOnError?: boolean }) {
        try {
            const data = await apiFetch<WorldIngestConfigResponse>(`/worlds/${worldId}/ingest/config`);
            applyIngestConfigData(data);
            return data;
        } catch (error) {
            if (options?.markStaleOnError) {
                markRuntimeSnapshotFailure(error);
            }
            if (options?.throwOnError) {
                throw error;
            }
        }
        return null;
    }

    async function refreshIngestActionState() {
        try {
            const [worldData, sourcesData, checkpointData, ingestConfigData] = await Promise.all([
                apiFetch<WorldResponse>(`/worlds/${worldId}`),
                apiFetch<Source[]>(`/worlds/${worldId}/sources`),
                apiFetch<Checkpoint>(`/worlds/${worldId}/ingest/checkpoint`),
                apiFetch<WorldIngestConfigResponse>(`/worlds/${worldId}/ingest/config`),
            ]);
            applyRuntimeSnapshot({ world: worldData, checkpoint: checkpointData }, {
                reconnectStream: worldData.ingestion_status === "in_progress" && worldData.active_ingestion_run === true,
            });
            markRuntimeSnapshotSuccess();
            applySourcesData(sourcesData);
            applyIngestConfigData(ingestConfigData);
        } catch (error) {
            markRuntimeSnapshotFailure(error);
            throw error;
        }
    }

    async function loadSafetyReviews(options?: { throwOnError?: boolean; markStaleOnError?: boolean }) {
        try {
            const data = await apiFetch<SafetyReviewResponse>(`/worlds/${worldId}/ingest/safety-reviews`);
            syncSafetyReviewState(data.reviews, data.summary);
            return data;
        } catch (error) {
            setSafetyReviewLoadError(buildRuntimeSyncMessage(error));
            if (options?.markStaleOnError) {
                markRuntimeSnapshotFailure(error);
            }
            if (options?.throwOnError) {
                throw error;
            }
        }
        return null;
    }

    const handleUpload = async (files: FileList | File[]) => {
        let uploadedCount = 0;
        for (const file of Array.from(files)) {
            if (!file.name.endsWith(".txt")) {
                alert("Only .txt files are supported.");
                continue;
            }
            const formData = new FormData();
            formData.append("file", file);
            try {
                await apiUpload(`/worlds/${worldId}/sources`, formData);
                uploadedCount += 1;
            } catch (err: unknown) {
                alert((err as Error).message);
            }
        }
        if (uploadedCount > 0) {
            try {
                await refreshIngestActionState();
            } catch (err: unknown) {
                alert((err as Error).message);
            }
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setDragOver(false);
        if (e.dataTransfer.files.length > 0) handleUpload(e.dataTransfer.files);
    };

    const connectToSSE = () => {
        if (esRef.current) esRef.current.close();
        esRef.current = apiStreamGet(
            `/worlds/${worldId}/ingest/status`,
            (data) => {
                const entry = data as LogEntry;
                const shouldAppendLogEntry = !(
                    entry.event === "status"
                    && !entry.message
                    && !isTerminalIngestionStatus(entry.ingestion_status)
                );
                if (shouldAppendLogEntry) {
                    setLogEntries((prev) => [...prev, entry]);
                }
                if (entry.event !== "waiting") {
                    syncProgressFromPayload(entry);
                }
                if (entry.safety_review_summary) {
                    setSafetyReviewSummary(entry.safety_review_summary);
                }
                if (entry.event === "aborting" || entry.progress_phase === "aborting") {
                    setAbortRequestPending(false);
                    setIngesting(true);
                }
                if (entry.error_type === "safety_block") {
                    void loadSafetyReviews({ markStaleOnError: true });
                    void loadCheckpoint();
                }
            },
            () => {
                esRef.current?.close();
                void refreshRuntimeView({
                    reconnectStream: false,
                    refreshSources: true,
                    refreshSafetyReviews: true,
                });
            },
            (err) => {
                esRef.current?.close();
                void refreshRuntimeView({
                    reconnectStream: true,
                    refreshSources: true,
                    refreshSafetyReviews: true,
                });
                setLogEntries((prev) => [...prev, { event: "error", message: err.message }]);
            },
            { isTerminal: isTerminalIngestStreamPayload }
        );
    };

    /* eslint-disable react-hooks/exhaustive-deps */
    // These loaders are scoped to the current world id and intentionally rerun only on world changes.
    useEffect(() => {
        const initializePage = async () => {
            await Promise.all([
                loadRuntimeSnapshot(true),
                loadSources(),
                loadSafetyReviews({ markStaleOnError: true }),
                loadIngestConfig(),
            ]);
        };
        void initializePage();
    }, [worldId]);
    /* eslint-enable react-hooks/exhaustive-deps */
    useEffect(() => {
        if (!pendingFocusReviewId) return;
        if (!safetyReviews.some((review) => review.review_id === pendingFocusReviewId)) return;
        focusSafetyReview(pendingFocusReviewId);
        setPendingFocusReviewId(null);
    }, [pendingFocusReviewId, safetyReviews]);
    useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [logEntries]);

    const buildIngestSettingsPayload = (override?: Partial<WorldIngestSettings>) => ({
        chunk_size_chars: override?.chunk_size_chars ?? savedIngestSettings?.chunk_size_chars ?? 4000,
        chunk_overlap_chars: override?.chunk_overlap_chars ?? savedIngestSettings?.chunk_overlap_chars ?? 150,
        embedding_model: override?.embedding_model ?? savedIngestSettings?.embedding_model ?? "gemini-embedding-2-preview",
        glean_amount: override?.glean_amount ?? savedIngestSettings?.glean_amount ?? 1,
    });

    const startIngestion = async (
        resume: boolean,
        operation: "default" | "rechunk_reingest" | "reembed_all" = "default",
        overrideSettings?: Partial<WorldIngestSettings>,
        options?: {
            useActiveChunkOverrides?: boolean;
            promptOverrides?: Record<WorldIngestPromptKey, string>;
        },
    ) => {
        resetProgress();
        setRetryNotice(null);
        setAbortRequestPending(false);
        setIngesting(true);
        setLogEntries([]);
        clearRuntimeSyncWarning();
        try {
            await apiFetch(`/worlds/${worldId}/ingest/start`, {
                method: "POST",
                body: JSON.stringify({
                    resume,
                    operation,
                    ingest_settings: buildIngestSettingsPayload(overrideSettings),
                    use_active_chunk_overrides: Boolean(options?.useActiveChunkOverrides),
                    prompt_overrides: options?.promptOverrides,
                }),
            });
            void loadIngestConfig();
            void loadWorld();
            setActiveRightPanel("progress");
            connectToSSE();
        } catch (err: unknown) {
            setIngesting(false);
            alert((err as Error).message);
        }
    };

    const retryFailures = async (stage: "extraction" | "embedding" | "all") => {
        resetProgress();
        setRetryNotice(null);
        setAbortRequestPending(false);
        setIngesting(true);
        setLogEntries([]);
        setActiveRightPanel("progress");
        clearRuntimeSyncWarning();
        try {
            const data = await apiFetch<RetryResponse>(`/worlds/${worldId}/ingest/retry`, {
                method: "POST",
                body: JSON.stringify({ stage }),
            });
            if (data.retry_notice) {
                const noticeMessage = data.retry_notice;
                setRetryNotice(noticeMessage);
                setLogEntries((prev) => [{ event: "status", message: noticeMessage }, ...prev]);
            }
            connectToSSE();
        } catch (err: unknown) {
            setIngesting(false);
            setAbortRequestPending(false);
            alert((err as Error).message);
        }
    };

    const rescueCollapsedFailures = async (failures: StageFailure[]) => {
        if (failures.length === 0) return;
        const groupedBySource = failures.reduce<Record<string, number[]>>((groups, failure) => {
            if (!groups[failure.source_id]) groups[failure.source_id] = [];
            groups[failure.source_id].push(failure.chunk_index);
            return groups;
        }, {});

        setIsRescuingCollapsedFailures(true);
        try {
            let firstReviewId: string | null = null;
            for (const [sourceId, chunkIndices] of Object.entries(groupedBySource)) {
                const data = await apiFetch<ManualRescueResponse>(
                    `/worlds/${worldId}/ingest/safety-reviews/manual-rescue`,
                    {
                        method: "POST",
                        body: JSON.stringify({
                            source_id: sourceId,
                            chunk_indices: chunkIndices,
                        }),
                    }
                );
                if (!firstReviewId) {
                    firstReviewId = data.reviews[0]?.review_id ?? null;
                }
            }
            await Promise.all([
                loadWorld(),
                loadSources(),
                loadCheckpoint(),
                loadSafetyReviews({ markStaleOnError: true }),
            ]);
            if (firstReviewId) {
                setActiveRightPanel("safety_queue");
                setPendingFocusReviewId(firstReviewId);
            }
        } catch (err: unknown) {
            alert((err as Error).message);
        } finally {
            setIsRescuingCollapsedFailures(false);
        }
    };

    const abortIngestion = async () => {
        try {
            setAbortRequestPending(true);
            await apiFetch(`/worlds/${worldId}/ingest/abort`, { method: "POST" });
            await loadRuntimeSnapshot(true);
        } catch (err: unknown) {
            setAbortRequestPending(false);
            alert((err as Error).message);
        }
    };

    const deleteSource = async (sourceId: string) => {
        try {
            await apiFetch(`/worlds/${worldId}/sources/${sourceId}`, { method: "DELETE" });
            await refreshIngestActionState();
        } catch (err: unknown) {
            alert((err as Error).message);
        }
    };

    const setReviewBusy = (
        setter: React.Dispatch<React.SetStateAction<Record<string, boolean>>>,
        reviewId: string,
        busy: boolean,
    ) => {
        setter((prev) => {
            const next = { ...prev };
            if (busy) next[reviewId] = true;
            else delete next[reviewId];
            return next;
        });
    };

    const isMissingSafetyReviewError = (err: unknown) => (
        (err as Error)?.message?.toLowerCase().includes("safety review item not found")
    );

    const refreshAfterMissingSafetyReview = async (reviewId?: string) => {
        if (reviewId) {
            setReviewDrafts((prev) => {
                const next = { ...prev };
                delete next[reviewId];
                return next;
            });
        }
        try {
            await Promise.all([
                refreshIngestActionState(),
                loadSafetyReviews({ throwOnError: true, markStaleOnError: true }),
            ]);
        } catch {
            // The stale runtime banner already reflects the failed refresh.
        }
    };

    const refreshAfterSafetyReviewMutation = async () => {
        try {
            await Promise.all([
                refreshIngestActionState(),
                loadSafetyReviews({ throwOnError: true, markStaleOnError: true }),
            ]);
        } catch {
            // The stale runtime banner already reflects the failed refresh.
        }
    };

    const reviewDraftValue = (review: SafetyReviewItem) => (
        reviewDrafts[review.review_id]
        ?? review.draft_raw_text
        ?? review.active_override_raw_text
        ?? review.original_raw_text
    );

    const saveReviewDraft = async (review: SafetyReviewItem, draftRawText?: string) => {
        const nextDraft = draftRawText ?? reviewDraftValue(review);
        setReviewBusy(setSavingReviewIds, review.review_id, true);
        try {
            const data = await apiFetch<{ review: SafetyReviewItem; summary: SafetyReviewSummary }>(
                `/worlds/${worldId}/ingest/safety-reviews/${review.review_id}`,
                {
                    method: "PATCH",
                    body: JSON.stringify({ draft_raw_text: nextDraft }),
                }
            );
            syncSafetyReviewState(
                safetyReviews.map((item) => item.review_id === data.review.review_id ? data.review : item),
                data.summary,
            );
            setReviewDrafts((prev) => ({ ...prev, [review.review_id]: nextDraft }));
            return true;
        } catch (err: unknown) {
            if (isMissingSafetyReviewError(err)) {
                await refreshAfterMissingSafetyReview(review.review_id);
                return false;
            }
            alert((err as Error).message);
            return false;
        } finally {
            setReviewBusy(setSavingReviewIds, review.review_id, false);
        }
    };

    const resetReviewDraftToOriginal = async (review: SafetyReviewItem) => {
        const resetText = review.original_raw_text;
        setReviewDrafts((prev) => ({ ...prev, [review.review_id]: resetText }));
        await saveReviewDraft(review, resetText);
    };

    const resetReviewDraftToLive = async (review: SafetyReviewItem) => {
        if (!review.has_active_override) return;
        const liveText = review.active_override_raw_text ?? "";
        setReviewDrafts((prev) => ({ ...prev, [review.review_id]: liveText }));
        await saveReviewDraft(review, liveText);
    };

    const testReviewDraft = async (review: SafetyReviewItem) => {
        const currentDraft = reviewDraftValue(review);
        const didSave = await saveReviewDraft(review, currentDraft);
        if (!didSave) return;
        setReviewBusy(setTestingReviewIds, review.review_id, true);
        try {
            await apiFetch(`/worlds/${worldId}/ingest/safety-reviews/${review.review_id}/test`, {
                method: "POST",
            });
            await refreshAfterSafetyReviewMutation();
        } catch (err: unknown) {
            if (isMissingSafetyReviewError(err)) {
                await refreshAfterMissingSafetyReview(review.review_id);
                return;
            }
            alert((err as Error).message);
            await refreshAfterSafetyReviewMutation();
        } finally {
            setReviewBusy(setTestingReviewIds, review.review_id, false);
        }
    };

    const resetReview = async (review: SafetyReviewItem) => {
        const hasActiveOverride = review.has_active_override;
        const confirmMessage = hasActiveOverride
            ? "This will delete this chunk's live chunk data, embeddings, nodes, and edges, then keep the chunk in the Safety Queue so it can be retried cleanly. If entity resolution already merged this chunk into a surviving entity description, that merged description will stay and cannot be discarded here. Re-ingest if you need those entity descriptions rebuilt cleanly. Continue?"
            : "This will delete any live chunk data for this chunk and keep it in the Safety Queue so it can be restarted cleanly. Continue?";
        if (!confirm(confirmMessage)) return;

        setReviewBusy(setResettingReviewIds, review.review_id, true);
        try {
            const response = await apiFetch<ResetSafetyReviewResponse>(`/worlds/${worldId}/ingest/safety-reviews/${review.review_id}/reset`, {
                method: "POST",
            });
            await refreshAfterSafetyReviewMutation();
            const warning = response?.reset_details?.warning;
            if (typeof warning === "string" && warning.trim()) {
                alert(warning);
            }
        } catch (err: unknown) {
            if (isMissingSafetyReviewError(err)) {
                await refreshAfterMissingSafetyReview(review.review_id);
                return;
            }
            alert((err as Error).message);
            await refreshAfterSafetyReviewMutation();
        } finally {
            setReviewBusy(setResettingReviewIds, review.review_id, false);
        }
    };

    const failureRecords = checkpoint?.failures || [];
    const unresolvedSafetyReviewByChunkId = safetyReviews.reduce<Record<string, SafetyReviewItem>>((lookup, review) => {
        if (review.status !== "resolved") {
            lookup[review.chunk_id] = review;
        }
        return lookup;
    }, {});
    const unresolvedSafetyReviewChunkIds = new Set<string>([
        ...Object.keys(unresolvedSafetyReviewByChunkId),
        ...(safetyReviewSummary?.unresolved_chunk_ids ?? []),
    ]);
    const collapsedCoverageGapFailures = failureRecords.filter((failure) => (
        failure.stage === "extraction"
        && failure.error_type === "coverage_gap"
        && !unresolvedSafetyReviewChunkIds.has(failure.chunk_id)
    ));
    const hasPending = sources.some((s) => s.status === "pending" || s.status === "ingesting");
    const hasRetryableFailuresOutsideSafetyQueue = failureRecords.some(
        (failure) => !unresolvedSafetyReviewChunkIds.has(failure.chunk_id)
    );
    const hasAnyIngested = sources.some((s) => s.chunk_count > 0 || s.ingested_at !== null || s.status === "partial_failure" || s.status === "complete");
    const allComplete = sources.length > 0 && sources.every((s) => s.status === "complete");
    const isPendingOnlyInitialCheckpoint = Boolean(
        checkpoint?.can_resume
        && checkpoint?.reason === "pending_work"
        && !hasAnyIngested
        && !hasRetryableFailuresOutsideSafetyQueue
        && Number(checkpoint?.chunks_total ?? 0) === 0
        && Number(checkpoint?.chunk_index ?? 0) === 0
        && checkpoint?.active_ingestion_run !== true
    );
    const showResume = Boolean(checkpoint?.can_resume) && !ingesting && !isPendingOnlyInitialCheckpoint;
    const showInitialIngestSetup = !ingesting && !hasAnyIngested && !showResume;
    const showReingestAction = !ingesting && hasAnyIngested;
    const showReembedAction = !ingesting && hasAnyIngested;
    const canReembedAll = Boolean(showReembedAction && reembedEligibility?.can_reembed_all);
    const reembedDisabledReason = reembedEligibility?.message || "Re-embed All is not currently safe for this world.";
    const initialIngestSubmitDisabledReason = hasPending
        ? null
        : "Add at least one pending .txt file before starting ingestion.";
    const savedEmbeddingProviderLabel = savedIngestSettings
        ? formatEmbeddingProviderLabel(
            savedIngestSettings.embedding_provider,
            savedIngestSettings.embedding_openai_compatible_provider,
        )
        : "-";
    const previousSettingsSummary = savedIngestSettings
        ? `Chunk ${savedIngestSettings.chunk_size_chars.toLocaleString()} chars | Overlap ${savedIngestSettings.chunk_overlap_chars.toLocaleString()} chars | Glean ${savedIngestSettings.glean_amount.toLocaleString()} | ${savedEmbeddingProviderLabel} | ${savedIngestSettings.embedding_model}`
        : null;
    const canResolveEntitiesBase = !ingesting && allComplete && hasAnyIngested;
    const isAborting = abortRequestPending || progress.phase === "aborting" || checkpoint?.progress_phase === "aborting";
    const sourceNameById = sources.reduce<Record<string, string>>((lookup, source) => {
        lookup[source.source_id] = source.display_name;
        return lookup;
    }, {});
    const progressSummary = resolveStableIngestProgress({
        active_operation: progress.operation,
        active_ingestion_run: ingesting,
        progress_phase: progress.phase,
        progress_scope: progress.progressScope,
        stage_counters: progress.stageCounters,
        completed_work_units: progress.completedWorkUnits ?? undefined,
        total_work_units: progress.totalWorkUnits ?? undefined,
        overall_percent: progress.overallPercent ?? undefined,
        wait_state: progress.waitState,
        wait_label: progress.waitLabel,
        wait_retry_after_seconds: progress.waitRetryAfterSeconds,
        active_agent: progress.activeAgent,
        progress_source_id: progress.progressSourceId,
        progress_source_display_name: progress.progressSourceDisplayName,
        progress_source_book_number: progress.progressSourceBookNumber,
    });
    const progressSecondaryLabel = buildIngestActivityLabel(progressSummary, {
        fallbackSourceDisplayName: progress.progressSourceId ? sourceNameById[progress.progressSourceId] : null,
    });
    const stageCounters = ingesting
        ? progress.stageCounters
        : (checkpoint?.stage_counters ?? progress.stageCounters);
    const failedRecordCount = stageCounters.failed_records ?? 0;
    const blockingIssueCount = stageCounters.blocking_issues ?? 0;
    const blockingIssueCode = typeof checkpoint?.blocking_issues?.[0]?.code === "string" ? checkpoint.blocking_issues[0].code : null;
    const blockingIssueMessage = checkpoint?.blocking_issues?.[0]?.message ?? null;
    const hasBlockingIssues = blockingIssueCount > 0;
    const totalReviewCount = safetyReviewSummary?.total_reviews ?? safetyReviews.length;
    const unresolvedReviewCount = safetyReviewSummary?.unresolved_reviews
        ?? safetyReviews.filter((review) => review.status !== "resolved").length;
    const hasAnySafetyQueueHistory = totalReviewCount > 0;
    const hasUnresolvedSafetyQueue = unresolvedReviewCount > 0;
    const showSafetyQueueUnavailableState = safetyReviews.length === 0 && Boolean(safetyReviewLoadError);
    const canResolveEntities = canResolveEntitiesBase && failedRecordCount === 0 && blockingIssueCount === 0 && !hasUnresolvedSafetyQueue;
    const resolveEntitiesDisabledReason = ingesting
        ? "Wait for ingestion to finish before starting entity resolution."
        : blockingIssueCount > 0
            ? (blockingIssueMessage ?? "Resolve world-level graph or vector blockers before running entity resolution.")
            : hasUnresolvedSafetyQueue
                ? "Resolve or reset pending safety review items before running entity resolution."
                : !allComplete || failedRecordCount > 0
                    ? "Finish ingestion or retry failed chunks before resolving entities."
                    : canResolveEntities
                        ? null
                        : "Entity resolution is currently unavailable for this world.";
    const rebuildBlockedReason = unresolvedReviewCount > 0
        ? "This world has unresolved safety review items. Resolve or reset them before running Re-ingest."
        : null;
    const hasProgress = progressSummary.totalWorkUnits > 0;
    const showProgressSummary = ingesting || hasProgress;
    const showCompletedIdleState = !ingesting && !hasPending && allComplete && !hasRetryableFailuresOutsideSafetyQueue && !hasBlockingIssues && !showResume;
    const showIdlePlaceholder = !ingesting && logEntries.length === 0 && failureRecords.length === 0 && !hasBlockingIssues && !hasProgress;
    const progressHeaderLabel = progressSummary.isAborting
        ? "Stopping ingest..."
        : "Input Progress";
    const groupedSafetyReviews = safetyReviews.reduce<Record<string, SafetyReviewItem[]>>((groups, review) => {
        const key = `${review.display_name}::${review.source_id}`;
        groups[key] = groups[key] || [];
        groups[key].push(review);
        return groups;
    }, {});
    const showRetryAllButton = !ingesting && hasRetryableFailuresOutsideSafetyQueue;
    const bookCountLabel = `${sources.length} book${sources.length === 1 ? "" : "s"}`;
    const booksSummaryLabel = sources.length === 0
        ? "No books uploaded yet."
        : `${bookCountLabel} in this world.`;
    const safetyQueueToggleLabel = activeRightPanel === "safety_queue"
        ? "Go to Ingest Progress"
        : "Go to Safety Queue";
    const safetyQueueButtonDetail = hasUnresolvedSafetyQueue
        ? `${unresolvedReviewCount} unresolved`
        : hasAnySafetyQueueHistory
            ? "View resolved items"
            : "Open panel";
    const showProgressHeaderCard = showProgressSummary || showReembedAction || failedRecordCount > 0 || blockingIssueCount > 0;
    const runtimeSyncSummary = lastSuccessfulRuntimeSyncAt
        ? `Last successful sync ${new Date(lastSuccessfulRuntimeSyncAt).toLocaleTimeString()}.`
        : "No successful live status sync yet.";
    const collapsedFailureActionLabel = `Add ${collapsedCoverageGapFailures.length} Failed Chunk${collapsedCoverageGapFailures.length === 1 ? "" : "s"} to Safety Queue`;
    const failureActionSteps: string[] = [];
    if (showResume) {
        failureActionSteps.push("If Resume is available, try Resume first.");
    }
    if (hasRetryableFailuresOutsideSafetyQueue) {
        failureActionSteps.push("If failures remain, click Retry All Failures.");
    }
    if (collapsedCoverageGapFailures.length > 0) {
        failureActionSteps.push(
            `If ${collapsedFailureActionLabel} is still showing, click it to move stubborn failed chunks into the repair queue.`
        );
    }
    if (hasUnresolvedSafetyQueue) {
        failureActionSteps.push("Open the Safety Queue and fix the remaining chunks there.");
    }
    const showFailureActionGuide = !ingesting && (failureActionSteps.length > 0 || Boolean(retryNotice));
    const worldBlockerNextStep = (() => {
        if (!blockingIssueCode) {
            if (showResume) {
                return "If this goes above 0 after an interrupted run, use Resume first.";
            }
            return canReembedAll
                ? "If this goes above 0, try Re-embed All first. If that is disabled, use Re-ingest."
                : "If this goes above 0, use Re-ingest.";
        }
        if (blockingIssueCode === "chunk_vector_store_unreadable" || blockingIssueCode === "unique_node_vector_store_unreadable") {
            return canReembedAll
                ? "Next step: use Re-embed All."
                : "Next step: use Re-ingest.";
        }
        if (blockingIssueCode === "ingestion_runtime_error") {
            if (showResume) {
                return "Next step: use Resume.";
            }
            if (hasRetryableFailuresOutsideSafetyQueue) {
                return "Next step: use Retry All Failures.";
            }
            return "Next step: use Re-ingest.";
        }
        return canReembedAll
            ? "Next step: try Re-embed All first. If that is disabled, use Re-ingest."
            : "Next step: use Re-ingest.";
    })();
    const ingestHealthTooltip = [
        [
            "Failed Records",
            failedRecordCount === 0
                ? "No specific books or chunks are failing right now."
                : "These are specific books or chunks that failed during ingest.",
            failedRecordCount > 0
                ? (hasRetryableFailuresOutsideSafetyQueue
                    ? "Next step: use Retry All Failures."
                    : hasUnresolvedSafetyQueue
                        ? "Next step: fix Safety Queue items there."
                        : "Next step: use Re-ingest.")
                : "If this goes above 0, use Retry All Failures.",
            hasUnresolvedSafetyQueue
                ? "If a chunk is in the Safety Queue, fix it there instead."
                : null,
        ].filter(Boolean).join("\n"),
        [
            "World Blockers",
            blockingIssueCount === 0
                ? "No whole-world data problems are recorded right now."
                : "This means the world's saved data needs repair, even if Failed Records is 0.",
            blockingIssueMessage ? `Current issue: ${blockingIssueMessage}` : null,
            worldBlockerNextStep,
        ].filter(Boolean).join("\n"),
    ].join("\n\n");
    const handleReingestModalSubmit = async (submission: ReingestSetupSubmission) => {
        await startIngestion(false, "rechunk_reingest", submission.ingest_settings, {
            useActiveChunkOverrides: submission.use_active_chunk_overrides,
            promptOverrides: submission.prompt_overrides,
        });
        setIsReingestModalOpen(false);
    };
    const handleInitialIngestDraftChange = (nextDraft: WorldIngestSetupDraft) => {
        initialIngestDraftWorldIdRef.current = worldId;
        initialIngestDraftDirtyRef.current = true;
        setInitialIngestDraftDirty(true);
        setInitialIngestDraft(nextDraft);
    };
    const handleInitialIngestSubmit = async () => {
        if (!initialIngestDraft) return;
        const submission = buildIngestSetupSubmission(initialIngestDraft);
        initialIngestDraftDirtyRef.current = false;
        setInitialIngestDraftDirty(false);
        await startIngestion(false, "default", submission.ingest_settings, {
            promptOverrides: submission.prompt_overrides,
        });
    };
    const toggleSafetyQueuePanel = () => {
        setActiveRightPanel((prev) => prev === "safety_queue" ? "progress" : "safety_queue");
    };
    const openReviewForFailure = (failure: StageFailure) => {
        const review = unresolvedSafetyReviewByChunkId[failure.chunk_id];
        if (!review) return;
        setActiveRightPanel("safety_queue");
        setPendingFocusReviewId(review.review_id);
    };

    return (
        <>
            <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
            {/* Left Panel — Source Management */}
                <div style={{ width: 380, flexShrink: 0, borderRight: "1px solid var(--border)", overflowY: "auto", padding: 20 }}>
                    <div style={{ marginBottom: 16 }}>
                        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>Ingest Controls</h2>
                        <div style={{ fontSize: 12, color: "var(--text-subtle)", lineHeight: 1.5 }}>
                            Upload books, manage rebuild actions, and open the safety review workspace from here.
                        </div>
                    </div>

                <div
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    onClick={() => fileRef.current?.click()}
                    style={{
                        border: `2px dashed ${dragOver ? "var(--primary)" : "var(--border)"}`,
                        borderRadius: "var(--radius)",
                        padding: "24px 16px",
                        textAlign: "center",
                        cursor: "pointer",
                        transition: "border-color 0.2s",
                        background: dragOver ? "var(--primary-soft)" : "transparent",
                    }}
                >
                    <Upload size={24} style={{ color: "var(--text-muted)", marginBottom: 8 }} />
                    <div style={{ fontSize: 14, color: "var(--text-subtle)" }}>
                        Drop .txt file here or <span style={{ color: "var(--primary-light)" }}>Browse</span>
                    </div>
                    <input ref={fileRef} type="file" accept=".txt" multiple style={{ display: "none" }} onChange={(e) => e.target.files && handleUpload(e.target.files)} />
                </div>

                <div style={{ marginTop: 16, border: "1px solid var(--border)", borderRadius: 12, background: "var(--background)", minWidth: 0, overflow: "hidden" }}>
                    <button
                        onClick={() => setIsBooksExpanded((prev) => !prev)}
                        style={{
                            width: "100%",
                            padding: "14px 16px",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 12,
                            background: "transparent",
                            border: "none",
                            color: "var(--text-primary)",
                            cursor: "pointer",
                            textAlign: "left",
                        }}
                    >
                        <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>Books in This World</div>
                            <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4 }}>
                                {booksSummaryLabel}
                            </div>
                        </div>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                            <span style={{
                                padding: "4px 10px",
                                borderRadius: 9999,
                                fontSize: 11,
                                fontWeight: 700,
                                background: "var(--primary)",
                                color: "var(--primary-contrast)",
                                border: "1px solid var(--primary)",
                            }}>
                                {bookCountLabel}
                            </span>
                            {isBooksExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                        </div>
                    </button>
                    {isBooksExpanded && (
                        <div style={{ padding: "0 12px 12px", borderTop: "1px solid var(--border)", minWidth: 0, overflow: "hidden" }}>
                            {sources.length === 0 ? (
                                <div style={{ padding: "16px 4px 4px", fontSize: 12, color: "var(--text-subtle)" }}>
                                    Upload a `.txt` source to add the first book to this world.
                                </div>
                            ) : (
                                <div style={{ display: "grid", gap: 6, paddingTop: 12, minWidth: 0 }}>
                                    {sources.map((s) => {
                                        const totalChunks = Math.max(0, Number(s.chunk_count ?? 0));
                                        const embeddedChunkCount = Math.min(
                                            totalChunks,
                                            Array.isArray(s.embedded_chunks) ? s.embedded_chunks.length : 0,
                                        );
                                        return (
                                            <div key={s.source_id} style={{
                                                display: "flex",
                                                alignItems: "flex-start",
                                                flexWrap: "wrap",
                                                padding: "10px 12px",
                                                background: "var(--background)",
                                                borderRadius: 8,
                                                border: "1px solid var(--border)",
                                                gap: 10,
                                                minWidth: 0,
                                                overflow: "hidden",
                                            }}>
                                                <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "1 1 180px", minWidth: 0 }}>
                                                    <FileText size={16} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
                                                    <div style={{ minWidth: 0 }}>
                                                        <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                            {s.display_name}
                                                        </div>
                                                        <div style={{ fontSize: 11, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                            {s.original_filename}
                                                        </div>
                                                    </div>
                                                </div>
                                                <div style={{
                                                    display: "flex",
                                                    alignItems: "center",
                                                    gap: 6,
                                                    flexShrink: 0,
                                                    flexWrap: "wrap",
                                                    justifyContent: "flex-end",
                                                    marginLeft: "auto",
                                                    maxWidth: "100%",
                                                }}>
                                                    <span style={{
                                                        padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 500,
                                                        background: "var(--primary)", color: "var(--primary-contrast)",
                                                    }}>Book {s.book_number}</span>
                                                    <span style={{
                                                        padding: "2px 8px",
                                                        borderRadius: 9999,
                                                        fontSize: 11,
                                                        fontWeight: 500,
                                                        background: "var(--background-secondary)",
                                                        color: "var(--text-primary)",
                                                        border: "1px solid var(--border)",
                                                    }}>
                                                        Embedded {embeddedChunkCount}/{totalChunks}
                                                    </span>
                                                    <StatusChip status={s.status} />
                                                    {s.status === "pending" && (
                                                        <button onClick={() => deleteSource(s.source_id)} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 2 }}>
                                                            <Trash2 size={13} />
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
                    {ingesting ? (
                        <button
                            onClick={abortIngestion}
                            disabled={isAborting}
                            style={{
                                ...btnStyle,
                                background: "var(--status-error-bg)",
                                color: "var(--status-error-fg)",
                                width: "100%",
                                opacity: isAborting ? 0.7 : 1,
                                cursor: isAborting ? "not-allowed" : "pointer",
                            }}
                        >
                            {isAborting ? "Aborting..." : "Abort"}
                        </button>
                    ) : (
                        <>
                            {showCompletedIdleState && (
                                <div style={{
                                    padding: "12px 14px",
                                    borderRadius: 10,
                                    border: "1px solid var(--status-success-soft-border)",
                                    background: "var(--status-success-soft-bg)",
                                    color: "var(--status-success-soft-fg)",
                                    fontSize: 13,
                                    fontWeight: 600,
                                    textAlign: "center",
                                }}>
                                    Ingestion complete for this world.
                                </div>
                            )}

                            {showInitialIngestSetup && (
                                initialIngestDraft ? (
                                    <WorldIngestSetupForm
                                        draft={initialIngestDraft}
                                        layout="inline"
                                        variant="initial_ingest"
                                        worldName={worldName}
                                        submitLabel="Start Ingestion"
                                        submitDisabled={!hasPending}
                                        submitDisabledReason={initialIngestSubmitDisabledReason}
                                        onDraftChange={handleInitialIngestDraftChange}
                                        onSubmit={() => void handleInitialIngestSubmit()}
                                    />
                                ) : (
                                    <div style={{
                                        border: "1px solid var(--border)",
                                        borderRadius: 16,
                                        background: "var(--background)",
                                        padding: 16,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        gap: 10,
                                        color: "var(--text-subtle)",
                                    }}>
                                        <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} />
                                        Loading ingest setup...
                                    </div>
                                )
                            )}

                            {showResume && (
                                <button
                                    onClick={() => startIngestion(true)}
                                    style={{ ...btnStyle, background: "var(--success)", color: "var(--primary-contrast)", width: "100%" }}
                                >
                                    Resume
                                </button>
                            )}

                            {showReingestAction && (
                                <div style={{ display: "grid", gap: 8 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                        <button
                                            onClick={() => {
                                                if (!confirm("This will clear this world's graph and vectors, then fully rebuild it using this world's saved ingest settings and prompts. Chats and other non-ingest data stay intact. Continue?")) return;
                                                startIngestion(false, "rechunk_reingest", savedIngestSettings ?? undefined, {
                                                    useActiveChunkOverrides: hasActiveChunkOverrides && reuseActiveChunkOverrides,
                                                });
                                            }}
                                            disabled={Boolean(rebuildBlockedReason)}
                                            style={{
                                                ...btnStyle,
                                                background: "var(--primary)",
                                                color: "var(--primary-contrast)",
                                                flex: 1,
                                                opacity: rebuildBlockedReason ? 0.45 : 1,
                                                cursor: rebuildBlockedReason ? "not-allowed" : "pointer",
                                            }}
                                        >
                                            Re-ingest
                                        </button>
                                        {rebuildBlockedReason && <InlineInfo title={rebuildBlockedReason} />}
                                        <button
                                            onClick={() => setIsReingestModalOpen(true)}
                                            aria-label="Edit re-ingest settings"
                                            title="Open the re-ingest setup popup to change this world's settings and prompts before starting."
                                            style={{
                                                display: "inline-flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                width: 36,
                                                height: 36,
                                                borderRadius: 10,
                                                border: "1px solid var(--border)",
                                                background: "var(--background)",
                                                color: "var(--text-primary)",
                                                cursor: "pointer",
                                                flexShrink: 0,
                                            }}
                                        >
                                            <Settings2 size={15} />
                                        </button>
                                    </div>
                                    {hasActiveChunkOverrides && (
                                        <LabeledToggle
                                            checked={reuseActiveChunkOverrides}
                                            onChange={setReuseActiveChunkOverrides}
                                            label={`Reuse ${activeChunkOverrideCount} repaired chunk override${activeChunkOverrideCount === 1 ? "" : "s"}`}
                                            helpText="When enabled, full Re-ingest will reuse the current repaired chunk text as long as the chunk size and overlap stay the same."
                                        />
                                    )}
                                </div>
                            )}

                            {(hasAnyIngested || hasAnySafetyQueueHistory) && (
                                <button
                                    onClick={toggleSafetyQueuePanel}
                                    style={{
                                        ...btnStyle,
                                        width: "100%",
                                        justifyContent: "space-between",
                                        background: hasUnresolvedSafetyQueue ? "var(--status-error-soft-bg)" : "var(--background)",
                                        color: hasUnresolvedSafetyQueue ? "var(--status-error-soft-fg)" : "var(--text-primary)",
                                        border: `1px solid ${hasUnresolvedSafetyQueue ? "var(--status-error-soft-border)" : "var(--border)"}`,
                                    }}
                                >
                                    <span>{safetyQueueToggleLabel}</span>
                                    <span style={{ fontSize: 12, fontWeight: 500 }}>
                                        {safetyQueueButtonDetail}
                                    </span>
                                </button>
                            )}
                        </>
                    )}
                </div>

                <EntityResolutionPanel
                    worldId={worldId}
                    canResolve={canResolveEntities}
                    allComplete={allComplete}
                    isIngesting={ingesting}
                    disabledReason={resolveEntitiesDisabledReason}
                />

                {!showInitialIngestSetup && (
                    <>
                        {/* Collapsible Ingestion Settings */}
                        <CollapsibleSection title="Ingestion Settings" open={showSettings} onToggle={() => setShowSettings(!showSettings)}>
                            <div style={{
                                marginBottom: 12,
                                padding: "10px 12px",
                                borderRadius: 8,
                                background: "var(--background)",
                                border: "1px solid var(--border)",
                                fontSize: 12,
                                color: "var(--text-primary)",
                                lineHeight: 1.5,
                            }}>
                                {savedIngestSettings?.locked_at
                                    ? `Locked for this world since ${new Date(savedIngestSettings.locked_at).toLocaleString()}. Use the Re-ingest popup if you want to change chunk settings, prompts, or the embedding provider/model before starting a full rebuild.`
                                    : "This world has not locked ingest settings yet. The snapshot below shows what will be used the next time you start or re-ingest this world."}
                            </div>
                            {previousSettingsSummary && (
                                <div style={{
                                    marginBottom: 12,
                                    padding: "10px 12px",
                                    borderRadius: 8,
                                    background: "var(--background)",
                                    border: "1px solid var(--border)",
                                    fontSize: 12,
                                    color: "var(--text-subtle)",
                                    lineHeight: 1.5,
                                }}>
                                    {previousSettingsSummary}
                                </div>
                            )}
                            <ReadOnlySettingRow label="Chunk Size (chars)" value={savedIngestSettings?.chunk_size_chars?.toLocaleString() ?? "-"} />
                            <ReadOnlySettingRow label="Chunk Overlap (chars)" value={savedIngestSettings?.chunk_overlap_chars?.toLocaleString() ?? "-"} />
                            <ReadOnlySettingRow label="Embedding Provider" value={savedEmbeddingProviderLabel} />
                            <ReadOnlySettingRow label="World Embedding Model" value={savedIngestSettings?.embedding_model ?? "-"} mono />
                            <ReadOnlySettingRow label="Graph Architect Glean Amount" value={savedIngestSettings?.glean_amount?.toLocaleString() ?? "-"} />
                        </CollapsibleSection>

                        {/* Collapsible Prompt Snapshot */}
                        <CollapsibleSection title="Prompt Snapshot" open={showPrompts} onToggle={() => setShowPrompts(!showPrompts)}>
                            {WORLD_INGEST_PROMPT_FIELDS.map(({ key, label }) => (
                                <StaticPromptField
                                    key={`${key}:${prompts[key]?.source || "default"}:${prompts[key]?.value || ""}`}
                                    label={label}
                                    prompt={prompts[key]}
                                />
                            ))}
                        </CollapsibleSection>
                    </>
                )}
            </div>

            {/* Right Panel — Progress */}
            <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
                {statusSyncError && (
                    <div style={{
                        marginBottom: 24,
                        padding: "12px 14px",
                        borderRadius: 10,
                        border: "1px solid var(--status-warning-soft-border)",
                        background: statusIsStale ? "var(--status-warning-soft-bg)" : "var(--background)",
                        color: "var(--status-warning-soft-fg)",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        gap: 16,
                        flexWrap: "wrap",
                    }}>
                        <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ fontSize: 13, fontWeight: 700 }}>Runtime status sync is stale</div>
                            <div style={{ fontSize: 12, lineHeight: 1.5, marginTop: 4 }}>
                                {statusSyncError}
                            </div>
                            <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 6 }}>
                                {runtimeSyncSummary}
                            </div>
                        </div>
                        <button
                            onClick={() => void refreshRuntimeView({
                                reconnectStream: true,
                                refreshSources: true,
                                refreshSafetyReviews: true,
                            })}
                            style={{
                                ...btnStyle,
                                background: "var(--background)",
                                color: "var(--text-primary)",
                                border: "1px solid var(--status-warning-soft-border)",
                            }}
                        >
                            Retry Status Sync
                        </button>
                    </div>
                )}
                {activeRightPanel === "safety_queue" ? (
                    <>
                        <div style={{
                            marginBottom: 24,
                            padding: "16px 18px",
                            borderRadius: 14,
                            border: "1px solid var(--border)",
                            background: "var(--background)",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "flex-start",
                            gap: 16,
                            flexWrap: "wrap",
                        }}>
                            <div>
                                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Safety Review Queue</div>
                                <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4, lineHeight: 1.45 }}>
                                    {unresolvedReviewCount} unresolved, {safetyReviewSummary?.resolved_reviews ?? 0} resolved, {safetyReviewSummary?.active_override_reviews ?? 0} active overrides
                                </div>
                            </div>
                            <button
                                onClick={toggleSafetyQueuePanel}
                                style={{
                                    ...btnStyle,
                                    background: "var(--background)",
                                    color: "var(--text-primary)",
                                    border: "1px solid var(--border)",
                                }}
                            >
                                Go to Ingest Progress
                            </button>
                        </div>

                        {ingesting && hasUnresolvedSafetyQueue && (
                            <div style={{
                                marginBottom: 24,
                                padding: "12px 14px",
                                borderRadius: 10,
                                border: "1px solid var(--status-error-soft-border)",
                                background: "var(--status-error-soft-bg)",
                                color: "var(--status-error-soft-fg)",
                                lineHeight: 1.5,
                            }}>
                                Safety review available. {unresolvedReviewCount} blocked chunk(s) have been queued for repair.
                                Let the current ingest run finish, then continue editing them here.
                            </div>
                        )}

                        {safetyReviews.length > 0 ? (
                            <SafetyReviewPanel
                                groupedReviews={groupedSafetyReviews}
                                summary={safetyReviewSummary}
                                drafts={reviewDrafts}
                                savingReviewIds={savingReviewIds}
                                testingReviewIds={testingReviewIds}
                                resettingReviewIds={resettingReviewIds}
                                onDraftChange={(reviewId, value) => setReviewDrafts((prev) => ({ ...prev, [reviewId]: value }))}
                                onDraftBlur={saveReviewDraft}
                                onResetToOriginal={resetReviewDraftToOriginal}
                                onResetToLive={resetReviewDraftToLive}
                                onTest={testReviewDraft}
                                onResetChunk={resetReview}
                            />
                        ) : showSafetyQueueUnavailableState ? (
                            <div style={{
                                border: "1px solid var(--status-warning-soft-border)",
                                borderRadius: 14,
                                background: "var(--status-warning-soft-bg)",
                                minHeight: 280,
                                display: "grid",
                                placeItems: "center",
                                padding: 24,
                                textAlign: "center",
                            }}>
                                <div style={{ maxWidth: 480 }}>
                                    <div style={{ fontSize: 18, fontWeight: 700, color: "var(--status-warning-soft-fg)" }}>
                                        Safety review items could not be loaded right now.
                                    </div>
                                    <div style={{ fontSize: 13, color: "var(--status-warning-soft-fg)", marginTop: 8, lineHeight: 1.5 }}>
                                        {safetyReviewLoadError}
                                    </div>
                                    <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 10, lineHeight: 1.5 }}>
                                        The counts above come from the saved world summary, but the detailed queue list is currently unavailable.
                                    </div>
                                    <button
                                        onClick={() => void refreshRuntimeView({
                                            reconnectStream: true,
                                            refreshSafetyReviews: true,
                                        })}
                                        style={{
                                            ...btnStyle,
                                            marginTop: 16,
                                            background: "var(--background)",
                                            color: "var(--text-primary)",
                                            border: "1px solid var(--status-warning-soft-border)",
                                        }}
                                    >
                                        Retry Queue Load
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <div style={{
                                border: "1px solid var(--border)",
                                borderRadius: 14,
                                background: "var(--background)",
                                minHeight: 280,
                                display: "grid",
                                placeItems: "center",
                                padding: 24,
                                textAlign: "center",
                            }}>
                                <div style={{ maxWidth: 420 }}>
                                    <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)" }}>No safety review items right now.</div>
                                    <div style={{ fontSize: 13, color: "var(--text-subtle)", marginTop: 8, lineHeight: 1.5 }}>
                                        Blocked chunks will appear here when extraction sends them to the repair queue.
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                ) : showIdlePlaceholder ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: showProgressHeaderCard ? 280 : "100%", color: "var(--text-muted)" }}>
                        <Upload size={48} style={{ marginBottom: 16, opacity: 0.3 }} />
                        <p style={{ fontSize: 16 }}>
                            {hasUnresolvedSafetyQueue
                                ? "This world has safety review items waiting in the queue."
                                : hasRetryableFailuresOutsideSafetyQueue
                                ? "This world has retryable ingest failures."
                                : hasAnyIngested
                                    ? "Ingestion complete for this world."
                                    : "Start ingestion to see progress."}
                        </p>
                        {(hasAnyIngested || hasRetryableFailuresOutsideSafetyQueue || hasUnresolvedSafetyQueue) && (
                            <p style={{ fontSize: 13, marginTop: 6, maxWidth: 520, textAlign: "center", lineHeight: 1.5 }}>
                                {hasUnresolvedSafetyQueue
                                    ? "Open the Safety Queue from the left column to edit blocked chunks and test repairs."
                                    : "Use Retry All Failures here, Re-embed All above, or Re-ingest from the left column."}
                            </p>
                        )}
                    </div>
                ) : (
                    <>
                        {showProgressHeaderCard && (
                            <div
                                style={{
                                    marginBottom: 24,
                                    padding: "16px 18px",
                                    borderRadius: 14,
                                    border: "1px solid var(--border)",
                                    background: "var(--background)",
                                    display: "grid",
                                    gap: 14,
                                }}
                            >
                                <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start" }}>
                                    <div style={{ minWidth: 0, flex: 1 }}>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                                            {progressHeaderLabel}
                                        </div>
                                        <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4, lineHeight: 1.45 }}>
                                            {progressSecondaryLabel
                                                || (blockingIssueMessage
                                                    ? blockingIssueMessage
                                                    : null)
                                                || (ingesting && !hasProgress
                                                    ? "Preparing stable progress summary for this run."
                                                    : (progressSummary.isReembedAll
                                                        ? "Rebuilding stored vectors without re-extracting or rebuilding the graph."
                                                        : hasAnyIngested
                                                            ? "Use this workspace for world progress, retries, and vector maintenance."
                                                            : "Start ingestion to populate world progress."))}
                                        </div>
                                    </div>
                                    <div style={{ display: "grid", gap: 8, justifyItems: "end", flexShrink: 0 }}>
                                        {showReembedAction && (
                                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                                <button
                                                    onClick={() => {
                                                        if (!confirm("This will clear this world's chunk and node vectors and re-embed all stored world content without re-extracting or rebuilding the graph. Chats and other non-ingest data stay intact. Continue?")) return;
                                                        startIngestion(false, "reembed_all");
                                                    }}
                                                    disabled={!canReembedAll}
                                                    style={{
                                                        ...btnStyle,
                                                        background: "var(--primary)",
                                                        color: "var(--primary-contrast)",
                                                        opacity: canReembedAll ? 1 : 0.45,
                                                        cursor: canReembedAll ? "pointer" : "not-allowed",
                                                    }}
                                                >
                                                    Re-embed All
                                                </button>
                                                {!canReembedAll && <InlineInfo title={reembedDisabledReason} />}
                                            </div>
                                        )}
                                        {showProgressSummary && (
                                            <>
                                                <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text-primary)" }}>
                                                    {Math.round(progressSummary.overallPercent)}%
                                                </div>
                                                <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: -4 }}>
                                                    {progressSummary.expectedChunks || "?"} total chunks
                                                </div>
                                            </>
                                        )}
                                        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                            <span style={{
                                                padding: "4px 10px",
                                                borderRadius: 9999,
                                                fontSize: 11,
                                                fontWeight: 700,
                                                background: failedRecordCount > 0 ? "var(--status-error-soft-bg)" : "var(--background-secondary)",
                                                color: failedRecordCount > 0 ? "var(--status-error-soft-fg)" : "var(--text-subtle)",
                                                border: failedRecordCount > 0 ? "1px solid var(--status-error-soft-border)" : "1px solid var(--border)",
                                            }}>
                                                Failed Records: {failedRecordCount}
                                            </span>
                                            <span style={{
                                                padding: "4px 10px",
                                                borderRadius: 9999,
                                                fontSize: 11,
                                                fontWeight: 700,
                                                background: blockingIssueCount > 0 ? "var(--status-pending-bg)" : "var(--background-secondary)",
                                                color: blockingIssueCount > 0 ? "var(--status-pending-fg)" : "var(--text-subtle)",
                                                border: blockingIssueCount > 0 ? "1px solid var(--status-pending-bg)" : "1px solid var(--border)",
                                            }}>
                                                World Blockers: {blockingIssueCount}
                                            </span>
                                            <ChipInfo title={ingestHealthTooltip} label="Failed Records and World Blockers help" />
                                            {showRetryAllButton && (
                                                <button
                                                    onClick={() => retryFailures("all")}
                                                    style={{
                                                        ...btnStyle,
                                                        background: "var(--background-tertiary)",
                                                        color: "var(--text-primary)",
                                                        border: "1px solid var(--border)",
                                                    }}
                                                >
                                                    Retry All Failures
                                                </button>
                                            )}
                                        </div>
                                        {blockingIssueCount > 0 && (
                                            <div style={{ fontSize: 11, color: "var(--status-pending-fg)", textAlign: "right", maxWidth: 340, lineHeight: 1.45 }}>
                                                {blockingIssueMessage ?? "This world has graph or vector blockers that need attention before it can be treated as fully healthy."}
                                            </div>
                                        )}
                                        {!ingesting && failedRecordCount === 0 && blockingIssueCount === 0 && hasAnyIngested && (
                                            <div style={{ fontSize: 11, color: "var(--text-subtle)", textAlign: "right", maxWidth: 260 }}>
                                                Retry actions appear here when this world has failed records or world-level blockers.
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {showProgressSummary && (
                                    <>
                                        <div>
                                            <div style={{ height: 8, background: "var(--border)", borderRadius: 999, overflow: "hidden" }}>
                                                    <div
                                                        style={{
                                                            height: "100%",
                                                            width: `${progressSummary.overallPercent}%`,
                                                            backgroundColor: "var(--primary)",
                                                            borderRadius: 999,
                                                            transition: "width 0.3s ease",
                                                        }}
                                                    />
                                            </div>
                                            {progressSummary.waitRetryAfterSeconds && progressSummary.waitState === "waiting_for_api_key" && (
                                                <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 8 }}>
                                                    Cooldown window is currently about {Math.max(1, Math.ceil(progressSummary.waitRetryAfterSeconds))}s.
                                                </div>
                                            )}
                                        </div>

                                        <div style={{ display: "grid", gap: 10 }}>
                                            {progressSummary.rows.map((row) => (
                                                <div key={row.key} style={{ display: "grid", gap: 6 }}>
                                                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                                                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                                                            <span>{row.label}</span>
                                                            {row.infoTitle && (
                                                                <span
                                                                    title={row.infoTitle}
                                                                    aria-label={`${row.label} info`}
                                                                    style={{
                                                                        display: "inline-flex",
                                                                        alignItems: "center",
                                                                        justifyContent: "center",
                                                                        minWidth: 18,
                                                                        height: 18,
                                                                        padding: "0 5px",
                                                                        borderRadius: 999,
                                                                        border: "1px solid var(--border)",
                                                                        color: "var(--text-subtle)",
                                                                        fontSize: 11,
                                                                        fontWeight: 700,
                                                                        cursor: "help",
                                                                        lineHeight: 1,
                                                                    }}
                                                                >
                                                                    (i)
                                                                </span>
                                                            )}
                                                        </span>
                                                        <span style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                                                            {row.completed}/{row.total}
                                                        </span>
                                                    </div>
                                                    <div style={{ height: 6, background: "var(--overlay-heavy)", borderRadius: 999, overflow: "hidden" }}>
                                                        <div
                                                            style={{
                                                                height: "100%",
                                                                width: `${row.percent}%`,
                                                                borderRadius: 999,
                                                                backgroundColor: "var(--primary)",
                                                                transition: "width 0.3s ease",
                                                            }}
                                                        />
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </>
                                )}
                            </div>
                        )}

                        {ingesting && hasUnresolvedSafetyQueue && (
                            <div style={{
                                marginBottom: 24,
                                padding: "12px 14px",
                                borderRadius: 10,
                                border: "1px solid var(--status-error-soft-border)",
                                background: "var(--status-error-soft-bg)",
                                color: "var(--status-error-soft-fg)",
                                lineHeight: 1.5,
                            }}>
                                Safety review available. {unresolvedReviewCount} blocked chunk(s) have been queued for repair.
                                Open the Safety Queue from the left column after the current ingest run finishes.
                            </div>
                        )}

                        {!ingesting && hasUnresolvedSafetyQueue && (
                            <div style={{
                                marginBottom: 24,
                                padding: "12px 14px",
                                borderRadius: 10,
                                border: "1px solid var(--status-warning-soft-border)",
                                background: "var(--status-warning-soft-bg)",
                                color: "var(--status-warning-soft-fg)",
                                lineHeight: 1.5,
                            }}>
                                Safety Queue has {unresolvedReviewCount} review item{unresolvedReviewCount === 1 ? "" : "s"} ready.
                                Use the left-column button to switch into the repair workspace.
                            </div>
                        )}

                        {failureRecords.length > 0 && (
                            <div style={{ marginBottom: 24 }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
                                    <div style={{ fontSize: 14, fontWeight: 600 }}>Failure Details</div>
                                    {collapsedCoverageGapFailures.length > 0 && (
                                        <button
                                            onClick={() => void rescueCollapsedFailures(collapsedCoverageGapFailures)}
                                            disabled={isRescuingCollapsedFailures}
                                            style={{
                                                ...btnStyle,
                                                background: "var(--status-warning-soft-bg)",
                                                color: "var(--status-progress-fg)",
                                                opacity: isRescuingCollapsedFailures ? 0.6 : 1,
                                                cursor: isRescuingCollapsedFailures ? "not-allowed" : "pointer",
                                            }}
                                        >
                                            {isRescuingCollapsedFailures
                                                ? "Adding Failed Chunks..."
                                                : collapsedFailureActionLabel}
                                        </button>
                                    )}
                                </div>
                                {showFailureActionGuide && (
                                    <div style={{
                                        marginBottom: 12,
                                        padding: "10px 12px",
                                        borderRadius: 8,
                                        background: "var(--status-warning-soft-bg)",
                                        border: "1px solid var(--status-warning-soft-border)",
                                        fontSize: 12,
                                        color: "var(--status-warning-soft-fg)",
                                        lineHeight: 1.5,
                                    }}>
                                        <div style={{ fontWeight: 700, marginBottom: 6 }}>What To Do</div>
                                        {failureActionSteps.length > 0 && (
                                            <ol style={{ margin: "0 0 8px 18px", padding: 0, display: "grid", gap: 6 }}>
                                                {failureActionSteps.map((step) => (
                                                    <li key={step}>{step}</li>
                                                ))}
                                            </ol>
                                        )}
                                        <div>Retry All Failures skips chunks that are already in the Safety Queue.</div>
                                        <div>Use the Safety Queue for chunks that still need manual repair after Resume and Retry.</div>
                                        {retryNotice && <div>{retryNotice}</div>}
                                    </div>
                                )}
                                <div style={{
                                    maxHeight: 220,
                                    overflowY: "auto",
                                    background: "var(--background)",
                                    border: "1px solid var(--border)",
                                    borderRadius: "var(--radius)",
                                }}>
                                    {failureRecords.map((failure, idx) => (
                                        <div key={`${failure.chunk_id}-${failure.stage}-${idx}`} style={{
                                            padding: "10px 12px",
                                            borderBottom: idx === failureRecords.length - 1 ? "none" : "1px solid var(--border)",
                                            fontSize: 12,
                                            display: "grid",
                                            gap: 4,
                                        }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                                                <strong style={{ color: "var(--text-primary)" }}>
                                                    {failure.display_name || failure.source_id} • B{failure.book_number}:C{failure.chunk_index}
                                                </strong>
                                                <span style={{
                                                    fontSize: 11,
                                                    padding: "1px 8px",
                                                    borderRadius: 9999,
                                                    background: failure.stage === "embedding" ? "var(--status-embedding-pill-bg)" : "var(--status-extraction-pill-bg)",
                                                    color: "var(--text-primary)",
                                                    textTransform: "uppercase",
                                                }}>
                                                    {failure.stage}
                                                </span>
                                            </div>
                                            <div style={{ color: "var(--text-subtle)" }}>
                                                {failure.error_type}: {failure.error_message}
                                            </div>
                                            <div style={{ color: "var(--text-muted)" }}>
                                                Attempts: {failure.attempt_count}
                                            </div>
                                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                                {unresolvedSafetyReviewByChunkId[failure.chunk_id] && failure.stage === "extraction" && (
                                                    <button
                                                        onClick={() => openReviewForFailure(failure)}
                                                        style={{
                                                            ...btnStyle,
                                                            background: "var(--primary)",
                                                            color: "var(--primary-contrast)",
                                                            padding: "4px 10px",
                                                            fontSize: 11,
                                                        }}
                                                    >
                                                        Edit Blocked Chunk
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Log */}
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <span style={{ fontSize: 14, fontWeight: 600 }}>Agent Log</span>
                            <button onClick={() => setShowLog(!showLog)} style={{ background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer", fontSize: 13 }}>
                                {showLog ? "Hide Log" : "Show Log"}
                            </button>
                        </div>
                        {showLog && (
                            <div style={{ maxHeight: 400, overflowY: "auto", background: "var(--background)", borderRadius: "var(--radius)", border: "1px solid var(--border)", padding: 12 }}>
                                {logEntries.map((entry, i) => (
                                    <LogEntryRow key={i} entry={entry} onViewBlocked={() => entry.chunk_text && setBlockedChunkData({ text: entry.chunk_text, reason: entry.safety_reason || "" })} />
                                ))}
                                <div ref={logEndRef} />
                            </div>
                        )}

                        {/* Blocked Chunk Modal */}
                        {blockedChunkData && (
                            <div style={{
                                position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
                                background: "var(--overlay-strong)", zIndex: 1000,
                                display: "flex", alignItems: "center", justifyContent: "center", padding: 40
                            }}>
                                <div style={{
                                    background: "var(--background)", border: "1px solid var(--border)",
                                    borderRadius: "var(--radius)", width: "100%", maxWidth: 800,
                                    maxHeight: "90vh", display: "flex", flexDirection: "column",
                                    boxShadow: "0 20px 25px -5px var(--shadow-color)"
                                }}>
                                    <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                        <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--error)" }}>Safety Block Details</h3>
                                        <button onClick={() => setBlockedChunkData(null)} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}>
                                            <XCircle size={20} />
                                        </button>
                                    </div>
                                    <div style={{ padding: 20, overflowY: "auto", flex: 1 }}>
                                        <div style={{ marginBottom: 16, padding: 12, background: "var(--status-error-soft-bg)", borderRadius: 8, border: "1px solid var(--status-error-soft-border)" }}>
                                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-subtle)", marginBottom: 4 }}>REASON</div>
                                            <div style={{ fontSize: 14 }}>{blockedChunkData.reason}</div>
                                        </div>
                                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-subtle)", marginBottom: 8 }}>CHUNK CONTENT</div>
                                        <div style={{
                                            fontSize: 13, background: "var(--background-secondary)",
                                            padding: 16, borderRadius: 8, border: "1px solid var(--border)",
                                            fontFamily: "monospace", whiteSpace: "pre-wrap", overflowX: "auto"
                                        }}>
                                            {blockedChunkData.text}
                                        </div>
                                    </div>
                                    <div style={{ padding: "16px 20px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "flex-end", gap: 12 }}>
                                        <button
                                            onClick={() => {
                                                navigator.clipboard.writeText(blockedChunkData.text);
                                                alert("Copied to clipboard!");
                                            }}
                                            style={{ ...btnStyle, background: "var(--primary)", color: "var(--primary-contrast)" }}
                                        >
                                            Copy Content
                                        </button>
                                        <button onClick={() => setBlockedChunkData(null)} style={{ ...btnStyle, background: "var(--border)", color: "var(--text-primary)" }}>
                                            Close
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>

        {isReingestModalOpen && (
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
                    <WorldReingestSetupContent
                        worldId={worldId}
                        mode="modal"
                        onClose={() => setIsReingestModalOpen(false)}
                        onSubmit={handleReingestModalSubmit}
                    />
                </div>
            </div>
        )}
        </>
    );
}

function StatusChip({ status }: { status: string }) {
    const colors: Record<string, { bg: string; fg: string }> = {
        pending: { bg: "var(--status-pending-bg)", fg: "var(--status-pending-fg)" },
        ingesting: { bg: "var(--status-progress-bg)", fg: "var(--status-progress-fg)" },
        complete: { bg: "var(--status-success-bg)", fg: "var(--status-success-fg)" },
        partial_failure: { bg: "var(--status-error-bg)", fg: "var(--status-error-fg)" },
        error: { bg: "var(--status-error-bg)", fg: "var(--status-error-fg)" },
    };
    const c = colors[status] || colors.pending;
    return (
        <span style={{ padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 500, background: c.bg, color: c.fg }}>
            {status}
        </span>
    );
}

function LogEntryRow({ entry, onViewBlocked }: { entry: LogEntry, onViewBlocked: () => void }) {
    const isStatusEvent = entry.event === "status";
    const isError = entry.event === "error" || entry.error_type || entry.ingestion_status === "error";
    const isComplete = (entry.event === "complete" && entry.status !== "partial_failure") || (isStatusEvent && entry.ingestion_status === "complete");
    const isPartialComplete = (entry.event === "complete" && entry.status === "partial_failure") || (isStatusEvent && entry.ingestion_status === "partial_failure");
    const isAgentDone = entry.event === "agent_complete";
    const isAborting = entry.event === "aborting";
    const isWaiting = entry.event === "waiting";
    const waitDurationSeconds = Math.max(1, Math.round(Number(entry.wait_duration_seconds ?? 0)));
    const waitMessage = isWaiting
        ? `Waited ${waitDurationSeconds}s ${formatWaitReason(entry.wait_label)}${formatAgentLabel(entry.active_agent) ? ` before ${formatAgentLabel(entry.active_agent)}` : ""}`
        : null;

    return (
        <div style={{
            padding: "6px 0",
            borderBottom: "1px solid var(--border)",
            fontSize: 13,
            display: "flex",
            gap: 8,
            alignItems: "center",
            color: isError ? "var(--error)" : isComplete ? "var(--success)" : isPartialComplete ? "var(--status-progress-fg)" : "var(--text-primary)",
        }}>
            {isError && <XCircle size={13} style={{ flexShrink: 0 }} />}
            {isComplete && <CheckCircle size={13} style={{ flexShrink: 0 }} />}
            {isPartialComplete && <CheckCircle size={13} style={{ flexShrink: 0, color: "var(--status-progress-fg)" }} />}
            {isAgentDone && <CheckCircle size={13} style={{ flexShrink: 0, color: "var(--success)" }} />}
            {!isError && !isComplete && !isPartialComplete && !isAgentDone && <Loader2 size={13} style={{ flexShrink: 0, color: "var(--text-muted)" }} />}

            {entry.book_number !== undefined && entry.chunk_index !== undefined && (
                <span style={{ padding: "1px 6px", borderRadius: 4, background: "var(--primary)", color: "var(--primary-contrast)", fontSize: 11, fontFamily: "monospace" }}>
                    B{entry.book_number}:C{entry.chunk_index}
                </span>
            )}

            <span style={{ flex: 1 }}>
                {entry.event === "progress" && `Processing — ${entry.active_agent?.replace(/_/g, " ")}`}
                {entry.event === "agent_complete" && (
                    <>
                        {entry.agent?.replace(/_/g, " ")} done
                        <span style={{ marginLeft: 6, opacity: 0.7 }}>
                            ({[
                                entry.node_count !== undefined && `${entry.node_count} nodes`,
                                entry.edge_count !== undefined && `${entry.edge_count} relationships`,
                                entry.claim_count !== undefined && `${entry.claim_count} claims`,
                                entry.chunk_vector_count !== undefined && `${entry.chunk_vector_count} chunk vectors`,
                                entry.node_vector_count !== undefined && `${entry.node_vector_count} node vectors`,
                            ].filter(Boolean).join(", ")})
                        </span>
                    </>
                )}
                {entry.event === "error" && (
                    <>
                        {entry.agent?.replace(/_/g, " ") || "Error"}: {entry.message || entry.error_type}
                        {entry.error_type === "safety_block" && entry.chunk_text && (
                            <button
                                onClick={(e) => { e.stopPropagation(); onViewBlocked(); }}
                                style={{
                                    marginLeft: 12, padding: "2px 8px", fontSize: 11, background: "var(--error)",
                                    color: "var(--primary-contrast)", border: "none", borderRadius: 4, cursor: "pointer", fontWeight: 600
                                }}
                            >
                                View Blocked Chunk
                            </button>
                        )}
                    </>
                )}
                {entry.event === "complete" && entry.status === "partial_failure" && "Retry finished. Some failures remain."}
                {entry.event === "complete" && entry.status !== "partial_failure" && "Ingestion complete!"}
                {entry.event === "status" && entry.message && !entry.ingestion_status && entry.message}
                {entry.event === "status" && entry.ingestion_status === "complete" && "Ingestion complete!"}
                {entry.event === "status" && entry.ingestion_status === "partial_failure" && "Retry finished. Some failures remain."}
                {entry.event === "status" && entry.ingestion_status === "error" && "Ingestion failed."}
                {isWaiting && waitMessage}
                {isAborting && "Aborting... waiting for in-flight work to stop."}
                {entry.event === "aborted" && `Ingestion aborted`}
            </span>
        </div>
    );
}

function safetyReviewStatusPresentation(review: SafetyReviewItem): { label: string; bg: string; fg: string } {
    if (review.status === "resolved") {
        return { label: "Resolved", bg: "var(--status-success-soft-bg)", fg: "var(--status-success-soft-fg)" };
    }
    if (review.status === "testing") {
        return { label: "Testing", bg: "var(--accent-soft-bg)", fg: "var(--accent-soft-fg)" };
    }
    if (review.status === "draft") {
        return { label: "Draft", bg: "var(--status-warning-soft-bg)", fg: "var(--status-warning-soft-fg)" };
    }
    return { label: "Blocked", bg: "var(--status-error-soft-bg)", fg: "var(--status-error-soft-fg)" };
}

function safetyReviewOutcomePresentation(review: SafetyReviewItem): { label: string; background: string; border: string; color: string } | null {
    if (review.last_test_outcome === "passed") {
        return {
            label: "Passed extraction and embedding.",
            background: "var(--status-success-bg)",
            border: "var(--status-success-fg)",
            color: "var(--status-success-fg)",
        };
    }
    if (review.last_test_outcome === "still_safety_blocked") {
        return {
            label: "Still safety blocked.",
            background: "var(--status-error-soft-bg)",
            border: "var(--status-error-soft-border)",
            color: "var(--status-error-soft-fg)",
        };
    }
    if (review.last_test_outcome === "transient_failure") {
        return {
            label: "Latest test hit a transient failure such as rate limiting.",
            background: "var(--status-warning-soft-bg)",
            border: "var(--status-warning-soft-border)",
            color: "var(--status-warning-soft-fg)",
        };
    }
    if (review.last_test_outcome === "other_failure") {
        return {
            label: "Latest test failed for another reason.",
            background: "var(--accent-soft-bg)",
            border: "var(--accent-soft-border)",
            color: "var(--accent-soft-fg)",
        };
    }
    return null;
}

function SafetyReviewPanel({
    groupedReviews,
    summary,
    drafts,
    savingReviewIds,
    testingReviewIds,
    resettingReviewIds,
    onDraftChange,
    onDraftBlur,
    onResetToOriginal,
    onResetToLive,
    onTest,
    onResetChunk,
}: {
    groupedReviews: Record<string, SafetyReviewItem[]>;
    summary: SafetyReviewSummary | null;
    drafts: Record<string, string>;
    savingReviewIds: Record<string, boolean>;
    testingReviewIds: Record<string, boolean>;
    resettingReviewIds: Record<string, boolean>;
    onDraftChange: (reviewId: string, value: string) => void;
    onDraftBlur: (review: SafetyReviewItem, draftRawText?: string) => Promise<boolean> | boolean | void;
    onResetToOriginal: (review: SafetyReviewItem) => Promise<void> | void;
    onResetToLive: (review: SafetyReviewItem) => Promise<void> | void;
    onTest: (review: SafetyReviewItem) => Promise<void> | void;
    onResetChunk: (review: SafetyReviewItem) => Promise<void> | void;
}) {
    const groups = Object.entries(groupedReviews);

    return (
        <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 12 }}>
                <div>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>Safety Review Queue</div>
                    <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4 }}>
                        {summary?.unresolved_reviews ?? 0} unresolved, {summary?.resolved_reviews ?? 0} resolved, {summary?.active_override_reviews ?? 0} active overrides
                    </div>
                </div>
            </div>

            <div style={{ display: "grid", gap: 14 }}>
                {groups.map(([groupKey, reviews]) => (
                    <div key={groupKey} style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius)",
                        background: "var(--background)",
                        overflow: "hidden",
                    }}>
                        <div style={{
                            padding: "12px 14px",
                            borderBottom: "1px solid var(--border)",
                            background: "var(--background-secondary)",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: 12,
                        }}>
                            <div style={{ fontSize: 14, fontWeight: 700 }}>{reviews[0]?.display_name}</div>
                            <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>{reviews.length} review item(s)</div>
                        </div>

                        <div style={{ display: "grid", gap: 0 }}>
                            {reviews.map((review, index) => {
                                const draftValue = drafts[review.review_id]
                                    ?? review.draft_raw_text
                                    ?? review.active_override_raw_text
                                    ?? review.original_raw_text;
                                const statusChip = safetyReviewStatusPresentation(review);
                                const lastOutcome = safetyReviewOutcomePresentation(review);
                                const hasActiveOverride = review.has_active_override;
                                const isEditingAwayFromLiveOverride = hasActiveOverride && draftValue !== review.active_override_raw_text;
                                const isSaving = Boolean(savingReviewIds[review.review_id]);
                                const isTesting = Boolean(testingReviewIds[review.review_id]) || review.status === "testing";
                                const isResetting = Boolean(resettingReviewIds[review.review_id]);
                                const isBusy = isSaving || isTesting || isResetting;
                                const liveResetTitle = hasActiveOverride
                                    ? "Reset the editor to the current live repaired chunk."
                                    : "No live chunk available";

                                return (
                                    <div id={`safety-review-${review.review_id}`} key={review.review_id} style={{
                                        padding: "14px",
                                        borderTop: index === 0 ? "none" : "1px solid var(--border)",
                                        display: "grid",
                                        gap: 12,
                                    }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                                            <div>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                                                    {review.prefix_label} • {review.display_name}
                                                </div>
                                                <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4 }}>
                                                    Safety reason: {review.original_safety_reason}
                                                </div>
                                            </div>
                                            <span style={{
                                                padding: "3px 10px",
                                                borderRadius: 9999,
                                                fontSize: 11,
                                                fontWeight: 700,
                                                background: statusChip.bg,
                                                color: statusChip.fg,
                                                whiteSpace: "nowrap",
                                            }}>
                                                {statusChip.label}
                                            </span>
                                        </div>

                                        {lastOutcome && (
                                            <div style={{
                                                padding: "10px 12px",
                                                borderRadius: 8,
                                                background: lastOutcome.background,
                                                border: `1px solid ${lastOutcome.border}`,
                                                fontSize: 12,
                                                color: lastOutcome.color,
                                                lineHeight: 1.45,
                                            }}>
                                                {lastOutcome.label}
                                                {review.last_test_error_message && (
                                                    <div style={{ marginTop: 6, color: "var(--text-subtle)" }}>
                                                        {review.last_test_error_message}
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {isEditingAwayFromLiveOverride && (
                                            <div style={{
                                                padding: "10px 12px",
                                                borderRadius: 8,
                                                background: "var(--status-warning-soft-bg)",
                                                border: "1px solid var(--status-warning-soft-border)",
                                                fontSize: 12,
                                                color: "var(--status-warning-soft-fg)",
                                                lineHeight: 1.45,
                                            }}>
                                                The current graph is still using the last passed version for this chunk. Test this draft to replace it.
                                            </div>
                                        )}

                                        <div style={{ display: "grid", gap: 8 }}>
                                            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6 }}>
                                                Read-only Prefix
                                            </div>
                                            <div style={{
                                                fontSize: 12,
                                                fontFamily: "monospace",
                                                padding: "9px 10px",
                                                borderRadius: 8,
                                                border: "1px solid var(--border)",
                                                background: "var(--background-secondary)",
                                                color: "var(--text-primary)",
                                            }}>
                                                {review.prefix_label}
                                            </div>
                                        </div>

                                        {review.overlap_raw_text?.trim() && (
                                            <div style={{ display: "grid", gap: 8 }}>
                                                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6 }}>
                                                    Reference Overlap
                                                </div>
                                                <div style={{
                                                    fontSize: 12,
                                                    fontFamily: "monospace",
                                                    padding: "9px 10px",
                                                    borderRadius: 8,
                                                    border: "1px solid var(--border)",
                                                    background: "var(--background-secondary)",
                                                    color: "var(--text-primary)",
                                                    whiteSpace: "pre-wrap",
                                                    lineHeight: 1.5,
                                                }}>
                                                    {review.overlap_raw_text}
                                                </div>
                                            </div>
                                        )}

                                        <div style={{ display: "grid", gap: 8 }}>
                                            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6 }}>
                                                Editable Chunk Body
                                            </div>
                                            <textarea
                                                id={`safety-review-textarea-${review.review_id}`}
                                                value={draftValue}
                                                readOnly={isBusy}
                                                onChange={(e) => onDraftChange(review.review_id, e.target.value)}
                                                onBlur={() => { void onDraftBlur(review, draftValue); }}
                                                rows={10}
                                                style={{
                                                    width: "100%",
                                                    resize: "vertical",
                                                    fontFamily: "monospace",
                                                    fontSize: 12,
                                                    lineHeight: 1.5,
                                                }}
                                            />
                                        </div>

                                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                                            <button
                                                onClick={() => void onTest(review)}
                                                disabled={isBusy}
                                                style={{
                                                    ...btnStyle,
                                                    background: "var(--primary)",
                                                    color: "var(--primary-contrast)",
                                                    opacity: isBusy ? 0.6 : 1,
                                                    cursor: isBusy ? "not-allowed" : "pointer",
                                                }}
                                            >
                                                {isTesting ? "Testing..." : "Test"}
                                            </button>
                                            <span title={liveResetTitle} style={{ display: "inline-flex" }}>
                                                <button
                                                    onClick={() => void onResetToLive(review)}
                                                    disabled={isBusy || !hasActiveOverride}
                                                    style={{
                                                        ...btnStyle,
                                                        background: hasActiveOverride ? "var(--background-tertiary)" : "var(--background-secondary)",
                                                        color: hasActiveOverride ? "var(--text-primary)" : "var(--text-muted)",
                                                        border: `1px solid ${hasActiveOverride ? "var(--border)" : "var(--background-tertiary)"}`,
                                                        opacity: isBusy || !hasActiveOverride ? 0.55 : 1,
                                                        cursor: isBusy || !hasActiveOverride ? "not-allowed" : "pointer",
                                                    }}
                                                >
                                                    Reset to Live
                                                </button>
                                            </span>
                                            <button
                                                onClick={() => void onResetToOriginal(review)}
                                                disabled={isBusy}
                                                style={{
                                                    ...btnStyle,
                                                    background: "var(--background-tertiary)",
                                                    color: "var(--text-primary)",
                                                    opacity: isBusy ? 0.6 : 1,
                                                    cursor: isBusy ? "not-allowed" : "pointer",
                                                }}
                                            >
                                                Reset to Original
                                            </button>
                                            <button
                                                onClick={() => void onResetChunk(review)}
                                                disabled={isBusy}
                                                style={{
                                                    ...btnStyle,
                                                    background: hasActiveOverride ? "var(--status-error-bg)" : "var(--border)",
                                                    color: hasActiveOverride ? "var(--status-error-fg)" : "var(--text-primary)",
                                                    opacity: isBusy ? 0.6 : 1,
                                                    cursor: isBusy ? "not-allowed" : "pointer",
                                                }}
                                            >
                                                {isResetting ? "Resetting..." : "Reset Chunk"}
                                            </button>
                                            {review.test_attempt_count !== undefined && review.test_attempt_count > 0 && (
                                                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                                                    Tests: {review.test_attempt_count}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

function CollapsibleSection({ title, open, onToggle, children }: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
    return (
        <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <button
                onClick={onToggle}
                style={{
                    width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center",
                    background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer",
                    fontSize: 13, fontWeight: 600, padding: "4px 0", textTransform: "uppercase", letterSpacing: "0.05em",
                }}
            >
                {title}
                {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {open && <div style={{ marginTop: 12 }}>{children}</div>}
        </div>
    );
}

function InlineInfo({ title }: { title: string }) {
    return (
        <span
            title={title}
            aria-label={title}
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
    );
}

function ChipInfo({ title, label }: { title: string; label: string }) {
    return (
        <span
            title={title}
            aria-label={label}
            style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                minWidth: 18,
                height: 18,
                padding: "0 5px",
                borderRadius: 999,
                border: "1px solid var(--border)",
                color: "var(--text-subtle)",
                fontSize: 11,
                flexShrink: 0,
                cursor: "help",
            }}
        >
            <Info size={11} />
        </span>
    );
}

function LabeledToggle({
    checked,
    onChange,
    label,
    helpText,
    disabled = false,
}: {
    checked: boolean;
    onChange: (next: boolean) => void;
    label: string;
    helpText?: string;
    disabled?: boolean;
}) {
    return (
        <label style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid var(--border)",
            background: "var(--background)",
            opacity: disabled ? 0.55 : 1,
            cursor: disabled ? "not-allowed" : "pointer",
        }}>
            <input
                type="checkbox"
                checked={checked}
                disabled={disabled}
                onChange={(e) => onChange(e.target.checked)}
            />
            <span style={{ flex: 1, fontSize: 12, color: "var(--text-primary)", lineHeight: 1.45 }}>
                {label}
            </span>
            {helpText && <InlineInfo title={helpText} />}
        </label>
    );
}

function ReadOnlySettingRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
    return (
        <div style={{
            marginBottom: 12,
            padding: "10px 12px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--background)",
            display: "grid",
            gap: 4,
        }}>
            <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>{label}</div>
            <div style={{ fontSize: 13, color: "var(--text-primary)", fontFamily: mono ? "monospace" : undefined }}>
                {value}
            </div>
        </div>
    );
}

function StaticPromptField({ label, prompt }: { label: string; prompt?: WorldPromptState }) {
    const sourceLabel = formatPromptSourceLabel(prompt?.source);
    const isWorld = sourceLabel === "world";
    const isGlobal = sourceLabel === "global";
    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
                <span style={{
                    fontSize: 11,
                    padding: "2px 8px",
                    borderRadius: 9999,
                    fontWeight: 600,
                    background: isWorld || isGlobal
                        ? "var(--accent-pill-bg)"
                        : "var(--status-pending-bg)",
                    color: isWorld || isGlobal
                        ? "var(--accent-pill-fg)"
                        : "var(--status-pending-fg)",
                    textTransform: "lowercase",
                }}>
                    {sourceLabel}
                </span>
            </div>
            <div style={{
                width: "100%",
                minHeight: 120,
                padding: "10px 12px",
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: "var(--background)",
                color: "var(--text-primary)",
                fontSize: 12,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
            }}>
                {prompt?.value || ""}
            </div>
        </div>
    );
}

const btnStyle: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
    padding: "8px 16px", borderRadius: "var(--radius)", border: "none",
    fontSize: 13, fontWeight: 600, cursor: "pointer", transition: "opacity 0.2s",
};
