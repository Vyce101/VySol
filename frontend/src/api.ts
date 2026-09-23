export type World = {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  artwork: string;
};
export type Speed = "fast" | "normal" | "slow";
export type WorldLayout = "shelf" | "grid";
export type Settings = { background_speed: Speed; world_layout: WorldLayout };
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
export type ProviderKey = { id: string; name: string; provider: string };
export type Providers = {
  keys: ProviderKey[];
  models: { id: string; name: string; provider: string }[];
  defaults: { model: string; key_id: string };
};

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
  return response.json();
}

export const jsonRequest = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
