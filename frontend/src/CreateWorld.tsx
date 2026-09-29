import { useEffect, useRef, useState } from "react";
import {
  CaretDown,
  Plus,
  Check,
  Question,
} from "@phosphor-icons/react";
import { BookList } from "./BookList";
import { WorldSectionsNav } from "./WorldSectionsNav";
import { providerName } from "./providerNames";
import {
  api,
  jsonRequest,
  type CreationAttempt,
  type EmbeddingProfile,
  type EmbeddingProfileList,
  type ProcessingConfig,
  type World,
  type WorldBook,
  type WorldDetail,
  bookCountLabel,
} from "./api";

type Choice = {
  id: string;
  filename: string;
  size: number;
  file?: File;
};

const defaults: ProcessingConfig = {
  size: 8000,
  search: 1000,
};

function ChunkingHelp() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <div
      className="chunking-heading"
      onPointerLeave={() => {
        if (document.activeElement !== button.current) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <span>Chunking</span>
      <button
        ref={button}
        type="button"
        className="icon-button chunking-help-button"
        aria-label="Chunking help"
        aria-describedby="chunking-help"
        onPointerEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
      >
        <Question size={18} />
      </button>
      <div
        id="chunking-help"
        role="tooltip"
        hidden={!open}
        className="chunking-tooltip"
      >
        <div>
          <p>
            VySol splits each book into smaller pieces called chunks, so it can
            index the text.
          </p>
        </div>
      </div>
    </div>
  );
}

function EmbeddingChoice({
  profiles,
  selectedProfileId,
  onChange,
}: {
  profiles: EmbeddingProfile[];
  selectedProfileId: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);

  return (
    <div className="embedding-choice">
      <div className="embedding-choice-labels">
        <span>Embedding Profile</span>
      </div>
      <div className="embedding-choice-row is-profile-choice">
        <div className="choice-menu-anchor">
          <button
            type="button"
            className="choice-card"
            aria-label="Embedding profile"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls="embedding-profile-options"
            onClick={() => setOpen((value) => !value)}
          >
            <span className="choice-card-copy">
              <strong>{selectedProfile?.name ?? "Choose a profile"}</strong>
              <small>{selectedProfile
                ? `${providerName(selectedProfile.provider)} · ${selectedProfile.model_name || selectedProfile.model}`
                : profiles.length
                  ? "Choose a profile for this World"
                  : "Create a profile in AI Connections before processing books."}</small>
            </span>
            <CaretDown size={18} />
          </button>
          {open && (
            <div
              id="embedding-profile-options"
              className="choice-menu"
              role="listbox"
              aria-label="Embedding profile options"
            >
              {profiles.map((profile) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={profile.id === selectedProfileId}
                  aria-disabled={!profile.usable}
                  disabled={!profile.usable}
                  key={profile.id}
                  onClick={() => {
                    onChange(profile.id);
                    setOpen(false);
                  }}
                >
                  <span className="choice-card-copy">
                    <strong>{profile.name}</strong>
                    <small>{profile.usable ? `${providerName(profile.provider)} · ${profile.model_name || profile.model}` : "Connection needs attention"}</small>
                  </span>
                  {profile.id === selectedProfileId && <Check size={18} />}
                </button>
              ))}
              {!profiles.length && <p role="status">No embedding profiles are available.</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function CreateWorld({
  visible,
  handoffTransition,
  onAttempt,
  onCreated,
  onManageKeys,
  onUploading,
  onResumeHandler,
}: {
  visible: boolean;
  handoffTransition: boolean;
  onAttempt: (value: CreationAttempt) => void;
  onCreated: (attempt: CreationAttempt) => void;
  onManageKeys: () => void;
  onUploading?: (attemptId: string, value: boolean) => void;
  onResumeHandler: (resume: (attempt: CreationAttempt) => Promise<CreationAttempt>) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const draftId = useRef<string>(crypto.randomUUID());
  const filesByAttempt = useRef(new Map<string, Map<string, File>>());
  const submissionId = useRef<string | null>(null);
  const [name, setName] = useState("");
  const [choices, setChoices] = useState<Choice[]>([]);
  const [config, setConfig] = useState<ProcessingConfig>(defaults);
  const [profileList, setProfileList] = useState<EmbeddingProfileList | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (!visible) return;
    heading.current?.focus({ preventScroll: true });
    let cancelled = false;
    api<EmbeddingProfileList>("/embedding-profiles")
      .then((value) => {
        if (cancelled) return;
        const profiles = Array.isArray(value?.profiles) ? value.profiles : [];
        setProfileList({
          profiles,
          default_profile_id: value?.default_profile_id ?? null,
          last_used_profile_id: value?.last_used_profile_id ?? null,
        });
        const preferred = value?.last_used_profile_id ?? "";
        setSelectedProfileId((current) =>
          profiles.some((profile) => profile.id === current)
            ? current
            : profiles.some((profile) => profile.id === preferred) ? preferred : "",
        );
      })
      .catch(() => {
        if (!cancelled)
          setError("Could not load your Embedding Profiles. Try again or open AI Connections.");
      });
    return () => {
      cancelled = true;
    };
  }, [visible]);

  function reorder(id: string, position: number) {
    setChoices((previous) => {
      const from = previous.findIndex((book) => book.id === id);
      const to = Math.max(0, Math.min(previous.length - 1, position));
      if (from === to || from < 0) return previous;
      const next = [...previous];
      const [book] = next.splice(from, 1);
      next.splice(to, 0, book);
      setAnnouncement(`${book.filename} moved to position ${to + 1}.`);
      return next;
    });
  }

  function addFiles(files: File[]) {
    setError("");
    setChoices((previous) => {
      const next = [...previous];
      for (const file of files) {
        const missing = next.findIndex(
          (book) => book.filename === file.name && !book.file,
        );
        if (missing >= 0)
          next[missing] = { ...next[missing], file, size: file.size };
        else
          next.push({ id: crypto.randomUUID(), filename: file.name, size: file.size, file });
      }
      return next;
    });
  }

  function validate() {
    if (!name.trim() || choices.length === 0) {
      setError("Give your world a name and add at least one story.");
      return false;
    }
    const selectedProfile = profileList?.profiles.find((profile) => profile.id === selectedProfileId);
    if (!selectedProfile?.usable) {
      setError("Choose a usable Embedding Profile in Processing before creating this World.");
      return false;
    }
    if (
      !Number.isInteger(config.size) ||
      config.size < 1 ||
      config.size > 1000000 ||
      !Number.isInteger(config.search) ||
      config.search < 0 ||
      config.search >= config.size
    ) {
      setError("Use a positive maximum chunk size and a smaller, nonnegative boundary search distance.");
      return false;
    }
    return true;
  }

  async function uploadBooks(current: CreationAttempt) {
    const files = filesByAttempt.current.get(current.id);
    for (const book of current.books) {
      if (book.uploaded) continue;
      const file = files?.get(book.id);
      if (!file)
        throw new Error(
          `The upload for ${book.filename} is unavailable. Discard this attempt and start again.`,
        );
      const operation = crypto.randomUUID();
      const path = `/creation/${current.id}/books/${book.id}?revision=${current.revision}&operation_id=${operation}`;
      const request = {
        method: "PUT",
        headers: {
          "X-Filename": encodeURIComponent(book.filename),
          "Content-Type": "application/octet-stream",
        },
        body: file,
      };
      try {
        current = await api<CreationAttempt>(path, request);
      } catch {
        current = await api<CreationAttempt>(path, request);
      }
      files?.delete(book.id);
      onAttempt(current);
    }
    if (files?.size === 0) filesByAttempt.current.delete(current.id);
    return current;
  }

  async function refreshAfterError(attemptId: string) {
    const saved = await api<CreationAttempt | null>(`/creation/${attemptId}`).catch(
      () => null,
    );
    if (saved) onAttempt(saved);
  }

  async function resumeSavedAttempt(current: CreationAttempt) {
    onUploading?.(current.id, true);
    try {
      current = await uploadBooks(current);
      const resumed = await api<CreationAttempt>(
        `/creation/${current.id}/start`,
        jsonRequest("POST", {
          revision: current.revision,
          operation_id: crypto.randomUUID(),
        }),
      );
      onAttempt(resumed);
      return resumed;
    } finally {
      onUploading?.(current.id, false);
    }
  }

  useEffect(() => {
    onResumeHandler(resumeSavedAttempt);
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submissionId.current || busy || !validate()) return;
    const currentDraftId = draftId.current;
    submissionId.current = currentDraftId;
    setBusy(true);
    setError("");
    let current: CreationAttempt | null = null;
    try {
      const files = new Map(
        choices.flatMap((choice) =>
          choice.file ? [[choice.id, choice.file] as const] : [],
        ),
      );
      const manifestRequest = jsonRequest("PUT", {
        operation_id: crypto.randomUUID(),
        revision: 0,
        name: name.trim(),
        embedding_profile_id: selectedProfileId,
        config: { size: config.size, search: config.search },
        books: choices.map(({ id, filename, size }) => ({ id, filename, size })),
      });
      try {
        current = await api<CreationAttempt>(`/creation/${currentDraftId}`, manifestRequest);
      } catch {
        current = await api<CreationAttempt>(`/creation/${currentDraftId}`, manifestRequest);
      }
      filesByAttempt.current.set(current.id, files);
      onAttempt(current);
      onCreated(current);
      setName("");
      setChoices([]);
      setConfig(defaults);
      setSelectedProfileId("");
      setAdvancedOpen(false);
      draftId.current = crypto.randomUUID();
      submissionId.current = null;
      setBusy(false);
      onUploading?.(current.id, true);
      current = await uploadBooks(current);
      current = await api<CreationAttempt>(
        `/creation/${current.id}/start`,
        jsonRequest("POST", {
          revision: current.revision,
          operation_id: crypto.randomUUID(),
        }),
      );
      onAttempt(current);
    } catch (cause) {
      if (current) await refreshAfterError(current.id);
      else {
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not save this creation. Please try again.",
        );
        const saved = await api<CreationAttempt | null>(`/creation/${currentDraftId}`).catch(
          () => null,
        );
        if (saved) {
          const files = new Map(
            choices.flatMap((choice) =>
              choice.file ? [[choice.id, choice.file] as const] : [],
            ),
          );
          filesByAttempt.current.set(saved.id, files);
          onAttempt(saved);
          onCreated(saved);
          setName("");
          setChoices([]);
          setConfig(defaults);
          setSelectedProfileId("");
          setAdvancedOpen(false);
          draftId.current = crypto.randomUUID();
        }
      }
    } finally {
      if (submissionId.current === currentDraftId) {
        submissionId.current = null;
        setBusy(false);
      }
      if (current) onUploading?.(current.id, false);
    }
  }

  const profiles = profileList?.profiles ?? [];
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);

  return (
    <section
      className={`view create-world-view ${visible ? "is-visible" : ""} ${handoffTransition ? "is-handoff" : ""}`}
      aria-hidden={!visible}
      inert={!visible}
    >
      <form className="world-page-content create-world-content" autoComplete="off" noValidate onSubmit={submit}>
        <header className="world-page-heading">
          <h1 ref={heading} tabIndex={-1}>Create World</h1>
        </header>

        <label className="world-name-field" htmlFor="world-name">
          <span>World Name</span>
          <input
            id="world-name"
            autoComplete="off"
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Give your world a name…"
            disabled={busy}
          />
        </label>

        <section className="world-page-section stories-section" aria-labelledby="stories-heading">
          <div className="section-heading-row">
            <h2 id="stories-heading">Stories</h2>
            <button
              type="button"
              className="outline-action add-stories-button"
              disabled={busy}
              onClick={() => picker.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                addFiles(Array.from(event.dataTransfer.files));
              }}
            >
              <Plus size={15} aria-hidden="true" /> <span>Add Books</span>
            </button>
          </div>
          <BookList
            books={choices}
            onReorder={reorder}
            onRemove={(id) => setChoices((previous) => previous.filter((book) => book.id !== id))}
          />
          <p id="reorder-help" className="sr-only">
            Drag a handle to reorder. With a handle focused, use the up and down arrow keys.
          </p>
          {!choices.length && (
            <button
              type="button"
              className="story-drop-prompt"
              disabled={busy}
              onClick={() => picker.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                addFiles(Array.from(event.dataTransfer.files));
              }}
            >
              Add a story file to begin
            </button>
          )}
          <input
            ref={picker}
            type="file"
            aria-label="Choose books"
            multiple
            accept=".txt,.epub"
            hidden
            onChange={(event) => {
              addFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
          <span className="sr-only" aria-live="polite">{announcement}</span>
        </section>

        <section className="world-page-section processing-section" aria-labelledby="processing-heading">
          <div className="section-heading-row">
            <h2 id="processing-heading">Processing</h2>
          </div>
          <EmbeddingChoice
            profiles={profiles}
            selectedProfileId={selectedProfileId}
            onChange={setSelectedProfileId}
          />
          <button type="button" className="text-action manage-connections" onClick={onManageKeys}>
            {profiles.length ? "Manage AI Connections" : "Add an Embedding Profile in AI Connections"}
          </button>

          <section className={`world-disclosure ${advancedOpen ? "is-open" : ""}`}>
            <button
              type="button"
              className="world-disclosure-trigger"
              aria-expanded={advancedOpen}
              aria-controls="advanced-settings-content"
              onClick={() => setAdvancedOpen((value) => !value)}
            >
              <span>Advanced Settings</span>
              <CaretDown size={18} />
            </button>
            <div
              id="advanced-settings-content"
              className="world-disclosure-panel"
              aria-hidden={!advancedOpen}
              inert={!advancedOpen}
            >
              <div className="world-disclosure-inner">
                <ChunkingHelp />
                <div className="processing-fields">
                  <label>
                    Maximum Chunk Size
                    <span className="number-input-row">
                      <input
                        aria-label="Maximum chunk size"
                        type="number"
                        min={1}
                        max={1000000}
                        value={config.size}
                        disabled={busy}
                        onChange={(event) =>
                          setConfig((previous) => ({ ...previous, size: Number(event.target.value) }))
                        }
                      />
                      <small>characters</small>
                    </span>
                  </label>
                  <label>
                    Boundary Search Distance
                    <span className="number-input-row">
                      <input
                        aria-label="Boundary search distance"
                        type="number"
                        min={0}
                        max={config.size - 1}
                        value={config.search}
                        disabled={busy}
                        onChange={(event) =>
                          setConfig((previous) => ({ ...previous, search: Number(event.target.value) }))
                        }
                      />
                      <small>characters</small>
                    </span>
                  </label>
                </div>
              </div>
            </div>
          </section>
        </section>

        {error && <p role="alert" className="error-message world-form-error">{error}</p>}
        <footer className="world-form-actions">
          <span aria-live="polite" className="muted">{busy ? "Starting your world…" : ""}</span>
          <button type="submit" className="primary-button" disabled={busy}>
            {busy ? "Creating…" : "Create World"}
          </button>
        </footer>
        <span className="sr-only">Selected embedding profile: {selectedProfile?.name ?? "none"}</span>
      </form>
    </section>
  );
}

function detailBooks(detail: WorldDetail | null, attempt: CreationAttempt | null): WorldBook[] {
  if (attempt)
    return attempt.books.map((book) => ({
      id: book.id,
      filename: book.filename,
      position: book.position,
      state: book.state,
      chunks_done: book.chunks_done,
      chunks_total: book.chunks_total,
    }));
  return detail?.books ?? [];
}

function bookProgress(book: WorldBook) {
  if (book.state === "done") return "Complete";
  if (book.state === "failed") return "Attention";
  if (book.chunks_total && book.chunks_total > 0)
    return `${book.chunks_done ?? 0} of ${book.chunks_total} chunks embedded`;
  if (["converting", "chunking", "prepared"].includes(book.state)) return "Preparing";
  if (book.state === "waiting" || book.state === "uploaded") return "Waiting";
  return "Creating";
}

export function WorldOverview({
  visible,
  handoffTransition,
  world,
  detail,
  attempt,
  uploading,
  busy,
  onPause,
  onResume,
  onDiscard,
  onChronicles,
}: {
  visible: boolean;
  handoffTransition: boolean;
  world: World | null;
  detail: WorldDetail | null;
  attempt: CreationAttempt | null;
  uploading: boolean;
  busy: boolean;
  onPause: () => void;
  onResume: () => void;
  onDiscard: () => void;
  onChronicles: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [discardConfirm, setDiscardConfirm] = useState(false);
  useEffect(() => {
    if (visible) heading.current?.focus({ preventScroll: true });
  }, [visible]);
  const title = detail?.name ?? attempt?.name ?? world?.name ?? "World";
  const books = detailBooks(detail, attempt);
  const state = attempt?.state ?? detail?.state ?? "complete";
  const isReady = state === "complete";
  const isActive = state === "running" || state === "pausing" || uploading;
  const statusLabel = uploading
    ? "Creating"
    : isReady
    ? "Ready"
    : state === "failed"
      ? "Attention"
      : state === "paused"
        ? "Paused"
        : state === "pausing"
          ? "Pausing"
          : "Creating";
  const chunksDone = attempt?.chunks_done ?? detail?.progress?.chunks_done ?? 0;
  const chunksTotal = attempt?.chunks_total ?? detail?.progress?.chunks_total ?? 0;
  const config = attempt?.config;
  const processing = detail?.processing;
  const maxChunkSize = config?.size ?? processing?.max_chunk_size;
  const boundarySearchDistance = config?.search ?? processing?.boundary_search_distance;
  const embeddingProfile = detail?.embedding_profile;
  const legacyEmbeddingModel = config?.model ?? processing?.model;
  const legacyModelName = legacyEmbeddingModel === "gemini-embedding-2"
    ? "Gemini Embedding 2"
    : legacyEmbeddingModel;

  return (
    <section
      className={`view world-overview-view ${visible ? "is-visible" : ""} ${handoffTransition ? "is-handoff" : ""}`}
      aria-hidden={!visible}
      inert={!visible}
    >
      <div className="overview-layout">
        <WorldSectionsNav
          section="overview"
          onOverview={() => {}}
          onChronicles={onChronicles}
        />
        <div className="world-page-content overview-content">
        <header className="world-page-heading overview-heading">
          <div>
            <h1 ref={heading} tabIndex={-1}>{title}</h1>
            <p className={`world-status status-${state}`}>
              <span className="world-status-state">
                <span className="status-dot" aria-hidden="true" />
                {statusLabel}
              </span>
              <span className="world-status-count">{bookCountLabel(books.length)}</span>
            </p>
          </div>
        </header>

        {!isReady && (
          <section className="world-progress-section" aria-label="Creation progress">
            <div className="world-progress-heading">
              <span>{chunksDone} of {chunksTotal} chunks embedded</span>
              {chunksTotal > 0 && (
                <span className="world-progress-percent">
                  {Math.min(100, Math.round((chunksDone / chunksTotal) * 100))}%
                </span>
              )}
            </div>
            {chunksTotal > 0 && (
              <progress max={chunksTotal} value={chunksDone} aria-label="Chunks embedded" />
            )}
            {attempt?.message && state === "failed" && (
              <p className="error-message" role="alert">{attempt.message.replace(/\s*Resume later\./g, "")}</p>
            )}
          </section>
        )}

        <section className="world-page-section overview-stories" aria-labelledby="overview-stories-heading">
          <div className="section-heading-row">
            <h2 id="overview-stories-heading">Stories</h2>
          </div>
          <BookList
            locked
            books={books.map((book) => ({
              id: book.id,
              filename: book.filename,
              size: 0,
              status: bookProgress(book),
              state: book.state,
              chunksDone: book.chunks_done ?? 0,
              chunksTotal: book.chunks_total ?? 0,
            }))}
          />
          {!books.length && <p className="muted">No story details are available.</p>}
        </section>

        <section className={`world-disclosure world-details-disclosure ${detailsOpen ? "is-open" : ""}`}>
          <button
            type="button"
            className="world-disclosure-trigger"
            aria-expanded={detailsOpen}
            aria-controls="world-details-content"
            onClick={() => setDetailsOpen((value) => !value)}
          >
            <span>World Details</span>
            <CaretDown size={18} />
          </button>
          <div
            id="world-details-content"
            className="world-disclosure-panel"
            aria-hidden={!detailsOpen}
            inert={!detailsOpen}
          >
            <div className="world-disclosure-inner">
              <section className="world-details-group" aria-labelledby="world-details-embedding">
                <h3 id="world-details-embedding">Embedding</h3>
                <dl className="world-details-grid">
                  <div><dt>Embedding Profile</dt><dd>{embeddingProfile?.name ?? (legacyEmbeddingModel ? "Legacy Embedding Profile" : "Unavailable")}</dd></div>
                  <div><dt>Embedding Model</dt><dd>{embeddingProfile ? `${providerName(embeddingProfile.provider)} · ${embeddingProfile.model}` : legacyModelName ?? "Unavailable"}</dd></div>
                  <div><dt>Dimensions</dt><dd>{embeddingProfile?.dimensions?.toLocaleString() ?? "Unavailable"}</dd></div>
                  <div><dt>Maximum Input</dt><dd>{embeddingProfile?.max_input_tokens?.toLocaleString() ?? "Unavailable"}{embeddingProfile?.max_input_tokens ? " tokens" : ""}</dd></div>
                </dl>
              </section>
              <section className="world-details-group" aria-labelledby="world-details-chunking">
                <h3 id="world-details-chunking">Chunking</h3>
                <dl className="world-details-grid">
                  <div><dt>Maximum Chunk Size</dt><dd>{maxChunkSize ?? "Unavailable"}{maxChunkSize != null ? " characters" : ""}</dd></div>
                  <div><dt>Boundary Search Distance</dt><dd>{boundarySearchDistance ?? "Unavailable"}{boundarySearchDistance != null ? " characters" : ""}</dd></div>
                </dl>
              </section>
            </div>
          </div>
        </section>

        {!isReady && (
          <footer className="world-overview-actions">
            {discardConfirm ? (
              <div className="world-discard-confirmation" role="group" aria-label="Confirm discard">
                <span>Discard this world and its progress?</span>
                <button type="button" className="text-action" disabled={busy} onClick={() => setDiscardConfirm(false)}>Keep</button>
                <button type="button" className="text-action pause-world-action discard-world-action" disabled={busy} onClick={onDiscard}>Discard World</button>
              </div>
            ) : (
              <button type="button" className="text-action pause-world-action discard-world-action" disabled={busy} onClick={() => setDiscardConfirm(true)}>
                Discard World
              </button>
            )}
            <button
              type="button"
              className="text-action pause-world-action"
              disabled={busy || state === "pausing"}
              onClick={isActive ? onPause : onResume}
            >
              {busy ? "Saving…" : isActive ? "Pause" : "Resume"}
            </button>
          </footer>
        )}
        </div>
      </div>
    </section>
  );
}
