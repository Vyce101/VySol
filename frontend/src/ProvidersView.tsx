import { CaretDown, Plus } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { api, jsonRequest } from "./api";

type Credential = {
  id: string;
  name: string;
  provider: string;
  sequence: number;
  connection_id: string;
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

const providers = [{ id: "google", name: "Google" }] as const;
const googleLogo = "/assets/google-g-logo.svg.webp";

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
    return data.connections.map((connection) => ({
      ...connection,
      enabled: connection.enabled ?? true,
      credentials: sortCredentials(connection.credentials),
    }));
  }

  // Keep older saved keys visible while the local store is upgraded.
  const credentials = sortCredentials(data.keys ?? []);
  if (!credentials.length) return [];
  return [
    {
      id: credentials[0].connection_id ?? "legacy-google",
      provider: credentials[0].provider,
      enabled: true,
      credentials,
    },
  ];
}

export function ProvidersView() {
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [expandedConnection, setExpandedConnection] = useState<string | null>(
    null,
  );
  const [expandedCredential, setExpandedCredential] = useState<string | null>(
    null,
  );
  const [draftCredential, setDraftCredential] = useState<Credential | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [chooserOpen, setChooserOpen] = useState(false);
  const selectorButtonRef = useRef<HTMLButtonElement>(null);
  const chooserRef = useRef<HTMLDivElement>(null);

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
    if (!existing && !enabled) return;

    setBusy(true);
    setError("");
    try {
      if (!existing) {
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
        setConnections((previous) => [...previous, connection]);
        setExpandedConnection(connection.id);
        return;
      }

      const updated = await api<ProviderConnection>(
        `/providers/connections/${existing.id}`,
        jsonRequest("PUT", { enabled }),
      );
      setConnections((previous) =>
        previous.map((connection) =>
          connection.id === existing.id
            ? { ...connection, enabled: updated.enabled ?? enabled }
            : connection,
        ),
      );
      if (!enabled) {
        setExpandedConnection(null);
        setExpandedCredential(null);
        setDraftCredential(null);
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
    setExpandedConnection(connection.id);
    setExpandedCredential(credential.id);
    setError("");
  }

  async function saveCredential(
    connection: ProviderConnection,
    credential: Credential,
    name: string,
    secret: string,
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
      setExpandedCredential(null);
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
      setExpandedCredential(null);
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
                    <span className="provider-choice-logo" aria-hidden="true">
                      <img src={googleLogo} alt="" />
                    </span>
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
          {connections.filter((connection) => connection.enabled).map((connection) => {
            const isExpanded = expandedConnection === connection.id;
            const draft =
              draftCredential?.connection_id === connection.id
                ? draftCredential
                : null;
            const credentials = sortCredentials([
              ...connection.credentials,
              ...(draft ? [draft] : []),
            ]);
            const isGoogle = connection.provider === "google";

            return (
              <section className="connection-card" key={connection.id}>
                <button
                  className="connection-heading"
                  type="button"
                  aria-expanded={isExpanded}
                  aria-controls={`connection-content-${connection.id}`}
                  onClick={() => {
                    setExpandedConnection(isExpanded ? null : connection.id);
                    setExpandedCredential(null);
                  }}
                >
                  <span className="provider-logo" aria-hidden="true">
                    {isGoogle ? <img src={googleLogo} alt="" /> : null}
                  </span>
                  <span className="connection-name">
                    {providers.find((provider) => provider.id === connection.provider)
                      ?.name ?? connection.provider}
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
                            expanded={expandedCredential === credential.id}
                            busy={busy}
                            onToggle={() =>
                              setExpandedCredential((previous) =>
                                previous === credential.id ? null : credential.id,
                              )
                            }
                            onSave={(name, secret) =>
                              saveCredential(connection, credential, name, secret)
                            }
                            onRemove={() => {
                              if (draft?.id === credential.id) {
                                setDraftCredential(null);
                                setExpandedCredential(null);
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
            );
          })}
        </>
      )}

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
  expanded,
  busy,
  onToggle,
  onSave,
  onRemove,
}: {
  credential: Credential;
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onSave: (name: string, secret: string) => Promise<boolean>;
  onRemove: () => void;
}) {
  const isNew = !credential.name;
  const [name, setName] = useState(credential.name);
  const [secret, setSecret] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => {
    setName(credential.name);
    setSecret("");
  }, [credential.id, credential.name]);

  return (
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
              void onSave(name, secret).then((saved) => {
                if (saved) {
                  setSecret("");
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
                placeholder="Personal Google key"
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="credential-field">
              <label htmlFor={`credential-secret-${credential.id}`}>API Key</label>
              <div className="credential-secret-control">
                <input
                  id={`credential-secret-${credential.id}`}
                  type="password"
                  autoComplete="new-password"
                  value={secret}
                  maxLength={1280}
                  required={isNew}
                  placeholder={isNew ? "Enter API key" : "••••••••••••••••••••"}
                  onChange={(event) => setSecret(event.target.value)}
                />
              </div>
            </div>
            {confirmRemove ? (
              <div className="credential-confirmation" role="alertdialog" aria-label="Remove credential">
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
            ) : (
              <div className="credential-actions">
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
                  disabled={busy || !name.trim() || (isNew && !secret.trim())}
                >
                  {busy ? "Saving…" : "Save Changes"}
                </button>
              </div>
            )}
          </form>
        </div>
      </div>
    </section>
  );
}
