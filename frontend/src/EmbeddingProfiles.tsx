import { ArrowClockwise, CaretDown, Plus, Trash } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  jsonRequest,
  type EmbeddingProfile,
  type EmbeddingProfileList,
  type ProviderKey,
  type Providers,
  type ProviderModel,
} from "./api";
import { providerName as displayProvider } from "./providerNames";

type ProfileDraft = {
  id: string | null;
  name: string;
  key_id: string;
  model: string;
  dimensions: number | null;
};

type SavedProfile = EmbeddingProfile & {
  world_count?: number;
  in_use?: boolean;
  pending_count?: number;
};

function modelChoices(key: ProviderKey | undefined, providers: Providers | null): ProviderModel[] {
  if (!key) return [];
  const source = key.models !== undefined
    ? key.models
    : (providers?.models ?? []).filter((model) => model.provider === key.provider);
  return source.filter((model) => model.capabilities?.embeddings !== false);
}

function highestDimension(model: ProviderModel | undefined) {
  const embedding = model?.capabilities?.embedding;
  return embedding?.max_dimensions ?? (embedding?.dimensions?.length
    ? Math.max(...embedding.dimensions)
    : null);
}

function minimumDimension(provider: string | undefined, model: string) {
  if (provider === "google" && (model === "gemini-embedding-2" || model === "gemini-embedding-001")) return 128;
  if (provider === "openai" && model === "text-embedding-ada-002") return 1536;
  return 1;
}

export function EmbeddingProfiles() {
  const [profiles, setProfiles] = useState<SavedProfile[]>([]);
  const [providers, setProviders] = useState<Providers | null>(null);
  const [lastUsedProfileId, setLastUsedProfileId] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const [draft, setDraft] = useState<ProfileDraft | null>(null);
  const [expandedProfiles, setExpandedProfiles] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refreshingKey, setRefreshingKey] = useState<string | null>(null);
  const [error, setError] = useState("");

  const keys = useMemo(() => {
    if (!providers) return [];
    const enabledIds = new Set((providers.connections ?? []).filter((item) => item.enabled).map((item) => item.id));
    return providers.keys.filter((key) => !providers.connections || enabledIds.has(key.connection_id ?? ""));
  }, [providers]);
  const draftKey = providers?.keys.find((key) => key.id === draft?.key_id);
  const draftModels = modelChoices(draftKey, providers);
  const draftModel = draftModels.find((model) => model.id === draft?.model);
  const profileInUse = (profile: SavedProfile) =>
    (profile.world_count ?? 0) > 0 || (profile.pending_count ?? 0) > 0 || profile.in_use === true;
  const editingProfile = profiles.find((profile) => profile.id === draft?.id);
  const editingLocked = Boolean(editingProfile && profileInUse(editingProfile));
  const editingPending = (editingProfile?.pending_count ?? 0) > 0;
  const allowedDraftKeys = editingLocked && editingProfile
    ? keys.filter((key) => {
        if (key.provider !== editingProfile.provider) return false;
        if (key.provider === "openai_compatible" && (key.base_url ?? null) !== (editingProfile.base_url ?? null)) return false;
        if (key.id === editingProfile.key_id) return true;
        const candidateModel = modelChoices(key, providers).find((model) => model.id === editingProfile.model);
        const maximum = highestDimension(candidateModel);
        return Boolean(candidateModel && editingProfile.dimensions != null &&
          (maximum == null || maximum >= editingProfile.dimensions));
      })
    : keys;

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [providerData, profileData] = await Promise.all([
        api<Providers>("/providers"),
        api<EmbeddingProfileList>("/embedding-profiles"),
      ]);
      setProviders(providerData && Array.isArray(providerData.keys) ? providerData : null);
      setProfiles((Array.isArray(profileData?.profiles) ? profileData.profiles : []) as SavedProfile[]);
      setLastUsedProfileId(profileData?.last_used_profile_id ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Embedding profiles could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  function startNew() {
    const preferredKey = keys.find((key) => key.id === profiles.find((profile) => profile.id === lastUsedProfileId)?.key_id)
      ?? keys[0];
    const firstModel = modelChoices(preferredKey, providers)[0];
    setDraft({ id: null, name: "", key_id: preferredKey?.id ?? "", model: firstModel?.id ?? "",
      dimensions: highestDimension(firstModel) });
    setOpen(true);
    setError("");
  }

  function editProfile(profile: SavedProfile) {
    setDraft({ id: profile.id, name: profile.name, key_id: profile.key_id, model: profile.model,
      dimensions: profile.dimensions });
    setExpandedProfiles((current) => {
      const next = new Set(current);
      next.delete(profile.id);
      return next;
    });
    setOpen(true);
    setError("");
  }

  async function refreshModels(keyId: string) {
    if (refreshingKey) return;
    setRefreshingKey(keyId);
    setError("");
    try {
      await api(`/providers/keys/${keyId}/models/refresh`, { method: "POST" });
      const latest = await api<Providers>("/providers");
      setProviders(latest);
      const refreshedKey = latest.keys.find((key) => key.id === keyId);
      const models = modelChoices(refreshedKey, latest);
      setDraft((current) => current?.key_id === keyId && !models.some((model) => model.id === current.model)
        ? { ...current, model: models[0]?.id ?? "", dimensions: highestDimension(models[0]) }
        : current);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Models could not be refreshed.");
    } finally {
      setRefreshingKey(null);
    }
  }

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    setBusy(true);
    setError("");
    try {
      const body = { name: draft.name.trim(), key_id: draft.key_id, model: draft.model,
        dimensions: draft.dimensions };
      const saved = await api<SavedProfile>(
        draft.id ? `/embedding-profiles/${draft.id}` : "/embedding-profiles",
        jsonRequest(draft.id ? "PUT" : "POST", body),
      );
      setProfiles((current) => [saved, ...current.filter((profile) => profile.id !== saved.id)]);
      setExpandedProfiles((current) => {
        const next = new Set(current);
        next.delete(saved.id);
        return next;
      });
      setDraft(null);
      setOpen(true);

      if (!saved.usable) {
        try {
          const checked = await api<SavedProfile>(`/embedding-profiles/${saved.id}/preflight`, { method: "POST" });
          setProfiles((current) => current.map((profile) => profile.id === checked.id ? checked : profile));
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "The embedding model could not be checked.");
        }
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The embedding profile could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function removeProfile(profile: SavedProfile) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/embedding-profiles/${profile.id}`, { method: "DELETE" });
      setProfiles((current) => current.filter((item) => item.id !== profile.id));
      setExpandedProfiles((current) => {
        if (!current.has(profile.id)) return current;
        const next = new Set(current);
        next.delete(profile.id);
        return next;
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "This profile could not be removed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="embedding-profiles-group">
      <h3 className="embedding-profiles-group-title">Embedding</h3>
      <section className="embedding-profiles-section" aria-labelledby="embedding-profiles-heading">
      <div className="embedding-profiles-heading-row">
        <button
          type="button"
          className="embedding-profiles-heading"
          aria-expanded={open}
          aria-controls="embedding-profiles-content"
          onClick={() => setOpen((value) => !value)}
        >
          <strong id="embedding-profiles-heading">Embedding Profiles</strong>
          <CaretDown size={18} aria-hidden="true" />
        </button>
      </div>
      <div id="embedding-profiles-content" className={`embedding-profiles-content ${open ? "is-open" : ""}`} aria-hidden={!open} inert={!open}>
        <div className="embedding-profiles-inner">
          <div className="embedding-profiles-body">
          {loading ? <p className="embedding-profile-empty" role="status">Loading embedding profiles…</p> : null}
          {!loading && !profiles.length && !draft && keys.length > 0 && <p className="embedding-profile-empty">No embedding profiles yet.</p>}
          {!keys.length && !loading && <p className="embedding-profile-empty">Add a credential with an embedding model to create a profile.</p>}
          {draft && (
            <form className="embedding-profile-form" onSubmit={(event) => void saveProfile(event)}>
              <h3>{draft.id ? "Edit Embedding Profile" : "New Embedding Profile"}</h3>
              <label>
                <span>Profile Name</span>
                <input autoFocus maxLength={100} required value={draft.name} placeholder="My Embeddings" disabled={busy} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
              </label>
              <label>
                <span className="embedding-profile-field-label">API Connection{editingPending && <small title="A World creation is using this profile">Locked</small>}</span>
                {editingPending ? (
                  <output className="embedding-profile-static-value" aria-label="API Connection">{editingProfile?.credential_name}</output>
                ) : (
                  <select
                    value={draft.key_id}
                    required
                    disabled={busy}
                    onChange={(event) => {
                      const key = keys.find((item) => item.id === event.target.value);
                      const model = modelChoices(key, providers)[0];
                      setDraft({ ...draft, key_id: event.target.value, model: editingLocked ? draft.model : model?.id ?? "",
                        dimensions: editingLocked ? draft.dimensions : highestDimension(model) });
                    }}
                  >
                    {allowedDraftKeys.map((key) => <option key={key.id} value={key.id}>{displayProvider(key.provider)} · {key.name}</option>)}
                  </select>
                )}
              </label>
              <div className="embedding-profile-field">
                <span className="embedding-profile-field-label">Embedding Model{editingLocked && <small title="This profile is used by a World">Locked</small>}</span>
                {editingLocked ? (
                  <output className="embedding-profile-static-value" aria-label="Embedding Model">
                    {draftModel?.name || editingProfile?.model_name || draft.model}
                  </output>
                ) : (
                  <span className="embedding-profile-model-row">
                    <select
                      value={draft.model}
                      required
                      aria-label="Embedding Model"
                      disabled={busy || !draftModels.length}
                      onChange={(event) => {
                        const model = draftModels.find((item) => item.id === event.target.value);
                        setDraft({ ...draft, model: event.target.value, dimensions: highestDimension(model) });
                      }}
                    >
                      {draftModels.map((model) => <option key={model.id} value={model.id}>{model.name}{model.tested ? "" : " · Untested"}</option>)}
                    </select>
                    <button type="button" className="credential-refresh embedding-model-refresh" aria-label="Refresh embedding models" title="Refresh models" disabled={!draft.key_id || refreshingKey === draft.key_id || busy} onClick={() => void refreshModels(draft.key_id)}>
                      <ArrowClockwise size={16} aria-hidden="true" />
                    </button>
                  </span>
                )}
                {draftModel && !draftModel.tested && (
                  <small className="embedding-profile-untested" title="VySol has not added model-specific settings for this model yet.">
                    Untested · VySol has not added model-specific settings for this model yet.
                  </small>
                )}
                {!draftModels.length && <small>No embedding models were found for this connection.</small>}
              </div>
              {!editingLocked && <div className="embedding-profile-facts" aria-live="polite">
                <label className="embedding-profile-dimensions">
                  <span className="embedding-profile-field-label">Dimensions</span>
                  <input type="number" step="1" min={minimumDimension(draftKey?.provider, draft.model)}
                    max={highestDimension(draftModel) ?? undefined}
                    value={draft.dimensions ?? ""} placeholder="Provider default"
                    disabled={busy}
                    onChange={(event) => setDraft({ ...draft, dimensions: event.target.value === "" ? null : Number(event.target.value) })} />
                </label>
              </div>}
              <div className="credential-actions">
                <button type="button" className="secondary-action" disabled={busy} onClick={() => { setDraft(null); setOpen(true); }}>Cancel</button>
                <button type="submit" className="primary-button" disabled={busy || !draft.name.trim() || !draft.key_id || !draft.model}>{busy ? "Saving…" : "Save Profile"}</button>
              </div>
            </form>
          )}
          <div className="embedding-profile-list">
            {profiles.filter((profile) => profile.id !== draft?.id).map((profile) => {
              const isExpanded = expandedProfiles.has(profile.id);
              const inUse = profileInUse(profile);
              return (
                <article className="embedding-profile-card" key={profile.id}>
                  <button type="button" className="embedding-profile-card-heading" aria-expanded={isExpanded} onClick={() => setExpandedProfiles((current) => {
                    const next = new Set(current);
                    if (isExpanded) next.delete(profile.id);
                    else next.add(profile.id);
                    return next;
                  })}>
                    <span className="embedding-profile-card-name">{profile.name}</span>
                    <CaretDown className="embedding-profile-caret" size={16} aria-hidden="true" />
                  </button>
                  <div className={`embedding-profile-card-body ${isExpanded ? "is-open" : ""}`} aria-hidden={!isExpanded} inert={!isExpanded}>
                    <div className="embedding-profile-card-inner">
                      <div className="embedding-profile-details">
                        <dl>
                          <div><dt>Embedding Model</dt><dd>{displayProvider(profile.provider)} · {profile.model_name || profile.model}</dd></div>
                          <div><dt>Connection</dt><dd>{profile.credential_name}</dd></div>
                          {profile.worlds?.length ? (
                            <div>
                              <dt>Used By</dt>
                              <dd><ul className="embedding-profile-world-list">{profile.worlds.map((world) => <li key={world.id}>{world.name}</li>)}</ul></dd>
                            </div>
                          ) : null}
                        </dl>
                        <div className="credential-actions">
                          <button type="button" className="secondary-action" disabled={busy} onClick={() => editProfile(profile)}>Edit</button>
                          <button type="button" className="danger-link embedding-profile-delete" title={inUse ? "This profile is used by a World" : undefined} disabled={busy || inUse} onClick={() => void removeProfile(profile)}><Trash size={15} /> Remove</button>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
          {!draft && <button type="button" className="add-credential embedding-profile-add" onClick={startNew} disabled={!keys.length || busy}>
            <Plus size={18} /> Add Profile
          </button>}
          {error && <p className="embedding-profile-error" role="status">{error}</p>}
          </div>
        </div>
      </div>
      </section>
    </div>
  );
}
