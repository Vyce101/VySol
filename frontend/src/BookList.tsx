import { useLayoutEffect, useRef, useState } from "react";
import { Check, DotsSixVertical, WarningCircle, X } from "@phosphor-icons/react";

type Book = {
  id: string;
  filename: string;
  size: number;
  file?: File;
  uploaded?: boolean;
  status?: string;
  state?: string;
  chunksDone?: number;
  chunksTotal?: number;
};
type Drag = { id: string; startY: number; y: number; slot: number; step: number };

function storyTitle(filename: string) {
  return filename.replace(/\.(txt|epub)$/i, "");
}

/** Book ordering with a lifted row and live space for its destination. */
export function BookList({
  books,
  onReorder,
  onRemove,
  locked = false,
}: {
  books: Book[];
  onReorder?: (id: string, position: number) => void;
  onRemove?: (id: string) => void;
  locked?: boolean;
}) {
  const list = useRef<HTMLOListElement>(null);
  const positions = useRef(new Map<string, number>());
  const dragging = useRef<Drag | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);

  useLayoutEffect(() => {
    const next = new Map<string, number>();
    for (const row of list.current?.querySelectorAll<HTMLElement>(
      "[data-book-id]",
    ) ?? []) {
      const id = row.dataset.bookId!;
      const top = row.offsetTop;
      const previous = positions.current.get(id);
      if (
        previous !== undefined &&
        previous !== top &&
        !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
      ) {
        row.animate?.(
          [
            { transform: `translateY(${previous - top}px)` },
            { transform: "translateY(0)" },
          ],
          { duration: 180, easing: "cubic-bezier(0.2, 0, 0.38, 0.9)" },
        );
      }
      next.set(id, top);
    }
    positions.current = next;
  }, [books]);

  function finish(commit: boolean) {
    const current = dragging.current;
    if (!current) return;
    dragging.current = null;
    setDrag(null);
    const from = books.findIndex((book) => book.id === current.id);
    const destination = current.slot - (from < current.slot ? 1 : 0);
    if (commit) {
      if (destination !== from) {
        // Land from the released position instead of jumping back to the old row.
        positions.current.set(
          current.id,
          (positions.current.get(current.id) ?? 0) + current.y - current.startY,
        );
      }
      onReorder?.(current.id, destination);
    }
  }
  return (
    <ol
      ref={list}
      className="selection-books"
      onKeyDown={(event) => {
        if (event.key === "Escape" && dragging.current) {
          event.preventDefault();
          event.stopPropagation();
          finish(false);
        }
      }}
    >
      {books.map((book, index) => (
        <li
          key={book.id}
          className={`selection-row${drag?.id === book.id ? " is-dragging" : ""}${locked ? " is-locked" : ""}${book.state ? ` book-state-${book.state}` : ""}`}
          data-book-id={book.id}
          style={drag ? { transform: dragTransform(drag, book.id, index, books) } : undefined}
        >
          {!locked && (
            <button
              type="button"
              className="reorder-handle icon-button"
              aria-label={`Reorder ${book.filename}`}
              aria-describedby="reorder-help"
              aria-pressed={drag?.id === book.id}
              onKeyDown={(event) => {
                if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                  event.preventDefault();
                  onReorder?.(book.id, index + (event.key === "ArrowUp" ? -1 : 1));
                }
              }}
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                event.preventDefault();
                event.currentTarget.focus();
                event.currentTarget.setPointerCapture(event.pointerId);
                const rows = [
                  ...list.current!.querySelectorAll<HTMLElement>("[data-book-id]"),
                ];
                const row = rows[index];
                const nextRow = rows[index + 1];
                const rowGap = Number.parseFloat(
                  getComputedStyle(list.current!).rowGap,
                ) || 7;
                const step = nextRow
                  ? nextRow.offsetTop - row.offsetTop ||
                    nextRow.getBoundingClientRect().top - row.getBoundingClientRect().top
                  : row.offsetHeight + rowGap;
                const current = {
                  id: book.id,
                  startY: event.clientY,
                  y: event.clientY,
                  slot: index,
                  step,
                };
                dragging.current = current;
                setDrag(current);
              }}
              onPointerMove={(event) => {
                const current = dragging.current;
                if (!current) return;
                const rows = [
                  ...list.current!.querySelectorAll<HTMLElement>("[data-book-id]"),
                ];
                const target = rows.findIndex((row) => {
                  if (row.dataset.bookId === current.id) return false;
                  const listTop = list.current!.getBoundingClientRect().top;
                  return event.clientY < listTop + row.offsetTop + row.offsetHeight / 2;
                });
                const updated = {
                  ...current,
                  y: event.clientY,
                  slot: target < 0 ? books.length : target,
                };
                dragging.current = updated;
                setDrag(updated);
                const content = list.current!.closest<HTMLElement>(".create-world-content");
                if (content) {
                  const bounds = content.getBoundingClientRect();
                  if (event.clientY < bounds.top + 40) content.scrollBy?.(0, -12);
                  else if (event.clientY > bounds.bottom - 40) content.scrollBy?.(0, 12);
                }
              }}
              onPointerUp={() => finish(true)}
              onPointerCancel={() => finish(false)}
              onLostPointerCapture={() => finish(false)}
            >
              <DotsSixVertical size={20} />
            </button>
          )}
          <span className="book-number">{String(index + 1).padStart(2, "0")}</span>
          <div className="book-selection-name">
            <span title={book.filename}>{storyTitle(book.filename)}</span>
            {book.status && !locked && <small className={`book-status status-${book.state ?? "running"}`}>{book.status}</small>}
            {book.chunksTotal !== undefined && book.chunksTotal > 0 && (
              <span className="book-row-progress">
                <progress max={book.chunksTotal} value={book.chunksDone ?? 0} aria-label={`Chunks embedded for ${book.filename}`} />
                <small>{book.chunksDone ?? 0} of {book.chunksTotal} chunks embedded</small>
              </span>
            )}
          </div>
          {locked ? (
            book.state === "done" || book.state === "failed" ? (
              <span className={`book-complete-mark book-state-label-${book.state}`}>
                {book.state === "done" ? <span className="complete-dot"><Check size={11} weight="bold" /></span> : <WarningCircle size={15} />}
                {book.state === "done" ? "Complete" : "Attention"}
              </span>
            ) : book.chunksTotal === undefined || book.chunksTotal <= 0 ? (
              <span className="book-progress-state">{book.status ?? "Creating"}</span>
            ) : null
          ) : (
            <button
              type="button"
              className="icon-button remove-book"
              aria-label={`Remove ${book.filename}`}
              onClick={() => onRemove?.(book.id)}
            >
              <X size={20} weight="light" />
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}

function dragTransform(drag: Drag, id: string, index: number, books: Book[]) {
  const sourceIndex = books.findIndex((book) => book.id === drag.id);
  if (id === drag.id) return `translateY(${drag.y - drag.startY}px)`;
  if (drag.slot > sourceIndex && index > sourceIndex && index < drag.slot)
    return `translateY(-${drag.step}px)`;
  if (drag.slot < sourceIndex && index >= drag.slot && index < sourceIndex)
    return `translateY(${drag.step}px)`;
  return undefined;
}
