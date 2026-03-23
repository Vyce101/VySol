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

interface WorldReingestSetupContentProps {
    worldId: string;
    mode?: "page" | "modal";
    onClose?: () => void;
    onSubmit?: (submission: ReingestSetupSubmission) => Promise<void>;
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
    const [chunkSize, setChunkSize] = useState("4000");
    const [chunkOverlap, setChunkOverlap] = useState("150");
    const [embeddingModel, setEmbeddingModel] = useState("gemini-embedding-2-preview");
    const [gleanAmount, setGleanAmount] = useState("1");
    const [prompts, setPrompts] = useState<Record<WorldIngestPromptKey, string>>({
        graph_architect_prompt: "",
        graph_architect_glean_prompt: "",
        entity_resolution_chooser_prompt: "",
        entity_resolution_combiner_prompt: "",
    });
    const [promptSources, setPromptSources] = useState<Record<WorldIngestPromptKey, string>>({
        graph_architect_prompt: "default",
        graph_architect_glean_prompt: "default",
        entity_resolution_chooser_prompt: "default",
        entity_resolution_combiner_prompt: "default",
    });
    const [baselineChunkSize, setBaselineChunkSize] = useState(4000);
    const [baselineChunkOverlap, setBaselineChunkOverlap] = useState(150);
    const [hasActiveChunkOverrides, setHasActiveChunkOverrides] = useState(false);
    const [activeChunkOverrideCount, setActiveChunkOverrideCount] = useState(0);
    const [reuseActiveChunkOverrides, setReuseActiveChunkOverrides] = useState(true);
    const [openPromptSections, setOpenPromptSections] = useState<Record<WorldIngestPromptKey, boolean>>({
        graph_architect_prompt: false,
        graph_architect_glean_prompt: false,
        entity_resolution_chooser_prompt: false,
        entity_resolution_combiner_prompt: false,
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
                setChunkSize(String(config.ingest_settings.chunk_size_chars));
                setChunkOverlap(String(config.ingest_settings.chunk_overlap_chars));
                setEmbeddingModel(config.ingest_settings.embedding_model);
                setGleanAmount(String(config.ingest_settings.glean_amount));
                setBaselineChunkSize(config.ingest_settings.chunk_size_chars);
                setBaselineChunkOverlap(config.ingest_settings.chunk_overlap_chars);
                setHasActiveChunkOverrides(Boolean(config.has_active_chunk_overrides));
                setActiveChunkOverrideCount(Number(config.active_chunk_override_count ?? 0));
                setReuseActiveChunkOverrides(Boolean(config.has_active_chunk_overrides));
                setPrompts({
                    graph_architect_prompt: config.prompts.graph_architect_prompt?.value ?? "",
                    graph_architect_glean_prompt: config.prompts.graph_architect_glean_prompt?.value ?? "",
                    entity_resolution_chooser_prompt: config.prompts.entity_resolution_chooser_prompt?.value ?? "",
                    entity_resolution_combiner_prompt: config.prompts.entity_resolution_combiner_prompt?.value ?? "",
                });
                setPromptSources({
                    graph_architect_prompt: config.prompts.graph_architect_prompt?.source ?? "default",
                    graph_architect_glean_prompt: config.prompts.graph_architect_glean_prompt?.source ?? "default",
                    entity_resolution_chooser_prompt: config.prompts.entity_resolution_chooser_prompt?.source ?? "default",
                    entity_resolution_combiner_prompt: config.prompts.entity_resolution_combiner_prompt?.source ?? "default",
                });
            } catch (err: unknown) {
                alert((err as Error).message);
            } finally {
                setLoading(false);
            }
        };
        void load();
    }, [worldId]);

    const normalizedChunkSize = useMemo(() => Math.max(1, Number.parseInt(chunkSize || "0", 10) || 4000), [chunkSize]);
    const normalizedChunkOverlap = useMemo(() => Math.max(0, Number.parseInt(chunkOverlap || "0", 10) || 150), [chunkOverlap]);
    const normalizedGleanAmount = useMemo(() => Math.max(0, Number.parseInt(gleanAmount || "0", 10) || 0), [gleanAmount]);
    const sameChunkMap = normalizedChunkSize === baselineChunkSize && normalizedChunkOverlap === baselineChunkOverlap;
    const reuseToggleDisabled = hasActiveChunkOverrides && !sameChunkMap;
    const reuseToggleReason = "Repaired chunk overrides can only be reused when chunk size and overlap stay the same.";
    const isModal = mode === "modal";

    useEffect(() => {
        if (reuseToggleDisabled) {
            setReuseActiveChunkOverrides(false);
        }
    }, [reuseToggleDisabled]);

    const handlePromptChange = (key: WorldIngestPromptKey, value: string) => {
        setPrompts((prev) => ({ ...prev, [key]: value }));
    };

    const togglePromptSection = (key: WorldIngestPromptKey) => {
        setOpenPromptSections((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const beginReingesting = async () => {
        const submission: ReingestSetupSubmission = {
            ingest_settings: {
                chunk_size_chars: normalizedChunkSize,
                chunk_overlap_chars: normalizedChunkOverlap,
                embedding_model: embeddingModel.trim(),
                glean_amount: normalizedGleanAmount,
            },
            prompt_overrides: prompts,
            use_active_chunk_overrides: hasActiveChunkOverrides && reuseActiveChunkOverrides && !reuseToggleDisabled,
        };

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
            <div style={{ padding: isModal ? 20 : 24, display: "grid", placeItems: "center", minHeight: isModal ? 320 : "100%" }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 10, color: "var(--text-subtle)" }}>
                    <Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} />
                    Loading re-ingest settings...
                </div>
            </div>
        );
    }

    return (
        <div style={{ height: isModal ? "auto" : "100%", overflowY: "auto", padding: isModal ? 20 : 24 }}>
            <div style={{ maxWidth: isModal ? "100%" : 1040, margin: "0 auto", display: "grid", gap: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
                    <div>
                        <div style={{ fontSize: isModal ? 24 : 28, fontWeight: 800, color: "var(--text-primary)" }}>Re-ingest Setup</div>
                        <div style={{ fontSize: 13, color: "var(--text-subtle)", marginTop: 6, lineHeight: 1.5, maxWidth: 780 }}>
                            Edit this world&apos;s saved ingest settings and prompts, then begin a full rebuild for {worldName}.
                        </div>
                    </div>
                    {isModal ? (
                        onClose && (
                            <button
                                onClick={onClose}
                                aria-label="Close re-ingest setup"
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
                        <Link
                            href={`/worlds/${worldId}/ingest`}
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
                    )}
                </div>

                <div style={{
                    display: "grid",
                    gap: 20,
                    gridTemplateColumns: isModal ? "minmax(0, 320px) minmax(0, 1fr)" : "minmax(0, 360px) minmax(0, 1fr)",
                }}>
                    <div style={{
                        border: "1px solid var(--border)",
                        borderRadius: 16,
                        background: "var(--background)",
                        padding: 18,
                        display: "grid",
                        gap: 14,
                        alignSelf: "start",
                    }}>
                        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Ingestion Settings</div>
                        <NumberField label="Chunk Size (chars)" value={chunkSize} onChange={setChunkSize} min={1} />
                        <NumberField label="Chunk Overlap (chars)" value={chunkOverlap} onChange={setChunkOverlap} min={0} />
                        <TextField label="World Embedding Model" value={embeddingModel} onChange={setEmbeddingModel} mono />
                        <NumberField label="Graph Architect Glean Amount" value={gleanAmount} onChange={setGleanAmount} min={0} />

                        {hasActiveChunkOverrides && (
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
                                    checked={reuseActiveChunkOverrides}
                                    disabled={reuseToggleDisabled}
                                    onChange={(e) => setReuseActiveChunkOverrides(e.target.checked)}
                                />
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                                        Reuse {activeChunkOverrideCount} repaired chunk override{activeChunkOverrideCount === 1 ? "" : "s"}
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
                        padding: 18,
                        display: "grid",
                        gap: 16,
                    }}>
                        <div>
                            <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Prompt Overrides</div>
                            <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 6, lineHeight: 1.5 }}>
                                These values become this world&apos;s saved prompt overrides when you begin Re-ingesting.
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
                                                background: promptSources[key] === "world" || promptSources[key] === "global"
                                                    ? "var(--primary)"
                                                    : "var(--status-pending-bg)",
                                                color: promptSources[key] === "world" || promptSources[key] === "global"
                                                    ? "var(--primary-contrast)"
                                                    : "var(--status-pending-fg)",
                                            }}>
                                                {formatPromptSourceLabel(promptSources[key])}
                                            </span>
                                            {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                                        </div>
                                    </button>
                                    {isOpen && (
                                        <div style={{ padding: "0 14px 14px", borderTop: "1px solid var(--border)" }}>
                                            <textarea
                                                value={prompts[key]}
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

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, flexWrap: "wrap" }}>
                    {isModal ? (
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
                        <Link
                            href={`/worlds/${worldId}/ingest`}
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
                    )}
                    <button
                        onClick={() => void beginReingesting()}
                        disabled={submitting}
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
                            opacity: submitting ? 0.7 : 1,
                            cursor: submitting ? "not-allowed" : "pointer",
                        }}
                    >
                        {submitting && <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} />}
                        Begin Re-ingesting
                    </button>
                </div>
            </div>
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
