"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronDown, ChevronUp, Info, Loader2, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import {
    formatPromptSourceLabel,
    WORLD_INGEST_PROMPT_FIELDS,
    type WorldIngestConfigResponse,
    type WorldIngestPromptKey,
    type WorldIngestSettings,
} from "@/lib/world-ingest";

interface WorldResponse {
    world_name?: string;
}

export interface ReingestSetupSubmission {
    ingest_settings: WorldIngestSettings;
    prompt_overrides: Record<WorldIngestPromptKey, string>;
    use_active_chunk_overrides: boolean;
}

export type IngestSetupVariant = "initial_ingest" | "reingest";
export type WorldIngestSetupLayout = "inline" | "modal" | "page";

export interface WorldIngestSetupDraft {
    chunkSize: string;
    chunkOverlap: string;
    embeddingModel: string;
    gleanAmount: string;
    prompts: Record<WorldIngestPromptKey, string>;
    promptSources: Record<WorldIngestPromptKey, string>;
    baselineChunkSize: number;
    baselineChunkOverlap: number;
    hasActiveChunkOverrides: boolean;
    activeChunkOverrideCount: number;
    reuseActiveChunkOverrides: boolean;
}

const EMPTY_PROMPTS: Record<WorldIngestPromptKey, string> = {
    graph_architect_prompt: "",
    graph_architect_glean_prompt: "",
    entity_resolution_chooser_prompt: "",
    entity_resolution_combiner_prompt: "",
};

const DEFAULT_PROMPT_SOURCES: Record<WorldIngestPromptKey, string> = {
    graph_architect_prompt: "default",
    graph_architect_glean_prompt: "default",
    entity_resolution_chooser_prompt: "default",
    entity_resolution_combiner_prompt: "default",
};

export function createWorldIngestSetupDraft(config: WorldIngestConfigResponse): WorldIngestSetupDraft {
    return {
        chunkSize: String(config.ingest_settings.chunk_size_chars),
        chunkOverlap: String(config.ingest_settings.chunk_overlap_chars),
        embeddingModel: config.ingest_settings.embedding_model,
        gleanAmount: String(config.ingest_settings.glean_amount),
        prompts: {
            graph_architect_prompt: config.prompts.graph_architect_prompt?.value ?? "",
            graph_architect_glean_prompt: config.prompts.graph_architect_glean_prompt?.value ?? "",
            entity_resolution_chooser_prompt: config.prompts.entity_resolution_chooser_prompt?.value ?? "",
            entity_resolution_combiner_prompt: config.prompts.entity_resolution_combiner_prompt?.value ?? "",
        },
        promptSources: {
            graph_architect_prompt: config.prompts.graph_architect_prompt?.source ?? "default",
            graph_architect_glean_prompt: config.prompts.graph_architect_glean_prompt?.source ?? "default",
            entity_resolution_chooser_prompt: config.prompts.entity_resolution_chooser_prompt?.source ?? "default",
            entity_resolution_combiner_prompt: config.prompts.entity_resolution_combiner_prompt?.source ?? "default",
        },
        baselineChunkSize: config.ingest_settings.chunk_size_chars,
        baselineChunkOverlap: config.ingest_settings.chunk_overlap_chars,
        hasActiveChunkOverrides: Boolean(config.has_active_chunk_overrides),
        activeChunkOverrideCount: Number(config.active_chunk_override_count ?? 0),
        reuseActiveChunkOverrides: Boolean(config.has_active_chunk_overrides),
    };
}

export function buildIngestSetupSubmission(draft: WorldIngestSetupDraft): ReingestSetupSubmission {
    const normalizedChunkSize = Math.max(1, Number.parseInt(draft.chunkSize || "0", 10) || 4000);
    const normalizedChunkOverlap = Math.max(0, Number.parseInt(draft.chunkOverlap || "0", 10) || 150);
    const normalizedGleanAmount = Math.max(0, Number.parseInt(draft.gleanAmount || "0", 10) || 0);
    const sameChunkMap = normalizedChunkSize === draft.baselineChunkSize && normalizedChunkOverlap === draft.baselineChunkOverlap;
    return {
        ingest_settings: {
            chunk_size_chars: normalizedChunkSize,
            chunk_overlap_chars: normalizedChunkOverlap,
            embedding_model: draft.embeddingModel.trim(),
            glean_amount: normalizedGleanAmount,
        },
        prompt_overrides: draft.prompts,
        use_active_chunk_overrides: draft.hasActiveChunkOverrides && draft.reuseActiveChunkOverrides && sameChunkMap,
    };
}

interface WorldIngestSetupFormProps {
    draft: WorldIngestSetupDraft;
    layout?: WorldIngestSetupLayout;
    variant?: IngestSetupVariant;
    worldName?: string;
    submitting?: boolean;
    submitLabel?: string;
    submitDisabled?: boolean;
    submitDisabledReason?: string | null;
    onDraftChange: (next: WorldIngestSetupDraft) => void;
    onSubmit: () => void;
    onClose?: () => void;
    cancelHref?: string;
}

interface WorldReingestSetupContentProps {
    worldId: string;
    mode?: "page" | "modal";
    onClose?: () => void;
    onSubmit?: (submission: ReingestSetupSubmission) => Promise<void>;
}

export function WorldIngestSetupForm({
    draft,
    layout = "page",
    variant = "reingest",
    worldName = "this world",
    submitting = false,
    submitLabel,
    submitDisabled = false,
    submitDisabledReason = null,
    onDraftChange,
    onSubmit,
    onClose,
    cancelHref,
}: WorldIngestSetupFormProps) {
    const [openPromptSections, setOpenPromptSections] = useState<Record<WorldIngestPromptKey, boolean>>({
        graph_architect_prompt: false,
        graph_architect_glean_prompt: false,
        entity_resolution_chooser_prompt: false,
        entity_resolution_combiner_prompt: false,
    });

    const normalizedChunkSize = useMemo(
        () => Math.max(1, Number.parseInt(draft.chunkSize || "0", 10) || 4000),
        [draft.chunkSize]
    );
    const normalizedChunkOverlap = useMemo(
        () => Math.max(0, Number.parseInt(draft.chunkOverlap || "0", 10) || 150),
        [draft.chunkOverlap]
    );
    const sameChunkMap = normalizedChunkSize === draft.baselineChunkSize && normalizedChunkOverlap === draft.baselineChunkOverlap;
    const reuseToggleDisabled = draft.hasActiveChunkOverrides && !sameChunkMap;
    const reuseToggleReason = "Repaired chunk overrides can only be reused when chunk size and overlap stay the same.";
    const isModal = layout === "modal";
    const isInline = layout === "inline";
    const isInitialIngest = variant === "initial_ingest";
    const showReuseToggle = variant === "reingest" && draft.hasActiveChunkOverrides;

    useEffect(() => {
        if (reuseToggleDisabled && draft.reuseActiveChunkOverrides) {
            onDraftChange({ ...draft, reuseActiveChunkOverrides: false });
        }
    }, [draft, onDraftChange, reuseToggleDisabled]);

    const updateDraft = (partial: Partial<WorldIngestSetupDraft>) => {
        onDraftChange({ ...draft, ...partial });
    };

    const handlePromptChange = (key: WorldIngestPromptKey, value: string) => {
        updateDraft({
            prompts: {
                ...draft.prompts,
                [key]: value,
            },
        });
    };

    const togglePromptSection = (key: WorldIngestPromptKey) => {
        setOpenPromptSections((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const title = isInitialIngest ? "Ingestion Setup" : "Re-ingest Setup";
    const description = isInitialIngest
        ? "Choose the settings and prompts this world will use for its first ingest."
        : `Edit this world's saved ingest settings and prompts, then begin a full rebuild for ${worldName}.`;
    const promptDescription = isInitialIngest
        ? "These values will be saved for this world when you start ingestion."
        : "These values become this world's saved prompt overrides when you begin Re-ingesting.";
    const resolvedSubmitLabel = submitLabel ?? (isInitialIngest ? "Start Ingestion" : "Begin Re-ingesting");
    const headerTitleSize = isInline ? 18 : isModal ? 24 : 28;
    const headerDescriptionMaxWidth = isInline ? "100%" : 780;
    const wrapperStyle = isInline
        ? {
            border: "1px solid var(--border)",
            borderRadius: 16,
            background: "var(--background)",
            padding: 16,
            display: "grid",
            gap: 16,
            minWidth: 0,
        }
        : {
            height: isModal ? "auto" : "100%",
            overflowY: "auto" as const,
            padding: isModal ? 20 : 24,
        };
    const innerStyle = isInline
        ? { display: "grid", gap: 16 }
        : { maxWidth: isModal ? "100%" : 1040, margin: "0 auto", display: "grid", gap: 20 };
    const sectionGridStyle = isInline
        ? { display: "grid", gap: 16 }
        : {
            display: "grid",
            gap: 20,
            gridTemplateColumns: isModal ? "minmax(0, 320px) minmax(0, 1fr)" : "minmax(0, 360px) minmax(0, 1fr)",
        };
    const actionRowStyle = isInline
        ? { display: "grid", gap: 8 }
        : { display: "flex", justifyContent: "flex-end", gap: 12, flexWrap: "wrap" as const };

    return (
        <div style={wrapperStyle}>
            <div style={innerStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
                    <div>
                        <div style={{ fontSize: headerTitleSize, fontWeight: 800, color: "var(--text-primary)" }}>{title}</div>
                        <div style={{ fontSize: 13, color: "var(--text-subtle)", marginTop: 6, lineHeight: 1.5, maxWidth: headerDescriptionMaxWidth }}>
                            {description}
                        </div>
                    </div>
                    {!isInline && (isModal ? (
                        onClose && (
                            <button
                                onClick={onClose}
                                aria-label={isInitialIngest ? "Close ingestion setup" : "Close re-ingest setup"}
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
                                <X size={16} />
                            </button>
                        )
                    ) : (
                        cancelHref && (
                            <Link
                                href={cancelHref}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    gap: 8,
                                    padding: "9px 14px",
                                    borderRadius: 10,
                                    border: "1px solid var(--border)",
                                    background: "var(--background)",
                                    color: "var(--text-primary)",
                                    fontSize: 13,
                                    fontWeight: 600,
                                }}
                            >
                                <ArrowLeft size={14} />
                                Back to Ingest
                            </Link>
                        )
                    ))}
                </div>

                <div style={sectionGridStyle}>
                    <div style={{
                        border: "1px solid var(--border)",
                        borderRadius: 16,
                        background: "var(--background)",
                        padding: isInline ? 16 : 18,
                        display: "grid",
                        gap: 14,
                        alignSelf: "start",
                    }}>
                        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Ingestion Settings</div>
                        <NumberField label="Chunk Size (chars)" value={draft.chunkSize} onChange={(next) => updateDraft({ chunkSize: next })} min={1} />
                        <NumberField label="Chunk Overlap (chars)" value={draft.chunkOverlap} onChange={(next) => updateDraft({ chunkOverlap: next })} min={0} />
                        <TextField label="World Embedding Model" value={draft.embeddingModel} onChange={(next) => updateDraft({ embeddingModel: next })} mono />
                        <NumberField label="Graph Architect Glean Amount" value={draft.gleanAmount} onChange={(next) => updateDraft({ gleanAmount: next })} min={0} />

                        {showReuseToggle && (
                            <label style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                padding: "12px 14px",
                                borderRadius: 12,
                                border: "1px solid var(--border)",
                                background: "var(--background-secondary)",
                                opacity: reuseToggleDisabled ? 0.6 : 1,
                                cursor: reuseToggleDisabled ? "not-allowed" : "pointer",
                            }}>
                                <input
                                    type="checkbox"
                                    checked={draft.reuseActiveChunkOverrides}
                                    disabled={reuseToggleDisabled}
                                    onChange={(e) => updateDraft({ reuseActiveChunkOverrides: e.target.checked })}
                                />
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                                        Reuse {draft.activeChunkOverrideCount} repaired chunk override{draft.activeChunkOverrideCount === 1 ? "" : "s"}
                                    </div>
                                    <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4, lineHeight: 1.45 }}>
                                        Keep the current repaired chunk text during Re-ingest when the chunk map stays the same.
                                    </div>
                                </div>
                                {reuseToggleDisabled && <InlineInfo title={reuseToggleReason} />}
                            </label>
                        )}
                    </div>

                    <div style={{
                        border: "1px solid var(--border)",
                        borderRadius: 16,
                        background: "var(--background)",
                        padding: isInline ? 16 : 18,
                        display: "grid",
                        gap: 16,
                    }}>
                        <div>
                            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Prompt Overrides</div>
                            <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 6, lineHeight: 1.5 }}>
                                {promptDescription}
                            </div>
                        </div>

                        {WORLD_INGEST_PROMPT_FIELDS.map(({ key, label }) => {
                            const isOpen = openPromptSections[key];
                            return (
                                <div
                                    key={key}
                                    style={{
                                        border: "1px solid var(--border)",
                                        borderRadius: 12,
                                        background: "var(--background)",
                                        overflow: "hidden",
                                    }}
                                >
                                    <button
                                        onClick={() => togglePromptSection(key)}
                                        style={{
                                            width: "100%",
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "space-between",
                                            gap: 12,
                                            padding: "12px 14px",
                                            background: "transparent",
                                            border: "none",
                                            color: "var(--text-primary)",
                                            cursor: "pointer",
                                            textAlign: "left",
                                        }}
                                    >
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{label}</div>
                                            <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 4 }}>
                                                {isOpen ? "Click to collapse this prompt." : "Click to expand and edit this prompt."}
                                            </div>
                                        </div>
                                        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                                            <span style={{
                                                fontSize: 11,
                                                padding: "3px 8px",
                                                borderRadius: 9999,
                                                fontWeight: 600,
                                                textTransform: "lowercase",
                                                background: draft.promptSources[key] === "world" || draft.promptSources[key] === "global"
                                                    ? "var(--primary)"
                                                    : "var(--status-pending-bg)",
                                                color: draft.promptSources[key] === "world" || draft.promptSources[key] === "global"
                                                    ? "var(--primary-contrast)"
                                                    : "var(--status-pending-fg)",
                                            }}>
                                                {formatPromptSourceLabel(draft.promptSources[key])}
                                            </span>
                                            {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                                        </div>
                                    </button>
                                    {isOpen && (
                                        <div style={{ padding: "0 14px 14px", borderTop: "1px solid var(--border)" }}>
                                            <textarea
                                                value={draft.prompts[key]}
                                                onChange={(e) => handlePromptChange(key, e.target.value)}
                                                rows={6}
                                                style={{
                                                    width: "100%",
                                                    minHeight: 150,
                                                    resize: "vertical",
                                                    padding: "10px 12px",
                                                    borderRadius: 10,
                                                    border: "1px solid var(--border)",
                                                    background: "var(--background-secondary)",
                                                    color: "var(--text-primary)",
                                                    fontSize: 12,
                                                    lineHeight: 1.5,
                                                    marginTop: 14,
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                <div style={actionRowStyle}>
                    {!isInline && (isModal ? (
                        onClose && (
                            <button
                                onClick={onClose}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    padding: "10px 16px",
                                    borderRadius: 10,
                                    border: "1px solid var(--border)",
                                    background: "var(--background)",
                                    color: "var(--text-primary)",
                                    fontSize: 13,
                                    fontWeight: 600,
                                    cursor: "pointer",
                                }}
                            >
                                Cancel
                            </button>
                        )
                    ) : (
                        cancelHref && (
                            <Link
                                href={cancelHref}
                                style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    padding: "10px 16px",
                                    borderRadius: 10,
                                    border: "1px solid var(--border)",
                                    background: "var(--background)",
                                    color: "var(--text-primary)",
                                    fontSize: 13,
                                    fontWeight: 600,
                                }}
                            >
                                Cancel
                            </Link>
                        )
                    ))}
                    <button
                        onClick={onSubmit}
                        disabled={submitting || submitDisabled}
                        title={submitDisabled && submitDisabledReason ? submitDisabledReason : undefined}
                        style={{
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: 8,
                            padding: "10px 18px",
                            borderRadius: 10,
                            border: "none",
                            background: "var(--primary)",
                            color: "var(--primary-contrast)",
                            fontSize: 13,
                            fontWeight: 700,
                            opacity: submitting || submitDisabled ? 0.7 : 1,
                            cursor: submitting || submitDisabled ? "not-allowed" : "pointer",
                            width: isInline ? "100%" : undefined,
                        }}
                    >
                        {submitting && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                        {resolvedSubmitLabel}
                    </button>
                    {isInline && submitDisabled && submitDisabledReason && (
                        <div style={{ fontSize: 12, color: "var(--text-subtle)", lineHeight: 1.45 }}>
                            {submitDisabledReason}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export default function WorldReingestSetupContent({
    worldId,
    mode = "page",
    onClose,
    onSubmit,
}: WorldReingestSetupContentProps) {
    const [worldName, setWorldName] = useState("World");
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [draft, setDraft] = useState<WorldIngestSetupDraft>({
        chunkSize: "4000",
        chunkOverlap: "150",
        embeddingModel: "gemini-embedding-2-preview",
        gleanAmount: "1",
        prompts: { ...EMPTY_PROMPTS },
        promptSources: { ...DEFAULT_PROMPT_SOURCES },
        baselineChunkSize: 4000,
        baselineChunkOverlap: 150,
        hasActiveChunkOverrides: false,
        activeChunkOverrideCount: 0,
        reuseActiveChunkOverrides: false,
    });

    useEffect(() => {
        const load = async () => {
            setLoading(true);
            try {
                const [world, config] = await Promise.all([
                    apiFetch<WorldResponse>(`/worlds/${worldId}`),
                    apiFetch<WorldIngestConfigResponse>(`/worlds/${worldId}/ingest/config`),
                ]);
                setWorldName(world.world_name || "World");
                setDraft(createWorldIngestSetupDraft(config));
            } catch (err: unknown) {
                alert((err as Error).message);
            } finally {
                setLoading(false);
            }
        };
        void load();
    }, [worldId]);

    const beginReingesting = async () => {
        const submission = buildIngestSetupSubmission(draft);
        setSubmitting(true);
        try {
            if (onSubmit) {
                await onSubmit(submission);
                return;
            }
            await apiFetch(`/worlds/${worldId}/ingest/start`, {
                method: "POST",
                body: JSON.stringify({
                    resume: false,
                    operation: "rechunk_reingest",
                    ...submission,
                }),
            });
            window.location.href = `/worlds/${worldId}/ingest`;
        } catch (err: unknown) {
            alert((err as Error).message);
        } finally {
            setSubmitting(false);
        }
    };

    if (loading) {
        return (
            <div style={{ padding: mode === "modal" ? 20 : 24, display: "grid", placeItems: "center", minHeight: mode === "modal" ? 320 : "100%" }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 10, color: "var(--text-subtle)" }}>
                    <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
                    Loading ingest settings...
                </div>
            </div>
        );
    }

    return (
        <WorldIngestSetupForm
            draft={draft}
            layout={mode}
            variant="reingest"
            worldName={worldName}
            submitting={submitting}
            onDraftChange={setDraft}
            onSubmit={() => void beginReingesting()}
            onClose={onClose}
            cancelHref={mode === "page" ? `/worlds/${worldId}/ingest` : undefined}
        />
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
                cursor: "help",
                flexShrink: 0,
            }}
        >
            <Info size={14} />
        </span>
    );
}

function NumberField({
    label,
    value,
    onChange,
    min,
}: {
    label: string;
    value: string;
    onChange: (next: string) => void;
    min: number;
}) {
    return (
        <div style={{ display: "grid", gap: 6 }}>
            <label style={{ fontSize: 12, color: "var(--text-subtle)" }}>{label}</label>
            <input
                type="number"
                min={min}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                style={{
                    width: "100%",
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: "1px solid var(--border)",
                    background: "var(--background-secondary)",
                    color: "var(--text-primary)",
                    fontSize: 13,
                }}
            />
        </div>
    );
}

function TextField({
    label,
    value,
    onChange,
    mono = false,
}: {
    label: string;
    value: string;
    onChange: (next: string) => void;
    mono?: boolean;
}) {
    return (
        <div style={{ display: "grid", gap: 6 }}>
            <label style={{ fontSize: 12, color: "var(--text-subtle)" }}>{label}</label>
            <input
                value={value}
                onChange={(e) => onChange(e.target.value)}
                style={{
                    width: "100%",
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: "1px solid var(--border)",
                    background: "var(--background-secondary)",
                    color: "var(--text-primary)",
                    fontSize: 13,
                    fontFamily: mono ? "monospace" : undefined,
                }}
            />
        </div>
    );
}
