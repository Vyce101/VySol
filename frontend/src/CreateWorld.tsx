import { useRef, useState } from "react";
import { Check, FileText, Plus, SpinnerGap, WarningCircle, X } from "@phosphor-icons/react";
import { api, jsonRequest, sendBook, type World, type CreationAttempt } from "./api";

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


type BookChoice = {
  id: string;
  file: File;
  state: "ready" | "pending" | "done" | "failed";
  message?: string;
};

export function CreateWorld({
  visible,
  onCreated,
  onFinished,
  onComplete,
}: {
  visible: boolean;
  onCreated: (world: World) => void;
  onFinished: (complete: boolean) => void;
  onComplete?: (world: World) => void;
}) {
  const [name, setName] = useState("");
  const [choices, setChoices] = useState<BookChoice[]>([]);
  const [world, setWorld] = useState<World | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const worldId = useRef(crypto.randomUUID());
  const filePicker = useRef<HTMLInputElement>(null);
  const submitting = useRef(false);
  const update = (id: string, patch: Partial<BookChoice>) =>
    setChoices((previous) =>
      previous.map((book) => (book.id === id ? { ...book, ...patch } : book)),
    );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    if (!name.trim()) {
      setMessage("Give your world a name.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setMessage("");
    onFinished(false);
    let allSucceeded = true;
    try {
      const created =
        world ??
        (await api<World>(
          "/worlds",
          jsonRequest("POST", { id: worldId.current, name }),
        ));
      setWorld(created);
      onCreated(created);
      for (const book of choices.filter((book) => book.state !== "done")) {
        update(book.id, { state: "pending", message: undefined });
        try {
          const outcome = await sendBook(created.id, book.id, book.file);
          if (outcome.error) allSucceeded = false;
          // A definitive failure may be retried as a new attempt; an uncertain
          // response retains its ID so reconciliation can prevent duplicates.
          update(
            book.id,
            outcome.error
              ? {
                  id: crypto.randomUUID(),
                  state: "failed",
                  message:
                    outcome.message || "This book could not be imported.",
                }
              : { state: "done" },
          );
        } catch (error) {
          allSucceeded = false;
          update(book.id, {
            state: "failed",
            message:
              error instanceof Error ? error.message : "Please try again.",
          });
        }
      }
      onFinished(allSucceeded);
      if (allSucceeded) onComplete?.(created);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Could not create your world.",
      );
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const failed = choices.some((book) => book.state === "failed");
  const pending = choices.some((book) => book.state === "ready");
  return (
    <section
      className={`view create-view ${visible ? "is-visible" : ""}`}
      aria-hidden={!visible}
      inert={!visible}
    >
      <form className="creation-form" onSubmit={submit}>
        <h1>Create World</h1>
        <label className="field-label" htmlFor="world-name">
          World name
        </label>
        <input
          id="world-name"
          className="name-input"
          value={name}
          maxLength={200}
          placeholder="Give your world a name"
          required
          disabled={!!world || busy}
          onChange={(event) => setName(event.target.value)}
        />
        <div className="books-heading">
          Books <span>(optional)</span>
        </div>
        <button
          type="button"
          className="text-action add-books"
          onClick={() => filePicker.current?.click()}
          disabled={busy}
        >
          <Plus weight="light" />
          <span>Add books</span>
        </button>
        <input
          ref={filePicker}
          type="file"
          multiple
          accept=".epub,.txt"
          hidden
          onChange={(event) => {
            const selectedFiles = Array.from(event.target.files ?? []);
            onFinished(false);
            setChoices((previous) => [
              ...previous,
              ...selectedFiles.map((file) => ({
                id: crypto.randomUUID(),
                file,
                state: "ready" as const,
              })),
            ]);
            event.target.value = "";
          }}
        />
        <p className="file-hint">EPUB or TXT. Books are optional.</p>
        <ul className="book-list">
          {choices.map((book) => (
            <li key={book.id} className={`book-row ${book.state}`}>
              <div className="book-line">
                <FileText size={21} weight="light" />
                <span className="book-filename" title={book.file.name}>
                  {book.file.name}
                </span>
                {book.state === "done" ? (
                  <Check size={18} aria-label="Imported" />
                ) : book.state === "pending" ? (
                  <SpinnerGap className="spinning" aria-label="Importing" />
                ) : (
                  <button
                    type="button"
                    className="icon-button remove-book"
                    aria-label={`Remove ${book.file.name}`}
                    disabled={busy}
                    onClick={() => {
                      const remaining = choices.filter(
                        (item) => item.id !== book.id,
                      );
                      setChoices(remaining);
                      onFinished(
                        !!world &&
                          remaining.every((item) => item.state === "done"),
                      );
                    }}
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
              {book.message && <p className="book-error">{book.message}</p>}
            </li>
          ))}
        </ul>
        <div aria-live="polite" className="creation-result">
          {busy && <p className="muted">Preparing your books…</p>}
          {world && !busy && (
            <p>
              {failed
                ? "Your world is created. Some books need attention."
                : pending
                  ? "Your world is created."
                  : choices.length
                    ? "Your world and books are ready."
                    : "Your world is created."}
            </p>
          )}
          {message && (
            <p role="alert" className="error-message">
              {message}
            </p>
          )}
        </div>
        {(!world || busy || failed || pending) && (
          <div className="form-actions">
            <button className="primary-button" disabled={busy} type="submit">
              {busy
                ? "Preparing…"
                : !world
                  ? "Create World"
                  : failed
                    ? "Retry Failed Books"
                    : "Import Books"}
            </button>
          </div>
        )}
      </form>
    </section>
  );
}

