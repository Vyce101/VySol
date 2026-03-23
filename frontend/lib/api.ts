/**
 * Central API utility — all fetch calls go through here.
 * Prepends NEXT_PUBLIC_API_URL. No component hardcodes localhost:8000.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
    status: number;
    detail?: unknown;

    constructor(status: number, message: string, detail?: unknown) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
    }
}

export type EntityResolutionMode = "exact_only" | "exact_then_ai";
export type EntityResolutionRunMode = EntityResolutionMode | "ai_only";

export interface EntityResolutionStartRequest {
    top_k: number;
    resolution_mode: EntityResolutionMode;
    embedding_batch_size?: number;
    embedding_cooldown_seconds?: number;
}

export interface EntityResolutionStatus {
    status?: string;
    phase?: string;
    message?: string;
    reason?: string;
    can_resume?: boolean;
    total_entities?: number;
    resolved_entities?: number;
    unresolved_entities?: number;
    auto_resolved_pairs?: number;
    top_k?: number;
    embedding_batch_size?: number;
    embedding_cooldown_seconds?: number;
    resolution_mode?: EntityResolutionRunMode;
    include_normalized_exact_pass?: boolean;
    review_mode?: boolean;
    new_nodes_since_last_completed_resolution?: number | null;
    current_anchor?: {
        node_id?: string;
        display_name?: string;
        description?: string;
    };
    current_anchor_label?: string;
    current_candidates?: Array<{
        node_id?: string;
        display_name?: string;
        description?: string;
        score?: number;
    }>;
    [key: string]: unknown;
}

export interface EntityResolutionEvent extends Record<string, unknown> {
    event?: string;
    status?: string;
    phase?: string;
    message?: string;
    reason?: string;
}

export function entityResolutionPaths(worldId: string) {
    const base = `/worlds/${worldId}/entity-resolution`;
    return {
        start: `${base}/start`,
        status: `${base}/status`,
        events: `${base}/events`,
        abort: `${base}/abort`,
        current: `${base}/current`,
    };
}

function normalizeFetchError(err: unknown): Error {
    if (err instanceof Error) {
        const message = err.message || "Unexpected error";
        if (
            err.name === "TypeError" &&
            (/fetch/i.test(message) || /networkerror/i.test(message) || /resource/i.test(message))
        ) {
            return new Error(`Could not reach the backend at ${API_BASE}. Make sure the API server is running.`);
        }
        return err;
    }
    return new Error("Unexpected error");
}

export async function apiFetch<T = unknown>(
    path: string,
    options: RequestInit = {}
): Promise<T> {
    const url = `${API_BASE}${path}`;
    let res: Response;
    try {
        res = await fetch(url, {
            ...options,
            headers: {
                "Content-Type": "application/json",
                ...options.headers,
            },
        });
    } catch (err) {
        throw normalizeFetchError(err);
    }

    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new ApiError(res.status, body.detail || `API error ${res.status}`, body);
    }

    return res.json();
}

export async function apiUpload<T = unknown>(
    path: string,
    formData: FormData
): Promise<T> {
    const url = `${API_BASE}${path}`;
    let res: Response;
    try {
        res = await fetch(url, { method: "POST", body: formData });
    } catch (err) {
        throw normalizeFetchError(err);
    }

    if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new ApiError(res.status, body.detail || `API error ${res.status}`, body);
    }

    return res.json();
}

export async function startEntityResolution(
    worldId: string,
    body: EntityResolutionStartRequest
): Promise<unknown> {
    return apiFetch(entityResolutionPaths(worldId).start, {
        method: "POST",
        body: JSON.stringify(body),
    });
}

export async function getEntityResolutionStatus(
    worldId: string
): Promise<EntityResolutionStatus> {
    return apiFetch<EntityResolutionStatus>(entityResolutionPaths(worldId).status);
}

export async function getEntityResolutionCurrent(
    worldId: string
): Promise<EntityResolutionStatus> {
    return apiFetch<EntityResolutionStatus>(entityResolutionPaths(worldId).current);
}

export async function abortEntityResolution(worldId: string): Promise<unknown> {
    return apiFetch(entityResolutionPaths(worldId).abort, { method: "POST" });
}

export function streamEntityResolutionEvents(
    worldId: string,
    onEvent: (data: EntityResolutionEvent) => void,
    onDone?: () => void,
    onError?: (err: Error) => void
): EventSource {
    return apiStreamGet(
        entityResolutionPaths(worldId).events,
        (data) => onEvent(data as EntityResolutionEvent),
        onDone,
        onError
    );
}

/**
 * Stream SSE from a POST endpoint.
 * Returns a reader that yields parsed JSON objects.
 */
export async function apiStreamPost(
    path: string,
    body: object,
    onEvent: (data: Record<string, unknown>) => void,
    onDone?: () => void,
    onError?: (err: Error) => void,
    options: { signal?: AbortSignal } = {}
): Promise<void> {
    const url = `${API_BASE}${path}`;
    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: options.signal,
        });

        if (!res.ok) {
            const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
            throw new ApiError(res.status, errorBody.detail || `API error ${res.status}`, errorBody);
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";
        let sawTerminalEvent = false;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.startsWith("data: ")) {
                    try {
                        const data = JSON.parse(trimmed.slice(6));
                        if (data.event === "error") {
                            throw new Error(
                                typeof data.message === "string"
                                    ? data.message
                                    : "The server failed while processing the chat request."
                            );
                        }
                        onEvent(data);
                        if (data.event === "done" || data.event === "complete") {
                            sawTerminalEvent = true;
                            onDone?.();
                            return;
                        }
                    } catch (err) {
                        if (err instanceof Error) {
                            throw err;
                        }
                        // skip malformed JSON
                    }
                }
            }
        }
        if (!sawTerminalEvent) {
            throw new Error("Chat stream ended before the reply was fully saved.");
        }
    } catch (err) {
        if ((err instanceof Error && err.name === "AbortError") || options.signal?.aborted) {
            return;
        }
        onError?.(normalizeFetchError(err));
    }
}

/**
 * Stream SSE from a GET endpoint.
 */
export function apiStreamGet(
    path: string,
    onEvent: (data: Record<string, unknown>) => void,
    onDone?: () => void,
    onError?: (err: Error) => void
): EventSource {
    const url = `${API_BASE}${path}`;
    const es = new EventSource(url);
    let terminal = false;

    es.onmessage = (ev) => {
        try {
            const data = JSON.parse(ev.data);
            onEvent(data);
            const ingestionStatus = typeof data.ingestion_status === "string" ? data.ingestion_status : undefined;
            const status = typeof data.status === "string" ? data.status : undefined;
            const isTerminalStatus = (
                (ingestionStatus && ingestionStatus !== "in_progress")
                || (status && ["complete", "aborted", "error", "partial_failure"].includes(status))
            );
            if (
                data.event === "complete"
                || data.event === "aborted"
                || data.event === "error"
                || (data.event === "status" && isTerminalStatus)
            ) {
                terminal = true;
                es.close();
                onDone?.();
            }
        } catch {
            // skip
        }
    };

    es.onerror = () => {
        es.close();
        if (!terminal) {
            onError?.(new Error("SSE connection error"));
        }
    };

    return es;
}
