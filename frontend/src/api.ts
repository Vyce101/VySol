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

export type Outcome = {
  status: "done" | "pending" | "unknown";
  error?: string | null;
  message?: string;
  book_id?: string;
};

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

export async function sendBook(
  worldId: string,
  operationId: string,
  file: File,
): Promise<Outcome> {
  const path = `/worlds/${worldId}/imports/${operationId}`;
  try {
    return await api<Outcome>(path, {
      method: "PUT",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
  } catch (error) {
    // Never blindly retry a request that may already have committed on the server.
    for (let attempt = 0; attempt < 15; attempt++) {
      const result = await api<Outcome>(path).catch(() => null);
      if (result?.status === "done") return result;
      if (result?.status === "unknown") throw error;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(
      "Could not confirm the import. Retry to check it again safely.",
    );
  }
}
