export type World = {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  artwork: string;
  book_count?: number;
};
export type Speed = "fast" | "normal" | "slow";
export type WorldLayout = "shelf" | "grid";
export type ChatAppearance = "focused" | "full_overlay";
export type Settings = { background_speed: Speed; world_layout: WorldLayout; chat_appearance: ChatAppearance };
export type ProcessingConfig = { model: string; size: number; search: number };
export type CreationBook = {
  id: string;
  filename: string;
  size: number;
  position: number;
  uploaded: boolean;
  state: string;
  message: string;
  chunks_total: number;
  chunks_done: number;
};
export type CreationAttempt = {
  id: string;
  name: string;
  revision: number;
  created_at: string;
  updated_at: string;
  state: "paused" | "running" | "pausing" | "failed" | "complete";
  phase: string;
  message: string;
  config: ProcessingConfig;
  key_id: string;
  books: CreationBook[];
  books_done: number;
  chunks_total: number;
  chunks_done: number;
};
export type WorldBook = {
  id: string;
  filename: string;
  position: number;
  state: string;
  chunks_done: number | null;
  chunks_total: number | null;
};
export type WorldProgress = {
  chunks_done: number;
  chunks_total: number;
  books_done: number;
  books_total: number;
};
export type WorldProcessing = {
  model: string | null;
  max_chunk_size: number | null;
  boundary_search_distance: number | null;
};
export type WorldDetail = World & {
  sources_locked: boolean;
  state: "complete" | "running" | "pausing" | "paused" | "failed";
  books: WorldBook[];
  progress: WorldProgress;
  processing: WorldProcessing | null;
};
export type ProviderKey = {
  id: string;
  name: string;
  provider: string;
  connection_id?: string;
};
export type ProviderConnection = {
  id: string;
  provider: string;
  enabled: boolean;
};
export type Providers = {
  keys: ProviderKey[];
  connections?: ProviderConnection[];
  models: { id: string; name: string; provider: string }[];
  chat_models?: ChatModel[];
  defaults: { model: string; key_id: string };
};

export type ChatModel = {
  id: string;
  name: string;
  provider: string;
  series: "Flash" | "Flash Lite" | "Gemma" | string;
};

export type Chronicle = {
  id: string;
  world_id: string;
  title: string;
  created_at: string;
  last_message_at: string | null;
  message_count: number;
  preview: string;
  not_started: boolean;
};

export type ChronicleMessage = {
  id: string;
  request_id?: string;
  streaming_speed?: number;
  role: "user" | "assistant";
  text: string;
  thinking: string | null;
  created_at: string;
  status: "complete" | "partial" | "error" | "stopped" | "streaming";
};

export type ChronicleSettings = {
  model: string;
  key_id: string;
  chunk_count: number;
  minimum_similarity: number;
  chunk_overlap: number;
  streaming_speed: number;
  chat_history_prefix: string;
  chat_history_suffix: string;
  rag_chunks_prefix: string;
  rag_chunks_suffix: string;
  sections: { ai: boolean; retrieval: boolean; response: boolean; section_tags: boolean };
};

export type ChronicleStreamEvent =
  | { type: "user_message"; message: ChronicleMessage }
  | { type: "thinking_delta"; text: string }
  | { type: "answer_delta"; text: string }
  | { type: "completed"; message: ChronicleMessage | null }
  | { type: "error"; message: string; code?: string; assistant?: ChronicleMessage | null };

export function bookCountLabel(count: number): string {
  return `${count} ${count === 1 ? "Book" : "Books"}`;
}

export function attemptLabel(attempt: CreationAttempt): string {
  if (attempt.state === "complete") return "Ready";
  if (attempt.state === "failed") return "Attention";
  if (attempt.state === "paused") return "Paused";
  if (attempt.state === "pausing") return "Pausing…";
  return "Creating";
}

export function attemptProgress(attempt: CreationAttempt): string {
  if (attempt.state === "complete")
    return `${attempt.books.length} books · ${attempt.chunks_total} chunks embedded`;
  if (attempt.phase === "embedding")
    return `${attempt.chunks_done} of ${attempt.chunks_total} chunks embedded`;
  if (attempt.phase === "publishing") return "Saving your world…";
  if (attempt.phase === "uploading")
    return `${attempt.books.filter((book) => book.uploaded).length} of ${attempt.books.length} books uploaded`;
  return `${attempt.books.filter((book) => ["prepared", "embedding", "done"].includes(book.state)).length} of ${attempt.books.length} books prepared`;
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.message || "Something went wrong. Please try again.",
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export async function streamChronicleMessage(
  chronicleId: string,
  requestId: string,
  text: string,
  onEvent: (event: ChronicleStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(
    `/api/chronicles/${encodeURIComponent(chronicleId)}/messages/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ request_id: requestId, text }),
      signal,
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.message || "Your message could not be sent. Please try again.",
    );
  }
  if (!response.body) throw new Error("The response stream is unavailable.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatch = (frame: string) => {
    let name = "message";
    const data: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return;
    const payload = JSON.parse(data.join("\n")) as Record<string, unknown>;
    const eventPayload = payload[name] && typeof payload[name] === "object"
      ? payload[name] as Record<string, unknown>
      : payload;
    if (name === "user_message" && eventPayload.message) {
      onEvent({ type: name, message: eventPayload.message as ChronicleMessage });
    } else if ((name === "thinking_delta" || name === "answer_delta") && typeof eventPayload.text === "string") {
      onEvent({ type: name, text: eventPayload.text });
    } else if (name === "completed" && Object.prototype.hasOwnProperty.call(eventPayload, "message")) {
      onEvent({ type: name, message: eventPayload.message as ChronicleMessage | null });
    } else if (name === "error") {
      onEvent({
        type: name,
        message: typeof eventPayload.message === "string" ? eventPayload.message : "Response generation failed.",
        code: typeof eventPayload.code === "string" ? eventPayload.code : undefined,
        assistant: (eventPayload.assistant ?? null) as ChronicleMessage | null,
      });
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let separator = buffer.search(/\r?\n\r?\n/);
    while (separator >= 0) {
      const frame = buffer.slice(0, separator);
      const match = buffer.slice(separator).match(/^\r?\n\r?\n/);
      buffer = buffer.slice(separator + (match?.[0].length ?? 2));
      dispatch(frame);
      separator = buffer.search(/\r?\n\r?\n/);
    }
    if (done) break;
  }
  if (buffer.trim()) dispatch(buffer);
}

export const jsonRequest = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
