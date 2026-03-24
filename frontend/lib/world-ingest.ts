import type { ProviderCapabilities } from "@/lib/provider-models";

export type WorldIngestPromptKey =
    | "graph_architect_prompt"
    | "graph_architect_glean_prompt"
    | "entity_resolution_chooser_prompt"
    | "entity_resolution_combiner_prompt";

export interface WorldPromptState {
    value: string;
    source: "world" | "global" | "default";
}

export interface WorldIngestSettings {
    chunk_size_chars: number;
    chunk_overlap_chars: number;
    embedding_provider: string;
    embedding_openai_compatible_provider: string;
    embedding_model: string;
    glean_amount: number;
    locked_at?: string | null;
    last_ingest_settings_at?: string | null;
}

export interface WorldIngestConfigResponse {
    ingest_settings: WorldIngestSettings;
    prompts: Record<WorldIngestPromptKey, WorldPromptState>;
    has_active_chunk_overrides: boolean;
    active_chunk_override_count: number;
    provider_registry: ProviderCapabilities;
}

export const WORLD_INGEST_PROMPT_FIELDS: Array<{ key: WorldIngestPromptKey; label: string }> = [
    { key: "graph_architect_prompt", label: "Graph Architect Prompt" },
    { key: "graph_architect_glean_prompt", label: "Graph Architect Glean Prompt" },
    { key: "entity_resolution_chooser_prompt", label: "Entity Resolution Chooser Prompt" },
    { key: "entity_resolution_combiner_prompt", label: "Entity Resolution Combiner Prompt" },
];

export function formatPromptSourceLabel(source?: string | null): string {
    const normalized = String(source ?? "").trim().toLowerCase();
    if (normalized === "world") return "world";
    if (normalized === "global") return "global";
    return "default";
}

export function formatEmbeddingProviderLabel(
    provider?: string | null,
    openAiCompatibleProvider?: string | null,
): string {
    const family = String(provider ?? "").trim().toLowerCase();
    if (family === "gemini") return "Google (Gemini)";
    if (family === "openai_compatible") {
        const implementation = String(openAiCompatibleProvider ?? "").trim();
        return implementation ? `OpenAI-compatible > ${implementation[0].toUpperCase()}${implementation.slice(1)}` : "OpenAI-compatible";
    }
    if (family === "intenserp") return "IntenseRP Next";
    return String(provider ?? "").trim() || "-";
}
