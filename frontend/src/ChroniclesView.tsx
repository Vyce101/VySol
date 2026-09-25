import { BookOpen, ChatCircleDots, Clock, DotsThree, MagnifyingGlass, PencilSimple, Plus, Trash, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, jsonRequest, type Chronicle } from "./api";
import { rankChronicles } from "./chronicleSearch";

export type ChronicleRoute = Pick<Chronicle, "id" | "title">;

type ChroniclesViewProps = {
  visible: boolean;
  worldId: string;
  worldName: string;
  isWorldReady: boolean;
  onOpenChronicle: (chronicle: ChronicleRoute) => void;
  onPendingChronicleAttempt?: () => void;
};

function relativeTime(value: string | null, now: number) {
  if (!value) return "Not started";
  const elapsedMinutes = Math.max(0, Math.floor((now - new Date(value).getTime()) / 60_000));
  if (elapsedMinutes < 1) return "Just now";
  if (elapsedMinutes < 60) return `${elapsedMinutes} min ago`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours} hr ago`;
  const elapsedDays = Math.floor(elapsedHours / 24);
  if (elapsedDays < 7) return `${elapsedDays} ${elapsedDays === 1 ? "day" : "days"} ago`;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

export function ChroniclesView({
  visible,
  worldId,
  worldName,
  isWorldReady,
  onOpenChronicle,
  onPendingChronicleAttempt,
}: ChroniclesViewProps) {
  const [chronicles, setChronicles] = useState<Chronicle[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pendingChat, setPendingChat] = useState(false);
  const [query, setQuery] = useState("");
  const [now, setNow] = useState(Date.now());
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Chronicle | null>(null);
  const [exitingRows, setExitingRows] = useState<{ chronicle: Chronicle; index: number }[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const exitTimer = useRef<number | undefined>(undefined);
  const previousPositions = useRef(new Map<string, DOMRect>());
  const rowRefs = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    if (!visible || !worldId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    api<Chronicle[]>(`/worlds/${encodeURIComponent(worldId)}/chronicles`)
      .then((items) => { if (!cancelled) setChronicles(items); })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Chronicles could not be loaded."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [visible, worldId]);

  useEffect(() => {
    if (!visible) return;
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [visible]);

  useEffect(() => () => window.clearTimeout(exitTimer.current), []);

  useEffect(() => {
    if (!openMenu) return;
    const closeFromOutside = (event: PointerEvent) => {
      if (!rowRefs.current.get(openMenu)?.contains(event.target as Node)) setOpenMenu(null);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      rowRefs.current.get(openMenu)?.querySelector<HTMLButtonElement>(".chronicle-menu-trigger")?.focus();
      setOpenMenu(null);
    };
    document.addEventListener("pointerdown", closeFromOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeFromOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [openMenu]);

  useEffect(() => {
    if (!visible || isWorldReady) setPendingChat(false);
  }, [visible, isWorldReady]);

  useEffect(() => {
    if (!deleteTarget) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDeleteTarget(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [deleteTarget]);

  const shownChronicles = useMemo(() => rankChronicles(chronicles, query), [chronicles, query]);

  function updateSearch(nextQuery: string) {
    if (exitTimer.current) window.clearTimeout(exitTimer.current);
    const nextIds = new Set(rankChronicles(chronicles, nextQuery).map((item) => item.id));
    const leaving = shownChronicles.flatMap((chronicle, index) =>
      nextIds.has(chronicle.id) ? [] : [{ chronicle, index }],
    );
    setExitingRows(leaving);
    setQuery(nextQuery);
    if (leaving.length) exitTimer.current = window.setTimeout(() => setExitingRows([]), 120);
  }

  const renderedRows = [...shownChronicles.map((chronicle) => ({ chronicle, exiting: false }))];
  for (const { chronicle, index } of exitingRows) {
    if (!renderedRows.some((row) => row.chronicle.id === chronicle.id)) {
      renderedRows.splice(Math.min(index, renderedRows.length), 0, { chronicle, exiting: true });
    }
  }

  useEffect(() => {
    const nextRects = new Map<string, DOMRect>();
    for (const [id, element] of rowRefs.current) nextRects.set(id, element.getBoundingClientRect());
    for (const [id, next] of nextRects) {
      const previous = previousPositions.current.get(id);
      const element = rowRefs.current.get(id);
      if (!previous || !element) continue;
      const deltaY = previous.top - next.top;
      if (Math.abs(deltaY) < 1 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) continue;
      element.animate(
        [{ transform: `translateY(${deltaY}px)` }, { transform: "translateY(0)" }],
        { duration: 180, easing: "cubic-bezier(0.2, 0, 0.38, 0.9)" },
      );
    }
    previousPositions.current = nextRects;
  }, [shownChronicles, chronicles]);

  async function createChronicle() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await api<Chronicle>(`/worlds/${encodeURIComponent(worldId)}/chronicles`, jsonRequest("POST", {}));
      setChronicles((items) => [created, ...items.filter((item) => item.id !== created.id)]);
      setExitingRows([]);
      setQuery("");
      headingRef.current?.focus({ preventScroll: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The Chronicle could not be created.");
    } finally {
      setBusy(false);
    }
  }

  function openChronicle(chronicle: Chronicle) {
    if (!isWorldReady) {
      setPendingChat(true);
      onPendingChronicleAttempt?.();
      return;
    }
    onOpenChronicle({ id: chronicle.id, title: chronicle.title });
  }

  function startRename(chronicle: Chronicle) {
    setOpenMenu(null);
    setEditing(chronicle.id);
    setEditTitle(chronicle.title);
  }

  async function saveRename(chronicle: Chronicle) {
    const title = editTitle.trim();
    if (!title || title === chronicle.title) {
      setEditing(null);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await api<{ id: string; world_id: string; title: string; created_at: string; last_message_at: string | null }>(
        `/chronicles/${encodeURIComponent(chronicle.id)}`,
        jsonRequest("PATCH", { title }),
      );
      setChronicles((items) => items.map((item) => item.id === updated.id ? { ...item, title: updated.title } : item));
      setEditing(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The Chronicle name could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteChronicle() {
    if (!deleteTarget) return;
    setBusy(true);
    setError("");
    try {
      await api<void>(`/chronicles/${encodeURIComponent(deleteTarget.id)}`, { method: "DELETE" });
      setChronicles((items) => items.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The Chronicle could not be deleted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chronicles-content">
      <header className="chronicles-heading-row">
        <h1 ref={headingRef} tabIndex={-1}>Chronicles</h1>
        {chronicles.length > 0 && (
          <div className="chronicles-tools">
            <label className="chronicles-search">
              <MagnifyingGlass size={19} aria-hidden="true" />
              <span className="sr-only">Search Chronicles</span>
              <input
                ref={searchRef}
                type="search"
                value={query}
                onChange={(event) => updateSearch(event.target.value)}
                placeholder="Search Chronicles…"
                aria-label="Search Chronicles"
              />
              {query && <button type="button" className="chronicles-clear-search" aria-label="Clear search" onClick={() => { updateSearch(""); searchRef.current?.focus(); }}><X size={15} /></button>}
            </label>
            <button type="button" className="create-world-button primary-button chronicle-create-button" disabled={busy} onClick={() => void createChronicle()}>
              <Plus size={17} aria-hidden="true" /> New Chronicle
            </button>
          </div>
        )}
      </header>

      {error && <p className="chronicles-error" role="alert">{error}</p>}
      {pendingChat && (
        <div className="chronicle-pending-notice" role="status">
          <span>Chat needs completed book embeddings. Check Overview for this World’s progress.</span>
          <button type="button" className="chronicle-notice-dismiss" aria-label="Dismiss" onClick={() => setPendingChat(false)}><X size={16} /></button>
        </div>
      )}

      {loading ? (
        <p className="chronicles-status" role="status">Loading Chronicles…</p>
      ) : chronicles.length === 0 ? (
        <section className="chronicles-empty-card" aria-labelledby="chronicles-empty-heading">
          <BookOpen size={34} aria-hidden="true" />
          <h2 id="chronicles-empty-heading">No Chronicles Yet</h2>
          <button type="button" className="create-world-button primary-button chronicle-create-button" disabled={busy} onClick={() => void createChronicle()}>
            <Plus size={17} aria-hidden="true" /> New Chronicle
          </button>
        </section>
      ) : shownChronicles.length === 0 && !exitingRows.length ? (
        <p className="chronicles-status">No Chronicles match “{query}”.</p>
      ) : (
        <div className="chronicle-list" aria-label={`${worldName} Chronicles`}>
          {renderedRows.map(({ chronicle, exiting }) => {
            return (
              <article
                className={`chronicle-row ${exiting ? "is-filtering-out" : ""} ${openMenu === chronicle.id ? "is-menu-open" : ""}`}
                key={chronicle.id}
                ref={(element) => { if (element) rowRefs.current.set(chronicle.id, element); else rowRefs.current.delete(chronicle.id); }}
                aria-hidden={exiting || undefined}
                inert={exiting}
              >
                {editing === chronicle.id ? (
                  <form className="chronicle-row-main chronicle-rename-form" onSubmit={(event) => { event.preventDefault(); void saveRename(chronicle); }}>
                    <span className="chronicle-row-copy">
                      <span className="chronicle-rename-title">
                        <input autoFocus aria-label="Chronicle name" value={editTitle} maxLength={120} onChange={(event) => setEditTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setEditing(null); }} />
                        <button type="submit" disabled={busy || !editTitle.trim()}>Save</button>
                        <button type="button" disabled={busy} onClick={() => setEditing(null)}>Cancel</button>
                      </span>
                      <span className={`chronicle-preview ${chronicle.not_started ? "is-empty" : ""}`}>{chronicle.preview || (chronicle.message_count ? "No preview available" : "No messages yet")}</span>
                    </span>
                  </form>
                ) : (
                  <button type="button" className="chronicle-row-main" onClick={() => openChronicle(chronicle)}>
                    <span className="chronicle-row-copy">
                      <strong>{chronicle.title}</strong>
                      <span className={`chronicle-preview ${chronicle.not_started ? "is-empty" : ""}`}>{chronicle.preview || (chronicle.message_count ? "No preview available" : "No messages yet")}</span>
                    </span>
                  </button>
                )}
                <div className="chronicle-row-meta">
                  <span className="chronicle-meta-item"><Clock size={16} aria-hidden="true" />{relativeTime(chronicle.last_message_at, now)}</span>
                  <span className="chronicle-meta-item"><ChatCircleDots size={16} aria-hidden="true" />{chronicle.message_count} {chronicle.message_count === 1 ? "message" : "messages"}</span>
                </div>
                <div className="chronicle-menu-anchor">
                  <button type="button" className="chronicle-menu-trigger" aria-label={`Options for ${chronicle.title}`} aria-haspopup="menu" aria-expanded={openMenu === chronicle.id} onClick={() => setOpenMenu((current) => current === chronicle.id ? null : chronicle.id)}>
                    <DotsThree size={22} weight="bold" aria-hidden="true" />
                  </button>
                  {openMenu === chronicle.id && (
                    <div className="chronicle-overflow-menu" role="menu" aria-label={`${chronicle.title} options`}>
                      <button type="button" role="menuitem" onClick={() => startRename(chronicle)}><PencilSimple size={16} aria-hidden="true" /> Rename</button>
                      <button type="button" role="menuitem" className="is-danger" onClick={() => { setOpenMenu(null); setDeleteTarget(chronicle); }}><Trash size={16} aria-hidden="true" /> Delete</button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {deleteTarget && (
        <div className="chronicle-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteTarget(null); }}>
          <section className="chronicle-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="chronicle-delete-title" aria-describedby="chronicle-delete-copy">
            <button type="button" className="chronicle-dialog-close" aria-label="Cancel" onClick={() => setDeleteTarget(null)}><X size={18} /></button>
            <h2 id="chronicle-delete-title">Delete Chronicle?</h2>
            <p id="chronicle-delete-copy">“{deleteTarget.title}” and its messages will be deleted.</p>
            <div className="chronicle-dialog-actions">
              <button type="button" onClick={() => setDeleteTarget(null)} disabled={busy}>Cancel</button>
              <button type="button" className="danger-action" onClick={() => void deleteChronicle()} disabled={busy}>Delete Chronicle</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
