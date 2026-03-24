"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { Info, KeyRound, Plus, Trash2, X } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { applyTheme, normalizeTheme, type UITheme } from "@/lib/theme";

type SlotKey = "flash" | "chat" | "entity_chooser" | "entity_combiner" | "embedding";

interface ProviderFamilyOption {
    value: string;
    label: string;
}

interface ProviderFieldMeta {
    name: string;
    label: string;
    secret?: boolean;
    multiline?: boolean;
}

interface ProviderMeta {
    id: string;
    display_name: string;
    family: string;
    supported_slots: string[];
    required_credential_fields: string[];
    credential_fields: ProviderFieldMeta[];
    supports_embedding: boolean;
    supports_gemini_safety: boolean;
    supports_gemini_thinking: boolean;
    supports_groq_reasoning: boolean;
}

interface ProviderCapabilities {
    providers: Record<string, ProviderMeta>;
    families: Record<string, { default: string; options: ProviderFamilyOption[] }>;
    openai_compatible_providers: Array<{ value: string; label: string }>;
}

interface ProviderStatus {
    slot: SlotKey;
    provider: string;
    provider_family: string;
    ok: boolean;
    severity: "ok" | "error";
    message: string;
    supports_gemini_safety: boolean;
    supports_gemini_thinking: boolean;
    supports_groq_reasoning: boolean;
}

interface PresetSummary {
    id: string;
    name: string;
    locked?: boolean;
}

interface SettingsData {
    key_rotation_mode: string;
    default_model_flash: string;
    default_model_flash_provider: string;
    default_model_flash_openai_compatible_provider: string;
    default_model_flash_thinking_level: string;
    default_model_flash_thinking_manual: string;
    default_model_flash_groq_reasoning_effort: string;
    default_model_chat: string;
    default_model_chat_provider: string;
    default_model_chat_openai_compatible_provider: string;
    default_model_chat_thinking_level: string;
    default_model_chat_thinking_manual: string;
    default_model_chat_groq_reasoning_effort: string;
    default_model_entity_chooser: string;
    default_model_entity_chooser_provider: string;
    default_model_entity_chooser_openai_compatible_provider: string;
    default_model_entity_chooser_thinking_level: string;
    default_model_entity_chooser_thinking_manual: string;
    default_model_entity_chooser_groq_reasoning_effort: string;
    default_model_entity_combiner: string;
    default_model_entity_combiner_provider: string;
    default_model_entity_combiner_openai_compatible_provider: string;
    default_model_entity_combiner_thinking_level: string;
    default_model_entity_combiner_thinking_manual: string;
    default_model_entity_combiner_groq_reasoning_effort: string;
    embedding_provider: string;
    embedding_openai_compatible_provider: string;
    embedding_model: string;
    chunk_size_chars: number;
    chunk_overlap_chars: number;
    glean_amount: number;
    graph_extraction_concurrency: number;
    graph_extraction_cooldown_seconds: number;
    embedding_concurrency: number;
    embedding_cooldown_seconds: number;
    gemini_disable_safety_filters: boolean;
    groq_chat_include_reasoning: boolean;
    gemini_chat_send_thinking: boolean;
    ui_theme: UITheme;
    intenserp_model_id: string;
    provider_status: Record<string, ProviderStatus>;
    provider_registry: ProviderCapabilities;
    settings_presets: PresetSummary[];
    active_settings_preset_id: string;
    active_settings_preset_name: string;
    active_settings_preset_locked?: boolean;
}

interface ProviderLibraryEntry {
    id: string;
    label: string;
    enabled: boolean;
    required_ready: boolean;
    has_api_key?: boolean;
    api_key_masked?: string;
    base_url?: string;
}

interface ProviderLibraryPayload {
    provider: string;
    display_name: string;
    credential_fields: ProviderFieldMeta[];
    entries: ProviderLibraryEntry[];
    env_fallback?: {
        label: string;
        enabled: boolean;
        has_api_key?: boolean;
        api_key_masked?: string;
        base_url?: string;
    } | null;
}

interface KeyLibraryResponse {
    providers: Record<string, ProviderLibraryPayload>;
}

const GEMINI_3_THINKING_LEVELS: Array<{ prefix: string; levels: string[] }> = [
    { prefix: "gemini-3.1-pro", levels: ["low", "medium", "high"] },
    { prefix: "gemini-3.1-flash-lite", levels: ["minimal", "low", "medium", "high"] },
    { prefix: "gemini-3-flash", levels: ["minimal", "low", "medium", "high"] },
];

const THINKING_TOOLTIP_TEXT = "Gemini 3 models use the dropdown when supported. Manual mode accepts either a named level or a numeric budget.";
const GROQ_REASONING_OPTIONS = [
    { value: "", label: "Use model default" },
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
];

function getSupportedGeminiThinkingLevels(modelName: string): string[] {
    const normalized = modelName.trim().toLowerCase();
    if (!normalized) return [];
    const match = GEMINI_3_THINKING_LEVELS.find((entry) => normalized.startsWith(entry.prefix));
    return match ? [...match.levels] : [];
}

function resolveSelectedProvider(settings: SettingsData, slot: SlotKey): string {
    if (slot === "flash") {
        return settings.default_model_flash_provider === "openai_compatible"
            ? settings.default_model_flash_openai_compatible_provider
            : settings.default_model_flash_provider;
    }
    if (slot === "chat") {
        return settings.default_model_chat_provider === "openai_compatible"
            ? settings.default_model_chat_openai_compatible_provider
            : settings.default_model_chat_provider;
    }
    if (slot === "entity_chooser") {
        return settings.default_model_entity_chooser_provider === "openai_compatible"
            ? settings.default_model_entity_chooser_openai_compatible_provider
            : settings.default_model_entity_chooser_provider;
    }
    if (slot === "entity_combiner") {
        return settings.default_model_entity_combiner_provider === "openai_compatible"
            ? settings.default_model_entity_combiner_openai_compatible_provider
            : settings.default_model_entity_combiner_provider;
    }
    return settings.embedding_provider === "openai_compatible"
        ? settings.embedding_openai_compatible_provider
        : settings.embedding_provider;
}

function formatSupportedSlotLabel(slot: string): string {
    if (slot === "flash") return "Graph Architect";
    if (slot === "chat") return "Chat";
    if (slot === "entity_chooser") return "Entity Chooser";
    if (slot === "entity_combiner") return "Entity Combiner";
    if (slot === "embedding") return "Default Embeddings";
    return slot;
}

const iconButtonStyle = {
    background: "transparent",
    border: "1px solid var(--border)",
    color: "var(--text-subtle)",
    borderRadius: 10,
    width: 34,
    height: 34,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
} as const;

const inputStyle = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: "1px solid var(--border)",
    background: "var(--background-secondary)",
    color: "var(--text-primary)",
    fontSize: 13,
    fontFamily: "monospace",
} as const;

const selectStyle = {
    ...inputStyle,
    cursor: "pointer",
} as const;

const labelStyle = {
    fontSize: 12,
    color: "var(--text-subtle)",
} as const;

const rowCardStyle = {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: 12,
    borderRadius: 12,
    border: "1px solid var(--border)",
    background: "var(--background)",
} as const;

export function SettingsSidebar({ onClose }: { onClose: () => void }) {
    const [settings, setSettings] = useState<SettingsData | null>(null);
    const [library, setLibrary] = useState<KeyLibraryResponse | null>(null);
    const [selectedTab, setSelectedTab] = useState<"configuration" | "key_library">("configuration");
    const [selectedProvider, setSelectedProvider] = useState("gemini");
    const [loadError, setLoadError] = useState<string | null>(null);
    const [toast, setToast] = useState("");
    const [newCredentialLabel, setNewCredentialLabel] = useState("");
    const [newCredentialValues, setNewCredentialValues] = useState<Record<string, string>>({});

    const showToast = (message: string) => {
        setToast(message);
        window.setTimeout(() => setToast(""), 2000);
    };

    const loadAll = async () => {
        try {
            const [nextSettings, nextLibrary] = await Promise.all([
                apiFetch<SettingsData>("/settings"),
                apiFetch<KeyLibraryResponse>("/settings/key-library"),
            ]);
            setSettings(nextSettings);
            setLibrary(nextLibrary);
            setSelectedProvider((current) => nextLibrary.providers[current] ? current : Object.keys(nextLibrary.providers)[0] ?? "gemini");
            setLoadError(null);
            applyTheme(normalizeTheme(nextSettings.ui_theme));
        } catch (error: unknown) {
            setLoadError((error as Error).message || "Could not load settings.");
        }
    };

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        void loadAll();
    }, []);
    /* eslint-enable react-hooks/set-state-in-effect */

    const saveField = async (updates: Record<string, unknown>) => {
        try {
            const nextSettings = await apiFetch<SettingsData>("/settings", {
                method: "POST",
                body: JSON.stringify(updates),
            });
            setSettings(nextSettings);
            applyTheme(normalizeTheme(nextSettings.ui_theme));
            showToast("Saved");
        } catch {
            showToast("Save failed");
        }
    };

    const refreshKeyLibrary = async () => {
        const nextLibrary = await apiFetch<KeyLibraryResponse>("/settings/key-library");
        setLibrary(nextLibrary);
    };

    const handlePresetSwitch = async (presetId: string) => {
        await apiFetch(`/settings/presets/${presetId}/activate`, { method: "POST" });
        await loadAll();
        showToast("Preset applied");
    };

    const handlePresetSaveAs = async () => {
        const name = window.prompt("New preset name", `${settings?.active_settings_preset_name ?? "Preset"} Copy`);
        if (!name?.trim()) return;
        await apiFetch("/settings/presets", {
            method: "POST",
            body: JSON.stringify({ name: name.trim() }),
        });
        await loadAll();
        showToast("Preset saved");
    };

    const handlePresetRename = async () => {
        if (!settings) return;
        const name = window.prompt("Rename preset", settings.active_settings_preset_name);
        if (!name?.trim()) return;
        await apiFetch(`/settings/presets/${settings.active_settings_preset_id}/rename`, {
            method: "POST",
            body: JSON.stringify({ name: name.trim() }),
        });
        await loadAll();
        showToast("Preset renamed");
    };

    const selectedLibrary = library?.providers[selectedProvider] ?? null;
    const selectedProviderMeta = settings?.provider_registry.providers[selectedProvider];

    const addCredential = async () => {
        if (!selectedLibrary) return;
        const body: Record<string, unknown> = {
            label: newCredentialLabel.trim() || undefined,
            enabled: true,
        };
        for (const field of selectedLibrary.credential_fields) {
            const value = newCredentialValues[field.name]?.trim();
            if (value) body[field.name] = value;
        }
        await apiFetch(`/settings/key-library/${selectedProvider}`, {
            method: "POST",
            body: JSON.stringify(body),
        });
        setNewCredentialLabel("");
        setNewCredentialValues({});
        await Promise.all([loadAll(), refreshKeyLibrary()]);
        showToast("Credential saved");
    };

    const toggleCredential = async (credentialId: string, enabled: boolean) => {
        await apiFetch(`/settings/key-library/${selectedProvider}/${credentialId}`, {
            method: "PATCH",
            body: JSON.stringify({ enabled }),
        });
        await Promise.all([loadAll(), refreshKeyLibrary()]);
    };

    const deleteCredential = async (credentialId: string) => {
        await apiFetch(`/settings/key-library/${selectedProvider}/${credentialId}`, { method: "DELETE" });
        await Promise.all([loadAll(), refreshKeyLibrary()]);
    };

    const anyGeminiSelected = useMemo(() => {
        if (!settings) return false;
        return (["flash", "chat", "entity_chooser", "entity_combiner"] as SlotKey[]).some(
            (slot) => resolveSelectedProvider(settings, slot) === "gemini"
        );
    }, [settings]);

    if (!settings && loadError) {
        return (
            <Overlay onClose={onClose}>
                <div style={{ color: "var(--text-primary)" }}>{loadError}</div>
            </Overlay>
        );
    }

    return (
        <Overlay onClose={onClose}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <h2 style={{ fontSize: 20, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
                    <KeyRound size={20} style={{ color: "var(--primary)" }} />
                    Settings
                </h2>
                <button onClick={onClose} style={iconButtonStyle}>
                    <X size={18} />
                </button>
            </div>

            {!settings ? <div style={{ color: "var(--text-subtle)", fontSize: 13 }}>Loading settings...</div> : (
                <>
                    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                        <TabButton active={selectedTab === "configuration"} onClick={() => setSelectedTab("configuration")}>Configuration</TabButton>
                        <TabButton active={selectedTab === "key_library"} onClick={() => setSelectedTab("key_library")}>Key Library</TabButton>
                    </div>

                    {selectedTab === "configuration" ? (
                        <>
                            <Section title="Preset">
                                <div style={{ display: "grid", gap: 12 }}>
                                    <select
                                        value={settings.active_settings_preset_id}
                                        onChange={(event) => { void handlePresetSwitch(event.target.value); }}
                                        style={selectStyle}
                                    >
                                        {settings.settings_presets.map((preset) => (
                                            <option key={preset.id} value={preset.id}>{preset.locked ? `${preset.name} (Locked)` : preset.name}</option>
                                        ))}
                                    </select>
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <ActionButton onClick={() => { void handlePresetSaveAs(); }}>Save As New Preset</ActionButton>
                                        <ActionButton
                                            disabled={Boolean(settings.active_settings_preset_locked)}
                                            onClick={() => { if (!settings.active_settings_preset_locked) void handlePresetRename(); }}
                                        >
                                            Rename Preset
                                        </ActionButton>
                                    </div>
                                </div>
                            </Section>

                            <Section title="App">
                                <Card title="Theme" description="Theme stays preset-backed in Configuration so each preset can carry its own feel.">
                                    <div style={{ display: "flex", gap: 8 }}>
                                        {(["dark", "light"] as UITheme[]).map((theme) => (
                                            <ActionButton
                                                key={theme}
                                                active={settings.ui_theme === theme}
                                                onClick={() => {
                                                    applyTheme(theme);
                                                    void saveField({ ui_theme: theme });
                                                }}
                                            >
                                                {theme}
                                            </ActionButton>
                                        ))}
                                    </div>
                                </Card>

                                <Card title="Key Rotation" description="Provider-backed model calls pool from the active provider’s enabled library entries.">
                                    <div style={{ display: "flex", gap: 8 }}>
                                        {["FAIL_OVER", "ROUND_ROBIN"].map((mode) => (
                                            <ActionButton
                                                key={mode}
                                                active={settings.key_rotation_mode === mode}
                                                onClick={() => { void saveField({ key_rotation_mode: mode }); }}
                                            >
                                                {mode.replace("_", " ")}
                                            </ActionButton>
                                        ))}
                                    </div>
                                </Card>
                            </Section>

                            <Section title="Ingestion">
                                <Card title="Chunking Defaults" description="These stay global defaults for new worlds until a world locks its own ingest snapshot.">
                                    <NumberField label="Chunk Size (chars)" value={settings.chunk_size_chars} onSave={(value) => saveField({ chunk_size_chars: value })} />
                                    <NumberField label="Chunk Overlap (chars)" value={settings.chunk_overlap_chars} onSave={(value) => saveField({ chunk_overlap_chars: value })} />
                                    <NumberField label="Graph Architect Glean Amount" value={settings.glean_amount} onSave={(value) => saveField({ glean_amount: value })} />
                                </Card>

                                <Card title="Concurrency" description="These limits control how many extraction and embedding jobs run at once per preset.">
                                    <NumberField label="Graph Extraction Concurrency" value={settings.graph_extraction_concurrency} onSave={(value) => saveField({ graph_extraction_concurrency: value })} />
                                    <NumberField label="Graph Extraction Cooldown Seconds" value={settings.graph_extraction_cooldown_seconds} step={0.1} onSave={(value) => saveField({ graph_extraction_cooldown_seconds: value })} />
                                    <NumberField label="Embedding Concurrency" value={settings.embedding_concurrency} onSave={(value) => saveField({ embedding_concurrency: value })} />
                                    <NumberField label="Embedding Cooldown Seconds" value={settings.embedding_cooldown_seconds} step={0.1} onSave={(value) => saveField({ embedding_cooldown_seconds: value })} />
                                </Card>
                            </Section>

                            <Section title="Providers">
                                <ModelCard
                                    settings={settings}
                                    slot="flash"
                                    title="Graph Architect"
                                    description="Chunk extraction model and provider."
                                    modelValue={settings.default_model_flash}
                                    onModelSave={(value) => saveField({ default_model_flash: value })}
                                    familyValue={settings.default_model_flash_provider}
                                    onFamilySave={(value) => saveField({ default_model_flash_provider: value })}
                                    openAiValue={settings.default_model_flash_openai_compatible_provider}
                                    onOpenAiSave={(value) => saveField({ default_model_flash_openai_compatible_provider: value })}
                                    geminiThinkingLevel={settings.default_model_flash_thinking_level}
                                    geminiThinkingManual={settings.default_model_flash_thinking_manual}
                                    onGeminiThinkingSave={(updates) => saveField(updates)}
                                    groqReasoningValue={settings.default_model_flash_groq_reasoning_effort}
                                    onGroqReasoningSave={(value) => saveField({ default_model_flash_groq_reasoning_effort: value })}
                                />
                                <ModelCard
                                    settings={settings}
                                    slot="chat"
                                    title="Chat"
                                    description="Provider and model for normal chat generation."
                                    modelValue={settings.default_model_chat}
                                    onModelSave={(value) => saveField({ default_model_chat: value })}
                                    familyValue={settings.default_model_chat_provider}
                                    onFamilySave={(value) => saveField({ default_model_chat_provider: value })}
                                    openAiValue={settings.default_model_chat_openai_compatible_provider}
                                    onOpenAiSave={(value) => saveField({ default_model_chat_openai_compatible_provider: value })}
                                    geminiThinkingLevel={settings.default_model_chat_thinking_level}
                                    geminiThinkingManual={settings.default_model_chat_thinking_manual}
                                    onGeminiThinkingSave={(updates) => saveField(updates)}
                                    groqReasoningValue={settings.default_model_chat_groq_reasoning_effort}
                                    onGroqReasoningSave={(value) => saveField({ default_model_chat_groq_reasoning_effort: value })}
                                    extra={resolveSelectedProvider(settings, "chat") === "groq" ? (
                                        <CheckboxRow
                                            label="Include Reasoning"
                                            help="When enabled, the app asks Groq for reasoning and shows it after completion instead of pretending it streams live."
                                            checked={settings.groq_chat_include_reasoning}
                                            onChange={(checked) => { void saveField({ groq_chat_include_reasoning: checked }); }}
                                        />
                                    ) : resolveSelectedProvider(settings, "chat") === "gemini" ? (
                                        <CheckboxRow
                                            label="Send Thinking"
                                            help="Gemini-only thought token support for chat."
                                            checked={settings.gemini_chat_send_thinking}
                                            onChange={(checked) => { void saveField({ gemini_chat_send_thinking: checked }); }}
                                        />
                                    ) : (
                                        <TextField label="IntenseRP Model ID" value={settings.intenserp_model_id} onSave={(value) => saveField({ intenserp_model_id: value })} />
                                    )}
                                />
                                <ModelCard
                                    settings={settings}
                                    slot="entity_chooser"
                                    title="Entity Chooser"
                                    description="AI pass for candidate selection in entity resolution."
                                    modelValue={settings.default_model_entity_chooser}
                                    onModelSave={(value) => saveField({ default_model_entity_chooser: value })}
                                    familyValue={settings.default_model_entity_chooser_provider}
                                    onFamilySave={(value) => saveField({ default_model_entity_chooser_provider: value })}
                                    openAiValue={settings.default_model_entity_chooser_openai_compatible_provider}
                                    onOpenAiSave={(value) => saveField({ default_model_entity_chooser_openai_compatible_provider: value })}
                                    geminiThinkingLevel={settings.default_model_entity_chooser_thinking_level}
                                    geminiThinkingManual={settings.default_model_entity_chooser_thinking_manual}
                                    onGeminiThinkingSave={(updates) => saveField(updates)}
                                    groqReasoningValue={settings.default_model_entity_chooser_groq_reasoning_effort}
                                    onGroqReasoningSave={(value) => saveField({ default_model_entity_chooser_groq_reasoning_effort: value })}
                                />
                                <ModelCard
                                    settings={settings}
                                    slot="entity_combiner"
                                    title="Entity Combiner"
                                    description="AI pass that writes the merged entity name and description."
                                    modelValue={settings.default_model_entity_combiner}
                                    onModelSave={(value) => saveField({ default_model_entity_combiner: value })}
                                    familyValue={settings.default_model_entity_combiner_provider}
                                    onFamilySave={(value) => saveField({ default_model_entity_combiner_provider: value })}
                                    openAiValue={settings.default_model_entity_combiner_openai_compatible_provider}
                                    onOpenAiSave={(value) => saveField({ default_model_entity_combiner_openai_compatible_provider: value })}
                                    geminiThinkingLevel={settings.default_model_entity_combiner_thinking_level}
                                    geminiThinkingManual={settings.default_model_entity_combiner_thinking_manual}
                                    onGeminiThinkingSave={(updates) => saveField(updates)}
                                    groqReasoningValue={settings.default_model_entity_combiner_groq_reasoning_effort}
                                    onGroqReasoningSave={(value) => saveField({ default_model_entity_combiner_groq_reasoning_effort: value })}
                                />
                                <ModelCard
                                    settings={settings}
                                    slot="embedding"
                                    title="Default Embeddings"
                                    description="Provider and model used as the default embedding backend for new worlds."
                                    modelValue={settings.embedding_model}
                                    onModelSave={(value) => saveField({ embedding_model: value })}
                                    familyValue={settings.embedding_provider}
                                    onFamilySave={(value) => saveField({ embedding_provider: value })}
                                    openAiValue={settings.embedding_openai_compatible_provider}
                                    onOpenAiSave={(value) => saveField({ embedding_openai_compatible_provider: value })}
                                />
                            </Section>

                            {anyGeminiSelected ? (
                                <Section title="Gemini Safety">
                                    <Card title="Safety Filters" description="This only appears while a selected slot uses Gemini. Unsupported providers do not get fake safety toggles.">
                                        <CheckboxRow
                                            label="Disable Safety Filters"
                                            help="Affects Gemini-backed text generation paths that honor app-level safety settings."
                                            checked={settings.gemini_disable_safety_filters}
                                            onChange={(checked) => { void saveField({ gemini_disable_safety_filters: checked }); }}
                                        />
                                    </Card>
                                </Section>
                            ) : null}
                        </>
                    ) : (
                        <Section title="Key Library">
                            <Card title="Shared Provider Credentials" description="These entries are shared globally across all presets. Configuration presets only choose which providers/models to use.">
                                <div style={{ display: "grid", gap: 12 }}>
                                    <select value={selectedProvider} onChange={(event) => setSelectedProvider(event.target.value)} style={selectStyle}>
                                        {Object.values(settings.provider_registry.providers).map((provider) => (
                                            <option key={provider.id} value={provider.id}>{provider.display_name}</option>
                                        ))}
                                    </select>
                                    {selectedLibrary?.entries.map((entry) => (
                                        <div key={entry.id} style={rowCardStyle}>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{entry.label}</div>
                                                {entry.has_api_key ? <div style={{ fontSize: 12, color: "var(--text-subtle)", fontFamily: "monospace" }}>{entry.api_key_masked}</div> : null}
                                                {entry.base_url ? <div style={{ fontSize: 12, color: "var(--text-subtle)", fontFamily: "monospace" }}>{entry.base_url}</div> : null}
                                                {!entry.required_ready ? <div style={{ fontSize: 11, color: "var(--error)" }}>Missing required fields for this provider.</div> : null}
                                            </div>
                                            <ActionButton active={entry.enabled} onClick={() => { void toggleCredential(entry.id, !entry.enabled); }}>
                                                {entry.enabled ? "Enabled" : "Disabled"}
                                            </ActionButton>
                                            <button onClick={() => { void deleteCredential(entry.id); }} style={iconButtonStyle}>
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    ))}
                                    {selectedLibrary?.env_fallback ? (
                                        <div style={{ ...rowCardStyle, opacity: 0.8 }}>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{selectedLibrary.env_fallback.label}</div>
                                                {selectedLibrary.env_fallback.api_key_masked ? <div style={{ fontSize: 12, color: "var(--text-subtle)", fontFamily: "monospace" }}>{selectedLibrary.env_fallback.api_key_masked}</div> : null}
                                                {selectedLibrary.env_fallback.base_url ? <div style={{ fontSize: 12, color: "var(--text-subtle)", fontFamily: "monospace" }}>{selectedLibrary.env_fallback.base_url}</div> : null}
                                            </div>
                                            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Fallback</span>
                                        </div>
                                    ) : null}
                                    <div style={{ ...rowCardStyle, flexDirection: "column", alignItems: "stretch" }}>
                                        <TextField label="Label" value={newCredentialLabel} onChange={setNewCredentialLabel} />
                                        {selectedLibrary?.credential_fields.map((field) => (
                                            <TextField
                                                key={field.name}
                                                label={field.label}
                                                value={newCredentialValues[field.name] ?? ""}
                                                secret={field.secret}
                                                onChange={(value) => setNewCredentialValues((current) => ({ ...current, [field.name]: value }))}
                                            />
                                        ))}
                                        <ActionButton onClick={() => { void addCredential(); }}>
                                            <Plus size={14} /> Add Credential
                                        </ActionButton>
                                    </div>
                                    {selectedProviderMeta ? (
                                        <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                                            {selectedProviderMeta.display_name} supports: {selectedProviderMeta.supported_slots.map(formatSupportedSlotLabel).join(", ")}.
                                        </div>
                                    ) : null}
                                </div>
                            </Card>
                        </Section>
                    )}
                </>
            )}

            {toast ? <div className="toast toast-success">{toast}</div> : null}
        </Overlay>
    );
}

function ModelCard({
    settings,
    slot,
    title,
    description,
    modelValue,
    onModelSave,
    familyValue,
    onFamilySave,
    openAiValue,
    onOpenAiSave,
    geminiThinkingLevel,
    geminiThinkingManual,
    onGeminiThinkingSave,
    groqReasoningValue,
    onGroqReasoningSave,
    extra,
}: {
    settings: SettingsData;
    slot: SlotKey;
    title: string;
    description: string;
    modelValue: string;
    onModelSave: (value: string) => void | Promise<void>;
    familyValue: string;
    onFamilySave: (value: string) => void | Promise<void>;
    openAiValue: string;
    onOpenAiSave: (value: string) => void | Promise<void>;
    geminiThinkingLevel?: string;
    geminiThinkingManual?: string;
    onGeminiThinkingSave?: (updates: Record<string, unknown>) => void | Promise<void>;
    groqReasoningValue?: string;
    onGroqReasoningSave?: (value: string) => void | Promise<void>;
    extra?: ReactNode;
}) {
    const status = settings.provider_status[slot];
    const resolvedProvider = resolveSelectedProvider(settings, slot);
    const providerOptions = settings.provider_registry.families[slot]?.options ?? [];
    const supportsGeminiThinking = settings.provider_registry.providers[resolvedProvider]?.supports_gemini_thinking;
    const supportsGroqReasoning = settings.provider_registry.providers[resolvedProvider]?.supports_groq_reasoning;
    const showGenericModelField = !(slot === "chat" && resolvedProvider === "intenserp");
    const prefix = slot === "flash"
        ? "default_model_flash"
        : slot === "chat"
            ? "default_model_chat"
            : slot === "entity_chooser"
                ? "default_model_entity_chooser"
                : "default_model_entity_combiner";

    return (
        <Card
            title={title}
            description={description}
            badge={status && !status.ok ? <StatusDot message={status.message} /> : null}
        >
            <div style={{ display: "grid", gap: 12 }}>
                <div>
                    <label style={labelStyle}>Provider</label>
                    <select value={familyValue} onChange={(event) => { void onFamilySave(event.target.value); }} style={selectStyle}>
                        {providerOptions.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>
                {familyValue === "openai_compatible" ? (
                    <div>
                        <label style={labelStyle}>OpenAI-compatible Provider</label>
                        <select value={openAiValue} onChange={(event) => { void onOpenAiSave(event.target.value); }} style={selectStyle}>
                            {settings.provider_registry.openai_compatible_providers.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>
                ) : null}
                {showGenericModelField ? <TextField label="Model" value={modelValue} onSave={onModelSave} /> : null}
                {supportsGeminiThinking && geminiThinkingLevel !== undefined && geminiThinkingManual !== undefined && onGeminiThinkingSave ? (
                    <ThinkingControl
                        modelName={modelValue}
                        levelValue={geminiThinkingLevel}
                        manualValue={geminiThinkingManual}
                        onSave={onGeminiThinkingSave}
                        levelKey={`${prefix}_thinking_level`}
                        manualKey={`${prefix}_thinking_manual`}
                    />
                ) : null}
                {supportsGroqReasoning && groqReasoningValue !== undefined && onGroqReasoningSave ? (
                    <div>
                        <label style={labelStyle}>Reasoning Effort</label>
                        <select value={groqReasoningValue} onChange={(event) => { void onGroqReasoningSave(event.target.value); }} style={selectStyle}>
                            {GROQ_REASONING_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                        </select>
                    </div>
                ) : null}
                {extra}
            </div>
        </Card>
    );
}

function Overlay({ children, onClose }: { children: ReactNode; onClose: () => void }) {
    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", justifyContent: "flex-end" }} onClick={onClose}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.45)" }} />
            <div
                onClick={(event) => event.stopPropagation()}
                className="animate-slide-in"
                style={{ position: "relative", width: 520, height: "100vh", background: "var(--card)", borderLeft: "1px solid var(--border)", overflowY: "auto", padding: 24 }}
            >
                {children}
            </div>
        </div>
    );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
    return (
        <div style={{ marginBottom: 28 }}>
            <h3 style={{ fontSize: 13, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 12 }}>{title}</h3>
            <div style={{ display: "grid", gap: 12 }}>{children}</div>
        </div>
    );
}

function Card({ title, description, children, badge }: { title: string; description: string; children: ReactNode; badge?: ReactNode }) {
    return (
        <div style={{ padding: 16, borderRadius: 14, border: "1px solid var(--border)", background: "linear-gradient(180deg, var(--overlay) 0%, var(--card) 100%)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 12 }}>
                <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>{title}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 4 }}>{description}</div>
                </div>
                {badge}
            </div>
            {children}
        </div>
    );
}

function StatusDot({ message }: { message: string }) {
    return (
        <span title={message} style={{ width: 12, height: 12, borderRadius: "999px", background: "#ef4444", boxShadow: "0 0 0 2px rgba(239,68,68,0.18)", flexShrink: 0 }} />
    );
}

function TabButton({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
    return <ActionButton active={active} onClick={onClick}>{children}</ActionButton>;
}

function ActionButton({ children, active = false, disabled = false, onClick }: { children: ReactNode; active?: boolean; disabled?: boolean; onClick: () => void }) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{
                border: `1px solid ${active ? "var(--primary)" : "var(--border)"}`,
                background: active ? "var(--primary-soft-strong)" : "var(--background)",
                color: active ? "var(--primary-light)" : "var(--text-primary)",
                borderRadius: 10,
                padding: "10px 12px",
                fontSize: 13,
                fontWeight: 600,
                cursor: disabled ? "not-allowed" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
                opacity: disabled ? 0.6 : 1,
            }}
        >
            {children}
        </button>
    );
}

function CheckboxRow({ label, help, checked, onChange }: { label: string; help: string; checked: boolean; onChange: (checked: boolean) => void }) {
    return (
        <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: 12, borderRadius: 12, background: "var(--background)", border: "1px solid var(--border)" }}>
            <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{label}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 4 }}>{help}</div>
            </div>
            <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
        </label>
    );
}

function TextField({
    label,
    value,
    onSave,
    onChange,
    secret = false,
}: {
    label: string;
    value: string;
    onSave?: (value: string) => void | Promise<void>;
    onChange?: (value: string) => void;
    secret?: boolean;
}) {
    return (
        <div style={{ display: "grid", gap: 6 }}>
            <label style={labelStyle}>{label}</label>
            <input
                key={`${label}-${value}`}
                type={secret ? "password" : "text"}
                defaultValue={value}
                onChange={(event) => {
                    onChange?.(event.target.value);
                }}
                onBlur={(event) => { if (onSave) void onSave(event.target.value); }}
                style={inputStyle}
            />
        </div>
    );
}

function NumberField({ label, value, onSave, step = 1 }: { label: string; value: number; onSave: (value: number) => void | Promise<void>; step?: number }) {
    return (
        <div style={{ display: "grid", gap: 6 }}>
            <label style={labelStyle}>{label}</label>
            <input
                key={`${label}-${value}`}
                type="number"
                defaultValue={String(value)}
                step={step}
                onBlur={(event) => { void onSave(Number(event.target.value)); }}
                style={inputStyle}
            />
        </div>
    );
}

function ThinkingControl({
    modelName,
    levelValue,
    manualValue,
    onSave,
    levelKey,
    manualKey,
}: {
    modelName: string;
    levelValue: string;
    manualValue: string;
    onSave: (updates: Record<string, unknown>) => void | Promise<void>;
    levelKey: string;
    manualKey: string;
}) {
    const supportedLevels = getSupportedGeminiThinkingLevels(modelName);

    if (supportedLevels.length > 0) {
        return (
            <div style={{ display: "grid", gap: 6 }}>
                <label style={labelStyle}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        Thinking
                        <span title={THINKING_TOOLTIP_TEXT} style={{ color: "var(--text-muted)", cursor: "help" }}>
                            <Info size={12} />
                        </span>
                    </span>
                </label>
                <select
                    value={levelValue}
                    onChange={(event) => { void onSave({ [levelKey]: event.target.value, [manualKey]: "" }); }}
                    style={selectStyle}
                >
                    <option value="">Use model default</option>
                    {supportedLevels.map((level) => <option key={level} value={level}>{level}</option>)}
                </select>
            </div>
        );
    }

    return (
        <TextField
            label="Manual Thinking"
            value={manualValue}
            onSave={(value) => onSave({ [levelKey]: "", [manualKey]: value.trim() })}
        />
    );
}
