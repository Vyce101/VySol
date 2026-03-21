"use client";

import { useEffect, useState } from "react";
import { X, Plus, Trash2, KeyRound } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { applyTheme, normalizeTheme, type UITheme } from "@/lib/theme";

interface KeyEntry {
    value: string;
    enabled: boolean;
}

interface SettingsData {
    api_keys: KeyEntry[];
    api_key_count: number;
    api_key_active_count: number;
    key_rotation_mode: string;
    default_model_flash: string;
    default_model_chat: string;
    default_model_entity_chooser: string;
    default_model_entity_combiner: string;
    embedding_model: string;
    chunk_size_chars: number;
    chunk_overlap_chars: number;
    retrieval_top_k_chunks: number;
    retrieval_graph_hops: number;
    retrieval_max_nodes: number;
    disable_safety_filters: boolean;
    ui_theme: UITheme;
    graph_extraction_concurrency: number;
    graph_extraction_cooldown_seconds: number;
    embedding_concurrency: number;
    embedding_cooldown_seconds: number;
    chat_provider: string;
    intenserp_base_url: string;
    intenserp_model_id: string;
}

export function SettingsSidebar({ onClose }: { onClose: () => void }) {
    const [settings, setSettings] = useState<SettingsData | null>(null);
    const [keys, setKeys] = useState<KeyEntry[]>([]);
    const [newKey, setNewKey] = useState("");
    const [rotationMode, setRotationMode] = useState("FAIL_OVER");
    const [flashModel, setFlashModel] = useState("");
    const [chatModel, setChatModel] = useState("");
    const [chooserModel, setChooserModel] = useState("");
    const [combinerModel, setCombinerModel] = useState("");
    const [embedModel, setEmbedModel] = useState("");
    const [disableSafety, setDisableSafety] = useState(false);
    const [uiTheme, setUiTheme] = useState<UITheme>("dark");
    const [graphExtractionBatchSize, setGraphExtractionBatchSize] = useState(4);
    const [graphExtractionSlotDelay, setGraphExtractionSlotDelay] = useState(0);
    const [embeddingBatchSize, setEmbeddingBatchSize] = useState(8);
    const [embeddingSlotDelay, setEmbeddingSlotDelay] = useState(0);
    const [chatProvider, setChatProvider] = useState("gemini");
    const [intenserpUrl, setIntenserpUrl] = useState("http://127.0.0.1:7777/v1");
    const [intenserpModelId, setIntenserpModelId] = useState("glm-chat");
    const [toast, setToast] = useState("");

    async function loadSettings() {
        try {
            const data = await apiFetch<SettingsData>("/settings");
            setSettings(data);
            setKeys(data.api_keys || []);
            setRotationMode(data.key_rotation_mode);
            setFlashModel(data.default_model_flash);
            setChatModel(data.default_model_chat);
            setChooserModel(data.default_model_entity_chooser);
            setCombinerModel(data.default_model_entity_combiner);
            setEmbedModel(data.embedding_model);
            setDisableSafety(data.disable_safety_filters);
            const nextTheme = normalizeTheme(data.ui_theme);
            setUiTheme(nextTheme);
            applyTheme(nextTheme);
            setGraphExtractionBatchSize(data.graph_extraction_concurrency ?? 4);
            setGraphExtractionSlotDelay(data.graph_extraction_cooldown_seconds ?? 0);
            setEmbeddingBatchSize(data.embedding_concurrency ?? 8);
            setEmbeddingSlotDelay(data.embedding_cooldown_seconds ?? 0);
            setChatProvider(data.chat_provider || "gemini");
            setIntenserpUrl(data.intenserp_base_url || "http://127.0.0.1:7777/v1");
            setIntenserpModelId(data.intenserp_model_id || "glm-chat");
        } catch {
            // ignore
        }
    }

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        void loadSettings();
    }, []);
    /* eslint-enable react-hooks/set-state-in-effect */

    const showToast = (msg: string) => {
        setToast(msg);
        setTimeout(() => setToast(""), 2000);
    };

    const saveField = async (updates: Record<string, unknown>) => {
        try {
            await apiFetch("/settings", {
                method: "POST",
                body: JSON.stringify(updates),
            });
            showToast("Saved");
            if ("api_keys" in updates && Array.isArray(updates.api_keys)) {
                const nextKeys = updates.api_keys as KeyEntry[];
                setSettings((current) => current ? {
                    ...current,
                    api_key_count: nextKeys.length,
                    api_key_active_count: nextKeys.filter((entry) => entry.enabled).length,
                } : current);
            }
        } catch {
            showToast("Save failed");
        }
    };

    const addKey = async () => {
        if (!newKey.trim()) return;
        const updated = [...keys, { value: newKey.trim(), enabled: true }];
        setKeys(updated);
        setNewKey("");
        await saveField({ api_keys: updated });
    };

    const removeKey = async (idx: number) => {
        const updated = keys.filter((_, i) => i !== idx);
        setKeys(updated);
        await saveField({ api_keys: updated });
    };

    const toggleKey = async (idx: number) => {
        const updated = keys.map((key, i) => (
            i === idx ? { ...key, enabled: !key.enabled } : key
        ));
        setKeys(updated);
        await saveField({ api_keys: updated });
    };

    return (
        <div
            style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", justifyContent: "flex-end" }}
            onClick={onClose}
        >
            <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.4)" }} />
            <div
                onClick={(e) => e.stopPropagation()}
                className="animate-slide-in"
                style={{
                    position: "relative", width: 480, height: "100vh", background: "var(--card)",
                    borderLeft: "1px solid var(--border)", overflowY: "auto", padding: 24,
                }}
            >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
                    <h2 style={{ fontSize: 20, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
                        <KeyRound size={20} style={{ color: "var(--primary)" }} /> Settings
                    </h2>
                    <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer" }}>
                        <X size={20} />
                    </button>
                </div>

                <Section title="API Keys">
                    <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                        Add Gemini API keys. Keys are stored in settings.json on disk. {settings && `(${settings.api_key_active_count} active / ${settings.api_key_count} stored)`}
                    </p>

                    {keys.map((key, i) => (
                        <div
                            key={i}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                marginBottom: 8,
                                opacity: key.enabled ? 1 : 0.6,
                            }}
                        >
                            <input
                                value={`********${key.value.slice(-4)}`}
                                readOnly
                                style={{
                                    flex: 1,
                                    fontFamily: "monospace",
                                    fontSize: 13,
                                    background: key.enabled ? "var(--background-secondary)" : "var(--overlay)",
                                }}
                            />
                            <button
                                onClick={() => toggleKey(i)}
                                style={{
                                    minWidth: 58,
                                    padding: "6px 10px",
                                    borderRadius: "var(--radius)",
                                    border: `1px solid ${key.enabled ? "var(--primary)" : "var(--border)"}`,
                                    background: key.enabled ? "var(--primary-soft-strong)" : "transparent",
                                    color: key.enabled ? "var(--primary-light)" : "var(--text-subtle)",
                                    cursor: "pointer",
                                    fontSize: 11,
                                    fontWeight: 700,
                                    letterSpacing: "0.04em",
                                }}
                            >
                                {key.enabled ? "ON" : "OFF"}
                            </button>
                            <button
                                onClick={() => removeKey(i)}
                                style={{ background: "none", border: "none", color: "var(--error)", cursor: "pointer", padding: 4 }}
                            >
                                <Trash2 size={14} />
                            </button>
                        </div>
                    ))}

                    <div style={{ display: "flex", gap: 8 }}>
                        <input
                            value={newKey}
                            onChange={(e) => setNewKey(e.target.value)}
                            placeholder="Paste API key..."
                            style={{ flex: 1, fontFamily: "monospace", fontSize: 13 }}
                        />
                        <button
                            onClick={addKey}
                            disabled={!newKey.trim()}
                            style={{
                                background: "var(--primary)", color: "var(--primary-contrast)", border: "none",
                                borderRadius: "var(--radius)", padding: "8px 12px", cursor: "pointer",
                                opacity: !newKey.trim() ? 0.5 : 1,
                            }}
                        >
                            <Plus size={14} />
                        </button>
                    </div>

                    <div style={{ marginTop: 16 }}>
                        <label style={{ fontSize: 13, color: "var(--text-subtle)", marginBottom: 8, display: "block" }}>Key Rotation Mode</label>
                        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                            {["FAIL_OVER", "ROUND_ROBIN"].map((mode) => (
                                <button
                                    key={mode}
                                    onClick={() => { setRotationMode(mode); saveField({ key_rotation_mode: mode }); }}
                                    style={{
                                        flex: 1, padding: "8px 12px", borderRadius: "var(--radius)",
                                        border: `1px solid ${rotationMode === mode ? "var(--primary)" : "var(--border)"}`,
                                        background: rotationMode === mode ? "var(--primary-soft-strong)" : "transparent",
                                        color: rotationMode === mode ? "var(--primary-light)" : "var(--text-subtle)",
                                        cursor: "pointer", fontSize: 13, fontWeight: 500,
                                        transition: "all 0.2s",
                                    }}
                                >
                                    {mode.replace("_", " ")}
                                </button>
                            ))}
                        </div>
                        <div style={{ padding: 12, borderRadius: "var(--radius)", background: "var(--overlay)", fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                            {rotationMode === "FAIL_OVER" ? (
                                <p><strong>Failover:</strong> Uses the first key until it hits a rate limit (429), then switches to the next one. Best for maximizing a high-tier key.</p>
                            ) : (
                                <p><strong>Round Robin:</strong> Cycles through each key for every request. Best for distributing load evenly across multiple free-tier keys.</p>
                            )}
                        </div>
                    </div>
                </Section>

                <Section title="Theme">
                    <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12, lineHeight: 1.5 }}>
                        Choose the global app theme. Dark keeps the current look. Light uses the VySol blue, white, and navy brand palette.
                    </p>
                    <div style={{ display: "flex", gap: 8 }}>
                        {(["dark", "light"] as UITheme[]).map((mode) => (
                            <button
                                key={mode}
                                onClick={() => {
                                    setUiTheme(mode);
                                    applyTheme(mode);
                                    saveField({ ui_theme: mode });
                                }}
                                style={{
                                    flex: 1,
                                    padding: "10px 12px",
                                    borderRadius: "var(--radius)",
                                    border: `1px solid ${uiTheme === mode ? "var(--primary)" : "var(--border)"}`,
                                    background: uiTheme === mode ? "var(--primary-soft-strong)" : "transparent",
                                    color: uiTheme === mode ? "var(--primary-light)" : "var(--text-subtle)",
                                    cursor: "pointer",
                                    fontSize: 13,
                                    fontWeight: 600,
                                    textTransform: "capitalize",
                                    transition: "all 0.2s",
                                }}
                            >
                                {mode}
                            </button>
                        ))}
                    </div>
                </Section>

                <Section title="Ingestion Performance">
                    <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12, lineHeight: 1.5 }}>
                        Batch size means the number of parallel slots for that stage, not a wait-for-all batch barrier.
                        Slot delay is per slot and starts the moment that slot finishes its current item.
                    </p>
                    <NumberInput
                        label="Graph Extraction Batch Size"
                        value={graphExtractionBatchSize}
                        min={1}
                        step={1}
                        onChange={setGraphExtractionBatchSize}
                        onBlur={() => saveField({ graph_extraction_concurrency: graphExtractionBatchSize })}
                    />
                    <NumberInput
                        label="Graph Extraction Slot Delay (seconds)"
                        value={graphExtractionSlotDelay}
                        min={0}
                        step={1}
                        onChange={setGraphExtractionSlotDelay}
                        onBlur={() => saveField({ graph_extraction_cooldown_seconds: graphExtractionSlotDelay })}
                    />
                    <NumberInput
                        label="Embedding Batch Size"
                        value={embeddingBatchSize}
                        min={1}
                        step={1}
                        onChange={setEmbeddingBatchSize}
                        onBlur={() => saveField({ embedding_concurrency: embeddingBatchSize })}
                    />
                    <NumberInput
                        label="Embedding Slot Delay (seconds)"
                        value={embeddingSlotDelay}
                        min={0}
                        step={1}
                        onChange={setEmbeddingSlotDelay}
                        onBlur={() => saveField({ embedding_cooldown_seconds: embeddingSlotDelay })}
                    />
                </Section>

                <Section title="AI Models">
                    <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                        Type the exact model name. Changes auto-save. Embedding model here is only the default for new worlds.
                    </p>
                    <ModelInput label="Graph Architect Model" value={flashModel} onChange={setFlashModel}
                        onBlur={() => saveField({ default_model_flash: flashModel })} />

                    <div style={{ marginBottom: 12 }}>
                        <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>
                            Chat Provider
                        </label>
                        <select
                            value={chatProvider}
                            onChange={(e) => {
                                const val = e.target.value;
                                setChatProvider(val);
                                saveField({ chat_provider: val });
                            }}
                            style={{
                                width: "100%", fontFamily: "monospace", fontSize: 13,
                                padding: "6px 8px", borderRadius: "var(--radius)",
                                border: "1px solid var(--border)", background: "var(--background-secondary)",
                                color: "var(--text-primary)", cursor: "pointer",
                            }}
                        >
                            <option value="gemini">Google (Gemini)</option>
                            <option value="intenserp">IntenseRP Next (GLM / others)</option>
                        </select>
                    </div>

                    {chatProvider === "gemini" ? (
                        <ModelInput label="Chat Model" value={chatModel} onChange={setChatModel}
                            onBlur={() => saveField({ default_model_chat: chatModel })} />
                    ) : (
                        <div style={{ marginBottom: 12, padding: 12, borderRadius: "var(--radius)", border: "1px solid var(--border)", background: "var(--overlay)" }}>
                            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 10, lineHeight: 1.5 }}>
                                IntenseRP Next must be running locally. Start it, log in to GLM, and leave it running.
                            </p>
                            <ModelInput label="IntenseRP URL" value={intenserpUrl} onChange={setIntenserpUrl}
                                onBlur={() => saveField({ intenserp_base_url: intenserpUrl })} />
                            <ModelInput label="Model ID" value={intenserpModelId} onChange={setIntenserpModelId}
                                onBlur={() => saveField({ intenserp_model_id: intenserpModelId })} />
                        </div>
                    )}

                    <ModelInput label="Entity Chooser Model" value={chooserModel} onChange={setChooserModel}
                        onBlur={() => saveField({ default_model_entity_chooser: chooserModel })} />
                    <ModelInput label="Entity Combiner Model" value={combinerModel} onChange={setCombinerModel}
                        onBlur={() => saveField({ default_model_entity_combiner: combinerModel })} />
                    <ModelInput label="Default Embedding Model" value={embedModel} onChange={setEmbedModel}
                        onBlur={() => saveField({ embedding_model: embedModel })} />

                    <div style={{ marginTop: 16, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div>
                            <label style={{ fontSize: 13, fontWeight: 500, color: "var(--text-subtle)", display: "block" }}>Disable Safety Filters</label>
                            <p style={{ fontSize: 11, color: "var(--text-muted)" }}>Relax Gemini content moderation for creative writing.</p>
                        </div>
                        <input
                            type="checkbox"
                            checked={disableSafety}
                            onChange={(e) => {
                                const val = e.target.checked;
                                setDisableSafety(val);
                                saveField({ disable_safety_filters: val });
                            }}
                            style={{ width: 20, height: 20, cursor: "pointer" }}
                        />
                    </div>
                </Section>

                {toast && (
                    <div className="toast toast-success">{toast}</div>
                )}
            </div>
        </div>
    );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <div style={{ marginBottom: 28, paddingBottom: 20, borderBottom: "1px solid var(--border)" }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-subtle)" }}>
                {title}
            </h3>
            {children}
        </div>
    );
}

function ModelInput({ label, value, onChange, onBlur }: { label: string; value: string; onChange: (v: string) => void; onBlur: () => void }) {
    return (
        <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>{label}</label>
            <input
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onBlur={onBlur}
                style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
            />
        </div>
    );
}

function NumberInput({
    label,
    value,
    min,
    step,
    onChange,
    onBlur,
}: {
    label: string;
    value: number;
    min: number;
    step: number;
    onChange: (v: number) => void;
    onBlur: () => void;
}) {
    return (
        <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: "var(--text-subtle)", marginBottom: 4, display: "block" }}>{label}</label>
            <input
                type="number"
                value={Number.isFinite(value) ? value : min}
                min={min}
                step={step}
                onChange={(e) => {
                    const nextValue = e.target.valueAsNumber;
                    onChange(Number.isFinite(nextValue) ? nextValue : min);
                }}
                onBlur={onBlur}
                style={{ width: "100%", fontFamily: "monospace", fontSize: 13 }}
            />
        </div>
    );
}
