import { CaretRight, Check, X } from "@phosphor-icons/react";
import { createPortal } from "react-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type ChronicleSettings, type Providers } from "./api";

const sectionNames = ["ai", "retrieval", "section_tags", "response"] as const;
type SectionName = (typeof sectionNames)[number];
const sectionLabels: Record<SectionName, string> = {
  ai: "AI",
  retrieval: "Retrieval",
  response: "Response",
  section_tags: "Section Tags",
};
const modelSeries = ["Flash", "Flash Lite", "Gemma"] as const;
const displayName = (provider: string) => provider === "google"
  ? "Google"
  : provider.charAt(0).toLocaleUpperCase() + provider.slice(1);

type Props = {
  open: boolean;
  settings: ChronicleSettings | null;
  onSettingsChange: (settings: ChronicleSettings) => void;
  saveState?: "idle" | "saving" | "saved" | "error";
  saveError?: string;
  onClose: () => void;
};

function ProviderMark({ provider }: { provider: string }) {
  return provider === "google"
    ? <img className="chronicle-provider-logo" src="/assets/google-g-logo.svg.webp" alt="" aria-hidden="true" />
    : <span className="chronicle-provider-initial" aria-hidden="true">{displayName(provider).slice(0, 1)}</span>;
}

export function ChronicleSettingsDrawer({ open, settings, onSettingsChange, saveState = "idle", saveError = "", onClose }: Props) {
  const drawerRef = useRef<HTMLElement>(null);
  const modelFieldRef = useRef<HTMLSpanElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [providerError, setProviderError] = useState("");
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [speedControlActive, setSpeedControlActive] = useState(false);
  const keys = useMemo(() => {
    if (!providers) return [];
    const enabledConnections = providers.connections?.filter((item) => item.enabled) ?? [];
    const hasConnectionData = providers.connections !== undefined;
    const enabledIds = new Set(enabledConnections.map((item) => item.id));
    return [...providers.keys]
      .filter((key) => !hasConnectionData || enabledIds.has(key.connection_id ?? ""))
      .sort((left, right) => displayName(left.provider).localeCompare(displayName(right.provider)) || left.name.localeCompare(right.name));
  }, [providers]);
  const models = providers?.chat_models ?? [];
  const selectedKey = keys.find((key) => key.id === settings?.key_id);
  const selectedModel = models.find((model) => model.id === settings?.model);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setProviderError("");
    api<Providers>("/providers")
      .then((data) => { if (!cancelled) setProviders(data); })
      .catch((reason: unknown) => { if (!cancelled) setProviderError(reason instanceof Error ? reason.message : "AI connections could not be loaded."); });
    return () => { cancelled = true; };
  }, [open]);

  useEffect(() => {
    if (!open || !modelOpen) return;
    const closeModelMenuOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !modelFieldRef.current?.contains(event.target)) {
        setModelOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeModelMenuOutside);
    return () => document.removeEventListener("pointerdown", closeModelMenuOutside);
  }, [open, modelOpen]);

  useEffect(() => {
    if (!open) return;
    const appRoot = document.getElementById("root");
    const wasInert = appRoot?.inert ?? false;
    const previousBodyOverflow = document.body.style.overflow;
    const previousDocumentOverflow = document.documentElement.style.overflow;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (appRoot) appRoot.inert = true;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    drawerRef.current?.querySelector<HTMLElement>("button:not(:disabled)")?.focus();
    return () => {
      if (appRoot) appRoot.inert = wasInert;
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousDocumentOverflow;
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  function update<K extends keyof ChronicleSettings>(key: K, value: ChronicleSettings[K]) {
    if (!settings) return;
    onSettingsChange({ ...settings, [key]: value });
  }

  function updateSection(section: SectionName, value: boolean) {
    if (!settings) return;
    onSettingsChange({ ...settings, sections: { ...settings.sections, [section]: value } });
  }

  function toggleSection(section: SectionName) {
    if (section === "ai") {
      setConnectionOpen(false);
      setModelOpen(false);
    }
    updateSection(section, !(settings?.sections[section] ?? true));
  }

  return createPortal((
    <div className={`chronicle-drawer-layer ${open ? "is-open" : ""}`} aria-hidden={!open} inert={!open}>
      <button type="button" tabIndex={open ? 0 : -1} className="chronicle-drawer-scrim" aria-label="Close Settings" onClick={onClose} />
      <aside ref={drawerRef} className="chronicle-settings-drawer" role="dialog" aria-modal="true" aria-labelledby="chronicle-settings-heading" tabIndex={-1}>
        <header className="chronicle-settings-header">
          <h2 id="chronicle-settings-heading">Settings</h2>
          <button type="button" className="chronicle-drawer-close" aria-label="Close Settings" onClick={onClose}><X size={20} /></button>
        </header>
        {saveState === "error" && saveError && <p className="chronicle-settings-error" role="alert">{saveError}</p>}
        {providerError && <p className="chronicle-settings-error" role="alert">{providerError}</p>}

        {sectionNames.map((section) => (
          <section className={`chronicle-settings-section ${(settings?.sections[section] ?? true) ? "is-open" : ""} ${section === "ai" && (connectionOpen || modelOpen) ? "has-open-select-menu" : ""}`} key={section}>
            <button type="button" className="chronicle-settings-section-heading" aria-expanded={settings?.sections[section] ?? true} aria-controls={`chronicle-settings-${section}`} onClick={() => toggleSection(section)}>
              <span>{sectionLabels[section]}</span><CaretRight size={16} aria-hidden="true" />
            </button>
            <div id={`chronicle-settings-${section}`} className="chronicle-settings-section-panel" aria-hidden={!(settings?.sections[section] ?? true)} inert={!(settings?.sections[section] ?? true)}>
              <div className="chronicle-settings-section-inner">
                {section === "ai" && (
                  <div className="chronicle-settings-fields">
                    <div className="chronicle-setting-field">
                      <span id="chronicle-api-connection-label">API Connection</span>
                      <span className="chronicle-select-wrap">
                        <button type="button" className="chronicle-select-button" aria-labelledby="chronicle-api-connection-label chronicle-api-connection-value" aria-haspopup="listbox" aria-expanded={connectionOpen} onClick={() => setConnectionOpen((value) => !value)} disabled={!settings}>
                          {selectedKey ? <><ProviderMark provider={selectedKey.provider} /><span id="chronicle-api-connection-value">{displayName(selectedKey.provider)} · {selectedKey.name}</span></> : <span id="chronicle-api-connection-value">Select a connection</span>}
                          <CaretRight className="chronicle-select-chevron" size={15} aria-hidden="true" />
                        </button>
                        {connectionOpen && <div className="chronicle-select-menu" role="listbox" aria-label="API Connection">
                          {keys.map((key) => <button key={key.id} type="button" role="option" aria-selected={key.id === settings?.key_id} onClick={() => { update("key_id", key.id); setConnectionOpen(false); }}><ProviderMark provider={key.provider} /><span>{displayName(key.provider)} · {key.name}</span>{key.id === settings?.key_id && <Check size={15} />}</button>)}
                          {!keys.length && <p>No enabled API connections are available.</p>}
                        </div>}
                      </span>
                    </div>
                    <div className="chronicle-setting-field">
                      <span>Chat Model</span>
                      <span ref={modelFieldRef} className="chronicle-select-wrap">
                        <button type="button" className="chronicle-select-button" aria-haspopup="listbox" aria-expanded={modelOpen} onClick={() => setModelOpen((value) => !value)} disabled={!settings}>
                          {selectedModel && <ProviderMark provider={selectedModel.provider} />}<span>{selectedModel?.name ?? "Select a model"}</span><CaretRight className="chronicle-select-chevron" size={15} aria-hidden="true" />
                        </button>
                        {modelOpen && <div className="chronicle-select-menu chronicle-model-menu" role="listbox" aria-label="Chat Model">
                          {modelSeries.map((series) => {
                            const seriesModels = models.filter((model) => model.series === series);
                            if (!seriesModels.length) return null;
                            return <div className="chronicle-model-group" key={series}><span>{series}</span>{seriesModels.map((model) => <button key={model.id} type="button" role="option" aria-selected={model.id === settings?.model} onClick={() => { update("model", model.id); setModelOpen(false); }}><ProviderMark provider={model.provider} /><span>{model.name}</span>{model.id === settings?.model && <Check size={15} />}</button>)}</div>;
                          })}
                          {!models.length && <p>No chat models are available.</p>}
                        </div>}
                      </span>
                    </div>
                    <div className="chronicle-setting-field is-disabled">
                      <span>Embedding Model</span><span aria-disabled="true">Gemini Embedding 2</span>
                    </div>
                  </div>
                )}
                {section === "retrieval" && <div className="chronicle-settings-fields">
                  <label className="chronicle-setting-field chronicle-number-setting"><span>Number of Chunks</span><input type="number" min={1} max={50} step={1} value={settings?.chunk_count ?? 3} disabled={!settings} onChange={(event) => update("chunk_count", Math.max(1, Math.min(50, Number(event.target.value) || 1)))} /></label>
                  <label className="chronicle-setting-field"><span className="chronicle-range-label"><span>Minimum Similarity</span><output>{(settings?.minimum_similarity ?? 0.6).toFixed(2)}</output></span><input className="chronicle-range" type="range" min={0} max={1} step={0.01} value={settings?.minimum_similarity ?? 0.6} disabled={!settings} onChange={(event) => update("minimum_similarity", Number(event.target.value))} /></label>
                  <label className="chronicle-setting-field chronicle-number-setting"><span>Chunk Overlap <small>chars</small></span><input type="number" min={0} max={100000} step={1} value={settings?.chunk_overlap ?? 150} disabled={!settings} onChange={(event) => update("chunk_overlap", Math.max(0, Math.min(100000, Number(event.target.value) || 0)))} /></label>
                </div>}
                {section === "response" && <div className="chronicle-settings-fields chronicle-response-fields">
                  <label className="chronicle-setting-field"><span className="chronicle-range-label"><span>Streaming Speed</span><output>{settings?.streaming_speed === 0 ? "Off" : settings?.streaming_speed === 100 ? "Instant" : `${settings?.streaming_speed ?? 50} chars/s`}</output></span><span className="chronicle-speed-slider-wrap"><output className={`chronicle-speed-tooltip ${speedControlActive ? "is-visible" : ""}`} style={{ left: `${settings?.streaming_speed ?? 50}%` }}>{settings?.streaming_speed === 0 ? "Off" : settings?.streaming_speed === 100 ? "Instant" : `${settings?.streaming_speed ?? 50} chars/s`}</output><input className="chronicle-speed-range" type="range" min={0} max={100} step={1} value={settings?.streaming_speed ?? 50} disabled={!settings} onChange={(event) => update("streaming_speed", Number(event.target.value))} onPointerDown={() => setSpeedControlActive(true)} onPointerUp={() => setSpeedControlActive(false)} onBlur={() => setSpeedControlActive(false)} onFocus={() => setSpeedControlActive(true)} aria-label="Streaming speed" /></span><span className="chronicle-speed-markers" aria-hidden="true"><span>Off</span><span>Slow</span><span>Normal</span><span>Fast</span><span>Instant</span></span></label>
                </div>}
                {section === "section_tags" && <div className="chronicle-settings-fields chronicle-tag-fields">
                  <label className="chronicle-setting-field"><span>Chat History Prefix</span><input type="text" value={settings?.chat_history_prefix ?? "<chat_history>"} disabled={!settings} onChange={(event) => update("chat_history_prefix", event.target.value)} /></label>
                  <label className="chronicle-setting-field"><span>Chat History Suffix</span><input type="text" value={settings?.chat_history_suffix ?? "</chat_history>"} disabled={!settings} onChange={(event) => update("chat_history_suffix", event.target.value)} /></label>
                  <label className="chronicle-setting-field"><span>Retrieved Chunks Prefix</span><input type="text" value={settings?.rag_chunks_prefix ?? "<rag_chunks>"} disabled={!settings} onChange={(event) => update("rag_chunks_prefix", event.target.value)} /></label>
                  <label className="chronicle-setting-field"><span>Retrieved Chunks Suffix</span><input type="text" value={settings?.rag_chunks_suffix ?? "</rag_chunks>"} disabled={!settings} onChange={(event) => update("rag_chunks_suffix", event.target.value)} /></label>
                </div>}
              </div>
            </div>
          </section>
        ))}
      </aside>
    </div>
  ), document.body);
}
