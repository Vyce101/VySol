import { useEffect, useState } from "react";
import { Plus } from "@phosphor-icons/react";
import { api, jsonRequest, type ProviderKey, type Providers } from "./api";

export function ProvidersView() {
  const [keys, setKeys] = useState<ProviderKey[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  async function load() {
    setError("");
    setLoading(true);
    try {
      setKeys((await api<Providers>("/providers")).keys);
    } catch {
      setError("Could not load your saved keys. Try again.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  function edit(key?: ProviderKey) {
    setEditing(key?.id ?? crypto.randomUUID());
    setName(key?.name ?? "");
    setSecret("");
    setError("");
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!editing || busy) return;
    setBusy(true);
    setError("");
    try {
      const key = await api<ProviderKey>(
        `/providers/keys/${editing}`,
        jsonRequest("PUT", {
          name,
          provider: "google",
          ...(secret ? { secret } : {}),
        }),
      );
      setKeys((previous) => [
        ...previous.filter((item) => item.id !== key.id),
        key,
      ]);
      setSecret("");
      setEditing(null);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not save your key.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/providers/keys/${id}`, { method: "DELETE" });
      setKeys(keys.filter((key) => key.id !== id));
      setDeleting(null);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not remove this key.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="providers-view">
      <p className="muted">
        Name your API keys so you can choose one when creating a world. Secrets
        are saved as plain text in your local credentials folder, which is
        ignored by Git.
      </p>
      {loading ? (
        <p role="status">Loading keys…</p>
      ) : (
        <>
          {keys.length === 0 && !editing && (
            <p className="provider-empty">No API keys yet.</p>
          )}
          {keys.map((key) => (
            <div className="provider-row" key={key.id}>
              <div>
                <strong>{key.name}</strong>
                <p className="muted">Google AI Studio / Gemini API</p>
                <small>Saved locally</small>
              </div>
              <div className="provider-actions">
                <button
                  className="text-action"
                  disabled={busy}
                  onClick={() => edit(key)}
                >
                  Edit<span className="sr-only"> {key.name}</span>
                </button>
                <button
                  className="text-action"
                  disabled={busy}
                  onClick={() => setDeleting(key.id)}
                >
                  Remove<span className="sr-only"> {key.name}</span>
                </button>
              </div>
              {deleting === key.id && (
                <div className="key-confirmation">
                  <p>
                    Remove this saved key? Attempts using it will need another
                    key.
                  </p>
                  <button
                    className="text-action"
                    onClick={() => setDeleting(null)}
                  >
                    Keep key
                  </button>
                  <button
                    className="danger-action"
                    disabled={busy}
                    onClick={() => void remove(key.id)}
                  >
                    Remove key
                  </button>
                </div>
              )}
            </div>
          ))}
          {!editing && (
            <button className="text-action add-provider" onClick={() => edit()}>
              <Plus /> Add API key
            </button>
          )}
        </>
      )}
      {editing && (
        <form className="provider-form" onSubmit={save}>
          <label>
            Provider
            <select disabled>
              <option>Google AI Studio / Gemini API</option>
            </select>
          </label>
          <label>
            Key name
            <input
              value={name}
              maxLength={100}
              required
              onChange={(event) => setName(event.target.value)}
              placeholder="Personal Gemini"
            />
          </label>
          <label>
            {keys.some((key) => key.id === editing)
              ? "Replacement API key (optional)"
              : "API key"}
            <input
              type="password"
              autoComplete="new-password"
              value={secret}
              maxLength={1280}
              required={!keys.some((key) => key.id === editing)}
              onChange={(event) => setSecret(event.target.value)}
            />
          </label>
          <div className="provider-actions">
            <button
              type="button"
              className="text-action"
              disabled={busy}
              onClick={() => {
                setEditing(null);
                setSecret("");
              }}
            >
              Cancel
            </button>
            <button className="primary-button" disabled={busy || !name.trim()}>
              {busy ? "Saving…" : "Save key"}
            </button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="error-message">
          {error}{" "}
          {loading || editing ? null : (
            <button className="text-action" onClick={() => void load()}>
              Reload keys
            </button>
          )}
        </p>
      )}
    </div>
  );
}
