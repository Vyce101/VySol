import { useEffect, useRef, useState } from "react";
import { BookList } from "./BookList";
import {
  Check,
  FileText,
  Plus,
  Question,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  api,
  jsonRequest,
  type CreationAttempt,
  type ProcessingConfig,
  type Providers,
} from "./api";

type Choice = {
  id: string;
  filename: string;
  size: number;
  file?: File;
  uploaded?: boolean;
  message?: string;
};
const defaults: ProcessingConfig = {
  model: "gemini-embedding-2",
  size: 8000,
  search: 1000,
};
const stageNames: Record<string, string> = {
  waiting: "Waiting for upload",
  uploaded: "Uploaded",
  converting: "Converting text…",
  chunking: "Splitting text…",
  prepared: "",
  embedding: "Embedding…",
  done: "Complete",
  failed: "",
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
      <h2>Chunking</h2>
      <button
        ref={button}
        type="button"
        className="icon-button chunking-help-button"
        aria-label="About chunking"
        aria-describedby="chunking-help"
        onPointerEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
      >
        <Question size={19} />
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
            index the text. All the text is kept, with no repeated text between
            chunks.
          </p>
          <p>
            <strong>Maximum chunk size</strong> is the most characters in each
            piece, including spaces. Pieces may be shorter.
          </p>
          <p>
            <strong>Boundary search distance</strong> is how far back from that
            limit VySol looks for a natural stopping point. It prefers paragraph
            breaks, then line breaks, then ? ! or . marks, then spaces. If none
            fit, it cuts at the limit.
          </p>
        </div>
      </div>
    </div>
  );
}

export function CreationProgress({ attempt }: { attempt: CreationAttempt }) {
  return (
    <div className="creation-progress">
      <p>
        {attempt.books_done} of {attempt.books.length} books complete
      </p>
      <p className="muted">
        {attempt.chunks_done} of {attempt.chunks_total} chunks embedded
      </p>
      {attempt.chunks_total > 0 && (
        <progress
          aria-label="Embedding progress"
          max={attempt.chunks_total}
          value={attempt.chunks_done}
        />
      )}
      <ol className="processing-books">
        {attempt.books.map((book) => (
          <li
            key={book.id}
            className={book.state === "failed" ? "has-error" : ""}
          >
            {book.state === "done" ? (
              <Check aria-label="Complete" />
            ) : book.state === "failed" ? (
              <WarningCircle aria-label="Failed" />
            ) : (
              <FileText />
            )}
            <div>
              <strong>{book.filename}</strong>
              <p className="muted">
                {stageNames[book.state] ?? book.state}
                {book.chunks_total > 0
                  ? `${stageNames[book.state] ? " · " : ""}${book.chunks_done} of ${book.chunks_total} chunks embedded`
                  : ""}
              </p>
              {book.message && (
                <p className="error-message">
                  {book.message.replace(/\s*Resume later\./g, "")}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
      {attempt.state === "failed" &&
        attempt.message &&
        !attempt.books.some((book) => book.message) && (
          <p
            className={attempt.state === "failed" ? "error-message" : ""}
            role={attempt.state === "failed" ? "alert" : "status"}
          >
            {attempt.state === "failed" && (
              <WarningCircle aria-label="Failed" />
            )}
            {attempt.message}
          </p>
        )}
      {attempt.state !== "complete" && (
        <p className="muted progress-note">
          You can close this window while VySol works. Your progress is saved
          locally.
        </p>
      )}
    </div>
  );
}

export function CreateWorld({
  visible,
  attempt,
  onAttempt,
  onClose,
  onManageKeys,
  onUploading,
}: {
  visible: boolean;
  attempt: CreationAttempt | null;
  onAttempt: (value: CreationAttempt | null) => void;
  onClose: () => void;
  onManageKeys: () => void;
  onUploading?: (value: boolean) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const draftId = useRef<string>(crypto.randomUUID());
  const loadedId = useRef<string | null>(null);
  const [name, setName] = useState("");
  const [choices, setChoices] = useState<Choice[]>([]);
  const [config, setConfig] = useState<ProcessingConfig>(defaults);
  const [keyId, setKeyId] = useState("");
  const [providers, setProviders] = useState<Providers | null>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const submitting = useRef(false);
  const defaultsLoaded = useRef(false);
  const active = attempt?.state === "running" || attempt?.state === "pausing";

  useEffect(() => {
    if (visible) dialog.current?.showModal();
    else dialog.current?.close();
  }, [visible]);
  useEffect(() => {
    if (visible) {
      dialog.current?.querySelector<HTMLElement>("#creation-title")?.focus();
      const content = dialog.current?.querySelector(".modal-content");
      if (content) content.scrollTop = 0;
    }
  }, [step]);

  function restore(value: CreationAttempt) {
    setName(value.name);
    setConfig(value.config);
    setKeyId(value.key_id);
    setChoices((previous) =>
      value.books.map((book) => ({
        ...book,
        file: previous.find((item) => item.id === book.id)?.file,
      })),
    );
  }
  useEffect(() => {
    if (attempt && loadedId.current !== attempt.id) {
      loadedId.current = attempt.id;
      draftId.current = attempt.id;
      restore(attempt);
      setStep(3);
    }
  }, [attempt]);
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    api<Providers>("/providers")
      .then((value) => {
        if (cancelled) return;
        setProviders(value);
        if (!defaultsLoaded.current && !attempt) {
          setKeyId(value.defaults.key_id);
          setConfig((previous) => ({
            ...previous,
            model: value.defaults.model,
          }));
          defaultsLoaded.current = true;
        }
      })
      .catch(() => {
        if (!cancelled)
          setError(
            "Could not load your API keys. Reopen this window to try again.",
          );
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
          (book) => book.filename === file.name && !book.uploaded && !book.file,
        );
        if (missing >= 0)
          next[missing] = { ...next[missing], file, size: file.size };
        else
          next.push({
            id: crypto.randomUUID(),
            filename: file.name,
            size: file.size,
            file,
          });
      }
      return next;
    });
  }
  function next() {
    setError("");
    if (step === 0 && (!name.trim() || choices.length === 0)) {
      setError("Give your world a name and add at least one book.");
      return;
    }
    if (
      step === 1 &&
      (!providers?.keys.some((key) => key.id === keyId) ||
        !Number.isInteger(config.size) ||
        config.size < 1 ||
        config.size > 1000000 ||
        !Number.isInteger(config.search) ||
        config.search < 0 ||
        config.search >= config.size)
    ) {
      setError(
        "Select an API key and use a positive chunk size with a smaller, nonnegative boundary search.",
      );
      return;
    }
    setStep(step + 1);
  }

  async function refreshAfterError(cause: unknown) {
    setError(
      cause instanceof Error
        ? cause.message
        : "Could not finish this action. Please try again.",
    );
    const saved = await api<CreationAttempt | null>(
      `/creation/${draftId.current}`,
    ).catch(() => null);
    if (saved) {
      onAttempt(saved);
      restore(saved);
      setStep(3);
    }
  }
  async function uploadBooks(current: CreationAttempt) {
    for (const book of current.books) {
      if (book.uploaded) continue;
      const selected = choices.find((choice) => choice.id === book.id);
      if (!selected?.file)
        throw new Error(
          `The upload for ${book.filename} is unavailable. Discard this attempt and start again.`,
        );
      const operation = crypto.randomUUID();
      const path: string = `/creation/${current.id}/books/${book.id}?revision=${current.revision}&operation_id=${operation}`;
      // Repeating this exact operation safely reconciles a lost upload response.
      const request = {
        method: "PUT",
        headers: {
          "X-Filename": encodeURIComponent(book.filename),
          "Content-Type": "application/octet-stream",
        },
        body: selected.file,
      };
      try {
        current = await api<CreationAttempt>(path, request);
      } catch {
        current = await api<CreationAttempt>(path, request);
      }
      onAttempt(current);
    }
    return current;
  }
  async function submit() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    let current = attempt;
    let savedManifest = false;
    try {
      const manifestRequest = jsonRequest("PUT", {
        operation_id: crypto.randomUUID(),
        revision: current?.revision ?? 0,
        name,
        key_id: keyId,
        config,
        books: choices.map(({ id, filename, size }) => ({
          id,
          filename,
          size,
        })),
      });
      try {
        current = await api<CreationAttempt>(
          `/creation/${draftId.current}`,
          manifestRequest,
        );
      } catch {
        current = await api<CreationAttempt>(
          `/creation/${draftId.current}`,
          manifestRequest,
        );
      }
      savedManifest = true;
      loadedId.current = current.id;
      onAttempt(current);
      setStep(3);
      onUploading?.(true);
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
      if (savedManifest) await refreshAfterError(cause);
      else {
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not save this attempt. Please try again.",
        );
        // A lost save response must not strand a draft at revision zero.
        // Submission fixes the manifest even when its response is lost.
        const saved = await api<CreationAttempt | null>(
          `/creation/${draftId.current}`,
        ).catch(() => null);
        if (saved) {
          loadedId.current = saved.id;
          onAttempt(saved);
          restore(saved);
          setStep(3);
        }
      }
    } finally {
      setBusy(false);
      submitting.current = false;
      onUploading?.(false);
    }
  }
  async function action(kind: "start" | "pause" | "discard") {
    if (busy) return;
    if (!attempt) return;
    setBusy(true);
    setError("");
    try {
      if (kind === "discard") {
        await api(`/creation/${attempt.id}?revision=${attempt.revision}`, {
          method: "DELETE",
        });
        onAttempt(null);
        resetDraft();
      } else {
        let current = attempt;
        if (kind === "start") {
          onUploading?.(current.books.some((book) => !book.uploaded));
          current = await uploadBooks(current);
        }
        const value = await api<CreationAttempt>(
          `/creation/${current.id}/${kind}`,
          jsonRequest("POST", {
            revision: current.revision,
            operation_id: crypto.randomUUID(),
          }),
        );
        onAttempt(value);
      }
    } catch (cause) {
      await refreshAfterError(cause);
    } finally {
      setBusy(false);
      onUploading?.(false);
    }
  }

  function resetDraft() {
    loadedId.current = null;
    draftId.current = crypto.randomUUID();
    setName("");
    setChoices([]);
    setConfig(defaults);
    setKeyId("");
    defaultsLoaded.current = false;
    setStep(0);
    setError("");
    setAnnouncement("");
    setConfirmDiscard(false);
    onClose();
  }

  function close() {
    if (!attempt && !submitting.current) resetDraft();
    else onClose();
  }

  return (
    <dialog
      ref={dialog}
      className="creation-modal"
      aria-labelledby="creation-title"
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled):not([hidden]), select:not(:disabled), [tabindex="0"]',
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0],
          last = controls[controls.length - 1];
        if (!first || !last) return;
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            !controls.includes(document.activeElement as HTMLElement))
        ) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <header className="modal-heading">
        <div>
          {step < 3 && (
            <p className="eyebrow">A world begins with its stories</p>
          )}
          <h1 id="creation-title" tabIndex={-1}>
            {step === 3 && attempt ? attempt.name : "Create World"}
          </h1>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Close creation"
          onClick={close}
        >
          <X size={24} />
        </button>
      </header>
      {step < 3 && (
        <ol className="creation-steps" aria-label="Creation steps">
          {["Books", "Processing", "Review"].map((label, index) => (
            <li key={label} aria-current={step === index ? "step" : undefined}>
              <span>{index + 1}</span>
              {label}
            </li>
          ))}
        </ol>
      )}
      <div className="modal-content">
        {step === 0 && (
          <>
            <label className="field-label" htmlFor="world-name">
              World name
            </label>
            <input
              id="world-name"
              className="name-input"
              maxLength={200}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Give your world a name"
            />
            <div className="books-heading">
              Books <span>{choices.length > 0 && `· ${choices.length}`}</span>
            </div>
            <p className="muted">
              Arrange your books in the order they should be read.
            </p>
            <p id="reorder-help" className="sr-only">
              Drag a handle to reorder. With a handle focused, use the up and
              down arrow keys.
            </p>
            <BookList
              books={choices}
              onReorder={reorder}
              onRemove={(id) =>
                setChoices(choices.filter((book) => book.id !== id))
              }
            />
            <button
              type="button"
              className="add-books-area"
              onClick={() => picker.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                addFiles(Array.from(event.dataTransfer.files));
              }}
            >
              <span className="text-action">
                <Plus size={18} /> Add books
              </span>
              <span className="muted">
                Choose or drop TXT and EPUB files here.
              </span>
            </button>
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
            <span className="sr-only" aria-live="polite">
              {announcement}
            </span>
          </>
        )}
        {step === 1 && (
          <>
            <h2>Embedding</h2>
            <div className="processing-fields">
              <label>
                Model
                <select
                  value={config.model}
                  onChange={(event) =>
                    setConfig({ ...config, model: event.target.value })
                  }
                >
                  <option value="gemini-embedding-2">Gemini Embedding 2</option>
                </select>
              </label>
              <label>
                API key
                <select
                  value={keyId}
                  onChange={(event) => setKeyId(event.target.value)}
                >
                  <option value="">Select a saved key</option>
                  {keyId &&
                    !providers?.keys.some((key) => key.id === keyId) && (
                      <option value={keyId} disabled>
                        Previously used key unavailable
                      </option>
                    )}
                  {providers?.keys.map((key) => (
                    <option key={key.id} value={key.id}>
                      {key.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button
              type="button"
              className="text-action"
              onClick={onManageKeys}
            >
              Manage API keys
            </button>
            <ChunkingHelp />
            <div className="processing-fields">
              <label>
                <span>
                  Maximum chunk size <span className="field-unit">(chars)</span>
                </span>
                <div className="number-field">
                  <input
                    aria-label="Maximum chunk size"
                    type="number"
                    min={1}
                    max={1000000}
                    value={config.size}
                    onChange={(event) =>
                      setConfig({ ...config, size: Number(event.target.value) })
                    }
                  />
                </div>
              </label>
              <label>
                <span>
                  Boundary search distance{" "}
                  <span className="field-unit">(chars)</span>
                </span>
                <div className="number-field">
                  <input
                    aria-label="Boundary search distance"
                    type="number"
                    min={0}
                    max={config.size - 1}
                    value={config.search}
                    onChange={(event) =>
                      setConfig({
                        ...config,
                        search: Number(event.target.value),
                      })
                    }
                  />
                </div>
              </label>
            </div>
          </>
        )}
        {step === 2 && (
          <div className="creation-review">
            <h2>{name}</h2>
            <h3>Books</h3>
            <ol>
              {choices.map((book) => (
                <li key={book.id}>{book.filename}</li>
              ))}
            </ol>
            <h3>Processing</h3>
            <dl>
              <dt>Embedding model</dt>
              <dd>Gemini Embedding 2</dd>
              <dt>API key</dt>
              <dd>
                {providers?.keys.find((key) => key.id === keyId)?.name ??
                  "Unavailable"}
              </dd>
              <dt>Maximum chunk size</dt>
              <dd>{config.size.toLocaleString()} characters</dd>
              <dt>Boundary search distance</dt>
              <dd>{config.search.toLocaleString()} characters</dd>
            </dl>
            <p className="acceptance-note">
              After this world is successfully created, its source text and book
              order are fixed.
            </p>
            <p className="muted"></p>
          </div>
        )}
        {step === 3 && attempt && (
          <CreationProgress
            attempt={
              busy && attempt.phase === "uploading"
                ? { ...attempt, state: "running" }
                : attempt
            }
          />
        )}
        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {confirmDiscard && (
          <div className="discard-confirmation">
            <p>
              Discard this attempt and its saved progress? Your existing worlds
              will be kept.
            </p>
            <button
              type="button"
              className="text-action"
              onClick={() => setConfirmDiscard(false)}
            >
              Keep attempt
            </button>
            <button
              type="button"
              className="danger-action"
              disabled={busy}
              onClick={() => void action("discard")}
            >
              Discard attempt
            </button>
          </div>
        )}
      </div>
      <footer className="modal-actions">
        {step < 3 ? (
          <>
            <div>
              <button
                type="button"
                className="text-action"
                disabled={busy}
                onClick={() => (step === 0 ? close() : setStep(step - 1))}
              >
                {step === 0 ? "Close" : "← Back"}
              </button>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={busy}
              onClick={() => (step === 2 ? void submit() : next())}
            >
              {busy
                ? "Starting…"
                : step === 2
                  ? "Create World"
                  : step === 1
                    ? "Review →"
                    : "Continue →"}
            </button>
          </>
        ) : attempt?.state === "complete" ? (
          <button type="button" className="primary-button" onClick={onClose}>
            Done
          </button>
        ) : (
          <>
            <button
              type="button"
              className="text-action"
              disabled={busy}
              onClick={() => setConfirmDiscard(true)}
            >
              Discard
            </button>
            <div>
              <button
                type="button"
                className="primary-button"
                disabled={busy || attempt?.state === "pausing"}
                onClick={() => void action(active ? "pause" : "start")}
              >
                {busy ? "Saving…" : active ? "Pause" : "Resume"}
              </button>
            </div>
          </>
        )}
      </footer>
    </dialog>
  );
}
