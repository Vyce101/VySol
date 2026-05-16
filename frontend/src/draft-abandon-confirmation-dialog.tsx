import { CircleAlert, X } from "lucide-react";
import { useEffect } from "react";

const DISCARDED_ITEMS = [
  "Draft world name and description",
  "Selected background and font choices",
  "Staged sources and extraction setup",
];

const RETAINED_ITEMS = ["Uploaded global assets"];

export function DraftAbandonConfirmationDialog({
  errorMessage,
  isDiscarding,
  onCancel,
  onConfirm,
}: {
  errorMessage: string | null;
  isDiscarding: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || isDiscarding) {
        return;
      }

      event.preventDefault();
      onCancel();
    };

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isDiscarding, onCancel]);

  return (
    <div className="draft-abandon-dialog-layer" role="presentation">
      <div className="draft-abandon-dialog-backdrop" aria-hidden="true" />
      <section
        className="draft-abandon-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="draft-abandon-dialog-title"
        aria-describedby="draft-abandon-dialog-description"
      >
        <button
          className="draft-abandon-dialog-close"
          type="button"
          onClick={onCancel}
          aria-label="Keep editing"
          disabled={isDiscarding}
        >
          <X aria-hidden="true" />
        </button>
        <div className="draft-abandon-dialog-header">
          <span className="draft-abandon-dialog-icon" aria-hidden="true">
            <CircleAlert />
          </span>
          <h2 id="draft-abandon-dialog-title">Discard draft world?</h2>
        </div>
        <p
          id="draft-abandon-dialog-description"
          className="draft-abandon-dialog-intro"
        >
          Leaving now will affect the following items:
        </p>
        <div className="draft-abandon-dialog-impact">
          <section aria-labelledby="draft-abandon-discarded-title">
            <h3 id="draft-abandon-discarded-title">Will be discarded</h3>
            <ul>
              {DISCARDED_ITEMS.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="draft-abandon-retained-title">
            <h3 id="draft-abandon-retained-title">Will remain available</h3>
            <ul>
              {RETAINED_ITEMS.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        </div>
        {errorMessage !== null ? (
          <p className="draft-abandon-dialog-error" role="alert">
            {errorMessage}
          </p>
        ) : null}
        <div className="draft-abandon-dialog-actions">
          <button
            className="draft-abandon-dialog-keep"
            type="button"
            onClick={onCancel}
            disabled={isDiscarding}
          >
            Keep Editing
          </button>
          <button
            className="draft-abandon-dialog-discard"
            type="button"
            onClick={onConfirm}
            disabled={isDiscarding}
          >
            {isDiscarding ? "Discarding..." : "Discard Draft"}
          </button>
        </div>
        <p className="draft-abandon-dialog-warning">
          This action cannot be undone.
        </p>
      </section>
    </div>
  );
}
