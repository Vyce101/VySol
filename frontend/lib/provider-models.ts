export const CUSTOM_MODEL_OPTION_VALUE = "__custom__";

export type SlotKey = "flash" | "chat" | "entity_chooser" | "entity_combiner" | "embedding";
export type ModelTask = "chat" | "embedding";

export interface ProviderFieldMeta {
    name: string;
    label: string;
    secret?: boolean;
    multiline?: boolean;
    help_text?: string;
}

export interface ProviderReasoningOption {
    value: string;
    label: string;
}

export interface ParamDefinition {
    name: string;
    label: string;
    type: "number" | "integer" | "enum" | "json";
    min?: number;
    max?: number;
    step?: number;
    options?: ProviderReasoningOption[];
    help_text?: string;
    tasks?: ModelTask[];
}

export interface ProviderModelOption {
    value: string;
    label: string;
    task: ModelTask;
    mode?: string;
    catalog_source?: string;
    max_input_tokens?: number | null;
    max_output_tokens?: number | null;
    output_vector_size?: number | null;
    supports_function_calling?: boolean;
    supports_response_schema?: boolean;
    supports_vision?: boolean;
    litellm_provider?: string;
    supported_params?: string[];
}

export interface CatalogProvider {
    id: string;
    display_name: string;
    supported_slots: SlotKey[];
    supported_tasks: ModelTask[];
    required_credential_fields: string[];
    credential_fields: ProviderFieldMeta[];
    catalog_source?: string;
    custom_model_first?: boolean;
    selectable?: boolean;
    placeholder_models?: Partial<Record<ModelTask, string>>;
    notes?: string | null;
    models: Record<ModelTask, ProviderModelOption[]>;
    provider_param_defs: ParamDefinition[];
}

export interface AICatalog {
    litellm_version: string;
    slots: Record<SlotKey, { task: ModelTask }>;
    providers: Record<string, CatalogProvider>;
    common_params: Record<ModelTask, ParamDefinition[]>;
}

export interface SlotConfig {
    provider: string;
    model: string;
    task: ModelTask;
    params: Record<string, unknown>;
}

export interface ProviderMeta {
    id: string;
    display_name: string;
    family: string;
    supported_slots: string[];
    required_credential_fields: string[];
    credential_fields: ProviderFieldMeta[];
    supports_embedding: boolean;
    supports_gemini_safety: boolean;
    supports_groq_reasoning: boolean;
    supports_gemini_thinking: boolean;
    text_model_options?: ProviderModelOption[];
    embedding_model_options?: ProviderModelOption[];
}

export interface ProviderCapabilities {
    providers: Record<string, ProviderMeta>;
    families: Record<string, { default: string; options: Array<{ value: string; label: string }> }>;
    openai_compatible_providers: Array<{ value: string; label: string }>;
}

export interface ParamUiShape {
    typed: ParamDefinition[];
    providerSpecific: ParamDefinition[];
    rawSupportedNames: string[];
}

function normalizeModelValue(value: string): string {
    return value.trim().toLowerCase();
}

export function listCatalogProviders(
    catalog: AICatalog | null | undefined,
    slot?: SlotKey,
): CatalogProvider[] {
    const providers = Object.values(catalog?.providers ?? {});
    const filtered = slot
        ? providers.filter((provider) => provider.selectable !== false && provider.supported_slots.includes(slot))
        : providers.filter((provider) => provider.selectable !== false);
    return filtered.slice().sort((left, right) => left.display_name.localeCompare(right.display_name));
}

export function getCatalogProvider(
    catalog: AICatalog | null | undefined,
    provider: string,
): CatalogProvider | null {
    return catalog?.providers?.[provider] ?? null;
}

export function getSlotTask(
    catalog: AICatalog | null | undefined,
    slot: SlotKey,
): ModelTask {
    return catalog?.slots?.[slot]?.task ?? (slot === "embedding" ? "embedding" : "chat");
}

export function getProviderModels(
    catalog: AICatalog | null | undefined,
    provider: string,
    task: ModelTask,
): ProviderModelOption[] {
    return catalog?.providers?.[provider]?.models?.[task] ?? [];
}

export function providerUsesCustomModelField(
    catalog: AICatalog | null | undefined,
    provider: string,
): boolean {
    return Boolean(catalog?.providers?.[provider]?.custom_model_first);
}

export function getProviderModelPlaceholder(
    catalog: AICatalog | null | undefined,
    provider: string,
    task: ModelTask,
): string {
    const explicit = String(catalog?.providers?.[provider]?.placeholder_models?.[task] ?? "").trim();
    if (explicit) {
        return explicit;
    }
    return String(getProviderModels(catalog, provider, task)[0]?.value ?? "").trim();
}

export function findProviderModelOption(
    options: ProviderModelOption[],
    modelValue: string,
): ProviderModelOption | null {
    const normalized = normalizeModelValue(modelValue);
    if (!normalized) return null;
    return options.find((option) => {
        const optionValue = normalizeModelValue(option.value);
        if (optionValue === normalized) {
            return true;
        }
        if (optionValue.endsWith("-preview") && optionValue.slice(0, -"-preview".length) === normalized) {
            return true;
        }
        return false;
    }) ?? null;
}

export function findCatalogModel(
    catalog: AICatalog | null | undefined,
    provider: string,
    task: ModelTask,
    modelValue: string,
): ProviderModelOption | null {
    return findProviderModelOption(getProviderModels(catalog, provider, task), modelValue);
}

export function getModelPickerValue(
    options: ProviderModelOption[],
    modelValue: string,
): string {
    return findProviderModelOption(options, modelValue)?.value ?? CUSTOM_MODEL_OPTION_VALUE;
}

export function getFirstCatalogModelValue(
    catalog: AICatalog | null | undefined,
    provider: string,
    task: ModelTask,
): string | null {
    const first = getProviderModels(catalog, provider, task)[0];
    return first?.value ?? null;
}

export function getParamUiShape(
    catalog: AICatalog | null | undefined,
    provider: string,
    task: ModelTask,
    modelValue: string,
): ParamUiShape {
    const providerEntry = getCatalogProvider(catalog, provider);
    const modelEntry = findCatalogModel(catalog, provider, task, modelValue);
    const supportedNames = new Set((modelEntry?.supported_params ?? []).map((item) => String(item)));
    if (!modelEntry && providerUsesCustomModelField(catalog, provider)) {
        for (const definition of catalog?.common_params?.[task] ?? []) {
            supportedNames.add(definition.name);
        }
    }
    const typed = (catalog?.common_params?.[task] ?? []).filter((definition) => supportedNames.has(definition.name));
    const providerSpecific = (providerEntry?.provider_param_defs ?? []).filter((definition) => {
        if (definition.tasks?.length && !definition.tasks.includes(task)) {
            return false;
        }
        return true;
    });
    const knownNames = new Set<string>([
        ...typed.map((definition) => definition.name),
        ...providerSpecific.map((definition) => definition.name),
    ]);
    const rawSupportedNames = Array.from(supportedNames)
        .filter((name) => !knownNames.has(name))
        .sort((left, right) => left.localeCompare(right));
    return {
        typed,
        providerSpecific,
        rawSupportedNames,
    };
}

export function sanitizeSlotParamsForModel(
    catalog: AICatalog | null | undefined,
    slotConfig: SlotConfig,
    provider: string,
    modelValue: string,
    task: ModelTask,
): Record<string, unknown> {
    const modelEntry = findCatalogModel(catalog, provider, task, modelValue);
    const providerEntry = getCatalogProvider(catalog, provider);
    const supportedNames = new Set((modelEntry?.supported_params ?? []).map((item) => String(item)));
    if (!modelEntry && providerUsesCustomModelField(catalog, provider)) {
        for (const definition of catalog?.common_params?.[task] ?? []) {
            supportedNames.add(definition.name);
        }
    }
    for (const definition of providerEntry?.provider_param_defs ?? []) {
        if (!definition.tasks?.length || definition.tasks.includes(task)) {
            supportedNames.add(definition.name);
        }
    }
    const nextParams: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(slotConfig.params ?? {})) {
        if (supportedNames.has(key)) {
            nextParams[key] = value;
        }
    }
    return nextParams;
}

export function buildModelOptionsWithCurrent(
    options: ProviderModelOption[],
    currentValue: string,
): ProviderModelOption[] {
    if (!currentValue.trim()) {
        return options;
    }
    const existing = findProviderModelOption(options, currentValue);
    if (existing) {
        return options;
    }
    return [
        {
            value: currentValue,
            label: `${currentValue} (Unlisted)`,
            task: options[0]?.task ?? "chat",
            supported_params: [],
        },
        ...options,
    ];
}

export function formatProviderLabel(
    catalog: AICatalog | null | undefined,
    provider?: string | null,
): string {
    const normalized = String(provider ?? "").trim();
    if (!normalized) return "-";
    const providerEntry = catalog?.providers?.[normalized];
    if (providerEntry?.display_name) {
        return providerEntry.display_name;
    }
    return normalized
        .split("_")
        .map((part) => part ? `${part[0].toUpperCase()}${part.slice(1)}` : part)
        .join(" ");
}
