import { ArrowClockwise, CaretRight, Check, X } from "@phosphor-icons/react";
import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type ChronicleSettings, type ModelCapabilities, type ProviderModel, type Providers, type WorldEmbeddingProfile } from "./api";
import { providerName as displayName } from "./providerNames";

const sectionNames = ["ai", "retrieval", "section_tags", "response"] as const;
type SectionName = (typeof sectionNames)[number];
const sectionLabels: Record<SectionName, string> = {
  ai: "AI",
  retrieval: "Retrieval",
  response: "Response",
  section_tags: "Section Tags",
};
const untestedModelHelp = "VySol has not added model-specific settings for this model yet.";
const EMPTY_MODELS: ProviderModel[] = [];
const RECENT_MODEL_STORAGE_KEY = "vysol.recent-chat-models";
const GPT_6_MODEL_ORDER = new Map([
  "gpt-6-astra", "gpt-6-sol", "gpt-6-terra", "gpt-6-luna",
].map((modelId, index) => [modelId, index]));
const GOOGLE_FAMILY_ORDER = ["pro", "flash", "flash lite", "gemma"];
const OPENAI_GENERATION_ORDER = ["gpt-6", "gpt-5.6", "gpt-5.5", "gpt-5.4", "gpt-5.3", "gpt-5.2", "gpt-5.1", "gpt-5", "gpt-4.1"];
type Props = {
  open: boolean;
  settings: ChronicleSettings | null;
  onSettingsChange: (settings: ChronicleSettings) => void;
  saveState?: "idle" | "saving" | "saved" | "error";
  saveError?: string;
  embeddingProfile?: WorldEmbeddingProfile | null;
  modelPreview?: boolean;
  onManageEmbedding?: () => void;
  onClose: () => void;
};

function resolvedLevel(
  requested: string | undefined,
  levels: string[] | null | undefined,
  documentedDefault: string | null | undefined,
) {
  if (!levels?.length) return undefined;
  if (requested && requested !== "auto" && levels.includes(requested)) return requested;
  if (documentedDefault && levels.includes(documentedDefault)) return documentedDefault;
  return levels[levels.length - 1];
}

function modelIdentity(model: ProviderModel) {
  return `${model.provider}:${model.id}`;
}

function readRecentModelIdentities() {
  if (typeof window === "undefined") return [];
  try {
    const saved = JSON.parse(window.localStorage.getItem(RECENT_MODEL_STORAGE_KEY) ?? "null");
    return Array.isArray(saved)
      ? saved.filter((value): value is string => typeof value === "string").slice(0, 12)
      : [];
  } catch {
    return [];
  }
}

function writeRecentModelIdentities(identities: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(RECENT_MODEL_STORAGE_KEY, JSON.stringify(identities));
  } catch {
    // A blocked or full local storage should not prevent model selection.
  }
}

function modelDisplayName(model: ProviderModel) {
  const rawName = (model.name || model.id).trim();
  if (model.provider === "openai") {
    return rawName.replace(/\bgpt\b/gi, "GPT");
  }
  if (model.provider !== "anthropic") return rawName;

  const idMatch = model.id.match(/^claude-(fable|opus|sonnet|haiku)-(\d+)(?:-(\d+))?/i);
  if (idMatch) {
    const family = idMatch[1].charAt(0).toLocaleUpperCase() + idMatch[1].slice(1).toLocaleLowerCase();
    return `Claude ${family} ${idMatch[2]}${idMatch[3] ? `.${idMatch[3]}` : ""}`;
  }
  return rawName
    .replace(/[\s-]+20\d{6,8}\b.*$/u, "")
    .replace(/\b(\d+)\s+(\d+)\b/g, "$1.$2");
}

function anthropicFamilyRank(model: ProviderModel) {
  if (model.provider !== "anthropic") return 99;
  const normalized = `${model.id} ${model.name}`.toLocaleLowerCase();
  const family = ["fable", "opus", "sonnet", "haiku"].findIndex((name) => normalized.includes(name));
  return family < 0 ? 98 : family;
}

function descendingModelVersion(left: ProviderModel, right: ProviderModel) {
  return modelDisplayName(right).localeCompare(modelDisplayName(left), undefined, { numeric: true, sensitivity: "base" })
    || right.id.localeCompare(left.id, undefined, { numeric: true, sensitivity: "base" });
}

function googleFamilyRank(model: ProviderModel) {
  const series = model.series?.trim().toLocaleLowerCase();
  if (series) {
    const exactFamily = GOOGLE_FAMILY_ORDER.indexOf(series);
    if (exactFamily >= 0) return exactFamily;
  }
  const id = model.id.toLocaleLowerCase();
  const inferredFamily = id.includes("flash-lite") ? "flash lite"
    : id.includes("gemma") ? "gemma"
      : id.includes("pro") ? "pro"
        : id.includes("flash") ? "flash" : "";
  const family = GOOGLE_FAMILY_ORDER.indexOf(inferredFamily);
  return family < 0 ? GOOGLE_FAMILY_ORDER.length : family;
}

function openAiGenerationRank(modelId: string) {
  const id = modelId.toLocaleLowerCase();
  const generation = OPENAI_GENERATION_ORDER.findIndex((prefix) => id === prefix || id.startsWith(`${prefix}-`));
  if (generation >= 0) return generation;
  if (/^o\d/.test(id)) return OPENAI_GENERATION_ORDER.length + 1;
  return OPENAI_GENERATION_ORDER.length;
}

function openAiVariantRank(modelId: string) {
  const id = modelId.toLocaleLowerCase();
  if (id.startsWith("gpt-6-")) return GPT_6_MODEL_ORDER.get(id) ?? 99;
  if (id.startsWith("gpt-5.6-")) {
    const variant = ["sol", "terra", "luna"].findIndex((name) => id === `gpt-5.6-${name}`);
    return variant < 0 ? 99 : variant;
  }
  if (id.endsWith("-pro")) return 0;
  if (!/(?:-mini|-nano|-codex)$/.test(id)) return 1;
  if (id.endsWith("-codex")) return 1;
  if (id.endsWith("-mini")) return 2;
  if (id.endsWith("-nano")) return 3;
  return 99;
}

function compareProviderModels(left: ProviderModel, right: ProviderModel) {
  if (left.provider === "google" && right.provider === "google") {
    return googleFamilyRank(left) - googleFamilyRank(right) || descendingModelVersion(left, right);
  }
  if (left.provider === "anthropic" && right.provider === "anthropic") {
    return anthropicFamilyRank(left) - anthropicFamilyRank(right) || descendingModelVersion(left, right);
  }
  if (left.provider === "openai" && right.provider === "openai") {
    const leftGpt6Index = GPT_6_MODEL_ORDER.get(left.id.toLocaleLowerCase());
    const rightGpt6Index = GPT_6_MODEL_ORDER.get(right.id.toLocaleLowerCase());
    if (leftGpt6Index !== undefined && rightGpt6Index !== undefined) return leftGpt6Index - rightGpt6Index;
    return openAiGenerationRank(left.id) - openAiGenerationRank(right.id)
      || openAiVariantRank(left.id) - openAiVariantRank(right.id)
      || descendingModelVersion(left, right);
  }
  if (left.provider === "deepseek" && right.provider === "deepseek") {
    const familyRank = (model: ProviderModel) => model.id.includes("pro") ? 0 : model.id.includes("flash") ? 1 : 2;
    return familyRank(left) - familyRank(right) || descendingModelVersion(left, right);
  }
  const leftGpt6Index = GPT_6_MODEL_ORDER.get(left.id.toLocaleLowerCase());
  const rightGpt6Index = GPT_6_MODEL_ORDER.get(right.id.toLocaleLowerCase());
  if (leftGpt6Index !== undefined && rightGpt6Index !== undefined && leftGpt6Index !== rightGpt6Index) {
    return leftGpt6Index - rightGpt6Index;
  }
  return descendingModelVersion(left, right);
}

function modelGroups(models: ProviderModel[], recentIdentities: string[], search: string) {
  const query = search.trim().toLocaleLowerCase();
  const matchesSearch = (model: ProviderModel) => !query || [
    modelDisplayName(model), model.id, displayName(model.provider), model.series ?? "",
  ].some((value) => value.toLocaleLowerCase().includes(query));
  const filteredModels = models.filter(matchesSearch);
  const modelByIdentity = new Map(filteredModels.map((model) => [modelIdentity(model), model]));
  const recentModels = recentIdentities
    .map((identity) => modelByIdentity.get(identity))
    .filter((model): model is ProviderModel => Boolean(model?.tested))
    .slice(0, 3);
  const groupsByProvider = new Map<string, ProviderModel[]>();
  for (const model of filteredModels.filter((item) => item.tested)) {
    groupsByProvider.set(model.provider, [...(groupsByProvider.get(model.provider) ?? []), model]);
  }
  const groups: Array<[string, ProviderModel[]]> = [];
  if (recentModels.length) groups.push(["Recent", recentModels]);
  for (const [provider, providerModels] of [...groupsByProvider.entries()].sort(([left], [right]) =>
    displayName(left).localeCompare(displayName(right), undefined, { sensitivity: "base" }))) {
    providerModels.sort(compareProviderModels);
    groups.push([displayName(provider), providerModels]);
  }
  const untestedModels = filteredModels
    .filter((model) => !model.tested)
    .sort((left, right) => modelDisplayName(left).localeCompare(modelDisplayName(right), undefined, {
      numeric: true,
      sensitivity: "base",
    }));
  if (untestedModels.length) groups.push(["Untested", untestedModels]);
  return groups;
}

export function ChronicleSettingsDrawer({ open, settings, onSettingsChange, saveState = "idle", saveError = "", embeddingProfile = null, modelPreview = false, onManageEmbedding = () => {}, onClose }: Props) {
  const drawerRef = useRef<HTMLElement>(null);
  const modelFieldRef = useRef<HTMLSpanElement>(null);
  const modelSearchRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [providerError, setProviderError] = useState("");
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [recentModelIdentities, setRecentModelIdentities] = useState<string[]>(readRecentModelIdentities);
  const [refreshingModels, setRefreshingModels] = useState(false);
  const [compatibleSettingsOpen, setCompatibleSettingsOpen] = useState(false);
  const [speedControlActive, setSpeedControlActive] = useState(false);
  const [outputDraft, setOutputDraft] = useState<string | null>(null);
  const [thinkingBudgetDraft, setThinkingBudgetDraft] = useState<string | null>(null);
  const keys = useMemo(() => {
    if (!providers) return [];
    const enabledConnections = providers.connections?.filter((item) => item.enabled) ?? [];
    const hasConnectionData = providers.connections !== undefined;
    const enabledIds = new Set(enabledConnections.map((item) => item.id));
    return [...providers.keys]
      .filter((key) => !hasConnectionData || enabledIds.has(key.connection_id ?? ""))
      .sort((left, right) => displayName(left.provider).localeCompare(displayName(right.provider)) || left.name.localeCompare(right.name));
  }, [providers]);
  const models = providers?.chat_models ?? EMPTY_MODELS;
  const selectedKey = keys.find((key) => key.id === settings?.key_id);
  const previewModels = useMemo(() => [...new Map([
    ...(providers?.preview_chat_models ?? []),
    ...(providers?.keys.flatMap((key) => key.models ?? []) ?? []),
  ].map((model) => [`${model.provider}:${model.id}`, model])).values()], [providers]);
  const catalogModels = modelPreview ? previewModels : selectedKey?.models ?? models;
  const availableModels = useMemo(
    () => catalogModels.filter((model) => model.capabilities?.chat !== false).filter((model, _index, candidates) =>
      model.provider !== "openai" || model.id !== "gpt-5.6"
      || !candidates.some((candidate) => candidate.provider === "openai" && candidate.id === "gpt-5.6-sol")),
    [catalogModels],
  );
  const modelMenuGroups = useMemo(
    () => modelGroups(availableModels, recentModelIdentities, modelSearch),
    [availableModels, recentModelIdentities, modelSearch],
  );
  const effectiveSelectedModelId = settings?.model === "gpt-5.6"
    && availableModels.some((model) => model.provider === "openai" && model.id === "gpt-5.6-sol")
    ? "gpt-5.6-sol"
    : settings?.model;
  const selectedModel = useMemo(
    () => availableModels.find((model) => model.id === effectiveSelectedModelId),
    [availableModels, effectiveSelectedModelId],
  );
  const isCompatible = selectedKey?.provider === "openai_compatible";
  const selectedCapabilities: ModelCapabilities | null | undefined = selectedModel?.capabilities;
  const thinkingBudget = selectedCapabilities?.thinking_budget;
  const requestedThinkingBudget = settings?.thinking_budget;
  const effectiveThinkingBudget = thinkingBudget && typeof requestedThinkingBudget === "number"
    ? requestedThinkingBudget === 0
      ? thinkingBudget.allow_zero ? 0 : null
      : Math.min(Math.max(requestedThinkingBudget, thinkingBudget.minimum), thinkingBudget.maximum)
    : null;
  const levels = selectedModel?.provider === "google"
    ? selectedCapabilities?.thinking_levels
    : selectedCapabilities?.reasoning_levels;
  const defaultLevel = selectedModel?.provider === "google"
    ? selectedCapabilities?.thinking_default
    : selectedCapabilities?.reasoning_default;
  const visibleLevels = levels?.filter((level) => level !== "none");
  const displayedDefaultLevel = defaultLevel && visibleLevels?.includes(defaultLevel)
    ? defaultLevel
    : visibleLevels?.[visibleLevels.length - 1];
  const defaultLevelSummary = defaultLevel === "auto"
    ? "dynamic"
    : defaultLevel === "off" || defaultLevel === "none"
      ? "off"
      : displayedDefaultLevel;
  const canTurnOffThinking = selectedModel?.provider === "google"
    ? selectedCapabilities?.thinking_off === true
    : selectedCapabilities?.reasoning_off === true;
  const sharedReasoningChoice = settings?.reasoning ?? "auto";
  const effectiveLevel = resolvedLevel(sharedReasoningChoice, visibleLevels, defaultLevel);
  const sharedChoiceIsOff = sharedReasoningChoice === "off" || sharedReasoningChoice === "none";
  const levelIsAdjusted = Boolean(
    sharedReasoningChoice !== "auto" &&
    (sharedChoiceIsOff ? !canTurnOffThinking : sharedReasoningChoice !== effectiveLevel),
  );
  const outputMaximum = selectedCapabilities?.output_limit;
  const requestedOutputLimit = settings?.output_limit ?? "max";
  const canSetCustomOutput = isCompatible || outputMaximum != null;
  const effectiveOutputLimit = typeof requestedOutputLimit === "number" && outputMaximum != null
    ? Math.min(requestedOutputLimit, outputMaximum)
    : requestedOutputLimit;
  const outputIsAdjusted = typeof requestedOutputLimit === "number" && (
    outputMaximum == null ? !isCompatible : effectiveOutputLimit !== requestedOutputLimit
  );
  const reasoningValue = sharedReasoningChoice === "auto"
    ? "auto"
    : sharedChoiceIsOff && canTurnOffThinking
      ? "off"
      : visibleLevels?.includes(sharedReasoningChoice)
        ? sharedReasoningChoice
        : effectiveLevel ?? "auto";
  const showReasoning = Boolean(!thinkingBudget && ((visibleLevels?.length ?? 0) > 0 || canTurnOffThinking));
  const showUnknownNativeDefaults = Boolean(selectedModel && !selectedModel.tested && !isCompatible && !thinkingBudget && !showReasoning);
  const displayedOutputLimit = !canSetCustomOutput ? "" : typeof effectiveOutputLimit === "number"
    ? String(effectiveOutputLimit)
    : outputMaximum != null ? String(outputMaximum) : "";
  useEffect(() => { setOutputDraft(null); setThinkingBudgetDraft(null); }, [selectedModel?.id]);
  useEffect(() => {
    if (!modelOpen) {
      setModelSearch("");
      return;
    }
    modelSearchRef.current?.focus();
  }, [modelOpen]);
  const outputLimitControl = (
    <label className="chronicle-setting-field chronicle-output-setting">
      <span>Output Limit</span>
      <input
        type="number"
        aria-label="Output Limit"
        min={1}
        max={outputMaximum ?? undefined}
        value={outputDraft ?? displayedOutputLimit}
        placeholder="Provider Default"
        disabled={!settings || !canSetCustomOutput}
        onChange={(event) => {
          setOutputDraft(event.target.value);
        }}
        onBlur={() => {
          if (outputDraft === null) return;
          const value = Number(outputDraft);
          if (!outputDraft.trim()) update("output_limit", "max");
          else if (Number.isInteger(value) && value > 0 && (outputMaximum == null || value <= outputMaximum)) update("output_limit", value);
          setOutputDraft(null);
        }}
        onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }}
      />
      {outputIsAdjusted && <small className="chronicle-control-note">{outputMaximum == null
        ? "Provider Default is used for this model. Your shared limit is kept for models with a known maximum."
        : "Adjusted to this model’s maximum. Your shared choice is kept for models that support it."}</small>}
    </label>
  );
  const reasoningControl = showReasoning ? (
    <label className="chronicle-setting-field">
      <span>{selectedModel?.provider === "google" ? "Thinking Level" : "Reasoning"}</span>
      <select value={reasoningValue} disabled={!settings} onChange={(event) => update("reasoning", event.target.value)}>
        <option value="auto">{defaultLevelSummary ? `Model Default (${defaultLevelSummary})` : "Model Default"}</option>
        {canTurnOffThinking && <option value="off">Off</option>}
        {(visibleLevels ?? []).map((level) => <option value={level} key={level}>{level.charAt(0).toLocaleUpperCase() + level.slice(1)}</option>)}
      </select>
      {levelIsAdjusted && selectedModel?.provider !== "anthropic" && <small className="chronicle-control-note">This model uses the closest supported setting. Your shared choice is kept for other models.</small>}
      {selectedModel?.provider === "anthropic" && !selectedModel.id.startsWith("claude-fable-") && <small className="chronicle-control-note">Effort can also affect answer detail and tool use.</small>}
    </label>
  ) : null;
  const thinkingBudgetControl = thinkingBudget ? (
    <label className="chronicle-setting-field chronicle-output-setting">
      <span>Thinking Budget</span>
      <input
        type="number"
        aria-label="Thinking Budget"
        min={thinkingBudget.allow_zero ? 0 : thinkingBudget.minimum}
        max={thinkingBudget.maximum}
        step={1}
        value={thinkingBudgetDraft ?? effectiveThinkingBudget ?? ""}
        placeholder={thinkingBudget.default === "off" ? "Off (default)" : "Dynamic (default)"}
        disabled={!settings}
        onChange={(event) => setThinkingBudgetDraft(event.target.value)}
        onBlur={() => {
          if (thinkingBudgetDraft === null) return;
          const value = Number(thinkingBudgetDraft);
          if (!thinkingBudgetDraft.trim()) update("thinking_budget", null);
          else if (Number.isInteger(value) && value <= thinkingBudget.maximum
            && (value >= thinkingBudget.minimum || (thinkingBudget.allow_zero && value === 0))) {
            update("thinking_budget", value);
          }
          setThinkingBudgetDraft(null);
        }}
        onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }}
      />
      <small className="chronicle-control-note">Leave blank to use Google’s {thinkingBudget.default === "off" ? "off" : "dynamic"} default. {thinkingBudget.allow_zero ? "Use 0 to turn thinking off; " : ""}{thinkingBudget.minimum.toLocaleString()}–{thinkingBudget.maximum.toLocaleString()} tokens when enabled.</small>
    </label>
  ) : null;
  const unknownNativeDefaults = showUnknownNativeDefaults ? (
    <label className="chronicle-setting-field">
      <span>{selectedModel?.provider === "google" ? "Thinking" : "Reasoning"}</span>
      <select aria-label={selectedModel?.provider === "google" ? "Thinking" : "Reasoning"} disabled value="default">
        <option value="default">Provider Default</option>
      </select>
    </label>
  ) : null;

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

  useLayoutEffect(() => {
    if (!open || !modelOpen) return;
    modelFieldRef.current
      ?.querySelector<HTMLElement>('[role="option"][aria-selected="true"]')
      ?.scrollIntoView?.({ block: "nearest" });
  }, [open, modelOpen, settings?.model, availableModels]);

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

  function rememberModel(model: ProviderModel) {
    const identity = modelIdentity(model);
    setRecentModelIdentities((current) => {
      const next = [identity, ...current.filter((item) => item !== identity)].slice(0, 12);
      writeRecentModelIdentities(next);
      return next;
    });
  }

  async function refreshSelectedModels() {
    if (!selectedKey || refreshingModels) return;
    setRefreshingModels(true);
    setProviderError("");
    try {
      const result = await api<{
        models: ProviderModel[];
        models_updated_at: string | null;
        models_error: string | null;
      }>(`/providers/keys/${selectedKey.id}/models/refresh`, { method: "POST" });
      setProviders((current) => {
        if (!current) return current;
        const updateKey = (key: typeof current.keys[number]) => key.id === selectedKey.id
          ? { ...key, ...result }
          : key;
        return {
          ...current,
          keys: current.keys.map(updateKey),
          connections: current.connections?.map((connection) => ({
            ...connection,
            credentials: connection.credentials?.map(updateKey),
          })),
          chat_models: current.chat_models?.filter((model) => model.provider !== selectedKey.provider).concat(
            result.models.filter((model) => model.capabilities?.chat !== false),
          ),
        };
      });
    } catch (cause) {
      setProviderError(cause instanceof Error ? cause.message : "Models could not be refreshed.");
    } finally {
      setRefreshingModels(false);
    }
  }

  function updateCompatibleOverride<K extends keyof NonNullable<ChronicleSettings["compatible_overrides"]>>(
    key: K,
    value: NonNullable<ChronicleSettings["compatible_overrides"]>[K] | undefined,
  ) {
    if (!settings) return;
    const overrides = { ...(settings.compatible_overrides ?? {}) };
    if (value === undefined || value === "") delete overrides[key];
    else overrides[key] = value;
    onSettingsChange({ ...settings, compatible_overrides: overrides });
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
                    {modelPreview && <p className="chronicle-model-preview-note" role="status">Model Picker Preview is on. You can inspect model controls here; sending is disabled.</p>}
                    <div className="chronicle-setting-field">
                      <span id="chronicle-api-connection-label">API Connection</span>
                      <span className="chronicle-select-wrap">
                        <button type="button" className="chronicle-select-button" aria-labelledby="chronicle-api-connection-label chronicle-api-connection-value" aria-haspopup="listbox" aria-expanded={connectionOpen} onClick={() => setConnectionOpen((value) => !value)} disabled={!settings || modelPreview}>
                          {modelPreview ? <span id="chronicle-api-connection-value">Preview · no connection</span> : selectedKey ? <span id="chronicle-api-connection-value">{displayName(selectedKey.provider)} · {selectedKey.name}</span> : <span id="chronicle-api-connection-value">Select a connection</span>}
                          <CaretRight className="chronicle-select-chevron" size={15} aria-hidden="true" />
                        </button>
                        {connectionOpen && <div className="chronicle-select-menu" role="listbox" aria-label="API Connection">
                          {keys.map((key) => <button key={key.id} type="button" role="option" aria-selected={key.id === settings?.key_id} onClick={() => { update("key_id", key.id); setConnectionOpen(false); }}><span>{displayName(key.provider)} · {key.name}</span>{key.id === settings?.key_id && <Check size={15} />}</button>)}
                          {!keys.length && <p>No enabled API connections are available.</p>}
                        </div>}
                      </span>
                    </div>
                    <div className="chronicle-setting-field">
                      <span>Chat Model</span>
                      <span ref={modelFieldRef} className="chronicle-select-wrap chronicle-model-picker">
                        <span className="chronicle-model-picker-row">
                          <button type="button" className="chronicle-select-button" aria-haspopup="listbox" aria-expanded={modelOpen} onClick={() => setModelOpen((value) => !value)} disabled={!settings || (!selectedKey && !modelPreview)}>
                            <span>{selectedModel ? modelDisplayName(selectedModel) : "Select a model"}</span><CaretRight className="chronicle-select-chevron" size={15} aria-hidden="true" />
                          </button>
                          {!modelPreview && <button type="button" className="chronicle-model-refresh" aria-label="Refresh Models" title="Refresh models" disabled={!selectedKey || refreshingModels} onClick={() => void refreshSelectedModels()}>
                            <ArrowClockwise size={15} aria-hidden="true" />
                          </button>}
                        </span>
                        {modelOpen && <div className="chronicle-select-menu chronicle-model-menu" role="listbox" aria-label="Chat Model">
                          <label className="chronicle-model-search">
                            <span className="sr-only">Search models</span>
                            <input
                              ref={modelSearchRef}
                              type="search"
                              aria-label="Search models"
                              placeholder="Search models"
                              value={modelSearch}
                              onChange={(event) => setModelSearch(event.target.value)}
                            />
                          </label>
                          <div className="chronicle-model-menu-list">
                            {modelMenuGroups.map(([group, groupModels]) => (
                              <div className="chronicle-model-group" key={group}>
                                <span>{group}</span>
                                {groupModels.map((model) => (
                                  <button
                                    key={`${model.provider}:${model.id}`}
                                    type="button"
                                    role="option"
                                    aria-selected={model.id === effectiveSelectedModelId}
                                    aria-label={model.tested ? modelDisplayName(model) : `${modelDisplayName(model)}, Untested. ${untestedModelHelp}`}
                                    title={model.tested ? undefined : untestedModelHelp}
                                    onClick={() => { update("model", model.id); rememberModel(model); setModelOpen(false); }}
                                  >
                                    <span className="chronicle-model-option-name">{modelDisplayName(model)}</span>
                                    {model.id === effectiveSelectedModelId && <Check size={15} />}
                                    {!model.tested && <span className="chronicle-untested-label">Untested</span>}
                                  </button>
                                ))}
                              </div>
                            ))}
                            {availableModels.length > 0 && !modelMenuGroups.length && <p>No models match your search.</p>}
                            {!availableModels.length && <p>{modelPreview ? "No models are available for preview." : "No chat models are available for this connection."}</p>}
                          </div>
                        </div>}
                      </span>
                      {!modelPreview && selectedKey?.models_error && <small className="chronicle-model-cache-error" role="status">{selectedKey.models_error}{selectedKey.models?.length ? " Showing the last successful list." : ""}</small>}
                    </div>
                    {selectedModel && !isCompatible && outputLimitControl}
                    {thinkingBudgetControl}
                    {reasoningControl}
                    {unknownNativeDefaults}
                    {embeddingProfile ? (
                      <div className="chronicle-world-embedding">
                        <span>World Embedding Profile</span>
                        <strong>{embeddingProfile.name}</strong>
                        <small>{displayName(embeddingProfile.provider)} · {embeddingProfile.model}</small>
                        <span className="chronicle-world-embedding-facts">{embeddingProfile.dimensions?.toLocaleString() ?? "Unknown"} dimensions · {embeddingProfile.max_input_tokens?.toLocaleString() ?? "Provider default"}{embeddingProfile.max_input_tokens ? " tokens" : " input"}</span>
                        <button type="button" className="chronicle-world-embedding-link" onClick={onManageEmbedding}>Open AI Connections</button>
                      </div>
                    ) : (
                      <div className="chronicle-world-embedding is-unavailable">
                        <span>World Embedding Profile</span>
                        <small>World details are loading.</small>
                      </div>
                    )}
                    {isCompatible && (
                      <div className={`chronicle-compatible-settings ${compatibleSettingsOpen ? "is-open" : ""}`}>
                        <button type="button" className="chronicle-compatible-trigger" aria-expanded={compatibleSettingsOpen} aria-controls="compatible-chat-settings" onClick={() => setCompatibleSettingsOpen((value) => !value)}>
                          <span>Advanced Settings</span><CaretRight size={15} aria-hidden="true" />
                        </button>
                        <div id="compatible-chat-settings" className="chronicle-compatible-panel" aria-hidden={!compatibleSettingsOpen} inert={!compatibleSettingsOpen}>
                          <div className="chronicle-settings-fields">
                            {selectedModel && outputLimitControl}
                            <p className="chronicle-control-note">Some compatible servers may reject an optional setting.</p>
                            <label className="chronicle-setting-field"><span>Temperature</span><input type="number" min={0} max={2} step={0.01} value={settings?.compatible_overrides?.temperature ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("temperature", event.target.value === "" ? undefined : Number(event.target.value))} /></label>
                            <label className="chronicle-setting-field"><span>Top P</span><input type="number" min={0} max={1} step={0.01} value={settings?.compatible_overrides?.top_p ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("top_p", event.target.value === "" ? undefined : Number(event.target.value))} /></label>
                            <label className="chronicle-setting-field"><span>Frequency Penalty</span><input type="number" min={-2} max={2} step={0.01} value={settings?.compatible_overrides?.frequency_penalty ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("frequency_penalty", event.target.value === "" ? undefined : Number(event.target.value))} /></label>
                            <label className="chronicle-setting-field"><span>Presence Penalty</span><input type="number" min={-2} max={2} step={0.01} value={settings?.compatible_overrides?.presence_penalty ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("presence_penalty", event.target.value === "" ? undefined : Number(event.target.value))} /></label>
                            <label className="chronicle-setting-field"><span>Seed</span><input type="number" step={1} value={settings?.compatible_overrides?.seed ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("seed", event.target.value === "" ? undefined : Number(event.target.value))} /></label>
                            <label className="chronicle-setting-field"><span>Stop Sequences</span><textarea rows={2} value={Array.isArray(settings?.compatible_overrides?.stop) ? settings.compatible_overrides.stop.join("\n") : settings?.compatible_overrides?.stop ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("stop", event.target.value ? event.target.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) : undefined)} /></label>
                            <label className="chronicle-setting-field"><span>Reasoning Effort</span><select value={settings?.compatible_overrides?.reasoning_effort ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("reasoning_effort", event.target.value || undefined)}><option value="">Provider Default</option><option value="minimal">Minimal</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
                            <label className="chronicle-setting-field"><span>Verbosity</span><select value={settings?.compatible_overrides?.verbosity ?? ""} disabled={!settings} onChange={(event) => updateCompatibleOverride("verbosity", event.target.value || undefined)}><option value="">Provider Default</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
                          </div>
                        </div>
                      </div>
                    )}
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
