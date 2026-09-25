import { useEffect, useRef, useState } from "react";
import {
  CaretDown,
  Plus,
  Check,
  Question,
} from "@phosphor-icons/react";
import { BookList } from "./BookList";
import { WorldSectionsNav } from "./WorldSectionsNav";
import {
  api,
  jsonRequest,
  type CreationAttempt,
  type ProcessingConfig,
  type Providers,
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
  model: "gemini-embedding-2",
  size: 8000,
  search: 1000,
};

function providerName(provider: string) {
  if (provider === "google") return "Google";
  return provider.charAt(0).toLocaleUpperCase() + provider.slice(1);
}

function ProviderMark({ provider }: { provider: string }) {
  if (provider === "google")
    return <img className="provider-logo-mark" src="/assets/google-g-logo.svg.webp" alt="" aria-hidden="true" />;
  return <span aria-hidden="true">{providerName(provider).slice(0, 1)}</span>;
}

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
  providers,
  config,
  keyId,
  onModel,
  onKey,
}: {
  providers: Providers | null;
  config: ProcessingConfig;
  keyId: string;
  onModel: (model: string) => void;
  onKey: (id: string) => void;
}) {
  const [openChoice, setOpenChoice] = useState<"model" | "key" | null>(null);
  const enabledConnections = (providers?.connections ?? []).filter(
    (connection) => connection.enabled,
  );
  const hasConnectionData = providers?.connections !== undefined;
  const enabledConnectionIds = new Set(enabledConnections.map((item) => item.id));
  const enabledProviders = new Set(enabledConnections.map((item) => item.provider));
  const models = (providers?.models ?? []).filter(
    (model) => !hasConnectionData || enabledProviders.has(model.provider),
  );
  const keys = [...(providers?.keys ?? [])]
    .filter(
      (key) =>
        !hasConnectionData ||
        enabledConnectionIds.has(key.connection_id ?? ""),
    )
    .sort(
      (left, right) =>
        left.provider.localeCompare(right.provider) ||
        left.name.localeCompare(right.name),
    );
  const selectedModel = models.find((model) => model.id === config.model);
  const selectedKey = keys.find((key) => key.id === keyId);

  return (
    <div className="embedding-choice">
      <div className="embedding-choice-labels">
        <span>Embedding Model</span>
        <span>API Connection</span>
      </div>
      <div className="embedding-choice-row">
        <div className="choice-menu-anchor">
          <button
            type="button"
            className="choice-card"
            aria-label="Embedding model"
            aria-haspopup="listbox"
            aria-expanded={openChoice === "model"}
            aria-controls="embedding-model-options"
            onClick={() =>
              setOpenChoice(openChoice === "model" ? null : "model")
            }
          >
            <ProviderMark provider={selectedModel?.provider ?? "google"} />
            <span className="choice-card-copy">
              <strong>{selectedModel?.name ?? "Select a model"}</strong>
              <small>{providerName(selectedModel?.provider ?? "google")}</small>
            </span>
            <CaretDown size={18} />
          </button>
          {openChoice === "model" && (
            <div
              id="embedding-model-options"
              className="choice-menu"
              role="listbox"
              aria-label="Embedding model options"
            >
              {models.map((model) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={model.id === config.model}
                  key={model.id}
                  onClick={() => {
                    onModel(model.id);
                    setOpenChoice(null);
                  }}
                >
                  <ProviderMark provider={model.provider} />
                  <span className="choice-card-copy">
                    <strong>{model.name}</strong>
                    <small>{providerName(model.provider)}</small>
                  </span>
                  {model.id === config.model && <Check size={18} />}
                </button>
              ))}
              {!models.length && <p role="status">No embedding models available.</p>}
            </div>
          )}
        </div>
        <span className="choice-via" aria-hidden="true">
          via
        </span>
        <div className="choice-menu-anchor">
          <button
            type="button"
            className="choice-card key-choice-card"
            aria-label="API connection"
            aria-haspopup="listbox"
            aria-expanded={openChoice === "key"}
            aria-controls="api-connection-options"
            onClick={() => setOpenChoice(openChoice === "key" ? null : "key")}
          >
            <ProviderMark provider={selectedKey?.provider ?? "google"} />
            <span className="choice-card-copy">
              <strong>{selectedKey?.name ?? "Select a connection"}</strong>
              <small>{providerName(selectedKey?.provider ?? "google")}</small>
            </span>
            <CaretDown size={18} />
          </button>
          {openChoice === "key" && (
            <div
              id="api-connection-options"
              className="choice-menu"
              role="listbox"
              aria-label="API connection options"
            >
              {keys.map((key) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={key.id === keyId}
                  key={key.id}
                  onClick={() => {
                    onKey(key.id);
                    setOpenChoice(null);
                  }}
                >
                  <ProviderMark provider={key.provider} />
                  <span className="choice-card-copy">
                    <strong>{key.name}</strong>
                    <small>{providerName(key.provider)}</small>
                  </span>
                  {key.id === keyId && <Check size={18} />}
                </button>
              ))}
              {!keys.length && <p role="status">No saved connections.</p>}
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
  const [keyId, setKeyId] = useState("");
  const [providers, setProviders] = useState<Providers | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (!visible) return;
    heading.current?.focus({ preventScroll: true });
    let cancelled = false;
    api<Providers>("/providers")
      .then((value) => {
        if (cancelled) return;
        setProviders(value);
        const enabledConnections = (value.connections ?? []).filter(
          (connection) => connection.enabled,
        );
        const enabledConnectionIds = new Set(
          enabledConnections.map((connection) => connection.id),
        );
        const selectableKeys = value.keys.filter(
          (key) =>
            value.connections === undefined ||
            enabledConnectionIds.has(key.connection_id ?? ""),
        );
        const enabledProviders = new Set(
          enabledConnections.map((connection) => connection.provider),
        );
        const selectableModels = value.models.filter(
          (model) =>
            value.connections === undefined || enabledProviders.has(model.provider),
        );
        setKeyId((current) =>
          selectableKeys.some((key) => key.id === current)
            ? current
            : (selectableKeys.find((key) => key.id === value.defaults.key_id)?.id ??
                selectableKeys[0]?.id ??
                ""),
        );
        setConfig((previous) => {
          const currentModelAvailable = selectableModels.some(
            (model) => model.id === previous.model,
          );
          if (currentModelAvailable) return previous;
          const defaultModelAvailable = selectableModels.some(
            (model) => model.id === value.defaults.model,
          );
          return {
            ...previous,
            model:
              (defaultModelAvailable ? value.defaults.model : selectableModels[0]?.id) ??
              value.defaults.model,
          };
        });
      })
      .catch(() => {
        if (!cancelled)
          setError("Could not load your API connections. Try again or open Settings.");
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
    const enabledConnections = (providers?.connections ?? []).filter(
      (connection) => connection.enabled,
    );
    const enabledConnectionIds = new Set(
      enabledConnections.map((connection) => connection.id),
    );
    const selectableKeys = (providers?.keys ?? []).filter(
      (key) =>
        providers?.connections === undefined ||
        enabledConnectionIds.has(key.connection_id ?? ""),
    );
    const enabledProviders = new Set(
      enabledConnections.map((connection) => connection.provider),
    );
    const selectableModels = (providers?.models ?? []).filter(
      (model) =>
        providers?.connections === undefined || enabledProviders.has(model.provider),
    );
    if (!selectableKeys.some((key) => key.id === keyId)) {
      setError("Choose an API connection in Processing before creating this world.");
      return false;
    }
    if (!selectableModels.some((model) => model.id === config.model)) {
      setError("Choose an available embedding model in Processing before creating this world.");
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
        key_id: keyId,
        config,
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
      setKeyId("");
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
          setKeyId("");
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

  const enabledConnections = (providers?.connections ?? []).filter(
    (connection) => connection.enabled,
  );
  const enabledConnectionIds = new Set(enabledConnections.map((item) => item.id));
  const enabledProviders = new Set(enabledConnections.map((item) => item.provider));
  const selectableModels = (providers?.models ?? []).filter(
    (model) =>
      providers?.connections === undefined || enabledProviders.has(model.provider),
  );
  const selectableKeys = (providers?.keys ?? []).filter(
    (key) =>
      providers?.connections === undefined ||
      enabledConnectionIds.has(key.connection_id ?? ""),
  );
  const choiceProviders: Providers | null = providers
    ? { ...providers, models: selectableModels, keys: selectableKeys }
    : null;
  const selectedModel = selectableModels.find((model) => model.id === config.model);

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
            providers={choiceProviders}
            config={config}
            keyId={keyId}
            onModel={(model) => setConfig((previous) => ({ ...previous, model }))}
            onKey={setKeyId}
          />
          {!providers?.keys.length && (
            <button type="button" className="text-action manage-connections" onClick={onManageKeys}>
              Add an API connection in Settings
            </button>
          )}
          {providers?.keys.length ? (
            <button type="button" className="text-action manage-connections" onClick={onManageKeys}>
              Manage API Connections
            </button>
          ) : null}

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
        <span className="sr-only">Selected model: {selectedModel?.name ?? config.model}</span>
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
  const embeddingModel = config?.model ?? processing?.model;
  const embeddingModelName = embeddingModel === "gemini-embedding-2" ? "Gemini Embedding 2" : embeddingModel;

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
              <dl className="world-details-grid">
                <div><dt>Embedding Model</dt><dd>{embeddingModelName ?? "Unavailable"}</dd></div>
                <div><dt>Maximum Chunk Size</dt><dd>{maxChunkSize ?? "Unavailable"}{maxChunkSize != null ? " characters" : ""}</dd></div>
                <div><dt>Boundary Search Distance</dt><dd>{boundarySearchDistance ?? "Unavailable"}{boundarySearchDistance != null ? " characters" : ""}</dd></div>
              </dl>
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
