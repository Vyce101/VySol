"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FocusEvent, type ReactNode, type SetStateAction, type Dispatch } from "react";
import { ChevronDown, ChevronUp, KeyRound, Plus, Trash2, X } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { applyTheme, normalizeTheme, type UITheme } from "@/lib/theme";
import {
    buildModelOptionsWithCurrent,
    getFirstCatalogModelValue,
    getParamUiShape,
    getProviderModelPlaceholder,
    getProviderModels,
    listCatalogProviders,
    providerUsesCustomModelField,
    sanitizeSlotParamsForModel,
    type AICatalog,
    type ParamDefinition,
    type ProviderFieldMeta,
    type SlotConfig,
    type SlotKey,
} from "@/lib/provider-models";

interface ProviderStatus {
    slot: SlotKey;
    provider: string;
    ok: boolean;
    severity: "ok" | "error";
    message: string;
}

interface PresetSummary {
    id: string;
    name: string;
    locked?: boolean;
}

interface SettingsData {
    key_rotation_mode: string;
    chunk_size_chars: number;
    chunk_overlap_chars: number;
    glean_amount: number;
    graph_extraction_concurrency: number;
    graph_extraction_cooldown_seconds: number;
    embedding_concurrency: number;
    embedding_cooldown_seconds: number;
    gemini_disable_safety_filters: boolean;
    ui_theme: UITheme;
    provider_status: Record<string, ProviderStatus>;
    settings_presets: PresetSummary[];
    active_settings_preset_id: string;
    active_settings_preset_name: string;
    active_settings_preset_locked?: boolean;
    slots: Record<SlotKey, SlotConfig>;
    ai_catalog: AICatalog;
}

interface ProviderLibraryEntry {
    id: string;
    label: string;
    enabled: boolean;
    required_ready: boolean;
    [key: string]: unknown;
}

interface ProviderLibraryPayload {
    provider: string;
    display_name: string;
    credential_fields: ProviderFieldMeta[];
    entries: ProviderLibraryEntry[];
    env_fallback?: Record<string, unknown> | null;
}

interface KeyLibraryResponse {
    providers: Record<string, ProviderLibraryPayload>;
}

const inputStyle = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: "1px solid var(--border)",
    background: "var(--background-secondary)",
    color: "var(--text-primary)",
    fontSize: 13,
} as const;

const labelStyle = { fontSize: 12, color: "var(--text-subtle)" } as const;

const rowCardStyle = {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: 12,
    borderRadius: 12,
    border: "1px solid var(--border)",
    background: "var(--background)",
} as const;

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

const slotMeta: Record<SlotKey, { title: string; description: string }> = {
    flash: { title: "Graph Architect", description: "Chunk extraction model and provider." },
    chat: { title: "Chat", description: "Provider and model for normal chat generation." },
    entity_chooser: { title: "Entity Chooser", description: "AI pass for candidate selection in entity resolution." },
    entity_combiner: { title: "Entity Combiner", description: "AI pass that writes the merged entity name and description." },
    embedding: { title: "Default Embeddings", description: "Default embedding backend for new worlds." },
};

function mergeSettingsPatch(current: SettingsData, updates: Record<string, unknown>): SettingsData {
    const next = { ...current, ...updates } as SettingsData;
    if (updates.slots && typeof updates.slots === "object") {
        next.slots = {
            ...current.slots,
            ...(updates.slots as Partial<Record<SlotKey, SlotConfig>>),
        };
    }
    return next;
}

export function SettingsSidebar({ onClose }: { onClose: () => void }) {
    const [settings, setSettings] = useState<SettingsData | null>(null);
    const [library, setLibrary] = useState<KeyLibraryResponse | null>(null);
    const [selectedTab, setSelectedTab] = useState<"configuration" | "key_library">("configuration");
    const [selectedProvider, setSelectedProvider] = useState("gemini");
    const [loadError, setLoadError] = useState<string | null>(null);
    const [toast, setToast] = useState("");
    const [newCredentialLabel, setNewCredentialLabel] = useState("");
    const [newCredentialValues, setNewCredentialValues] = useState<Record<string, string>>({});
    const [credentialLabelDrafts, setCredentialLabelDrafts] = useState<Record<string, string>>({});
    const settingsRef = useRef<SettingsData | null>(null);
    const latestSaveRequestRef = useRef(0);

    const showToast = (message: string) => {
        setToast(message);
        window.setTimeout(() => setToast(""), 2000);
    };

    const applyLoadedSettings = useCallback((nextSettings: SettingsData) => {
        settingsRef.current = nextSettings;
        setSettings(nextSettings);
        applyTheme(normalizeTheme(nextSettings.ui_theme));
    }, []);

    const loadAll = useCallback(async () => {
        try {
            const [nextSettings, nextLibrary] = await Promise.all([
                apiFetch<SettingsData>("/settings"),
                apiFetch<KeyLibraryResponse>("/settings/key-library"),
            ]);
            const visibleProviders = listCatalogProviders(nextSettings.ai_catalog);
            applyLoadedSettings(nextSettings);
            setLibrary(nextLibrary);
            setSelectedProvider((current) => {
                if (visibleProviders.some((provider) => provider.id === current)) {
                    return current;
                }
                return visibleProviders[0]?.id ?? "gemini";
            });
            setLoadError(null);
        } catch (error: unknown) {
            setLoadError((error as Error).message || "Could not load settings.");
        }
    }, [applyLoadedSettings]);

    const saveField = async (updates: Record<string, unknown>) => {
        const requestId = latestSaveRequestRef.current + 1;
        latestSaveRequestRef.current = requestId;
        if (settingsRef.current) {
            const optimistic = mergeSettingsPatch(settingsRef.current, updates);
            settingsRef.current = optimistic;
            setSettings(optimistic);
        }
        try {
            const nextSettings = await apiFetch<SettingsData>("/settings", {
                method: "POST",
                body: JSON.stringify(updates),
            });
            if (requestId !== latestSaveRequestRef.current) {
                return;
            }
            applyLoadedSettings(nextSettings);
            showToast("Saved");
        } catch {
            if (requestId !== latestSaveRequestRef.current) {
                return;
            }
            void loadAll();
            showToast("Save failed");
        }
    };

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        void loadAll();
    }, [loadAll]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const refreshKeyLibrary = async () => setLibrary(await apiFetch<KeyLibraryResponse>("/settings/key-library"));
    const sortedProviders = useMemo(() => listCatalogProviders(settings?.ai_catalog), [settings?.ai_catalog]);
    const selectedLibrary = library?.providers[selectedProvider] ?? null;
    const selectedProviderMeta = settings?.ai_catalog.providers[selectedProvider] ?? null;
    const anyGeminiSelected = Boolean(settings && Object.values(settings.slots).some((slot) => slot.provider === "gemini"));

    const updateSlot = (
        slot: SlotKey,
        nextSlotOrFactory: SlotConfig | ((current: SlotConfig) => SlotConfig),
    ) => {
        const currentSettings = settingsRef.current;
        const currentSlot = currentSettings?.slots[slot];
        if (!currentSettings || !currentSlot) {
            return;
        }
        const nextSlot = typeof nextSlotOrFactory === "function"
            ? nextSlotOrFactory(currentSlot)
            : nextSlotOrFactory;
        void saveField({ slots: { [slot]: nextSlot } });
    };

    const handlePresetSwitch = async (presetId: string) => {
        await apiFetch(`/settings/presets/${presetId}/activate`, { method: "POST" });
        await loadAll();
        showToast("Preset applied");
    };

    const handlePresetSaveAs = async () => {
        const name = window.prompt("New preset name", `${settings?.active_settings_preset_name ?? "Preset"} Copy`);
        if (!name?.trim()) return;
        await apiFetch("/settings/presets", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
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

    const addCredential = async () => {
        if (!selectedLibrary) return;
        const body: Record<string, unknown> = { label: newCredentialLabel.trim() || undefined, enabled: true };
        for (const field of selectedLibrary.credential_fields) {
            const value = newCredentialValues[field.name]?.trim();
            if (value) body[field.name] = value;
        }
        await apiFetch(`/settings/key-library/${selectedProvider}`, { method: "POST", body: JSON.stringify(body) });
        setNewCredentialLabel("");
        setNewCredentialValues({});
        await Promise.all([loadAll(), refreshKeyLibrary()]);
        showToast("Credential saved");
    };

    const toggleCredential = async (credentialId: string, enabled: boolean) => {
        await apiFetch(`/settings/key-library/${selectedProvider}/${credentialId}`, { method: "PATCH", body: JSON.stringify({ enabled }) });
        await Promise.all([loadAll(), refreshKeyLibrary()]);
    };

    const deleteCredential = async (credentialId: string) => {
        await apiFetch(`/settings/key-library/${selectedProvider}/${credentialId}`, { method: "DELETE" });
        await Promise.all([loadAll(), refreshKeyLibrary()]);
    };

    const saveCredentialLabel = async (credentialId: string, label: string) => {
        await apiFetch(`/settings/key-library/${selectedProvider}`, {
            method: "POST",
            body: JSON.stringify({ id: credentialId, label: label.trim() || undefined }),
        });
        await Promise.all([loadAll(), refreshKeyLibrary()]);
        showToast("Credential renamed");
    };

    if (!settings && loadError) {
        return <Overlay onClose={onClose}><div style={{ color: "var(--text-primary)" }}>{loadError}</div></Overlay>;
    }

    return (
        <Overlay onClose={onClose}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <h2 style={{ fontSize: 20, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
                    <KeyRound size={20} style={{ color: "var(--primary)" }} />
                    Settings
                </h2>
                <button onClick={onClose} style={iconButtonStyle}><X size={18} /></button>
            </div>
            {!settings ? <div style={{ color: "var(--text-subtle)", fontSize: 13 }}>Loading settings...</div> : (
                <>
                    <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
                        <TabButton active={selectedTab === "configuration"} onClick={() => setSelectedTab("configuration")}>Configuration</TabButton>
                        <TabButton active={selectedTab === "key_library"} onClick={() => setSelectedTab("key_library")}>Key Library</TabButton>
                    </div>
                    {selectedTab === "configuration" ? (
                        <ConfigurationTab
                            settings={settings}
                            anyGeminiSelected={anyGeminiSelected}
                            onSaveField={saveField}
                            onPresetSwitch={handlePresetSwitch}
                            onPresetSaveAs={handlePresetSaveAs}
                            onPresetRename={handlePresetRename}
                            onSaveSlot={updateSlot}
                        />
                    ) : (
                        <KeyLibraryTab
                            providers={sortedProviders}
                            selectedProvider={selectedProvider}
                            selectedProviderMeta={selectedProviderMeta}
                            selectedLibrary={selectedLibrary}
                            credentialLabelDrafts={credentialLabelDrafts}
                            newCredentialLabel={newCredentialLabel}
                            newCredentialValues={newCredentialValues}
                            onProviderChange={setSelectedProvider}
                            onCredentialLabelDraftsChange={setCredentialLabelDrafts}
                            onNewCredentialLabelChange={setNewCredentialLabel}
                            onNewCredentialValuesChange={setNewCredentialValues}
                            onAddCredential={addCredential}
                            onToggleCredential={toggleCredential}
                            onDeleteCredential={deleteCredential}
                            onSaveCredentialLabel={saveCredentialLabel}
                        />
                    )}
                </>
            )}
            {toast ? <div className="toast toast-success">{toast}</div> : null}
        </Overlay>
    );
}

function ConfigurationTab({
    settings,
    anyGeminiSelected,
    onSaveField,
    onPresetSwitch,
    onPresetSaveAs,
    onPresetRename,
    onSaveSlot,
}: {
    settings: SettingsData;
    anyGeminiSelected: boolean;
    onSaveField: (updates: Record<string, unknown>) => Promise<void>;
    onPresetSwitch: (presetId: string) => Promise<void>;
    onPresetSaveAs: () => Promise<void>;
    onPresetRename: () => Promise<void>;
    onSaveSlot: (slot: SlotKey, nextSlot: SlotConfig | ((current: SlotConfig) => SlotConfig)) => void;
}) {
    const [openSlots, setOpenSlots] = useState<Record<SlotKey, boolean>>({
        flash: false,
        chat: false,
        entity_chooser: false,
        entity_combiner: false,
        embedding: false,
    });

    return (
        <>
            <Section title="Preset">
                <Card title="Preset" description="Configuration presets switch slot choices and tuning together.">
                    <div style={{ display: "grid", gap: 12 }}>
                        <select value={settings.active_settings_preset_id} onChange={(event) => { void onPresetSwitch(event.target.value); }} style={inputStyle}>
                            {settings.settings_presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.locked ? `${preset.name} (Locked)` : preset.name}</option>)}
                        </select>
                        <div style={{ display: "flex", gap: 8 }}>
                            <ActionButton onClick={() => { void onPresetSaveAs(); }}>Save As New Preset</ActionButton>
                            <ActionButton disabled={Boolean(settings.active_settings_preset_locked)} onClick={() => { if (!settings.active_settings_preset_locked) void onPresetRename(); }}>Rename Preset</ActionButton>
                        </div>
                    </div>
                </Card>
            </Section>

            <Section title="App">
                <Card title="Theme" description="Theme remains preset-backed.">
                    <div style={{ display: "flex", gap: 8 }}>
                        {(["dark", "light"] as UITheme[]).map((theme) => (
                            <ActionButton key={theme} active={settings.ui_theme === theme} onClick={() => { applyTheme(theme); void onSaveField({ ui_theme: theme }); }}>{theme}</ActionButton>
                        ))}
                    </div>
                </Card>
                <Card title="Key Rotation" description="Requests target one explicit provider, one explicit model, and one credential entry.">
                    <div style={{ display: "flex", gap: 8 }}>
                        {["FAIL_OVER", "ROUND_ROBIN"].map((mode) => (
                            <ActionButton key={mode} active={settings.key_rotation_mode === mode} onClick={() => { void onSaveField({ key_rotation_mode: mode }); }}>{mode.replace("_", " ")}</ActionButton>
                        ))}
                    </div>
                </Card>
            </Section>

            <Section title="Ingestion">
                <Card title="Chunking Defaults" description="These stay global defaults for new worlds until a world locks its own ingest snapshot.">
                    <NumberField label="Chunk Size (chars)" value={settings.chunk_size_chars} onSave={(value) => onSaveField({ chunk_size_chars: value })} />
                    <NumberField label="Chunk Overlap (chars)" value={settings.chunk_overlap_chars} onSave={(value) => onSaveField({ chunk_overlap_chars: value })} />
                    <NumberField label="Graph Architect Glean Amount" value={settings.glean_amount} onSave={(value) => onSaveField({ glean_amount: value })} />
                </Card>
                <Card title="Concurrency" description="These limits control how many extraction and embedding jobs run at once per preset.">
                    <NumberField label="Graph Extraction Concurrency" value={settings.graph_extraction_concurrency} onSave={(value) => onSaveField({ graph_extraction_concurrency: value })} />
                    <NumberField label="Graph Extraction Cooldown Seconds" value={settings.graph_extraction_cooldown_seconds} step={0.1} onSave={(value) => onSaveField({ graph_extraction_cooldown_seconds: value })} />
                    <NumberField label="Embedding Concurrency" value={settings.embedding_concurrency} onSave={(value) => onSaveField({ embedding_concurrency: value })} />
                    <NumberField label="Embedding Cooldown Seconds" value={settings.embedding_cooldown_seconds} step={0.1} onSave={(value) => onSaveField({ embedding_cooldown_seconds: value })} />
                </Card>
            </Section>

            <Section title="Providers">
                {(Object.keys(slotMeta) as SlotKey[]).map((slot) => (
                    <SlotCard
                        key={slot}
                        slot={slot}
                        settings={settings}
                        open={openSlots[slot]}
                        onToggle={() => setOpenSlots((current) => ({ ...current, [slot]: !current[slot] }))}
                        onSave={onSaveSlot}
                    />
                ))}
            </Section>

            {anyGeminiSelected ? (
                <Section title="Gemini Safety">
                    <Card title="Safety Filters" description="Only shown while at least one selected slot uses Google AI Studio.">
                        <CheckboxRow label="Disable Safety Filters" help="Affects Gemini-backed text generation paths that honor app-level safety settings." checked={settings.gemini_disable_safety_filters} onChange={(checked) => { void onSaveField({ gemini_disable_safety_filters: checked }); }} />
                    </Card>
                </Section>
            ) : null}
        </>
    );
}

function KeyLibraryTab({
    providers,
    selectedProvider,
    selectedProviderMeta,
    selectedLibrary,
    credentialLabelDrafts,
    newCredentialLabel,
    newCredentialValues,
    onProviderChange,
    onCredentialLabelDraftsChange,
    onNewCredentialLabelChange,
    onNewCredentialValuesChange,
    onAddCredential,
    onToggleCredential,
    onDeleteCredential,
    onSaveCredentialLabel,
}: {
    providers: AICatalog["providers"][string][];
    selectedProvider: string;
    selectedProviderMeta: AICatalog["providers"][string] | null;
    selectedLibrary: ProviderLibraryPayload | null;
    credentialLabelDrafts: Record<string, string>;
    newCredentialLabel: string;
    newCredentialValues: Record<string, string>;
    onProviderChange: (provider: string) => void;
    onCredentialLabelDraftsChange: Dispatch<SetStateAction<Record<string, string>>>;
    onNewCredentialLabelChange: Dispatch<SetStateAction<string>>;
    onNewCredentialValuesChange: Dispatch<SetStateAction<Record<string, string>>>;
    onAddCredential: () => Promise<void>;
    onToggleCredential: (credentialId: string, enabled: boolean) => Promise<void>;
    onDeleteCredential: (credentialId: string) => Promise<void>;
    onSaveCredentialLabel: (credentialId: string, label: string) => Promise<void>;
}) {
    return (
        <Section title="Key Library">
            <Card title="Shared Provider Credentials" description="These entries are global across presets.">
                <div style={{ display: "grid", gap: 12 }}>
                    <select value={selectedProvider} onChange={(event) => onProviderChange(event.target.value)} style={inputStyle}>
                        {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name}</option>)}
                    </select>
                    {selectedLibrary?.entries.map((entry) => (
                        <div key={entry.id} style={rowCardStyle}>
                            <div style={{ flex: 1, minWidth: 0, display: "grid", gap: 6 }}>
                                <TextField label="Label" value={credentialLabelDrafts[entry.id] ?? entry.label} onChange={(value) => onCredentialLabelDraftsChange((current) => ({ ...current, [entry.id]: value }))} onSave={(value) => void onSaveCredentialLabel(entry.id, value)} hideLabel />
                                <CredentialValueSummary entry={entry} fields={selectedLibrary.credential_fields} />
                                {!entry.required_ready ? <div style={{ fontSize: 11, color: "var(--error)" }}>Missing required fields for this provider.</div> : null}
                            </div>
                            <ActionButton active={entry.enabled} onClick={() => { void onToggleCredential(entry.id, !entry.enabled); }}>{entry.enabled ? "Enabled" : "Disabled"}</ActionButton>
                            <button onClick={() => { void onDeleteCredential(entry.id); }} style={iconButtonStyle}><Trash2 size={14} /></button>
                        </div>
                    ))}
                    {selectedLibrary?.env_fallback ? (
                        <div style={{ ...rowCardStyle, opacity: 0.8 }}>
                            <div style={{ flex: 1, display: "grid", gap: 6 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{String(selectedLibrary.env_fallback.label || "Environment Fallback")}</div>
                                <CredentialValueSummary entry={selectedLibrary.env_fallback} fields={selectedLibrary.credential_fields} />
                            </div>
                            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Fallback</span>
                        </div>
                    ) : null}
                    {selectedLibrary && selectedLibrary.credential_fields.length > 0 ? (
                        <div style={{ ...rowCardStyle, flexDirection: "column", alignItems: "stretch" }}>
                            <TextField label="Label" value={newCredentialLabel} onChange={onNewCredentialLabelChange} />
                            {selectedLibrary.credential_fields.map((field) => (
                                <TextField key={field.name} label={field.label} value={newCredentialValues[field.name] ?? ""} secret={field.secret} multiline={field.multiline} onChange={(value) => onNewCredentialValuesChange((current) => ({ ...current, [field.name]: value }))} />
                            ))}
                            <ActionButton onClick={() => { void onAddCredential(); }}><Plus size={14} /> Add Credential</ActionButton>
                        </div>
                    ) : null}
                    {selectedProviderMeta?.notes ? <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>{selectedProviderMeta.notes}</div> : null}
                </div>
            </Card>
        </Section>
    );
}

function SlotCard({
    slot,
    settings,
    open,
    onToggle,
    onSave,
}: {
    slot: SlotKey;
    settings: SettingsData;
    open: boolean;
    onToggle: () => void;
    onSave: (slot: SlotKey, nextSlot: SlotConfig | ((current: SlotConfig) => SlotConfig)) => void;
}) {
    const slotConfig = settings.slots[slot];
    const providerOptions = listCatalogProviders(settings.ai_catalog, slot).map((provider) => ({ value: provider.id, label: provider.display_name }));
    const isCustomModelProvider = providerUsesCustomModelField(settings.ai_catalog, slotConfig.provider);
    const modelOptions = buildModelOptionsWithCurrent(getProviderModels(settings.ai_catalog, slotConfig.provider, slotConfig.task), slotConfig.model);
    const modelPlaceholder = getProviderModelPlaceholder(settings.ai_catalog, slotConfig.provider, slotConfig.task);
    const paramShape = getParamUiShape(settings.ai_catalog, slotConfig.provider, slotConfig.task, slotConfig.model);
    const knownParamNames = new Set([...paramShape.typed, ...paramShape.providerSpecific].map((item) => item.name));
    const extraParams = Object.fromEntries(Object.entries(slotConfig.params ?? {}).filter(([key]) => !knownParamNames.has(key)));
    const status = settings.provider_status[slot];

    const saveProvider = (provider: string) => {
        onSave(slot, (currentSlot) => {
            const model = getProviderModelPlaceholder(settings.ai_catalog, provider, currentSlot.task)
                || getFirstCatalogModelValue(settings.ai_catalog, provider, currentSlot.task)
                || currentSlot.model;
            const params = sanitizeSlotParamsForModel(settings.ai_catalog, currentSlot, provider, model, currentSlot.task);
            return { ...currentSlot, provider, model, params };
        });
    };

    const saveModel = (model: string) => {
        onSave(slot, (currentSlot) => {
            const params = sanitizeSlotParamsForModel(settings.ai_catalog, currentSlot, currentSlot.provider, model, currentSlot.task);
            return { ...currentSlot, model, params };
        });
    };

    const saveParam = (name: string, value: unknown) => {
        onSave(slot, (currentSlot) => {
            const params = { ...(currentSlot.params ?? {}) };
            if (value === "" || value === null || value === undefined) delete params[name];
            else params[name] = value;
            return { ...currentSlot, params };
        });
    };

    const saveExtraParams = (value: Record<string, unknown>) => {
        onSave(slot, (currentSlot) => {
            const params = Object.fromEntries(Object.entries(currentSlot.params ?? {}).filter(([key]) => knownParamNames.has(key)));
            return { ...currentSlot, params: { ...params, ...value } };
        });
    };

    return (
        <Card
            title={slotMeta[slot].title}
            description={slotMeta[slot].description}
            badge={status && !status.ok ? <StatusDot message={status.message} /> : null}
            collapsible
            open={open}
            onToggle={onToggle}
        >
            {open ? (
                <div style={{ display: "grid", gap: 12 }}>
                    <SelectField label="Provider" value={slotConfig.provider} options={providerOptions} onChange={saveProvider} />
                    {isCustomModelProvider ? (
                        <CustomModelField
                            label={slot === "embedding" ? "Embedding Model" : "Model"}
                            value={slotConfig.model}
                            placeholder={modelPlaceholder}
                            onSave={saveModel}
                        />
                    ) : (
                        <SelectField
                            label={slot === "embedding" ? "Embedding Model" : "Model"}
                            value={slotConfig.model}
                            options={modelOptions.map((option) => ({ value: option.value, label: option.label }))}
                            onChange={saveModel}
                        />
                    )}
                    {paramShape.typed.map((definition) => <ParameterField key={definition.name} definition={definition} value={slotConfig.params?.[definition.name]} onSave={(value) => saveParam(definition.name, value)} />)}
                    {paramShape.providerSpecific.map((definition) => <ParameterField key={definition.name} definition={definition} value={slotConfig.params?.[definition.name]} onSave={(value) => saveParam(definition.name, value)} />)}
                    {(paramShape.rawSupportedNames.length > 0 || Object.keys(extraParams).length > 0) ? (
                        <JsonObjectField label="Additional LiteLLM Params JSON" help={paramShape.rawSupportedNames.length > 0 ? `Extra supported params without built-in controls: ${paramShape.rawSupportedNames.join(", ")}` : "Saved extra params without built-in controls."} value={extraParams} onSave={saveExtraParams} />
                    ) : null}
                    {status && !status.ok ? <div style={{ fontSize: 12, color: "var(--error)", lineHeight: 1.45 }}>{status.message}</div> : null}
                    {settings.ai_catalog.providers[slotConfig.provider]?.notes ? <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.45 }}>{settings.ai_catalog.providers[slotConfig.provider]?.notes}</div> : null}
                </div>
            ) : null}
        </Card>
    );
}

function Overlay({ children, onClose }: { children: ReactNode; onClose: () => void }) {
    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", justifyContent: "flex-end" }} onClick={onClose}>
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.45)" }} />
            <div onClick={(event) => event.stopPropagation()} className="animate-slide-in" style={{ position: "relative", width: 520, height: "100vh", background: "var(--card)", borderLeft: "1px solid var(--border)", overflowY: "auto", padding: 24 }}>
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

function Card({
    title,
    description,
    children,
    badge,
    collapsible = false,
    open = true,
    onToggle,
}: {
    title: string;
    description: string;
    children: ReactNode;
    badge?: ReactNode;
    collapsible?: boolean;
    open?: boolean;
    onToggle?: () => void;
}) {
    return (
        <div style={{ padding: 16, borderRadius: 14, border: "1px solid var(--border)", background: "linear-gradient(180deg, var(--overlay) 0%, var(--card) 100%)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: open ? 12 : 0 }}>
                <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)", display: "flex", alignItems: "center", gap: 8 }}>
                        {title}
                        {collapsible ? (
                            <button onClick={onToggle} style={{ ...iconButtonStyle, width: 26, height: 26 }}>
                                {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                        ) : null}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 4 }}>{description}</div>
                </div>
                {badge}
            </div>
            {children}
        </div>
    );
}

function StatusDot({ message }: { message: string }) {
    return <span title={message} style={{ width: 12, height: 12, borderRadius: "999px", background: "#ef4444", boxShadow: "0 0 0 2px rgba(239,68,68,0.18)", flexShrink: 0 }} />;
}

function TabButton({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
    return <ActionButton active={active} onClick={onClick}>{children}</ActionButton>;
}

function ActionButton({ children, active = false, disabled = false, onClick }: { children: ReactNode; active?: boolean; disabled?: boolean; onClick: () => void }) {
    return <button onClick={onClick} disabled={disabled} style={{ border: `1px solid ${active ? "var(--primary)" : "var(--border)"}`, background: active ? "var(--primary-soft-strong)" : "var(--background)", color: active ? "var(--primary-light)" : "var(--text-primary)", borderRadius: 10, padding: "10px 12px", fontSize: 13, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, opacity: disabled ? 0.6 : 1 }}>{children}</button>;
}

function CheckboxRow({ label, help, checked, onChange }: { label: string; help: string; checked: boolean; onChange: (checked: boolean) => void }) {
    return <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: 12, borderRadius: 12, background: "var(--background)", border: "1px solid var(--border)" }}><div><div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{label}</div><div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 4 }}>{help}</div></div><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /></label>;
}

function TextField({ label, value, onSave, onChange, secret = false, multiline = false, hideLabel = false }: { label: string; value: string; onSave?: (value: string) => void | Promise<void>; onChange?: (value: string) => void; secret?: boolean; multiline?: boolean; hideLabel?: boolean }) {
    const sharedProps = {
        defaultValue: value,
        onBlur: (event: FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => { if (onSave) void onSave(event.target.value); },
        onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange?.(event.target.value),
        style: { ...inputStyle, fontFamily: secret ? "monospace" : undefined },
    };
    return (
        <div style={{ display: "grid", gap: 6 }}>
            {!hideLabel ? <label style={labelStyle}>{label}</label> : null}
            {multiline ? <textarea rows={4} {...sharedProps} /> : <input type={secret ? "password" : "text"} {...sharedProps} />}
        </div>
    );
}

function CustomModelField({ label, value, placeholder, onSave }: { label: string; value: string; placeholder: string; onSave: (value: string) => void | Promise<void> }) {
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
                    void onSave(nextValue);
                }}
                style={inputStyle}
            />
        </label>
    );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
    return <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>{label}<select value={value} onChange={(event) => onChange(event.target.value)} style={{ ...inputStyle, cursor: "pointer" }}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}

function NumberField({ label, value, onSave, step = 1 }: { label: string; value: number; onSave: (value: number) => void | Promise<void>; step?: number }) {
    return <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>{label}<input type="number" defaultValue={String(value)} step={step} onBlur={(event) => { void onSave(Number(event.target.value)); }} style={inputStyle} /></label>;
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
            <input type="number" defaultValue={value === undefined || value === null ? "" : String(value)} min={definition.min} max={definition.max} step={definition.step ?? (definition.type === "integer" ? 1 : 0.1)} onBlur={(event) => { const raw = event.target.value.trim(); if (!raw) onSave(""); else onSave(definition.type === "integer" ? Number.parseInt(raw, 10) : Number.parseFloat(raw)); }} style={inputStyle} />
            {definition.help_text ? <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }}>{definition.help_text}</span> : null}
        </label>
    );
}

function JsonValueField({ label, help, value, onSave }: { label: string; help?: string; value: unknown; onSave: (value: unknown) => void }) {
    const serialized = value === undefined ? "" : JSON.stringify(value, null, 2);
    return (
        <label style={{ display: "grid", gap: 6, fontSize: 12, color: "var(--text-subtle)" }}>
            {label}
            <textarea key={`${label}-${serialized}`} defaultValue={serialized} rows={4} onBlur={(event) => { const raw = event.target.value.trim(); if (!raw) onSave(""); else { try { onSave(JSON.parse(raw)); } catch { alert(`Invalid JSON for ${label}.`); } } }} style={{ ...inputStyle, minHeight: 110, resize: "vertical", fontSize: 12, fontFamily: "monospace", lineHeight: 1.5 }} />
            {help ? <span style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.45 }}>{help}</span> : null}
        </label>
    );
}

function JsonObjectField({ label, help, value, onSave }: { label: string; help?: string; value: Record<string, unknown>; onSave: (value: Record<string, unknown>) => void }) {
    return <JsonValueField label={label} help={help} value={value} onSave={(nextValue) => { if (nextValue === "") onSave({}); else if (nextValue && typeof nextValue === "object" && !Array.isArray(nextValue)) onSave(nextValue as Record<string, unknown>); else alert(`${label} must be a JSON object.`); }} />;
}

function CredentialValueSummary({ entry, fields }: { entry: Record<string, unknown>; fields: ProviderFieldMeta[] }) {
    return (
        <>
            {fields.map((field) => {
                const rawValue = field.secret ? entry[`${field.name}_masked`] : entry[field.name];
                const present = field.secret ? Boolean(entry[`has_${field.name}`]) : String(rawValue ?? "").trim().length > 0;
                if (!present) return null;
                return <div key={field.name} style={{ fontSize: 12, color: "var(--text-subtle)", fontFamily: "monospace", whiteSpace: "pre-wrap" }}>{String(rawValue)}</div>;
            })}
        </>
    );
}
