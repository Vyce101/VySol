"use client";

import { useState, useEffect, useRef, use } from "react";
import { Upload, FileText, Trash2, Play, ChevronDown, ChevronUp, CheckCircle, XCircle, Loader2 } from "lucide-react";
import EntityResolutionPanel from "@/components/EntityResolutionPanel";
import { apiFetch, apiUpload, apiStreamGet } from "@/lib/api";
import { buildIngestActivityLabel, resolveStableIngestProgress } from "@/lib/ingest-progress";

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
    sources_total: number;
    sources_complete: number;
    sources_partial_failure: number;
    synthesized_failures: number;
}

interface Checkpoint {
    can_resume: boolean;
    chunk_index: number;
    chunks_total: number;
    reason: string | null;
    stage_counters?: StageCounters;
    failures?: StageFailure[];
    safety_review_summary?: SafetyReviewSummary;
    active_ingestion_run?: boolean;
    progress_phase?: "extracting" | "embedding" | "aborting" | "idle";
    completed_chunks_current_phase?: number;
    total_chunks_current_phase?: number;
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

interface IngestSettings {
    chunk_size_chars: number;
    chunk_overlap_chars: number;
    embedding_model: string;
    locked_at?: string | null;
    last_ingest_settings_at?: string | null;
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
    ingestion_status?: string;
    ingest_settings?: IngestSettings;
    active_ingestion_run?: boolean;
    reembed_eligibility?: ReembedEligibility;
    safety_review_summary?: SafetyReviewSummary;
}

interface SettingsResponse {
    glean_amount?: number;
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
    progress_phase?: "extracting" | "embedding" | "aborting" | "idle";
    completed_chunks_current_phase?: number;
    total_chunks_current_phase?: number;
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
    phase: "extracting" | "embedding" | "aborting" | "idle";
    operation: string;
    activeAgent: string | null;
    stageCounters: StageCounters;
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

function normalizeGleanAmount(value: unknown): number {
    const raw = typeof value === "string" ? value.trim() : String(value ?? "");
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed)) return 1;
    return Math.min(5, Math.max(0, Math.trunc(parsed)));
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
        operation: "default",
        activeAgent: null,
        stageCounters: {
            expected_chunks: 0,
            extracted_chunks: 0,
            embedded_chunks: 0,
            current_unique_nodes: 0,
            embedded_unique_nodes: 0,
            failed_records: 0,
            sources_total: 0,
            sources_complete: 0,
            sources_partial_failure: 0,
            synthesized_failures: 0,
        },
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
    const [isAborting, setIsAborting] = useState(false);
    const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
    const [progress, setProgress] = useState(initialProgress);
    const [showLog, setShowLog] = useState(true);
    const [showSettings, setShowSettings] = useState(false);
    const [showPrompts, setShowPrompts] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const logEndRef = useRef<HTMLDivElement>(null);
    const fileRef = useRef<HTMLInputElement>(null);
    const esRef = useRef<EventSource | null>(null);

    // Settings state
    const [chunkSize, setChunkSize] = useState(4000);
    const [chunkOverlap, setChunkOverlap] = useState(150);
    const [embeddingModel, setEmbeddingModel] = useState("gemini-embedding-2-preview");
    const [savedIngestSettings, setSavedIngestSettings] = useState<IngestSettings | null>(null);
    const [reembedEligibility, setReembedEligibility] = useState<ReembedEligibility | null>(null);
    const [gleanAmountDraft, setGleanAmountDraft] = useState("1");
    const [prompts, setPrompts] = useState<Record<string, { value: string; source: string }>>({});
    const [blockedChunkData, setBlockedChunkData] = useState<{ text: string; reason: string } | null>(null);
    const [safetyReviews, setSafetyReviews] = useState<SafetyReviewItem[]>([]);
    const [safetyReviewSummary, setSafetyReviewSummary] = useState<SafetyReviewSummary | null>(null);
    const [reviewDrafts, setReviewDrafts] = useState<Record<string, string>>({});
    const [savingReviewIds, setSavingReviewIds] = useState<Record<string, boolean>>({});
    const [testingReviewIds, setTestingReviewIds] = useState<Record<string, boolean>>({});
    const [discardingReviewIds, setDiscardingReviewIds] = useState<Record<string, boolean>>({});
    const [retryNotice, setRetryNotice] = useState<string | null>(null);
    const [pendingFocusReviewId, setPendingFocusReviewId] = useState<string | null>(null);
    const [isRescuingCollapsedFailures, setIsRescuingCollapsedFailures] = useState(false);

    const resetProgress = () => setProgress(initialProgress);
    const isTerminalIngestionStatus = (status?: string | null) => Boolean(status && status !== "in_progress");
    const mergeStageCounters = (previous: StageCounters, incoming?: StageCounters): StageCounters => {
        if (!incoming) return previous;
        return {
            expected_chunks: Math.max(Number(previous.expected_chunks ?? 0), Number(incoming.expected_chunks ?? 0)),
            extracted_chunks: Math.max(Number(previous.extracted_chunks ?? 0), Number(incoming.extracted_chunks ?? 0)),
            embedded_chunks: Math.max(Number(previous.embedded_chunks ?? 0), Number(incoming.embedded_chunks ?? 0)),
            current_unique_nodes: Math.max(Number(previous.current_unique_nodes ?? 0), Number(incoming.current_unique_nodes ?? 0)),
            embedded_unique_nodes: Math.max(Number(previous.embedded_unique_nodes ?? 0), Number(incoming.embedded_unique_nodes ?? 0)),
            failed_records: Math.max(Number(previous.failed_records ?? 0), Number(incoming.failed_records ?? 0)),
            sources_total: Math.max(Number(previous.sources_total ?? 0), Number(incoming.sources_total ?? 0)),
            sources_complete: Math.max(Number(previous.sources_complete ?? 0), Number(incoming.sources_complete ?? 0)),
            sources_partial_failure: Math.max(Number(previous.sources_partial_failure ?? 0), Number(incoming.sources_partial_failure ?? 0)),
            synthesized_failures: Math.max(Number(previous.synthesized_failures ?? 0), Number(incoming.synthesized_failures ?? 0)),
        };
    };

    const syncSafetyReviewState = (reviews: SafetyReviewItem[], summary?: SafetyReviewSummary | null) => {
        setSafetyReviews(reviews);
        setSafetyReviewSummary(summary ?? null);
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
            return {
                phase: payload.progress_phase || prev.phase,
                operation: payload.active_operation || prev.operation,
                activeAgent: payload.active_agent || payload.agent || prev.activeAgent,
                stageCounters: nextStageCounters,
                waitState: payload.wait_state ?? null,
                waitLabel: payload.wait_label ?? null,
                waitRetryAfterSeconds: payload.wait_retry_after_seconds ?? null,
                progressSourceId: payload.progress_source_id ?? payload.source_id ?? prev.progressSourceId,
                progressSourceDisplayName: payload.progress_source_display_name ?? prev.progressSourceDisplayName,
                progressSourceBookNumber: payload.progress_source_book_number ?? payload.book_number ?? prev.progressSourceBookNumber,
            };
        });
    };

    async function loadSettings() {
        try {
            const data = await apiFetch<SettingsResponse>(`/settings`);
            const normalized = normalizeGleanAmount(data.glean_amount);
            setGleanAmountDraft(String(normalized));
        } catch { /* ignore */ }
    }

    const applyWorldData = (data: WorldResponse, options?: { syncIngestInputs?: boolean }) => {
        const syncIngestInputs = options?.syncIngestInputs ?? true;
        setReembedEligibility(data.reembed_eligibility ?? null);
        setSafetyReviewSummary(data.safety_review_summary ?? null);
        if (data.ingest_settings) {
            setSavedIngestSettings(data.ingest_settings);
            if (syncIngestInputs) {
                setChunkSize(data.ingest_settings.chunk_size_chars);
                setChunkOverlap(data.ingest_settings.chunk_overlap_chars);
                setEmbeddingModel(data.ingest_settings.embedding_model);
            }
        }
        const liveRun = data.ingestion_status === "in_progress" && data.active_ingestion_run === true;
        if (liveRun) {
            setIngesting(true);
            setIsAborting(false);
            connectToSSE();
        } else {
            esRef.current?.close();
            setIngesting(false);
            setIsAborting(false);
        }
    };

    const applySourcesData = (data: Source[]) => {
        setSources(data);
    };

    const applyCheckpointData = (data: Checkpoint) => {
        setCheckpoint(data);
        syncProgressFromPayload(data);
        setIsAborting(data.progress_phase === "aborting");
        if (data.safety_review_summary) {
            setSafetyReviewSummary(data.safety_review_summary);
        }
    };

    async function loadWorld() {
        try {
            const data = await apiFetch<WorldResponse>(`/worlds/${worldId}`);
            applyWorldData(data);
        } catch { /* ignore */ }
    }

    async function loadSources() {
        try {
            const data = await apiFetch<Source[]>(`/worlds/${worldId}/sources`);
            applySourcesData(data);
        } catch { /* ignore */ }
    }

    async function loadCheckpoint() {
        try {
            const data = await apiFetch<Checkpoint>(`/worlds/${worldId}/ingest/checkpoint`);
            applyCheckpointData(data);
        } catch { /* ignore */ }
    }

    async function refreshIngestActionState() {
        const [worldData, sourcesData, checkpointData] = await Promise.all([
            apiFetch<WorldResponse>(`/worlds/${worldId}`),
            apiFetch<Source[]>(`/worlds/${worldId}/sources`),
            apiFetch<Checkpoint>(`/worlds/${worldId}/ingest/checkpoint`),
        ]);
        applyWorldData(worldData, { syncIngestInputs: false });
        applySourcesData(sourcesData);
        applyCheckpointData(checkpointData);
    }

    async function loadSafetyReviews() {
        try {
            const data = await apiFetch<SafetyReviewResponse>(`/worlds/${worldId}/ingest/safety-reviews`);
            syncSafetyReviewState(data.reviews, data.summary);
        } catch { /* ignore */ }
    }

    async function loadPrompts() {
        try {
            const data = await apiFetch<Record<string, { value: string; source: string }>>(`/settings/prompts`);
            setPrompts(data);
        } catch { /* ignore */ }
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
                    setIsAborting(true);
                    setIngesting(true);
                }
                if (entry.error_type === "safety_block") {
                    void loadSafetyReviews();
                    void loadCheckpoint();
                }
                const terminalStatus = entry.ingestion_status || entry.status;
                const isTerminalEvent = (
                    entry.event === "complete"
                    || entry.event === "aborted"
                    || (entry.event === "status" && isTerminalIngestionStatus(entry.ingestion_status))
                );
                if (isTerminalEvent || (entry.active_ingestion_run === false && isTerminalIngestionStatus(terminalStatus))) {
                    esRef.current?.close();
                    setIngesting(false);
                    setIsAborting(false);
                    void loadWorld();
                    void loadSources();
                    void loadCheckpoint();
                    void loadSafetyReviews();
                }
            },
            () => {
                esRef.current?.close();
                setIngesting(false);
                setIsAborting(false);
                void loadWorld();
                void loadSources();
                void loadCheckpoint();
                void loadSafetyReviews();
            },
            (err) => {
                esRef.current?.close();
                setIngesting(false);
                setIsAborting(false);
                void loadWorld();
                void loadSources();
                void loadCheckpoint();
                void loadSafetyReviews();
                setLogEntries((prev) => [...prev, { event: "error", message: err.message }]);
            }
        );
    };

    /* eslint-disable react-hooks/exhaustive-deps */
    // These loaders are scoped to the current world id and intentionally rerun only on world changes.
    useEffect(() => {
        const initializePage = async () => {
            await Promise.all([
                loadWorld(),
                loadSources(),
                loadCheckpoint(),
                loadSafetyReviews(),
                loadSettings(),
                loadPrompts(),
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

    const buildIngestSettingsPayload = (override?: Partial<IngestSettings>) => ({
        chunk_size_chars: override?.chunk_size_chars ?? chunkSize,
        chunk_overlap_chars: override?.chunk_overlap_chars ?? chunkOverlap,
        embedding_model: override?.embedding_model ?? embeddingModel.trim(),
    });

    const startIngestion = async (
        resume: boolean,
        operation: "default" | "rechunk_reingest" | "reembed_all" = "default",
        overrideSettings?: Partial<IngestSettings>,
    ) => {
        resetProgress();
        setRetryNotice(null);
        setIngesting(true);
        setLogEntries([]);
        try {
            await apiFetch(`/worlds/${worldId}/ingest/start`, {
                method: "POST",
                body: JSON.stringify({
                    resume,
                    operation,
                    ingest_settings: buildIngestSettingsPayload(overrideSettings),
                }),
            });
            connectToSSE();
        } catch (err: unknown) {
            setIngesting(false);
            alert((err as Error).message);
        }
    };

    const retryFailures = async (stage: "extraction" | "embedding" | "all") => {
        resetProgress();
        setRetryNotice(null);
        setIngesting(true);
        setLogEntries([]);
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
                loadSafetyReviews(),
            ]);
            if (firstReviewId) {
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
            setIsAborting(true);
            await apiFetch(`/worlds/${worldId}/ingest/abort`, { method: "POST" });
        } catch {
            setIsAborting(false);
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

    const savePrompt = async (key: string, value: string) => {
        try {
            await apiFetch("/settings/prompts", {
                method: "POST",
                body: JSON.stringify({ key, value }),
            });
            loadPrompts();
        } catch { /* ignore */ }
    };

    const resetPrompt = async (key: string) => {
        try {
            await apiFetch(`/settings/prompts/reset/${key}`, { method: "POST" });
            loadPrompts();
        } catch { /* ignore */ }
    };

    const saveAgentSettings = async () => {
        try {
            const normalized = normalizeGleanAmount(gleanAmountDraft);
            setGleanAmountDraft(String(normalized));
            await apiFetch("/settings", {
                method: "POST",
                body: JSON.stringify({
                    glean_amount: normalized,
                }),
            });
        } catch { /* ignore */ }
    };

    const commitGleanDraft = () => {
        const normalized = normalizeGleanAmount(gleanAmountDraft);
        setGleanAmountDraft(String(normalized));
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
        await Promise.all([
            loadWorld(),
            loadSources(),
            loadCheckpoint(),
            loadSafetyReviews(),
        ]);
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

    const resetReviewDraft = async (review: SafetyReviewItem) => {
        const resetText = review.original_raw_text;
        setReviewDrafts((prev) => ({ ...prev, [review.review_id]: resetText }));
        await saveReviewDraft(review, resetText);
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
            await Promise.all([
                loadWorld(),
                loadSources(),
                loadCheckpoint(),
                loadSafetyReviews(),
            ]);
        } catch (err: unknown) {
            if (isMissingSafetyReviewError(err)) {
                await refreshAfterMissingSafetyReview(review.review_id);
                return;
            }
            alert((err as Error).message);
            await Promise.all([loadCheckpoint(), loadSafetyReviews()]);
        } finally {
            setReviewBusy(setTestingReviewIds, review.review_id, false);
        }
    };

    const discardReview = async (review: SafetyReviewItem) => {
        const hasActiveOverride = Boolean(review.active_override_raw_text?.trim());
        const confirmMessage = hasActiveOverride
            ? "This will remove the saved override for this repaired chunk so rebuild actions can use the original source again. Continue?"
            : "This will remove this safety review item from the queue. The underlying ingest failure record will still remain until you retry or rebuild. Continue?";
        if (!confirm(confirmMessage)) return;

        setReviewBusy(setDiscardingReviewIds, review.review_id, true);
        try {
            await apiFetch(`/worlds/${worldId}/ingest/safety-reviews/${review.review_id}/discard`, {
                method: "POST",
            });
            await Promise.all([
                loadWorld(),
                loadCheckpoint(),
                loadSafetyReviews(),
            ]);
        } catch (err: unknown) {
            if (isMissingSafetyReviewError(err)) {
                await refreshAfterMissingSafetyReview(review.review_id);
                return;
            }
            alert((err as Error).message);
        } finally {
            setReviewBusy(setDiscardingReviewIds, review.review_id, false);
        }
    };

    const failureRecords = checkpoint?.failures || [];
    const safetyReviewByChunkId = safetyReviews.reduce<Record<string, SafetyReviewItem>>((lookup, review) => {
        lookup[review.chunk_id] = review;
        return lookup;
    }, {});
    const collapsedCoverageGapFailures = failureRecords.filter((failure) => (
        failure.stage === "extraction"
        && failure.error_type === "coverage_gap"
        && !safetyReviewByChunkId[failure.chunk_id]
    ));
    const hasPending = sources.some((s) => s.status === "pending" || s.status === "ingesting");
    const hasRetryableFailures = failureRecords.some(
        (failure) => !(failure.stage === "extraction" && safetyReviewByChunkId[failure.chunk_id])
    );
    const hasAnyIngested = sources.some((s) => s.chunk_count > 0 || s.ingested_at !== null || s.status === "partial_failure" || s.status === "complete");
    const allComplete = sources.length > 0 && sources.every((s) => s.status === "complete");
    const hasLockedPreviousSettings = Boolean(
        savedIngestSettings?.locked_at
        && Number.isFinite(savedIngestSettings?.chunk_size_chars)
        && Number.isFinite(savedIngestSettings?.chunk_overlap_chars)
        && savedIngestSettings?.embedding_model
    );
    const chunkSettingsChanged = Boolean(savedIngestSettings) && (
        chunkSize !== (savedIngestSettings?.chunk_size_chars ?? chunkSize)
        || chunkOverlap !== (savedIngestSettings?.chunk_overlap_chars ?? chunkOverlap)
    );
    const embeddingModelChanged = Boolean(savedIngestSettings)
        && embeddingModel.trim() !== (savedIngestSettings?.embedding_model ?? embeddingModel.trim());
    const showRechunkAction = !ingesting && hasAnyIngested;
    const showReembedAction = !ingesting && hasAnyIngested;
    const canReembedAll = Boolean(
        showReembedAction
        && reembedEligibility?.can_reembed_all
        && !chunkSettingsChanged
    );
    const reembedReadyExplanation = reembedEligibility?.message
        || "This rebuild clears and re-creates all chunk and node vectors for the world without re-extracting or rebuilding the graph.";
    const reembedDisabledReason = chunkSettingsChanged
        ? "Re-embed All always uses this world's locked chunk settings. Use Re-ingest With Previous Settings or Rechunk And Re-ingest to change chunk size or overlap."
        : reembedEligibility?.message
            || "Re-embed All is not currently safe for this world.";
    const previousSettingsSummary = savedIngestSettings
        ? `Chunk ${savedIngestSettings.chunk_size_chars.toLocaleString()} chars | Overlap ${savedIngestSettings.chunk_overlap_chars.toLocaleString()} chars | ${savedIngestSettings.embedding_model}`
        : null;
    const hasPendingWorldSettingChange = chunkSettingsChanged || embeddingModelChanged;
    const canResolveEntities = !ingesting && !hasPending && hasAnyIngested;
    const showResume = Boolean(checkpoint?.can_resume) && !ingesting && (hasPending || hasRetryableFailures);
    const sourceNameById = sources.reduce<Record<string, string>>((lookup, source) => {
        lookup[source.source_id] = source.display_name;
        return lookup;
    }, {});
    const progressSummary = resolveStableIngestProgress({
        active_operation: progress.operation,
        progress_phase: progress.phase,
        stage_counters: progress.stageCounters,
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
    const reviewCount = safetyReviewSummary?.total_reviews ?? safetyReviews.length;
    const blocksRebuild = Boolean(safetyReviewSummary?.blocks_rebuild);
    const rebuildBlockedReason = safetyReviewSummary?.blocking_message
        || "Safety review work is still pending for this world.";
    const hasProgress = progressSummary.totalWorkUnits > 0;
    const showProgressSummary = ingesting || hasProgress;
    const showCompletedIdleState = !ingesting && !hasPending && allComplete && !hasRetryableFailures && !showResume;
    const showIdlePlaceholder = !ingesting && logEntries.length === 0 && failureRecords.length === 0 && safetyReviews.length === 0 && !hasProgress;
    const progressHeaderLabel = progressSummary.isAborting
        ? "Stopping ingest..."
        : progressSummary.isReembedAll
            ? "Re-embedding world content"
            : "Ingest progress";
    const groupedSafetyReviews = safetyReviews.reduce<Record<string, SafetyReviewItem[]>>((groups, review) => {
        const key = `${review.display_name}::${review.source_id}`;
        groups[key] = groups[key] || [];
        groups[key].push(review);
        return groups;
    }, {});
    const openReviewForFailure = (failure: StageFailure) => {
        const review = safetyReviewByChunkId[failure.chunk_id];
        if (!review) return;
        setPendingFocusReviewId(review.review_id);
    };

    return (
        <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
            {/* Left Panel — Source Management */}
            <div style={{ width: 380, flexShrink: 0, borderRight: "1px solid var(--border)", overflowY: "auto", padding: 20 }}>
                <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>Sources</h2>

                {/* Drop zone */}
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
                        marginBottom: 16,
                        transition: "border-color 0.2s",
                        background: dragOver ? "var(--primary-soft)" : "transparent",
                    }}
                >
                    <Upload size={24} style={{ color: "var(--text-muted)", marginBottom: 8 }} />
                    <div style={{ fontSize: 14, color: "var(--text-subtle)" }}>Drop .txt file here or <span style={{ color: "var(--primary-light)" }}>Browse</span></div>
                    <input ref={fileRef} type="file" accept=".txt" multiple style={{ display: "none" }} onChange={(e) => e.target.files && handleUpload(e.target.files)} />
                </div>

                {/* Source list */}
                {sources.map((s) => (
                    <div key={s.source_id} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        padding: "10px 12px", background: "var(--background)", borderRadius: 8, marginBottom: 6,
                        border: "1px solid var(--border)",
                    }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
                            <FileText size={16} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {s.display_name}
                                </div>
                                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{s.original_filename}</div>
                            </div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{
                                padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 500,
                                background: "var(--status-info-pill-bg)", color: "var(--status-info-pill-fg)",
                            }}>Book {s.book_number}</span>
                            <StatusChip status={s.status} />
                            {s.status === "pending" && (
                                <button onClick={() => deleteSource(s.source_id)} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 2 }}>
                                    <Trash2 size={13} />
                                </button>
                            )}
                        </div>
                    </div>
                ))}

                {/* Start / Resume buttons */}
                <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                    {ingesting ? (
                        <button
                            onClick={abortIngestion}
                            disabled={isAborting}
                            style={{
                                ...btnStyle,
                                background: "var(--status-error-bg)",
                                color: "var(--status-error-fg)",
                                flex: 1,
                                opacity: isAborting ? 0.7 : 1,
                                cursor: isAborting ? "not-allowed" : "pointer",
                            }}
                        >
                            {isAborting ? "Aborting..." : "Abort"}
                        </button>
                    ) : showResume ? (
                        <>
                            <button onClick={() => startIngestion(true)} style={{ ...btnStyle, background: "var(--success)", color: "var(--primary-contrast)", flex: 1 }}>
                                Resume
                            </button>
                            <button
                                onClick={() => { if (confirm("This will erase all graph and vector data for this world, then rebuild it using the currently shown world settings. Are you sure?")) startIngestion(false); }}
                                disabled={blocksRebuild}
                                title={blocksRebuild ? rebuildBlockedReason : undefined}
                                style={{
                                    ...btnStyle,
                                    background: "var(--status-error-bg)",
                                    color: "var(--status-error-fg)",
                                    flex: 1,
                                    opacity: blocksRebuild ? 0.45 : 1,
                                    cursor: blocksRebuild ? "not-allowed" : "pointer",
                                }}
                            >
                                Start Over
                            </button>
                        </>
                    ) : showCompletedIdleState ? (
                        <div style={{
                            flex: 1,
                            padding: "12px 14px",
                            borderRadius: 10,
                            border: "1px solid rgba(34,197,94,0.28)",
                            background: "rgba(34,197,94,0.08)",
                            color: "#86efac",
                            fontSize: 13,
                            fontWeight: 600,
                            textAlign: "center",
                        }}>
                            Ingestion complete for this world.
                        </div>
                    ) : (
                        <button
                            onClick={() => { startIngestion(false); }}
                            disabled={!hasPending}
                            style={{ ...btnStyle, background: "var(--primary)", color: "var(--primary-contrast)", flex: 1, opacity: !hasPending ? 0.4 : 1 }}
                        >
                            <Play size={14} /> Start Ingestion
                        </button>
                    )}
                </div>

                {showRechunkAction && (
                    <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                        <div style={{ fontSize: 12, color: "var(--status-progress-fg)", lineHeight: 1.5 }}>
                            {chunkSettingsChanged
                                ? "Chunk size or overlap changed. This full rebuild will re-chunk, re-extract, rebuild the graph, and re-embed everything for this world."
                                : "This full rebuild re-chunks, re-extracts, rebuilds the graph, and re-embeds everything for this world using the current ingest settings."}
                        </div>
                        {hasLockedPreviousSettings && savedIngestSettings && (
                            <button
                                onClick={() => {
                                    if (!confirm("This will clear this world's graph and vectors, then fully rebuild it using the previously locked ingest settings from the last clean ingest. Chats and other non-ingest data stay intact. Continue?")) return;
                                    startIngestion(false, "rechunk_reingest", savedIngestSettings);
                                }}
                                disabled={blocksRebuild}
                                title={blocksRebuild ? rebuildBlockedReason : undefined}
                                style={{
                                    ...btnStyle,
                                    background: "var(--primary)",
                                    color: "var(--primary-contrast)",
                                    width: "100%",
                                    opacity: blocksRebuild ? 0.45 : 1,
                                    cursor: blocksRebuild ? "not-allowed" : "pointer",
                                }}
                            >
                                Re-ingest With Previous Settings
                            </button>
                        )}
                        <button
                            onClick={() => {
                                if (!confirm("This will clear this world's graph and vectors, then re-chunk, re-extract, rebuild the graph, and re-embed everything for this world. Chats and other non-ingest data stay intact. Continue?")) return;
                                startIngestion(false, "rechunk_reingest");
                            }}
                            disabled={blocksRebuild}
                            title={blocksRebuild ? rebuildBlockedReason : undefined}
                            style={{
                                ...btnStyle,
                                background: "var(--status-progress-bg)",
                                color: "var(--primary-contrast)",
                                width: "100%",
                                opacity: blocksRebuild ? 0.45 : 1,
                                cursor: blocksRebuild ? "not-allowed" : "pointer",
                            }}
                        >
                            Rechunk And Re-ingest (Current Settings)
                        </button>
                    </div>
                )}

                {showReembedAction && (
                    <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                        <div style={{ fontSize: 12, color: "var(--status-info-pill-fg)", lineHeight: 1.5 }}>
                            {embeddingModelChanged
                                ? "Embedding model changed. This rebuild clears and re-creates all chunk and node vectors for the world without re-extracting or rebuilding the graph."
                                : "This rebuild clears and re-creates all chunk and node vectors for the world without re-extracting or rebuilding the graph."}
                        </div>
                        <div style={{
                            fontSize: 12,
                            color: canReembedAll ? "var(--text-subtle)" : "#fca5a5",
                            lineHeight: 1.5,
                            padding: "10px 12px",
                            borderRadius: 8,
                            border: canReembedAll ? "1px solid var(--border)" : "1px solid rgba(248,113,113,0.28)",
                            background: canReembedAll ? "var(--background)" : "rgba(127,29,29,0.16)",
                        }}>
                            {canReembedAll ? reembedReadyExplanation : reembedDisabledReason}
                        </div>
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
                                width: "100%",
                                opacity: canReembedAll ? 1 : 0.45,
                                cursor: canReembedAll ? "pointer" : "not-allowed",
                            }}
                        >
                            Re-embed All
                        </button>
                    </div>
                )}

                {blocksRebuild && (
                    <div style={{
                        marginTop: 10,
                        padding: "10px 12px",
                        borderRadius: 8,
                        background: "rgba(248,113,113,0.08)",
                        border: "1px solid rgba(248,113,113,0.25)",
                        fontSize: 12,
                        color: "#fecaca",
                        lineHeight: 1.5,
                    }}>
                        {rebuildBlockedReason}
                    </div>
                )}

                {!ingesting && failureRecords.length > 0 && (
                    <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                        <button onClick={() => retryFailures("embedding")} style={{ ...btnStyle, background: "var(--primary)", color: "var(--primary-contrast)", width: "100%" }}>
                            Retry Embedding Failures
                        </button>
                        <button onClick={() => retryFailures("extraction")} style={{ ...btnStyle, background: "var(--status-progress-bg)", color: "var(--primary-contrast)", width: "100%" }}>
                            Retry Extraction Failures
                        </button>
                        <button onClick={() => retryFailures("all")} style={{ ...btnStyle, background: "var(--background-tertiary)", color: "var(--text-primary)", width: "100%" }}>
                            Retry All Failures
                        </button>
                        {collapsedCoverageGapFailures.length > 0 && (
                            <button
                                onClick={() => void rescueCollapsedFailures(collapsedCoverageGapFailures)}
                                disabled={isRescuingCollapsedFailures}
                                style={{
                                    ...btnStyle,
                                    background: "var(--status-warning-soft-bg)",
                                    color: "var(--status-progress-fg)",
                                    width: "100%",
                                    opacity: isRescuingCollapsedFailures ? 0.6 : 1,
                                    cursor: isRescuingCollapsedFailures ? "not-allowed" : "pointer",
                                }}
                            >
                                {isRescuingCollapsedFailures
                                    ? "Recovering Blocked Chunks..."
                                    : `Recover ${collapsedCoverageGapFailures.length} Collapsed Blocked Chunk(s) For Editing`}
                            </button>
                        )}
                    </div>
                )}

                {(hasPendingWorldSettingChange || retryNotice || collapsedCoverageGapFailures.length > 0) && !ingesting && (
                    <div style={{
                        marginTop: 10,
                        padding: "10px 12px",
                        borderRadius: 8,
                        background: "rgba(251,191,36,0.08)",
                        border: "1px solid rgba(251,191,36,0.25)",
                        fontSize: 12,
                        color: "#fcd34d",
                        lineHeight: 1.5,
                    }}>
                        {hasPendingWorldSettingChange && (
                            <div>
                                Retry buttons only fix failures in the currently locked ingest. Use the rebuild actions above to intentionally apply new chunk settings or a new embedding model.
                            </div>
                        )}
                        <div>
                            Retry Extraction Failures and Retry All Failures skip chunks that are already in the Safety Review queue.
                        </div>
                        {retryNotice && (
                            <div>{retryNotice}</div>
                        )}
                        {collapsedCoverageGapFailures.length > 0 && (
                            <div>
                                The recover button above converts the current collapsed `coverage_gap` extraction failures into editable safety-review items for this world only.
                            </div>
                        )}
                    </div>
                )}

                <EntityResolutionPanel
                    worldId={worldId}
                    canResolve={canResolveEntities}
                    allComplete={allComplete}
                    isIngesting={ingesting}
                />

                {/* Resumable checkpoint info */}
                {showResume && (
                    <div style={{
                        marginTop: 12, padding: "10px 12px", background: "var(--status-warning-soft-bg)", border: "1px solid var(--status-warning-soft-border)",
                        borderRadius: 8, fontSize: 13, color: "var(--status-progress-fg)",
                    }}>
                        Resumable: {checkpoint?.chunk_index ?? 0}/{checkpoint?.chunks_total ?? 0} chunks complete
                    </div>
                )}

                {stageCounters && (
                    <div style={{
                        marginTop: 12,
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        padding: 10,
                        background: "var(--background)",
                        fontSize: 12,
                        color: "var(--text-subtle)",
                        display: "grid",
                        gap: 4,
                    }}>
                        <div><strong style={{ color: "var(--text-primary)" }}>Expected:</strong> {stageCounters.expected_chunks}</div>
                        <div><strong style={{ color: "var(--text-primary)" }}>Extracted:</strong> {stageCounters.extracted_chunks}</div>
                        <div><strong style={{ color: "var(--text-primary)" }}>Embedded:</strong> {stageCounters.embedded_chunks}</div>
                        <div><strong style={{ color: "var(--text-primary)" }}>Failed Records:</strong> {stageCounters.failed_records}</div>
                    </div>
                )}

                {failureRecords.length > 0 && (
                    <div style={{
                        marginTop: 12,
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        maxHeight: 220,
                        overflowY: "auto",
                        background: "var(--background)",
                    }}>
                        {failureRecords.map((failure, idx) => (
                            <div key={`side-${failure.chunk_id}-${failure.stage}-${idx}`} style={{
                                padding: "8px 10px",
                                borderBottom: idx === failureRecords.length - 1 ? "none" : "1px solid var(--border)",
                                fontSize: 12,
                                display: "grid",
                                gap: 3,
                            }}>
                                <div style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                                    {failure.stage.toUpperCase()} • B{failure.book_number}:C{failure.chunk_index}
                                </div>
                                <div style={{ color: "var(--text-subtle)" }}>
                                    {failure.error_type}: {failure.error_message}
                                </div>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                    {safetyReviewByChunkId[failure.chunk_id] && failure.stage === "extraction" && (
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
                )}

                {/* Collapsible Ingestion Settings */}
                <CollapsibleSection title="Ingestion Settings" open={showSettings} onToggle={() => setShowSettings(!showSettings)}>
                    <div style={{
                        marginBottom: 12,
                        padding: "10px 12px",
                        borderRadius: 8,
                        background: "rgba(59,130,246,0.08)",
                        border: "1px solid rgba(59,130,246,0.2)",
                        fontSize: 12,
                        color: "#bfdbfe",
                        lineHeight: 1.5,
                    }}>
                        {savedIngestSettings?.locked_at
                            ? `Locked for this world since ${new Date(savedIngestSettings.locked_at).toLocaleString()}. Changing chunk settings requires a full Rechunk And Re-ingest. Changing only the embedding model uses Re-embed All to rebuild chunk and node vectors without re-extracting.`
                            : "This world has not locked ingest settings yet. The values below will be locked on the first full ingest."}
                    </div>
                    {savedIngestSettings?.locked_at && previousSettingsSummary && (
                        <div style={{
                            marginBottom: 12,
                            padding: "10px 12px",
                            borderRadius: 8,
                            background: "var(--background)",
                            border: "1px solid var(--border)",
                            display: "grid",
                            gap: 4,
                        }}>
                            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.6 }}>
                                Locked Previous Settings
                            </div>
                            <div style={{ fontSize: 13, color: "var(--text-primary)", lineHeight: 1.5 }}>
                                {previousSettingsSummary}
                            </div>
                            {savedIngestSettings.locked_at && (
                                <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                                    Locked on {new Date(savedIngestSettings.locked_at).toLocaleString()}
                                </div>
                            )}
                        </div>
                    )}
                    <div style={{ marginBottom: 12 }}>
                        <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>Chunk Size (chars)</label>
                        <input type="number" value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} style={{ width: "100%" }} />
                    </div>
                    <div style={{ marginBottom: 12 }}>
                        <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>Chunk Overlap (chars)</label>
                        <input type="number" value={chunkOverlap} onChange={(e) => setChunkOverlap(Number(e.target.value))} style={{ width: "100%" }} />
                    </div>
                    <div style={{ marginBottom: 12 }}>
                        <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>World Embedding Model</label>
                        <input value={embeddingModel} onChange={(e) => setEmbeddingModel(e.target.value)} style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }} />
                    </div>
                    <div style={{ marginBottom: 16 }}>
                        <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>Graph Architect Glean Amount (iterations)</label>
                        <input
                            type="number"
                            min="0"
                            max="5"
                            value={gleanAmountDraft}
                            onChange={(e) => setGleanAmountDraft(e.target.value)}
                            onBlur={commitGleanDraft}
                            style={{ width: "100%" }}
                        />
                    </div>
                    <button onClick={saveAgentSettings} style={{ ...btnStyle, background: "var(--primary)", color: "var(--primary-contrast)", width: "100%" }}>
                        Save Graph Architect Settings
                    </button>
                </CollapsibleSection>

                {/* Collapsible Prompt Editor */}
                <CollapsibleSection title="Prompt Editor" open={showPrompts} onToggle={() => setShowPrompts(!showPrompts)}>
                    {[
                        "graph_architect_prompt",
                        "graph_architect_glean_prompt",
                        "entity_resolution_chooser_prompt",
                        "entity_resolution_combiner_prompt",
                    ].map((key) => (
                        <PromptField
                            key={`${key}:${prompts[key]?.source || "default"}:${prompts[key]?.value || ""}`}
                            label={key.replace(/_prompt$/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                            promptKey={key}
                            prompt={prompts[key]}
                            onSave={savePrompt}
                            onReset={resetPrompt}
                        />
                    ))}
                </CollapsibleSection>
            </div>

            {/* Right Panel — Progress */}
            <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
                {showIdlePlaceholder ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)" }}>
                        <Upload size={48} style={{ marginBottom: 16, opacity: 0.3 }} />
                        <p style={{ fontSize: 16 }}>
                            {safetyReviewSummary?.unresolved_reviews
                                ? "This world has safety review items waiting for edits."
                                : hasRetryableFailures
                                ? "This world has retryable ingest failures."
                                : hasAnyIngested
                                    ? "Ingestion complete for this world."
                                    : "Start ingestion to see progress."}
                        </p>
                        {(hasAnyIngested || hasRetryableFailures || Boolean(safetyReviewSummary?.unresolved_reviews)) && (
                            <p style={{ fontSize: 13, marginTop: 6 }}>
                                {safetyReviewSummary?.unresolved_reviews
                                    ? "Use the Safety Review Queue below or the left-panel recover/edit actions to fix blocked chunks."
                                    : "Retry failures or use Re-embed All / Re-ingest With Previous Settings / Rechunk And Re-ingest from the left panel."}
                            </p>
                        )}
                    </div>
                ) : (
                    <>
                        {showProgressSummary && (
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
                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
                                            {progressHeaderLabel}
                                        </div>
                                        <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4, lineHeight: 1.45 }}>
                                            {progressSecondaryLabel
                                                || (ingesting && !hasProgress
                                                    ? "Preparing stable progress summary for this run."
                                                    : (progressSummary.isReembedAll
                                                        ? "Rebuilding stored vectors without re-extracting or rebuilding the graph."
                                                        : "Stable world-level progress across extraction and embedding."))}
                                        </div>
                                    </div>
                                    <div style={{ textAlign: "right", flexShrink: 0 }}>
                                        <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text-primary)" }}>
                                            {Math.round(progressSummary.overallPercent)}%
                                        </div>
                                        <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 2 }}>
                                            {progressSummary.expectedChunks || "?"} total chunks
                                        </div>
                                    </div>
                                </div>

                                <div>
                                    <div style={{ height: 8, background: "var(--border)", borderRadius: 999, overflow: "hidden" }}>
                                        <div
                                            style={{
                                                height: "100%",
                                                width: `${progressSummary.overallPercent}%`,
                                                background: "linear-gradient(90deg, var(--primary), var(--primary-light))",
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
                                                        background: row.key === "embedded" || row.key === "reembed"
                                                            ? "linear-gradient(90deg, var(--primary), var(--primary-light))"
                                                            : "linear-gradient(90deg, rgba(8,146,208,0.45), rgba(8,146,208,0.82))",
                                                        transition: "width 0.3s ease",
                                                    }}
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {ingesting && reviewCount > 0 && (
                            <div style={{
                                marginBottom: 24,
                                padding: "12px 14px",
                                borderRadius: 10,
                                border: "1px solid rgba(248,113,113,0.25)",
                                background: "rgba(248,113,113,0.08)",
                                color: "#fecaca",
                                lineHeight: 1.5,
                            }}>
                                Safety review available. {safetyReviewSummary?.unresolved_reviews ?? reviewCount} blocked chunk(s) have been queued for repair.
                                Let the current ingest run finish, then edit and test them from the review queue below.
                            </div>
                        )}

                        {!ingesting && safetyReviews.length > 0 && (
                            <SafetyReviewPanel
                                groupedReviews={groupedSafetyReviews}
                                summary={safetyReviewSummary}
                                drafts={reviewDrafts}
                                savingReviewIds={savingReviewIds}
                                testingReviewIds={testingReviewIds}
                                discardingReviewIds={discardingReviewIds}
                                onDraftChange={(reviewId, value) => setReviewDrafts((prev) => ({ ...prev, [reviewId]: value }))}
                                onDraftBlur={saveReviewDraft}
                                onReset={resetReviewDraft}
                                onTest={testReviewDraft}
                                onDiscard={discardReview}
                            />
                        )}

                        {failureRecords.length > 0 && (
                            <div style={{ marginBottom: 24 }}>
                                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Failure Details</div>
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
                                                {safetyReviewByChunkId[failure.chunk_id] && failure.stage === "extraction" && (
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
                <span style={{ padding: "1px 6px", borderRadius: 4, background: "var(--status-info-pill-bg)", color: "var(--status-info-pill-fg)", fontSize: 11, fontFamily: "monospace" }}>
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
        return { label: "Resolved", bg: "rgba(34,197,94,0.16)", fg: "#86efac" };
    }
    if (review.status === "testing") {
        return { label: "Testing", bg: "rgba(59,130,246,0.16)", fg: "#bfdbfe" };
    }
    if (review.status === "draft") {
        return { label: "Draft", bg: "rgba(251,191,36,0.16)", fg: "#fde68a" };
    }
    return { label: "Blocked", bg: "rgba(248,113,113,0.16)", fg: "#fecaca" };
}

function safetyReviewOutcomePresentation(review: SafetyReviewItem): { label: string; color: string } | null {
    if (review.last_test_outcome === "passed") {
        return { label: "Passed extraction and embedding.", color: "#86efac" };
    }
    if (review.last_test_outcome === "still_safety_blocked") {
        return { label: "Still safety blocked.", color: "#fecaca" };
    }
    if (review.last_test_outcome === "transient_failure") {
        return { label: "Latest test hit a transient failure such as rate limiting.", color: "#fde68a" };
    }
    if (review.last_test_outcome === "other_failure") {
        return { label: "Latest test failed for another reason.", color: "#bfdbfe" };
    }
    return null;
}

function SafetyReviewPanel({
    groupedReviews,
    summary,
    drafts,
    savingReviewIds,
    testingReviewIds,
    discardingReviewIds,
    onDraftChange,
    onDraftBlur,
    onReset,
    onTest,
    onDiscard,
}: {
    groupedReviews: Record<string, SafetyReviewItem[]>;
    summary: SafetyReviewSummary | null;
    drafts: Record<string, string>;
    savingReviewIds: Record<string, boolean>;
    testingReviewIds: Record<string, boolean>;
    discardingReviewIds: Record<string, boolean>;
    onDraftChange: (reviewId: string, value: string) => void;
    onDraftBlur: (review: SafetyReviewItem, draftRawText?: string) => Promise<boolean> | boolean | void;
    onReset: (review: SafetyReviewItem) => Promise<void> | void;
    onTest: (review: SafetyReviewItem) => Promise<void> | void;
    onDiscard: (review: SafetyReviewItem) => Promise<void> | void;
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
                {summary?.blocks_rebuild && (
                    <div style={{
                        maxWidth: 360,
                        padding: "8px 10px",
                        borderRadius: 8,
                        background: "rgba(248,113,113,0.08)",
                        border: "1px solid rgba(248,113,113,0.2)",
                        color: "#fecaca",
                        fontSize: 12,
                        lineHeight: 1.45,
                    }}>
                        {summary.blocking_message}
                    </div>
                )}
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
                                const hasActiveOverride = Boolean(review.active_override_raw_text?.trim());
                                const isEditingAwayFromLiveOverride = hasActiveOverride && draftValue !== review.active_override_raw_text;
                                const isSaving = Boolean(savingReviewIds[review.review_id]);
                                const isTesting = Boolean(testingReviewIds[review.review_id]) || review.status === "testing";
                                const isDiscarding = Boolean(discardingReviewIds[review.review_id]);
                                const isBusy = isSaving || isTesting || isDiscarding;

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
                                                background: "rgba(15,23,42,0.22)",
                                                border: "1px solid var(--border)",
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
                                                background: "rgba(251,191,36,0.08)",
                                                border: "1px solid rgba(251,191,36,0.2)",
                                                fontSize: 12,
                                                color: "#fde68a",
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
                                            <button
                                                onClick={() => void onReset(review)}
                                                disabled={isBusy}
                                                style={{
                                                    ...btnStyle,
                                                    background: "var(--background-tertiary)",
                                                    color: "var(--text-primary)",
                                                    opacity: isBusy ? 0.6 : 1,
                                                    cursor: isBusy ? "not-allowed" : "pointer",
                                                }}
                                            >
                                                {isSaving ? "Saving..." : "Reset"}
                                            </button>
                                            <button
                                                onClick={() => void onDiscard(review)}
                                                disabled={isBusy}
                                                style={{
                                                    ...btnStyle,
                                                    background: hasActiveOverride ? "var(--status-error-bg)" : "var(--border)",
                                                    color: hasActiveOverride ? "var(--status-error-fg)" : "var(--text-primary)",
                                                    opacity: isBusy ? 0.6 : 1,
                                                    cursor: isBusy ? "not-allowed" : "pointer",
                                                }}
                                            >
                                                {isDiscarding ? "Discarding..." : "Discard"}
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

function PromptField({ label, promptKey, prompt, onSave, onReset }: {
    label: string;
    promptKey: string;
    prompt?: { value: string; source: string };
    onSave: (key: string, value: string) => void;
    onReset: (key: string) => void;
}) {
    const [value, setValue] = useState(prompt?.value || "");

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{label}</span>
                <span style={{
                    fontSize: 11, padding: "2px 8px", borderRadius: 9999, fontWeight: 500,
                    background: prompt?.source === "custom" ? "var(--primary-soft-strong)" : "var(--status-pending-bg)",
                    color: prompt?.source === "custom" ? "var(--primary-light)" : "var(--status-pending-fg)",
                }}>
                    {prompt?.source || "default"}
                </span>
            </div>
            <textarea
                value={value}
                onChange={(e) => setValue(e.target.value)}
                rows={4}
                style={{ width: "100%", minHeight: 120, resize: "vertical", fontSize: 12 }}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <button onClick={() => onSave(promptKey, value)} style={{ ...btnStyle, background: "var(--primary)", color: "var(--primary-contrast)", flex: 1, fontSize: 12 }}>
                    Save
                </button>
                <button onClick={() => onReset(promptKey)} style={{ ...btnStyle, background: "var(--border)", color: "var(--text-subtle)", flex: 1, fontSize: 12 }}>
                    Reset to Default
                </button>
            </div>
        </div>
    );
}

const btnStyle: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
    padding: "8px 16px", borderRadius: "var(--radius)", border: "none",
    fontSize: 13, fontWeight: 600, cursor: "pointer", transition: "opacity 0.2s",
};
