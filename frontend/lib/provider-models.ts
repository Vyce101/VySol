export const CUSTOM_MODEL_OPTION_VALUE = "__custom__";

export interface ProviderFamilyOption {
    value: string;
    label: string;
}

export interface ProviderReasoningOption {
    value: string;
    label: string;
}

export type ModelCapabilityState = "supported" | "unsupported" | "custom";

export interface ModelCapabilityInfo {
    state: ModelCapabilityState;
    option: ProviderModelOption | null;
}

export interface GeminiThinkingUiState extends ModelCapabilityInfo {
    supportedLevels: string[];
}

export interface GroqReasoningUiState extends ModelCapabilityInfo {
    supportedOptions: ProviderReasoningOption[];
}

export interface ProviderModelOption {
    value: string;
    label: string;
    supports_gemini_thinking?: boolean;
    gemini_thinking_levels?: string[];
    supports_groq_reasoning?: boolean;
    groq_reasoning_options?: ProviderReasoningOption[];
    provider?: string;
}

export interface ProviderFieldMeta {
    name: string;
    label: string;
    secret?: boolean;
    multiline?: boolean;
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
    supports_gemini_thinking: boolean;
    supports_groq_reasoning: boolean;
    text_model_options?: ProviderModelOption[];
    embedding_model_options?: ProviderModelOption[];
}

export interface ProviderCapabilities {
    providers: Record<string, ProviderMeta>;
    families: Record<string, { default: string; options: ProviderFamilyOption[] }>;
    openai_compatible_providers: Array<{ value: string; label: string }>;
}

export function getProviderTextModelOptions(
    registry: ProviderCapabilities | null | undefined,
    provider: string,
): ProviderModelOption[] {
    return registry?.providers?.[provider]?.text_model_options ?? [];
}

export function getProviderEmbeddingModelOptions(
    registry: ProviderCapabilities | null | undefined,
    provider: string,
): ProviderModelOption[] {
    return registry?.providers?.[provider]?.embedding_model_options ?? [];
}

export function findProviderModelOption(
    options: ProviderModelOption[],
    modelValue: string,
): ProviderModelOption | null {
    const normalized = modelValue.trim().toLowerCase();
    if (!normalized) return null;
    return options.find((option) => {
        const optionValue = option.value.trim().toLowerCase();
        if (optionValue === normalized) {
            return true;
        }
        if (optionValue.endsWith("-preview") && optionValue.slice(0, -"-preview".length) === normalized) {
            return true;
        }
        return false;
    }) ?? null;
}

export function getModelPickerValue(
    options: ProviderModelOption[],
    modelValue: string,
): string {
    return findProviderModelOption(options, modelValue)?.value ?? CUSTOM_MODEL_OPTION_VALUE;
}

export function getGeminiThinkingLevelsForModel(
    registry: ProviderCapabilities | null | undefined,
    provider: string,
    modelValue: string,
): string[] {
    const option = findProviderModelOption(getProviderTextModelOptions(registry, provider), modelValue);
    return option?.gemini_thinking_levels ?? [];
}

export function getGroqReasoningOptionsForModel(
    registry: ProviderCapabilities | null | undefined,
    provider: string,
    modelValue: string,
): ProviderReasoningOption[] | null {
    const option = findProviderModelOption(getProviderTextModelOptions(registry, provider), modelValue);
    if (!option?.groq_reasoning_options?.length) {
        return null;
    }
    return option.groq_reasoning_options.map((reasoningOption) => {
        if (reasoningOption.value === "default") {
            return {
                ...reasoningOption,
                label: "Reasoning On (provider default)",
            };
        }
        return reasoningOption;
    });
}

export function getGeminiThinkingUiState(
    registry: ProviderCapabilities | null | undefined,
    provider: string,
    modelValue: string,
): GeminiThinkingUiState {
    const option = findProviderModelOption(getProviderTextModelOptions(registry, provider), modelValue);
    const supportedLevels = option?.gemini_thinking_levels ?? [];
    if (!option) {
        return {
            state: "custom",
            option: null,
            supportedLevels: [],
        };
    }
    if (!supportedLevels.length) {
        return {
            state: "unsupported",
            option,
            supportedLevels: [],
        };
    }
    return {
        state: "supported",
        option,
        supportedLevels,
    };
}

export function getGroqReasoningUiState(
    registry: ProviderCapabilities | null | undefined,
    provider: string,
    modelValue: string,
): GroqReasoningUiState {
    const option = findProviderModelOption(getProviderTextModelOptions(registry, provider), modelValue);
    const supportedOptions = getGroqReasoningOptionsForModel(registry, provider, modelValue) ?? [];
    if (!option) {
        return {
            state: "custom",
            option: null,
            supportedOptions: [],
        };
    }
    if (!supportedOptions.length) {
        return {
            state: "unsupported",
            option,
            supportedOptions: [],
        };
    }
    return {
        state: "supported",
        option,
        supportedOptions,
    };
}
