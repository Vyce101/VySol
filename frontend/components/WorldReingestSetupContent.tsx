"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, ChevronDown, ChevronUp, Info, Loader2, X } from "lucide-react";

import { apiFetch } from "@/lib/api";
import {
    formatProviderLabel,
    getFirstCatalogModelValue,
    getParamUiShape,
    getProviderModelPlaceholder,
    getProviderModels,
    listCatalogProviders,
    providerUsesCustomModelField,
    sanitizeSlotParamsForModel,
    type AICatalog,
    type ParamDefinition,
    type SlotConfig,
} from "@/lib/provider-models";
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
    embeddingProvider: string;
    embeddingModel: string;
    embeddingParams: Record<string, unknown>;
    aiCatalog: AICatalog;
    gleanAmount: string;
    prompts: Record<WorldIngestPromptKey, string>;
    promptSources: Record<WorldIngestPromptKey, string>;
    baselineChunkSize: number;
    baselineChunkOverlap: number;
    hasActiveChunkOverrides: boolean;
    activeChunkOverrideCount: number;
    reuseActiveChunkOverrides: boolean;
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

const EMPTY_CATALOG: AICatalog = {
    litellm_version: "",
    slots: {
        flash: { task: "chat" },
        chat: { task: "chat" },
        entity_chooser: { task: "chat" },
        entity_combiner: { task: "chat" },
        embedding: { task: "embedding" },
    },
    providers: {},
    common_params: { chat: [], embedding: [] },
};

const panelStyle = {
    border: "1px solid var(--border)",
    borderRadius: 16,
    background: "var(--background)",
    padding: 18,
    display: "grid",
    gap: 14,
} as const;

const inputStyle = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: "1px solid var(--border)",
    background: "var(--background-secondary)",
    color: "var(--text-primary)",
    fontSize: 13,
} as const;

export function createWorldIngestSetupDraft(config: WorldIngestConfigResponse): WorldIngestSetupDraft {
    return {
        chunkSize: String(config.ingest_settings.chunk_size_chars),
        chunkOverlap: String(config.ingest_settings.chunk_overlap_chars),
        embeddingProvider: config.ingest_settings.embedding_provider,
        embeddingModel: config.ingest_settings.embedding_model,
        embeddingParams: { ...(config.ingest_settings.embedding_params ?? {}) },
        aiCatalog: config.ai_catalog ?? EMPTY_CATALOG,
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
    const chunkSize = Math.max(1, Number.parseInt(draft.chunkSize || "0", 10) || 4000);
    const chunkOverlap = Math.max(0, Number.parseInt(draft.chunkOverlap || "0", 10) || 150);
    const gleanAmount = Math.max(0, Number.parseInt(draft.gleanAmount || "0", 10) || 0);
    const sameChunkMap = chunkSize === draft.baselineChunkSize && chunkOverlap === draft.baselineChunkOverlap;
    return {
        ingest_settings: {
            chunk_size_chars: chunkSize,
            chunk_overlap_chars: chunkOverlap,
            embedding_provider: draft.embeddingProvider,
            embedding_openai_compatible_provider: draft.embeddingProvider,
            embedding_model: draft.embeddingModel.trim(),
            embedding_params: { ...draft.embeddingParams },
            glean_amount: gleanAmount,
        },
        prompt_overrides: draft.prompts,
        use_active_chunk_overrides: draft.hasActiveChunkOverrides && draft.reuseActiveChunkOverrides && sameChunkMap,
    };
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
    const isModal = layout === "modal";
    const isInline = layout === "inline";
    const isInitialIngest = variant === "initial_ingest";
    const chunkSize = Math.max(1, Number.parseInt(draft.chunkSize || "0", 10) || 4000);
    const chunkOverlap = Math.max(0, Number.parseInt(draft.chunkOverlap || "0", 10) || 150);
    const sameChunkMap = chunkSize === draft.baselineChunkSize && chunkOverlap === draft.baselineChunkOverlap;
    const reuseToggleDisabled = draft.hasActiveChunkOverrides && !sameChunkMap;
    const embeddingModels = getProviderModels(draft.aiCatalog, draft.embeddingProvider, "embedding");
    const customModelProvider = providerUsesCustomModelField(draft.aiCatalog, draft.embeddingProvider);
    const providerOptions = listCatalogProviders(draft.aiCatalog, "embedding").map((provider) => ({
        value: provider.id,
        label: provider.display_name,
    }));
    const modelPlaceholder = getProviderModelPlaceholder(draft.aiCatalog, draft.embeddingProvider, "embedding");
    const paramShape = getParamUiShape(draft.aiCatalog, draft.embeddingProvider, "embedding", draft.embeddingModel);
    const knownParamNames = new Set([...paramShape.typed, ...paramShape.providerSpecific].map((item) => item.name));
    const extraParams = Object.fromEntries(Object.entries(draft.embeddingParams).filter(([key]) => !knownParamNames.has(key)));
    const providerUnavailable = !customModelProvider && embeddingModels.length === 0;

    useEffect(() => {
        if (reuseToggleDisabled && draft.reuseActiveChunkOverrides) {
            onDraftChange({ ...draft, reuseActiveChunkOverrides: false });
        }
    }, [draft, onDraftChange, reuseToggleDisabled]);

    const updateDraft = (partial: Partial<WorldIngestSetupDraft>) => onDraftChange({ ...draft, ...partial });
    const updateParams = (updater: (current: Record<string, unknown>) => Record<string, unknown>) => updateDraft({ embeddingParams: updater(draft.embeddingParams) });

    const setProvider = (provider: string) => {
        const model = getProviderModelPlaceholder(draft.aiCatalog, provider, "embedding")
            || getFirstCatalogModelValue(draft.aiCatalog, provider, "embedding")
            || draft.embeddingModel;
        const params = sanitizeSlotParamsForModel(
            draft.aiCatalog,
            { provider: draft.embeddingProvider, model: draft.embeddingModel, task: "embedding", params: draft.embeddingParams } as SlotConfig,
            provider,
            model,
            "embedding",
        );
        updateDraft({ embeddingProvider: provider, embeddingModel: model, embeddingParams: params });
    };

    const setModel = (model: string) => {
        const params = sanitizeSlotParamsForModel(
            draft.aiCatalog,
            { provider: draft.embeddingProvider, model: draft.embeddingModel, task: "embedding", params: draft.embeddingParams } as SlotConfig,
            draft.embeddingProvider,
            model,
            "embedding",
        );
        updateDraft({ embeddingModel: model, embeddingParams: params });
    };

    const saveParam = (name: string, value: unknown) => {
        updateParams((current) => {
            const next = { ...current };
            if (value === "" || value === null || value === undefined) delete next[name];
            else next[name] = value;
            return next;
        });
    };

    const saveExtraParams = (value: Record<string, unknown>) => {
        updateParams((current) => {
            const next = Object.fromEntries(Object.entries(current).filter(([key]) => knownParamNames.has(key)));
            return { ...next, ...value };
        });
    };

    const title = isInitialIngest ? "Ingestion Setup" : "Re-ingest Setup";
    const description = isInitialIngest
        ? "Choose the settings and prompts this world will use for its first ingest."
        : `Edit this world's saved ingest settings and prompts, then begin a full rebuild for ${worldName}.`;

    return (
        <div style={isInline ? { ...panelStyle, padding: 16 } : { padding: isModal ? 20 : 24, display: "grid", gap: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
                <div>
                    <div style={{ fontSize: isInline ? 18 : isModal ? 24 : 28, fontWeight: 800, color: "var(--text-primary)" }}>{title}</div>
                    <div style={{ fontSize: 13, color: "var(--text-subtle)", marginTop: 6, lineHeight: 1.5, maxWidth: 780 }}>{description}</div>
                </div>
                {!isInline && (isModal ? (
                    onClose ? <IconButton label="Close setup" onClick={onClose}><X size={16} /></IconButton> : null
                ) : (
                    cancelHref ? (
                        <Link href={cancelHref} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "9px 14px", borderRadius: 10, border: "1px solid var(--border)", color: "var(--text-primary)" }}>
                            <ArrowLeft size={14} /> Back to Ingest
                        </Link>
                    ) : null
                ))}
            </div>

            <div style={{ display: "grid", gap: 20, gridTemplateColumns: isInline ? undefined : (isModal ? "minmax(0,320px) minmax(0,1fr)" : "minmax(0,360px) minmax(0,1fr)") }}>
                <div style={panelStyle}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Ingestion Settings</div>
                    <NumberField label="Chunk Size (chars)" value={draft.chunkSize} onChange={(value) => updateDraft({ chunkSize: value })} min={1} />
                    <NumberField label="Chunk Overlap (chars)" value={draft.chunkOverlap} onChange={(value) => updateDraft({ chunkOverlap: value })} min={0} />
                    <SelectField label="Embedding Provider" value={draft.embeddingProvider} options={providerOptions} onChange={setProvider} />
                    {customModelProvider ? (
                        <CustomModelField
                            label="World Embedding Model"
                            value={draft.embeddingModel}
                            placeholder={modelPlaceholder}
                            onSave={setModel}
                        />
                    ) : (
                        <SelectField
                            label="World Embedding Model"
                            value={draft.embeddingModel}
                            disabled={providerUnavailable}
                            options={embeddingModels.map((option) => ({ value: option.value, label: option.label }))}
                            onChange={setModel}
                        />
                    )}
                    {(paramShape.typed.length > 0 || paramShape.providerSpecific.length > 0 || paramShape.rawSupportedNames.length > 0 || Object.keys(extraParams).length > 0) ? (
                        <div style={{ border: "1px solid var(--border)", borderRadius: 12, background: "var(--background-secondary)", padding: 14, display: "grid", gap: 12 }}>
                            <div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>Embedding Parameters</div>
                                <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 4, lineHeight: 1.45 }}>
                                    Only supported parameters for the selected embedding model are exposed here.
                                </div>
                            </div>
                            {paramShape.typed.map((definition) => (
                                <ParameterField key={definition.name} definition={definition} value={draft.embeddingParams[definition.name]} onSave={(value) => saveParam(definition.name, value)} />
                            ))}
                            {paramShape.providerSpecific.map((definition) => (
                                <ParameterField key={definition.name} definition={definition} value={draft.embeddingParams[definition.name]} onSave={(value) => saveParam(definition.name, value)} />
                            ))}
                            {(paramShape.rawSupportedNames.length > 0 || Object.keys(extraParams).length > 0) ? (
                                <JsonObjectField
                                    label="Additional LiteLLM Params JSON"
                                    help={paramShape.rawSupportedNames.length > 0 ? `Extra supported params without built-in controls: ${paramShape.rawSupportedNames.join(", ")}` : "Saved extra params without built-in controls."}
                                    value={extraParams}
                                    onSave={saveExtraParams}
                                />
                            ) : null}
                        </div>
                    ) : null}
                    <NumberField label="Graph Architect Glean Amount" value={draft.gleanAmount} onChange={(value) => updateDraft({ gleanAmount: value })} min={0} />
                    {providerUnavailable ? <div style={{ fontSize: 12, color: "var(--error)" }}>{formatProviderLabel(draft.aiCatalog, draft.embeddingProvider)} does not currently expose any embedding models in this catalog.</div> : null}
                    {variant === "reingest" && draft.hasActiveChunkOverrides ? (
                        <label style={{ display: "flex", gap: 10, alignItems: "center", padding: "12px 14px", borderRadius: 12, border: "1px solid var(--border)", background: "var(--background-secondary)", opacity: reuseToggleDisabled ? 0.6 : 1 }}>
                            <input type="checkbox" checked={draft.reuseActiveChunkOverrides} disabled={reuseToggleDisabled} onChange={(event) => updateDraft({ reuseActiveChunkOverrides: event.target.checked })} />
                            <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>Reuse {draft.activeChunkOverrideCount} repaired chunk override{draft.activeChunkOverrideCount === 1 ? "" : "s"}</div>
                                <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 4, lineHeight: 1.45 }}>Keep the current repaired chunk text during Re-ingest when the chunk map stays the same.</div>
                            </div>
                            {reuseToggleDisabled ? <InlineInfo title="Repaired chunk overrides can only be reused when chunk size and overlap stay the same." /> : null}
                        </label>
                    ) : null}
                </div>

                <div style={panelStyle}>
                    <div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>Prompt Overrides</div>
                        <div style={{ fontSize: 12, color: "var(--text-subtle)", marginTop: 6, lineHeight: 1.5 }}>
                            {isInitialIngest ? "These values will be saved for this world when you start ingestion." : "These values become this world's saved prompt overrides when you begin Re-ingesting."}
                        </div>
                    </div>
                    {WORLD_INGEST_PROMPT_FIELDS.map(({ key, label }) => {
                        const isOpen = openPromptSections[key];
                        return (
                            <div key={key} style={{ border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
                                <button onClick={() => setOpenPromptSections((current) => ({ ...current, [key]: !current[key] }))} style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px", background: "transparent", border: "none", color: "var(--text-primary)", cursor: "pointer", textAlign: "left" }}>
                                    <div>
                                        <div style={{ fontSize: 13, fontWeight: 700 }}>{label}</div>
                                        <div style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 4 }}>{isOpen ? "Click to collapse this prompt." : "Click to expand and edit this prompt."}</div>
                                    </div>
                                    <div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                                        <span style={{ fontSize: 11, padding: "3px 8px", borderRadius: 9999, fontWeight: 600, textTransform: "lowercase", background: draft.promptSources[key] === "world" || draft.promptSources[key] === "global" ? "var(--primary)" : "var(--status-pending-bg)", color: draft.promptSources[key] === "world" || draft.promptSources[key] === "global" ? "var(--primary-contrast)" : "var(--status-pending-fg)" }}>
                                            {formatPromptSourceLabel(draft.promptSources[key])}
                                        </span>
                                        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                                    </div>
                                </button>
                                {isOpen ? (
                                    <div style={{ padding: "0 14px 14px", borderTop: "1px solid var(--border)" }}>
                                        <textarea value={draft.prompts[key]} onChange={(event) => updateDraft({ prompts: { ...draft.prompts, [key]: event.target.value } })} rows={6} style={{ ...inputStyle, minHeight: 150, resize: "vertical", marginTop: 14, fontSize: 12, lineHeight: 1.5 }} />
                                    </div>
                                ) : null}
                            </div>
                        );
                    })}
                </div>
            </div>

            <div style={{ display: isInline ? "grid" : "flex", justifyContent: "flex-end", gap: 12, flexWrap: "wrap" }}>
                {!isInline && (isModal ? (
                    onClose ? <button onClick={onClose} style={{ padding: "10px 16px", borderRadius: 10, border: "1px solid var(--border)", background: "var(--background)", color: "var(--text-primary)", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>Cancel</button> : null
                ) : (
                    cancelHref ? <Link href={cancelHref} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "10px 16px", borderRadius: 10, border: "1px solid var(--border)", background: "var(--background)", color: "var(--text-primary)", fontSize: 13, fontWeight: 600 }}>Cancel</Link> : null
                ))}
                <button
                    onClick={onSubmit}
                    disabled={submitting || submitDisabled || providerUnavailable}
                    title={submitDisabled && submitDisabledReason ? submitDisabledReason : providerUnavailable ? "Choose a provider that exposes embedding models in the catalog." : undefined}
                    style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "10px 18px", borderRadius: 10, border: "none", background: "var(--primary)", color: "var(--primary-contrast)", fontSize: 13, fontWeight: 700, opacity: submitting || submitDisabled || providerUnavailable ? 0.7 : 1, cursor: submitting || submitDisabled || providerUnavailable ? "not-allowed" : "pointer", width: isInline ? "100%" : undefined }}
                >
                    {submitting ? <Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> : null}
                    {submitLabel ?? (isInitialIngest ? "Start Ingestion" : "Begin Re-ingesting")}
                </button>
            </div>
        </div>
    );
}

export default function WorldReingestSetupContent({ worldId, mode = "page", onClose, onSubmit }: WorldReingestSetupContentProps) {
    const [worldName, setWorldName] = useState("World");
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [draft, setDraft] = useState<WorldIngestSetupDraft>({
        chunkSize: "4000",
        chunkOverlap: "150",
        embeddingProvider: "gemini",
        embeddingModel: "gemini/gemini-embedding-001",
        embeddingParams: {},
        aiCatalog: EMPTY_CATALOG,
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
            if (onSubmit) await onSubmit(submission);
            else {
                await apiFetch(`/worlds/${worldId}/ingest/start`, { method: "POST", body: JSON.stringify({ resume: false, operation: "rechunk_reingest", ...submission }) });
                window.location.href = `/worlds/${worldId}/ingest`;
            }
        } catch (err: unknown) {
            alert((err as Error).message);
        } finally {
            setSubmitting(false);
        }
    };

    if (loading) {
        return (
            <div style={{ padding: mode === "modal" ? 20 : 24, display: "grid", placeItems: "center", minHeight: mode === "modal" ? 320 : "100%" }}>
                <div style={{ display: "inline-flex", alignItems: "center", gap: 10, color: "var(--text-subtle)" }}><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> Loading ingest settings...</div>
            </div>
        );
    }

    return <WorldIngestSetupForm draft={draft} layout={mode} variant="reingest" worldName={worldName} submitting={submitting} onDraftChange={setDraft} onSubmit={() => void beginReingesting()} onClose={onClose} cancelHref={mode === "page" ? `/worlds/${worldId}/ingest` : undefined} />;
}

function NumberField({ label, value, onChange, min }: { label: string; value: string; onChange: (value: string) => void; min: number }) {
    return <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>{label}<input type="number" min={min} value={value} onChange={(event) => onChange(event.target.value)} style={inputStyle} /></label>;
}

function SelectField({ label, value, options, onChange, disabled = false }: { label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void; disabled?: boolean }) {
    return <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>{label}<select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} style={{ ...inputStyle, opacity: disabled ? 0.65 : 1, cursor: disabled ? "not-allowed" : "pointer" }}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}

function CustomModelField({ label, value, placeholder, onSave }: { label: string; value: string; placeholder: string; onSave: (value: string) => void }) {
    const [draft, setDraft] = useState(value);

    useEffect(() => {
        setDraft(value);
    }, [value]);

    return (
        <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>
            {label}
            <input
                type="text"
                value={draft}
                placeholder={placeholder}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={() => {
                    const nextValue = draft.trim() || placeholder.trim() || value;
                    setDraft(nextValue);
                    onSave(nextValue);
                }}
                style={inputStyle}
            />
        </label>
    );
}

function ParameterField({ definition, value, onSave }: { definition: ParamDefinition; value: unknown; onSave: (value: unknown) => void }) {
    if (definition.type === "json") return <JsonValueField label={definition.label} help={definition.help_text} value={value} onSave={onSave} />;
    if (definition.type === "enum") {
        return (
            <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>
                {definition.label}
                <select value={typeof value === "string" ? value : ""} onChange={(event) => onSave(event.target.value)} style={inputStyle}>
                    <option value="">Use model default</option>
                    {(definition.options ?? []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                {definition.help_text ? <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }}>{definition.help_text}</span> : null}
            </label>
        );
    }
    return (
        <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>
            {definition.label}
            <input
                type="number"
                defaultValue={value === undefined || value === null ? "" : String(value)}
                min={definition.min}
                max={definition.max}
                step={definition.step ?? (definition.type === "integer" ? 1 : 0.1)}
                onBlur={(event) => {
                    const raw = event.target.value.trim();
                    if (!raw) onSave("");
                    else onSave(definition.type === "integer" ? Number.parseInt(raw, 10) : Number.parseFloat(raw));
                }}
                style={inputStyle}
            />
            {definition.help_text ? <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }}>{definition.help_text}</span> : null}
        </label>
    );
}

function JsonValueField({ label, help, value, onSave }: { label: string; help?: string; value: unknown; onSave: (value: unknown) => void }) {
    const serialized = value === undefined ? "" : JSON.stringify(value, null, 2);
    return (
        <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>
            {label}
            <textarea
                key={`${label}-${serialized}`}
                defaultValue={serialized}
                rows={4}
                onBlur={(event) => {
                    const raw = event.target.value.trim();
                    if (!raw) onSave("");
                    else {
                        try { onSave(JSON.parse(raw)); }
                        catch { alert(`Invalid JSON for ${label}.`); }
                    }
                }}
                style={{ ...inputStyle, minHeight: 110, resize: "vertical", fontSize: 12, fontFamily: "monospace", lineHeight: 1.5 }}
            />
            {help ? <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }}>{help}</span> : null}
        </label>
    );
}

function JsonObjectField({ label, help, value, onSave }: { label: string; help?: string; value: Record<string, unknown>; onSave: (value: Record<string, unknown>) => void }) {
    return <JsonValueField label={label} help={help} value={value} onSave={(nextValue) => {
        if (nextValue === "") onSave({});
        else if (nextValue && typeof nextValue === "object" && !Array.isArray(nextValue)) onSave(nextValue as Record<string, unknown>);
        else alert(`${label} must be a JSON object.`);
    }} />;
}

function InlineInfo({ title }: { title: string }) {
    return <span title={title} aria-label={title} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 28, height: 28, borderRadius: 9999, border: "1px solid var(--border)", color: "var(--text-subtle)", cursor: "help", flexShrink: 0 }}><Info size={14} /></span>;
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
    return <button onClick={onClick} aria-label={label} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 36, height: 36, borderRadius: 10, border: "1px solid var(--border)", background: "var(--background)", color: "var(--text-primary)", cursor: "pointer" }}>{children}</button>;
}
