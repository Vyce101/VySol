import { useLayoutEffect, useRef, useState } from "react";
import { DotsSixVertical, FileText, X } from "@phosphor-icons/react";

type Book = {
  id: string;
  filename: string;
  size: number;
  file?: File;
  uploaded?: boolean;
};
type Drag = { id: string; startY: number; y: number; slot: number };

/** Book ordering with a lifted row and a destination marker; order changes on drop. */
export function BookList({
  books,
  onReorder,
  onRemove,
}: {
  books: Book[];
  onReorder: (id: string, position: number) => void;
  onRemove: (id: string) => void;
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
          { duration: 180, easing: "ease-out" },
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
      onReorder(current.id, destination);
    }
  }
  const from = drag ? books.findIndex((book) => book.id === drag.id) : -1;
  const destination = drag ? drag.slot - (from < drag.slot ? 1 : 0) : -1;
  const showMarker = drag && destination !== from;

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
          className={`selection-row${drag?.id === book.id ? " is-dragging" : ""}`}
          data-book-id={book.id}
          data-drop-before={(showMarker && drag.slot === index) || undefined}
          data-drop-after={
            (showMarker &&
              drag.slot === books.length &&
              index === books.length - 1) ||
            undefined
          }
          style={
            drag?.id === book.id
              ? { transform: `translateY(${drag.y - drag.startY}px)` }
              : undefined
          }
        >
          <button
            type="button"
            className="reorder-handle icon-button"
            aria-label={`Reorder ${book.filename}`}
            aria-describedby="reorder-help"
            aria-pressed={drag?.id === book.id}
            onKeyDown={(event) => {
              if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                event.preventDefault();
                onReorder(book.id, index + (event.key === "ArrowUp" ? -1 : 1));
              }
            }}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.preventDefault();
              event.currentTarget.focus();
              event.currentTarget.setPointerCapture(event.pointerId);
              const current = {
                id: book.id,
                startY: event.clientY,
                y: event.clientY,
                slot: index,
              };
              dragging.current = current;
              setDrag(current);
            }}
            onPointerMove={(event) => {
              const current = dragging.current;
              if (!current) return;
              const rows = [
                ...list.current!.querySelectorAll<HTMLElement>(
                  "[data-book-id]",
                ),
              ];
              const target = rows.findIndex((row) => {
                if (row.dataset.bookId === current.id) return false;
                const rect = row.getBoundingClientRect();
                return event.clientY < rect.top + rect.height / 2;
              });
              const updated = {
                ...current,
                y: event.clientY,
                slot: target < 0 ? books.length : target,
              };
              dragging.current = updated;
              setDrag(updated);
              const content =
                list.current!.closest<HTMLElement>(".modal-content");
              if (content) {
                const bounds = content.getBoundingClientRect();
                if (event.clientY < bounds.top + 40) content.scrollBy?.(0, -12);
                else if (event.clientY > bounds.bottom - 40)
                  content.scrollBy?.(0, 12);
              }
            }}
            onPointerUp={() => finish(true)}
            onPointerCancel={() => finish(false)}
            onLostPointerCapture={() => finish(false)}
          >
            <DotsSixVertical size={22} />
          </button>
          <span className="book-number">{index + 1}</span>
          <FileText size={22} />
          <div className="book-selection-name">
            <span title={book.filename}>{book.filename}</span>
            <small>{(book.size / 1024 / 1024).toFixed(2)} MB</small>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label={`Remove ${book.filename}`}
            onClick={() => onRemove(book.id)}
          >
            <X size={19} />
          </button>
        </li>
      ))}
    </ol>
  );
}
