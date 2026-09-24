import { useEffect, useRef, useState } from "react";
import { ArrowRight, GearSix, Plus, X } from "@phosphor-icons/react";
import {
  api,
  jsonRequest,
  type CreationAttempt,
  type Settings,
  type Speed,
  type World,
  type WorldDetail,
  type WorldLayout,
  bookCountLabel,
  attemptLabel,
  attemptProgress,
} from "./api";
import { Background } from "./Background";
import { CreateWorld, WorldOverview } from "./CreateWorld";
import { SettingsView } from "./SettingsView";
import { WorldSearch } from "./WorldSearch";
import {
  artworkUrl,
  sampleWorlds,
  type CollectionPreview,
  type PreviewWorld,
} from "./collectionPreview";

type View = "worlds" | "settings" | "create" | "overview";
type PageView = Exclude<View, "settings">;

function pendingBookCount(attempt: CreationAttempt) {
  return attempt.books.length;
}

function worldForAttempt(attempt: CreationAttempt): PreviewWorld {
  return {
    id: attempt.id,
    name: attempt.name,
    created_at: attempt.created_at,
    last_used_at: null,
    artwork: "frostwake",
    artworkUrl: "/assets/frostwake.png",
    book_count: pendingBookCount(attempt),
  };
}

export function App() {
  const homeRef = useRef<HTMLElement>(null);
  const shelfRef = useRef<HTMLDivElement>(null);
  const edgeAnimation = useRef<Animation | null>(null);
  const resumeAttemptRef = useRef<
    ((attempt: CreationAttempt) => Promise<CreationAttempt>) | null
  >(null);
  useEffect(() => () => edgeAnimation.current?.cancel(), []);
  const [view, setView] = useState<View>("worlds");
  const [previousView, setPreviousView] = useState<PageView>("worlds");
  const [worlds, setWorlds] = useState<World[]>([]);
  const [preview, setPreview] = useState<PreviewWorld | null>(null);
  const [selectedWorldId, setSelectedWorldId] = useState<string | null>(null);
  const [worldDetail, setWorldDetail] = useState<WorldDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [collectionPreview, setCollectionPreview] =
    useState<CollectionPreview>("saved");
  const [speed, setSpeed] = useState<Speed>("normal");
  const [layout, setLayout] = useState<WorldLayout>("shelf");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempts, setAttempts] = useState<CreationAttempt[]>([]);
  const [manageKeys, setManageKeys] = useState(false);
  const [progressError, setProgressError] = useState("");
  const [uploadingIds, setUploadingIds] = useState<Set<string>>(() => new Set());
  const [attemptBusyIds, setAttemptBusyIds] = useState<Set<string>>(() => new Set());
  const [searchEpoch, setSearchEpoch] = useState(0);
  const [overviewHandoff, setOverviewHandoff] = useState(false);
  const [settingsReturning, setSettingsReturning] = useState(false);
  const completedAttemptIds = useRef(new Set<string>());
  const discardedAttemptIds = useRef(new Set<string>());

  function updateAttempt(value: CreationAttempt) {
    if (discardedAttemptIds.current.has(value.id)) return;
    setAttempts((previous) => {
      const existing = previous.find((item) => item.id === value.id);
      if (existing && existing.revision > value.revision) return previous;
      return existing
        ? previous.map((item) => (item.id === value.id ? value : item))
        : [value, ...previous];
    });
  }

  useEffect(() => {
    if (!overviewHandoff) return;
    const timer = setTimeout(() => setOverviewHandoff(false), 290);
    return () => clearTimeout(timer);
  }, [overviewHandoff]);

  useEffect(() => {
    if (!settingsReturning) return;
    const timer = setTimeout(() => setSettingsReturning(false), 210);
    return () => clearTimeout(timer);
  }, [settingsReturning]);

  async function load() {
    setError("");
    setLoading(true);
    try {
      const [records, settings, savedAttemptsResponse] = await Promise.all([
        api<World[]>("/worlds"),
        api<Settings>("/settings"),
        api<CreationAttempt[]>("/creations").catch(() => null),
      ]);
      const savedAttempts = Array.isArray(savedAttemptsResponse)
        ? savedAttemptsResponse
        : await api<CreationAttempt | null>("/creation").then((saved) =>
            saved ? [saved] : [],
          );
      setWorlds(records);
      setAttempts(savedAttempts);
      setPreview((previous) => previous ?? records[0] ?? null);
      setSpeed(settings.background_speed);
      setLayout(settings.world_layout ?? "shelf");
      records.forEach((world) => {
        const image = new Image();
        image.src = `/api/worlds/${world.id}/artwork`;
      });
    } catch {
      setError("Your worlds could not be loaded. Please try again.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  const pollableAttemptIds = attempts
    .filter((attempt) => attempt.state !== "complete")
    .map((attempt) => attempt.id);
  const pollableAttemptKey = pollableAttemptIds.join("|");
  useEffect(() => {
    if (!pollableAttemptIds.length) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const results = await Promise.allSettled(
        pollableAttemptIds.map((id) =>
          api<CreationAttempt>(`/creation/${id}`),
        ),
      );
      if (cancelled) return;
      let failed = false;
      for (const result of results) {
        if (result.status === "fulfilled") updateAttempt(result.value);
        else failed = true;
      }
      setProgressError(
        failed ? "Could not refresh creation progress. Reconnecting…" : "",
      );
      if (!cancelled) timer = setTimeout(poll, 1000);
    }
    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pollableAttemptKey]);

  useEffect(() => {
    const newlyCompleted = attempts.filter(
      (attempt) =>
        attempt.state === "complete" &&
        !completedAttemptIds.current.has(attempt.id),
    );
    if (!newlyCompleted.length) return;
    for (const attempt of newlyCompleted)
      completedAttemptIds.current.add(attempt.id);
    api<World[]>("/worlds")
      .then(setWorlds)
      .catch(() =>
        setError("Your world is ready, but the collection could not refresh. Try again."),
      );
  }, [attempts]);

  useEffect(() => {
    if (view !== "overview" || !selectedWorldId) return;
    let cancelled = false;
    setWorldDetail(null);
    setDetailError("");
    api<WorldDetail>(`/worlds/${selectedWorldId}`)
      .then((detail) => {
        if (!cancelled) setWorldDetail(detail);
      })
      .catch((cause) => {
        if (!cancelled)
          setDetailError(
            cause instanceof Error
              ? cause.message
              : "World details could not be loaded. Please try again.",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [view, selectedWorldId]);

  const displayedAttempts = attempts.map((attempt) =>
    uploadingIds.has(attempt.id) && attempt.state !== "complete"
      ? { ...attempt, state: "running" as const }
      : attempt,
  );
  const attemptWorlds = displayedAttempts
    .filter(
      (attempt) =>
        attempt.state !== "complete" ||
        !worlds.some((world) => world.id === attempt.id),
    )
    .map(worldForAttempt);
  const savedCollection: PreviewWorld[] = [
    ...attemptWorlds,
    ...worlds.filter((world) => !attemptWorlds.some((attempt) => attempt.id === world.id)),
  ];
  const collection =
    collectionPreview === "empty"
      ? []
      : collectionPreview === "four"
        ? sampleWorlds(worlds).slice(0, 4)
        : collectionPreview === "sample"
          ? sampleWorlds(worlds)
          : savedCollection;

  function openWorld(world: PreviewWorld) {
    if (
      !worlds.some((saved) => saved.id === world.id) &&
      !attempts.some((attempt) => attempt.id === world.id)
    ) return;
    setPreview(world);
    setSelectedWorldId(world.id);
    setWorldDetail(null);
    setDetailError("");
    setOverviewHandoff(false);
    setView("overview");
  }

  function openCreateWorld() {
    setOverviewHandoff(false);
    setSelectedWorldId(null);
    setWorldDetail(null);
    setView("create");
  }

  function openSettings(from: PageView = view === "settings" ? previousView : view) {
    setSettingsReturning(false);
    setPreviousView(from);
    setManageKeys(false);
    setView("settings");
  }

  function returnFromSettings() {
    setManageKeys(false);
    setSettingsReturning(true);
    setView(previousView);
  }

  async function handleAttemptAction(
    attemptId: string,
    action: "pause" | "resume" | "discard",
  ) {
    const attempt = attempts.find((item) => item.id === attemptId);
    if (!attempt || attemptBusyIds.has(attemptId)) return;
    setAttemptBusyIds((current) => new Set(current).add(attemptId));
    try {
      if (action === "discard") {
        await api(`/creation/${attempt.id}?revision=${attempt.revision}`, {
          method: "DELETE",
        });
        discardedAttemptIds.current.add(attempt.id);
        setAttempts((previous) => previous.filter((item) => item.id !== attempt.id));
        setUploadingIds((current) => {
          const next = new Set(current);
          next.delete(attempt.id);
          return next;
        });
        if (selectedWorldId === attempt.id) {
          setSelectedWorldId(null);
          setWorldDetail(null);
          setView("worlds");
        }
        return;
      }
      if (action === "resume" && resumeAttemptRef.current) {
        const value = await resumeAttemptRef.current(attempt);
        updateAttempt(value);
        return;
      }
      const value = await api<CreationAttempt>(
        `/creation/${attempt.id}/${action === "pause" ? "pause" : "start"}`,
        jsonRequest("POST", {
          revision: attempt.revision,
          ...(action === "resume" ? { operation_id: crypto.randomUUID() } : {}),
        }),
      );
      updateAttempt(value);
    } catch (cause) {
      setDetailError(
        cause instanceof Error ? cause.message : "This action could not be completed.",
      );
      const saved = await api<CreationAttempt>(`/creation/${attempt.id}`).catch(
        () => null,
      );
      if (saved) updateAttempt(saved);
    } finally {
      setAttemptBusyIds((current) => {
        const next = new Set(current);
        next.delete(attempt.id);
        return next;
      });
    }
  }

  useEffect(() => {
    const home = homeRef.current;
    if (!home || view !== "worlds" || layout !== "shelf") return;
    const wheelGain = 1.5;
    const wheelBurstGapMs = 250;
    let target = 0;
    let lastWheelAt = -Infinity;
    let lastDirection = 0;
    function scrollShelf(event: WheelEvent) {
      const shelf = shelfRef.current;
      if (!shelf || shelf.scrollWidth <= shelf.clientWidth || event.ctrlKey)
        return;
      const amount =
        Math.abs(event.deltaY) > Math.abs(event.deltaX)
          ? event.deltaY
          : event.deltaX;
      const unit =
        event.deltaMode === 1
          ? 24
          : event.deltaMode === 2
            ? shelf.clientWidth
            : 1;
      const delta = amount * unit * wheelGain;
      event.preventDefault();
      const now = performance.now();
      const direction = Math.sign(delta);
      if (now - lastWheelAt > wheelBurstGapMs || direction !== lastDirection)
        target = shelf.scrollLeft;
      target = Math.max(
        0,
        Math.min(shelf.scrollWidth - shelf.clientWidth, target + delta),
      );
      lastWheelAt = now;
      lastDirection = direction;
      shelf.scrollTo({
        left: target,
        behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")
          .matches
          ? "instant"
          : "smooth",
      });
      const atEdge =
        delta < 0
          ? shelf.scrollLeft <= 0
          : shelf.scrollLeft >= shelf.scrollWidth - shelf.clientWidth - 1;
      if (
        atEdge &&
        !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches &&
        edgeAnimation.current?.playState !== "running"
      ) {
        edgeAnimation.current = shelf.animate(
          [
            { transform: "translateX(0)" },
            { transform: `translateX(${delta > 0 ? -7 : 7}px)` },
            { transform: "translateX(0)" },
          ],
          { duration: 220, easing: "ease-out" },
        );
      }
    }
    home.addEventListener("wheel", scrollShelf, { passive: false });
    return () => home.removeEventListener("wheel", scrollShelf);
  }, [view, layout]);

  function changeCollection(next: CollectionPreview) {
    setCollectionPreview(next);
    setPreview(
      next === "empty"
        ? null
        : next === "sample" || next === "four"
          ? sampleWorlds(worlds)[0]
          : (worlds[0] ?? null),
    );
  }

  const selectedWorld =
    collection.find((world) => world.id === selectedWorldId) ??
    attemptWorlds.find((world) => world.id === selectedWorldId) ??
    worlds.find((world) => world.id === selectedWorldId) ??
    null;
  const selectedAttempt =
    displayedAttempts.find((attempt) => attempt.id === selectedWorldId) ?? null;
  const routeTitle = view === "create" ? "Create World" : selectedWorld?.name;

  return (
    <>
      <Background url={artworkUrl(preview)} speed={speed} />
      <header className={`app-header ${view !== "worlds" ? "app-header-subpage" : ""}`}>
        <div className="brand">
          <img src="/assets/logo.png" alt="" />
          <span>VySol</span>
        </div>
        {view !== "settings" && (
          <nav aria-label="Main navigation" className="route-navigation">
            <button
              className={view === "worlds" ? "active" : ""}
              aria-current={view === "worlds" ? "page" : undefined}
              onClick={() => setView("worlds")}
            >
              Worlds
            </button>
            {view !== "worlds" && (
              <>
                <ArrowRight size={16} aria-hidden="true" />
                <button className="active" aria-current="page">
                  {routeTitle}
                </button>
              </>
            )}
          </nav>
        )}
        <div className="header-tools">
          {view === "worlds" && (
            <>
              <WorldSearch
                key={`${collectionPreview}-${searchEpoch}`}
                worlds={collection}
                disabled={false}
                onSelect={openWorld}
              />
              <button
                className="icon-button settings-button"
                aria-label="Settings"
                onClick={() => openSettings("worlds")}
              >
                <GearSix size={25} weight="light" />
              </button>
            </>
          )}
          {(view === "overview" || view === "create") && (
            <button
              className="icon-button close-world-button"
              aria-label={view === "create" ? "Close Create World" : "Back to Worlds"}
              onClick={() => setView("worlds")}
            >
              <X size={24} weight="light" />
            </button>
          )}
          {view === "settings" && (
            <button
              className="icon-button close-settings-button"
              aria-label="Close Settings"
              title="Close Settings"
              onClick={returnFromSettings}
            >
              <X size={24} weight="light" />
            </button>
          )}
        </div>
      </header>
      <main className={`${view === "worlds" && (layout === "shelf" || collection.length <= 4) ? "fit-home" : ""} ${settingsReturning ? "settings-returning" : ""}`}>
        <section
          ref={homeRef}
          className={`view worlds-view ${layout === "shelf" || collection.length <= 4 ? "fitted-worlds" : ""} ${view === "worlds" ? "is-visible" : ""}`}
          aria-hidden={view !== "worlds"}
          inert={view !== "worlds"}
        >
          {collection.length > 0 && (
            <div className="hero-title">
              {preview && <h1 key={preview.id}>{preview.name}</h1>}
            </div>
          )}
          {collection.length > 0 && (
            <div className="collection-heading">
              <h2>Your Worlds</h2>
              <button
                className="create-world-button"
                aria-label="New World"
                onClick={openCreateWorld}
              >
                <Plus size={15} aria-hidden="true" /> <span>New World</span>
              </button>
              <span />
            </div>
          )}
          {loading ? (
            <div className="empty-state" role="status">Gathering your worlds…</div>
          ) : error ? (
            <div className="empty-state">
              <p role="alert">{error}</p>
              <button className="text-action" onClick={load}>Try again</button>
            </div>
          ) : collection.length === 0 ? (
            <div className="welcome-state">
              <h1>Create Your First World</h1>
              <button className="primary-button" onClick={openCreateWorld}>Create World</button>
            </div>
          ) : (
            <div
              className={`world-grid ${layout === "shelf" ? "world-shelf" : ""} ${collection.length <= 4 ? "short-collection" : ""}`}
              ref={shelfRef}
            >
              {collection.map((world) => {
                const isSamplePreview = collectionPreview === "sample" || collectionPreview === "four";
                const cardAttempt = displayedAttempts.find((attempt) => attempt.id === world.id) ?? null;
                const isPending = !!cardAttempt && cardAttempt.state !== "complete";
                const bookCount = isPending
                  ? pendingBookCount(cardAttempt!)
                  : (world.book_count ?? 0);
                const state = cardAttempt?.state ?? "complete";
                return (
                  <article
                    tabIndex={isSamplePreview ? undefined : 0}
                    role={isSamplePreview ? undefined : "button"}
                    key={world.id}
                    className={`world-card ${isPending ? "is-pending" : ""} ${isSamplePreview ? "is-preview-card" : ""}`}
                    id={`world-card-${world.id}`}
                    aria-label={isSamplePreview ? `${world.name}, sample preview` : `${world.name}, ${isPending ? attemptLabel(cardAttempt!) : "Ready"}, ${bookCountLabel(bookCount)}`}
                    onClick={isSamplePreview ? undefined : () => openWorld(world)}
                    onKeyDown={isSamplePreview ? undefined : (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openWorld(world);
                      }
                    }}
                    onMouseEnter={() => setPreview(world)}
                    onFocus={() => setPreview(world)}
                    onTouchStart={() => setPreview(world)}
                  >
                    <img
                      src={artworkUrl(world)}
                      alt=""
                      onError={(event) => {
                        if (!event.currentTarget.src.endsWith("/assets/frostwake.png"))
                          event.currentTarget.src = "/assets/frostwake.png";
                      }}
                    />
                    <div className="card-shade" />
                    {isSamplePreview && <span className="world-card-preview-label">Preview</span>}
                    <div className="world-card-copy">
                      <h3>{world.name}</h3>
                      <div className="world-card-meta">
                        <span className={`card-status status-${state}`}>
                          <span className="status-dot" aria-hidden="true" />
                          {isPending ? attemptLabel(cardAttempt!) : "Ready"}
                        </span>
                        <span className="card-book-count">{bookCountLabel(bookCount)}</span>
                        {cardAttempt && cardAttempt.state !== "complete" && (
                          <progress
                            className="card-progress-line"
                            max={Math.max(1, cardAttempt.chunks_total)}
                            value={cardAttempt.chunks_done}
                            aria-label={`Creation progress for ${world.name}`}
                          />
                        )}
                      </div>
                      {cardAttempt && (
                        <span className="sr-only">{attemptProgress(cardAttempt)}</span>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
          <footer>Stories live longer here.</footer>
          {progressError && <p role="status" className="progress-connection-error">{progressError}</p>}
        </section>

        <CreateWorld
          visible={view === "create"}
          handoffTransition={overviewHandoff}
          onAttempt={(value) => {
            updateAttempt(value);
            setCollectionPreview("saved");
            setSearchEpoch((epoch) => epoch + 1);
          }}
          onCreated={(value) => {
            setOverviewHandoff(true);
            setSelectedWorldId(value.id);
            setWorldDetail(null);
            setPreview({
              id: value.id,
              name: value.name,
              created_at: value.created_at,
              last_used_at: null,
              artwork: "frostwake",
              artworkUrl: "/assets/frostwake.png",
              book_count: value.books.length,
            });
            setView("overview");
          }}
          onUploading={(attemptId, value) => {
            setUploadingIds((current) => {
              const next = new Set(current);
              if (value) next.add(attemptId);
              else next.delete(attemptId);
              return next;
            });
          }}
          onResumeHandler={(resume) => {
            resumeAttemptRef.current = resume;
          }}
          onManageKeys={() => {
            setPreviousView("create");
            setManageKeys(true);
            setView("settings");
          }}
        />

        {detailError && view === "overview" && (
          <p role="alert" className="detail-load-error">{detailError}</p>
        )}
        <WorldOverview
          visible={view === "overview"}
          handoffTransition={overviewHandoff}
          world={selectedWorld}
          detail={worldDetail}
          attempt={selectedAttempt}
          uploading={selectedAttempt ? uploadingIds.has(selectedAttempt.id) : false}
          busy={selectedAttempt ? attemptBusyIds.has(selectedAttempt.id) : false}
          onPause={() => {
            if (selectedAttempt) void handleAttemptAction(selectedAttempt.id, "pause");
          }}
          onResume={() => {
            if (selectedAttempt) void handleAttemptAction(selectedAttempt.id, "resume");
          }}
          onDiscard={() => {
            if (selectedAttempt) void handleAttemptAction(selectedAttempt.id, "discard");
          }}
        />

        <SettingsView
          visible={view === "settings"}
          speed={speed}
          layout={layout}
          onSaved={(settings) => {
            setSpeed(settings.background_speed);
            setLayout(settings.world_layout);
          }}
          collectionPreview={collectionPreview}
          onCollectionPreview={changeCollection}
          manageKeys={manageKeys}
          onClose={returnFromSettings}
        />
      </main>
    </>
  );
}
