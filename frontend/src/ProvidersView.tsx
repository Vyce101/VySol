import { CaretDown, Eye, EyeSlash, Plus } from "@phosphor-icons/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, jsonRequest } from "./api";
import { EmbeddingProfiles } from "./EmbeddingProfiles";
import { providerModelAge } from "./providerModelAge";

type Credential = {
  id: string;
  name: string;
  provider: string;
  sequence: number;
  connection_id: string;
  base_url?: string | null;
  models?: { id: string; name: string; provider: string; tested?: boolean }[];
  models_updated_at?: string | null;
  models_error?: string | null;
};

type ProviderConnection = {
  id: string;
  provider: string;
  credentials: Credential[];
  enabled?: boolean;
  next_sequence?: number;
};

type ProviderResponse = {
  keys: Credential[];
  connections?: ProviderConnection[];
};

const providers = [
  { id: "anthropic", name: "Anthropic" },
  { id: "deepseek", name: "DeepSeek" },
  { id: "google", name: "Google" },
  { id: "openai", name: "OpenAI" },
  { id: "openai_compatible", name: "OpenAI-compatible" },
] as const;
function providerName(provider: string) {
  return providers.find((item) => item.id === provider)?.name ?? provider;
}

function sortCredentials(credentials: Credential[]) {
  return [...credentials].sort((left, right) => left.sequence - right.sequence);
}

function nextCredentialSequence(credentials: Credential[]) {
  const used = new Set(credentials.map((credential) => credential.sequence));
  let sequence = 1;
  while (used.has(sequence)) sequence += 1;
  return sequence;
}

function getConnections(data: ProviderResponse): ProviderConnection[] {
  if (data.connections) {
    const existing = new Map(data.connections.map((connection) => [connection.provider, connection]));
    return providers.map(({ id }) => {
      const connection = existing.get(id);
      return connection
        ? {
            ...connection,
            enabled: connection.enabled ?? true,
            credentials: sortCredentials(connection.credentials),
          }
        : { id: `provider-${id}`, provider: id, enabled: false, credentials: [] };
    });
  }

  // Keep older saved keys visible while the local store is upgraded.
  const credentials = sortCredentials(data.keys ?? []);
  return providers.map(({ id }) => {
    const providerCredentials = credentials.filter((credential) => credential.provider === id);
    return {
      id: providerCredentials[0]?.connection_id ?? `provider-${id}`,
      provider: id,
      enabled: providerCredentials.length > 0,
      credentials: providerCredentials,
    };
  });
}

export function ProvidersView() {
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [expandedConnections, setExpandedConnections] = useState<Set<string>>(
    () => new Set(),
  );
  const [expandedCredentials, setExpandedCredentials] = useState<Set<string>>(
    () => new Set(),
  );
  const [draftCredential, setDraftCredential] = useState<Credential | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [chooserOpen, setChooserOpen] = useState(false);
  const [leavingProvider, setLeavingProvider] = useState<string | null>(null);
  const [enteringProvider, setEnteringProvider] = useState<string | null>(null);
  const [leavingCredential, setLeavingCredential] = useState<string | null>(null);
  const selectorButtonRef = useRef<HTMLButtonElement>(null);
  const chooserRef = useRef<HTMLDivElement>(null);
  const connectionListRef = useRef<HTMLDivElement>(null);
  const cardPositions = useRef(new Map<string, number>());
  const skipNextConnectionShiftAnimation = useRef(false);

  useLayoutEffect(() => {
    const positions = new Map<string, number>();
    for (const card of connectionListRef.current?.querySelectorAll<HTMLElement>("[data-provider]") ?? []) {
      const provider = card.dataset.provider!;
      const top = card.offsetTop;
      const previous = cardPositions.current.get(provider);
      if (!skipNextConnectionShiftAnimation.current && previous !== undefined && previous !== top &&
          !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        card.animate?.([
          { transform: `translateY(${previous - top}px)` },
          { transform: "translateY(0)" },
        ], { duration: 180, easing: "cubic-bezier(0.2, 0, 0.38, 0.9)" });
      }
      positions.set(provider, top);
    }
    cardPositions.current = positions;
    skipNextConnectionShiftAnimation.current = false;
  }, [connections]);

  useEffect(() => {
    if (!enteringProvider) return;
    const timer = window.setTimeout(() => setEnteringProvider(null), 240);
    return () => window.clearTimeout(timer);
  }, [enteringProvider]);

  useEffect(() => {
    if (!chooserOpen) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      if (
        !selectorButtonRef.current?.contains(event.target as Node) &&
        !chooserRef.current?.contains(event.target as Node)
      ) {
        setChooserOpen(false);
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setChooserOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [chooserOpen]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await api<ProviderResponse>("/providers");
      setConnections(getConnections(data));
    } catch {
      setError("Could not load your AI connections. Try again.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function setProviderEnabled(providerId: string, enabled: boolean) {
    if (busy) return;
    const existing = connections.find(
      (connection) => connection.provider === providerId,
    );
    if ((!existing || existing.id.startsWith("provider-")) && !enabled) return;

    setBusy(true);
    setError("");
    try {
      if (!existing || existing.id.startsWith("provider-")) {
        const created = await api<ProviderConnection>(
          "/providers/connections",
          jsonRequest("POST", { provider: providerId }),
        );
        const connection = {
          ...created,
          enabled: created.enabled ?? true,
          credentials: sortCredentials(created.credentials ?? []),
        };
        if (!connection.enabled) {
          await api<ProviderConnection>(
            `/providers/connections/${connection.id}`,
            jsonRequest("PUT", { enabled: true }),
          );
          connection.enabled = true;
        }
        setConnections((previous) => [
          ...previous.filter((item) => item.provider !== providerId),
          connection,
        ]);
        setEnteringProvider(providerId);
        setExpandedConnections((previous) => new Set(previous).add(connection.id));
        return;
      }

      const updated = await api<ProviderConnection>(
        `/providers/connections/${existing.id}`,
        jsonRequest("PUT", { enabled }),
      );
      if (!enabled && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        setLeavingProvider(providerId);
        await new Promise<void>((resolve) => window.setTimeout(resolve, 190));
        // The list has already closed this card's layout space, so don't replay the
        // same movement when React removes the disabled connection.
        skipNextConnectionShiftAnimation.current = true;
      }
      setConnections((previous) =>
        previous.map((connection) =>
          connection.id === existing.id
            ? { ...connection, enabled: updated.enabled ?? enabled }
            : connection,
        ),
      );
      if (!enabled) {
        setLeavingProvider(null);
        setExpandedConnections((previous) => {
          const next = new Set(previous);
          next.delete(existing.id);
          return next;
        });
        setExpandedCredentials((previous) => {
          const next = new Set(previous);
          for (const credential of existing.credentials) next.delete(credential.id);
          return next;
        });
        setDraftCredential(null);
      } else {
        setEnteringProvider(providerId);
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not update the selected connection.",
      );
    } finally {
      setBusy(false);
    }
  }

  function addCredential(connection: ProviderConnection) {
    const nextSequence = nextCredentialSequence(connection.credentials);
    const credential: Credential = {
      id: crypto.randomUUID(),
      name: "",
      provider: connection.provider,
      sequence: nextSequence,
      connection_id: connection.id,
    };
    setDraftCredential(credential);
    setExpandedConnections((previous) => new Set(previous).add(connection.id));
    setExpandedCredentials((previous) => new Set(previous).add(credential.id));
    setError("");
  }

  async function saveCredential(
    connection: ProviderConnection,
    credential: Credential,
    name: string,
    secret: string,
    baseUrl: string,
  ): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setError("");
    try {
      const saved = await api<Credential>(
        `/providers/keys/${credential.id}`,
        jsonRequest("PUT", {
          name,
          provider: connection.provider,
          connection_id: connection.id,
          ...(connection.provider === "openai_compatible" ? { base_url: baseUrl.trim() } : {}),
          ...(secret ? { secret } : {}),
        }),
      );
      setConnections((previous) =>
        previous.map((item) => {
          if (item.id !== connection.id) return item;
          const credentials = sortCredentials([
            ...item.credentials.filter((entry) => entry.id !== saved.id),
            saved,
          ]);
          return {
            ...item,
            next_sequence: nextCredentialSequence(credentials),
            credentials,
          };
        }),
      );
      setDraftCredential(null);
      setExpandedCredentials((previous) => {
        const next = new Set(previous);
        next.delete(credential.id);
        return next;
      });
      return true;
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not save this credential.",
      );
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function removeCredential(credential: Credential) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/providers/keys/${credential.id}`, { method: "DELETE" });
      if (!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
        setLeavingCredential(credential.id);
        await new Promise<void>((resolve) => window.setTimeout(resolve, 190));
      }
      setConnections((previous) =>
        previous.map((connection) => {
          const credentials = connection.credentials.filter(
            (entry) => entry.id !== credential.id,
          );
          return {
            ...connection,
            credentials,
            next_sequence: nextCredentialSequence(credentials),
          };
        }),
      );
      setDraftCredential(null);
      setExpandedCredentials((previous) => {
        const next = new Set(previous);
        next.delete(credential.id);
        return next;
      });
      setLeavingCredential(null);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not remove this credential.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="providers-view">
      <div className="connections-selector">
        <button
          ref={selectorButtonRef}
          className="select-connections"
          type="button"
          aria-expanded={chooserOpen}
          aria-controls="provider-chooser"
          disabled={loading}
          onClick={() => setChooserOpen((open) => !open)}
        >
          Select Connections
          <CaretDown
            className="selector-caret"
            size={18}
            aria-hidden="true"
          />
        </button>

        <div
          ref={chooserRef}
          id="provider-chooser"
          className={`connection-chooser ${chooserOpen ? "is-open" : ""}`}
          aria-hidden={!chooserOpen}
          inert={!chooserOpen}
        >
          <div className="connection-chooser-inner">
            <h3>Available Providers</h3>
            <div className="provider-choice-list">
              {providers.map((provider) => {
                const connection = connections.find(
                  (item) => item.provider === provider.id,
                );
                return (
                  <label className="provider-choice" key={provider.id}>
                    <span className="provider-choice-name">
                      <strong>{provider.name}</strong>
                    </span>
                    <input
                      type="checkbox"
                      checked={connection?.enabled ?? false}
                      disabled={busy}
                      onChange={(event) =>
                        void setProviderEnabled(provider.id, event.target.checked)
                      }
                      aria-label={provider.name}
                    />
                  </label>
                );
              })}
            </div>
            {error && <p className="chooser-error" role="alert">{error}</p>}
          </div>
        </div>
      </div>

      {loading ? (
        <p className="providers-loading" role="status">
          Loading connections…
        </p>
      ) : (
        <>
          {connections.some((connection) => connection.enabled) && (
            <div className="connection-card-list" ref={connectionListRef}>
              {connections
                .filter((connection) => connection.enabled)
                .sort((left, right) =>
                  providerName(left.provider).localeCompare(providerName(right.provider)),
                )
                .map((connection) => {
                  const isExpanded = expandedConnections.has(connection.id);
                  const draft =
                    draftCredential?.connection_id === connection.id
                      ? draftCredential
                      : null;
                  const credentials = sortCredentials([
                    ...connection.credentials,
                    ...(draft ? [draft] : []),
                  ]);
                  const isLeaving = leavingProvider === connection.provider;
                  const isEntering = enteringProvider === connection.provider;

                  return (
                    <div
                      className={`connection-card-track${isLeaving ? " is-leaving" : ""}${isEntering ? " is-entering" : ""}`}
                      key={connection.id}
                      data-provider={connection.provider}
                    >
                      <section className="connection-card">
                        <button
                          className="connection-heading"
                          type="button"
                          aria-expanded={isExpanded}
                          aria-controls={`connection-content-${connection.id}`}
                          onClick={() => {
                            setExpandedConnections((previous) => {
                              const next = new Set(previous);
                              if (isExpanded) next.delete(connection.id);
                              else next.add(connection.id);
                              return next;
                            });
                          }}
                        >
                          <span className="connection-name">
                            {providerName(connection.provider)}
                          </span>
                          <CaretDown
                            className="connection-caret"
                            size={20}
                            aria-hidden="true"
                          />
                        </button>

                        <div
                          id={`connection-content-${connection.id}`}
                          className={`connection-disclosure ${isExpanded ? "is-open" : ""}`}
                          aria-hidden={!isExpanded}
                          inert={!isExpanded}
                        >
                          <div className="connection-disclosure-inner">
                            <div className="connection-content">
                              <div className="credential-list">
                                {credentials.map((credential) => (
                                  <CredentialDisclosure
                                    key={credential.id}
                                    credential={credential}
                                    leaving={leavingCredential === credential.id}
                                    expanded={expandedConnections.has(connection.id) && expandedCredentials.has(credential.id)}
                                    busy={busy}
                                    onToggle={() => setExpandedCredentials((previous) => {
                                      const next = new Set(previous);
                                      if (next.has(credential.id)) next.delete(credential.id);
                                      else next.add(credential.id);
                                      return next;
                                    })}
                                    onSave={(name, secret, baseUrl) =>
                                      saveCredential(connection, credential, name, secret, baseUrl)
                                    }
                                    onRemove={() => {
                                      if (draft?.id === credential.id) {
                                        setDraftCredential(null);
                                        setExpandedCredentials((previous) => {
                                          const next = new Set(previous);
                                          next.delete(credential.id);
                                          return next;
                                        });
                                        return;
                                      }
                                      void removeCredential(credential);
                                    }}
                                  />
                                ))}
                              </div>

                              {!draft && (
                                <button
                                  className="add-credential"
                                  type="button"
                                  disabled={busy}
                                  onClick={() => addCredential(connection)}
                                >
                                  <Plus size={18} /> Add Credential
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      </section>
                    </div>
                  );
                })}
            </div>
          )}
        </>
      )}

      {!loading && <EmbeddingProfiles />}

      {error && !chooserOpen && (
        <p className="provider-error" role="alert">
          {error}
          {loading ? null : (
            <button type="button" onClick={() => void load()}>
              Try again
            </button>
          )}
        </p>
      )}
    </div>
  );
}

function CredentialDisclosure({
  credential,
  leaving,
  expanded,
  busy,
  onToggle,
  onSave,
  onRemove,
}: {
  credential: Credential;
  leaving: boolean;
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onSave: (name: string, secret: string, baseUrl: string) => Promise<boolean>;
  onRemove: () => void;
}) {
  const isNew = !credential.name;
  const isCompatible = credential.provider === "openai_compatible";
  const [name, setName] = useState(credential.name);
  const [baseUrl, setBaseUrl] = useState(credential.base_url ?? "");
  const [secret, setSecret] = useState("");
  const [storedSecret, setStoredSecret] = useState<string | null>(null);
  const [secretVisible, setSecretVisible] = useState(false);
  const [loadingSecret, setLoadingSecret] = useState(false);
  const [secretError, setSecretError] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const revealRequestGeneration = useRef(0);

  useLayoutEffect(() => {
    revealRequestGeneration.current += 1;
  }, [expanded, credential.id, credential.name]);

  useLayoutEffect(
    () => () => {
      revealRequestGeneration.current += 1;
    },
    [],
  );

  useEffect(() => {
    setName(credential.name);
    setBaseUrl(credential.base_url ?? "");
    setSecret("");
    setStoredSecret(null);
    setSecretVisible(false);
    setLoadingSecret(false);
  }, [credential.id, credential.name]);

  useEffect(() => {
    if (expanded) return;
    setSecretVisible(false);
    setLoadingSecret(false);
    setSecretError("");
    if (storedSecret !== null && secret === storedSecret) {
      setSecret("");
      setStoredSecret(null);
    }
  }, [expanded, secret, storedSecret]);

  async function toggleSecretVisibility() {
    setSecretError("");
    if (secretVisible) {
      setSecretVisible(false);
      if (storedSecret !== null && secret === storedSecret) {
        setSecret("");
        setStoredSecret(null);
      }
      return;
    }

    if (secret || isNew) {
      setSecretVisible(true);
      return;
    }

    const generation = revealRequestGeneration.current + 1;
    revealRequestGeneration.current = generation;
    setLoadingSecret(true);
    try {
      const response = await api<{ secret: string }>(
        `/providers/keys/${credential.id}/secret`,
      );
      if (generation !== revealRequestGeneration.current) return;
      setSecret(response.secret);
      setStoredSecret(response.secret);
      setSecretVisible(true);
    } catch {
      if (generation === revealRequestGeneration.current) {
        setSecretError("Could not reveal this API key. Try again.");
      }
    } finally {
      if (generation === revealRequestGeneration.current) {
        setLoadingSecret(false);
      }
    }
  }

  return (
    <div className={`credential-card-track${leaving ? " is-leaving" : ""}`}>
      <section className="credential-card">
        <button
          className="credential-heading"
          type="button"
          aria-expanded={expanded}
          aria-controls={`credential-content-${credential.id}`}
          onClick={onToggle}
        >
          <span className="credential-name">Credential {credential.sequence}</span>
          {credential.name && <span className="credential-custom-name">{credential.name}</span>}
          <CaretDown
            className="credential-caret"
            size={17}
            aria-hidden="true"
          />
        </button>
      <div
        id={`credential-content-${credential.id}`}
        className={`credential-disclosure ${expanded ? "is-open" : ""}`}
        aria-hidden={!expanded}
        inert={!expanded}
      >
        <div className="credential-disclosure-inner">
          <form
            className="credential-form"
            onSubmit={(event) => {
              event.preventDefault();
              void onSave(name, secret, baseUrl).then((saved) => {
                if (saved) {
                  setSecret("");
                  setStoredSecret(null);
                  setSecretVisible(false);
                }
              });
            }}
          >
            <div className="credential-field">
              <label htmlFor={`credential-name-${credential.id}`}>Connection Name</label>
              <input
                id={`credential-name-${credential.id}`}
                value={name}
                maxLength={100}
                required
                placeholder={`Personal ${providerName(credential.provider)} connection`}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            {isCompatible && (
              <div className="credential-field">
                <label htmlFor={`credential-base-url-${credential.id}`}>Base URL</label>
                <input
                  id={`credential-base-url-${credential.id}`}
                  type="url"
                  value={baseUrl}
                  required
                  readOnly={!isNew}
                  placeholder="https://api.example.com/v1"
                  aria-describedby={`credential-base-url-help-${credential.id}`}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
                <span id={`credential-base-url-help-${credential.id}`} className="credential-help">
                  This address stays fixed after you save the connection.
                </span>
              </div>
            )}
            <div className="credential-field">
              <label htmlFor={`credential-secret-${credential.id}`}>API Key</label>
              <div className="credential-secret-control">
                <input
                  id={`credential-secret-${credential.id}`}
                  type={secretVisible ? "text" : "password"}
                  autoComplete="new-password"
                  value={secret}
                  maxLength={1280}
                  required={isNew && !isCompatible}
                  placeholder={isNew ? (isCompatible ? "Optional API key" : "Enter API key") : "••••••••••••••••••••"}
                  onChange={(event) => {
                    setSecret(event.target.value);
                    setSecretError("");
                  }}
                />
                <button
                  className="secret-visibility"
                  type="button"
                  aria-label={secretVisible ? "Hide API Key" : "Show API Key"}
                  disabled={busy || loadingSecret}
                  onClick={() => void toggleSecretVisibility()}
                >
                  {secretVisible ? (
                    <EyeSlash size={18} aria-hidden="true" />
                  ) : (
                    <Eye size={18} aria-hidden="true" />
                  )}
                </button>
              </div>
              {loadingSecret && <span className="secret-loading">Loading API key…</span>}
              {secretError && <span className="secret-error" role="alert">{secretError}</span>}
            </div>
            {!isNew && (
              <div className="credential-models">
                <div className="credential-models-heading">
                  <span>Available Models</span>
                </div>
                {credential.models_updated_at && (
                  <span className="credential-models-meta" title={new Date(credential.models_updated_at).toLocaleString()}>
                    Last checked {providerModelAge(credential.models_updated_at)}
                  </span>
                )}
                {credential.models_error && (
                  <span className="credential-models-error" role="status">
                    {credential.models_error} {credential.models?.length ? "Showing the last successful list." : ""}
                  </span>
                )}
                {!credential.models_updated_at && !credential.models_error && (
                  <span className="credential-models-meta">Model list has not been checked yet.</span>
                )}
                {credential.models_updated_at && !credential.models?.length && !credential.models_error && (
                  <span className="credential-models-meta">No models were returned.</span>
                )}
                {credential.models?.length ? (
                  <span className="credential-models-meta">
                    {credential.models.length} models available for this connection.
                  </span>
                ) : null}
              </div>
            )}
            <div className="credential-action-state">
              <div
                className={`credential-confirmation${confirmRemove ? " is-open" : ""}`}
                role="alertdialog"
                aria-label="Remove credential"
                aria-hidden={!confirmRemove}
                inert={!confirmRemove}
              >
                <p>Remove Credential {credential.sequence}?</p>
                <button
                  type="button"
                  className="secondary-action"
                  disabled={busy}
                  onClick={() => setConfirmRemove(false)}
                >
                  Keep Credential
                </button>
                <button
                  type="button"
                  className="danger-action"
                  disabled={busy}
                  onClick={onRemove}
                >
                  Remove Credential
                </button>
              </div>
              <div
                className={`credential-actions${confirmRemove ? " is-hidden" : ""}`}
                aria-hidden={confirmRemove}
                inert={confirmRemove}
              >
                {isNew ? (
                  <button
                    type="button"
                    className="secondary-action"
                    disabled={busy}
                    onClick={onRemove}
                  >
                    Cancel
                  </button>
                ) : (
                  <button
                    type="button"
                    className="danger-link"
                    disabled={busy}
                    onClick={() => setConfirmRemove(true)}
                  >
                    Remove
                  </button>
                )}
                <button
                  type="submit"
                  className="primary-button"
                  disabled={busy || !name.trim() || (isNew && !isCompatible && !secret.trim()) || (isCompatible && !baseUrl.trim())}
                >
                  {busy ? "Saving…" : "Save Changes"}
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
      </section>
    </div>
  );
}
