import { useEffect, useRef, useState } from "react";
import { GearSix, Plus } from "@phosphor-icons/react";
import {
  api,
  type Settings,
  type Speed,
  type WorldLayout,
  type World,
  type CreationAttempt,
  attemptLabel,
  attemptProgress,
} from "./api";
import { Background } from "./Background";
import { CreateWorld } from "./CreateWorld";
import { SettingsView } from "./SettingsView";
import { WorldSearch } from "./WorldSearch";
import {
  artworkUrl,
  sampleWorlds,
  type CollectionPreview,
  type PreviewWorld,
} from "./collectionPreview";

type View = "worlds" | "settings";
export function App() {
  const homeRef = useRef<HTMLElement>(null);
  const shelfRef = useRef<HTMLDivElement>(null);
  const edgeAnimation = useRef<Animation | null>(null);
  useEffect(() => () => edgeAnimation.current?.cancel(), []);
  const [view, setView] = useState<View>("worlds");
  const [worlds, setWorlds] = useState<World[]>([]);
  const [preview, setPreview] = useState<PreviewWorld | null>(null);
  const [collectionPreview, setCollectionPreview] =
    useState<CollectionPreview>("saved");
  const [speed, setSpeed] = useState<Speed>("normal");
  const [layout, setLayout] = useState<WorldLayout>("shelf");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [draftKey, setDraftKey] = useState(0);
  const [creationOpen, setCreationOpen] = useState(false);
  const [attempt, setAttempt] = useState<CreationAttempt | null>(null);
  const [manageKeys, setManageKeys] = useState(false);
  const [progressError, setProgressError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [searchEpoch, setSearchEpoch] = useState(0);
  async function load() {
    setError("");
    setLoading(true);
    try {
      const [records, settings, savedAttempt] = await Promise.all([
        api<World[]>("/worlds"),
        api<Settings>("/settings"),
        api<CreationAttempt | null>("/creation"),
      ]);
      setWorlds(records);
      setAttempt(savedAttempt);
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
  function navigate(next: View) {
    setView(next);
  }
  function openCreation() {
    if (attempt?.state === "complete") {
      setAttempt(null);
      setDraftKey((key) => key + 1);
    }
    setCreationOpen(true);
  }
  useEffect(() => {
    if (!attempt || attempt.state === "complete") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api<CreationAttempt>(`/creation/${attempt!.id}`);
        if (!cancelled) {
          setAttempt((previous) =>
            previous?.id === value.id && previous.revision <= value.revision
              ? value
              : previous,
          );
          setProgressError("");
        }
      } catch {
        if (!cancelled)
          setProgressError(
            "Could not refresh creation progress. Reconnecting…",
          );
      }
      if (!cancelled) timer = setTimeout(poll, 1000);
    }
    timer = setTimeout(poll, 1000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [attempt?.id, attempt?.state]);
  useEffect(() => {
    if (attempt?.state !== "complete") return;
    api<World[]>("/worlds")
      .then(setWorlds)
      .catch(() =>
        setError(
          "Your world is ready, but the collection could not refresh. Try again.",
        ),
      );
  }, [attempt?.id, attempt?.state]);
  const pendingWorld: PreviewWorld | null =
    attempt && attempt.state !== "complete"
      ? {
          id: attempt.id,
          name: attempt.name,
          created_at: attempt.created_at,
          last_used_at: null,
          artwork: "frostwake",
          artworkUrl: "/assets/frostwake.png",
        }
      : null;
  const displayedAttempt =
    attempt && uploading ? { ...attempt, state: "running" as const } : attempt;
  const savedCollection: PreviewWorld[] = pendingWorld
    ? [pendingWorld, ...worlds.filter((world) => world.id !== pendingWorld.id)]
    : attempt?.state === "complete" &&
        !worlds.some((world) => world.id === attempt.id)
      ? [
          {
            id: attempt.id,
            name: attempt.name,
            created_at: attempt.updated_at,
            last_used_at: null,
            artwork: "frostwake",
          },
          ...worlds,
        ]
      : worlds;
  const collection =
    collectionPreview === "empty"
      ? []
      : collectionPreview === "four"
        ? sampleWorlds(worlds).slice(0, 4)
        : collectionPreview === "sample"
          ? sampleWorlds(worlds)
          : savedCollection;
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
      // Accumulate wheel bursts without losing distance during an unfinished glide.
      // Reversing direction starts from the visible position for immediate response.
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
  return (
    <>
      <Background url={artworkUrl(preview)} speed={speed} />
      <header className="app-header">
        <div className="brand">
          <img src="/assets/logo.png" alt="" />
          <span>VySol</span>
        </div>
        <nav aria-label="Main navigation">
          <button
            className={view === "worlds" ? "active" : ""}
            aria-current={view === "worlds" ? "page" : undefined}
            onClick={() => navigate("worlds")}
          >
            Worlds
          </button>
        </nav>
        <div className="header-tools">
          {!creationOpen && (
            <WorldSearch
              key={`${collectionPreview}-${searchEpoch}`}
              worlds={collection}
              disabled={view !== "worlds"}
              onSelect={(world) => {
                const card = document.getElementById(`world-card-${world.id}`);
                card?.focus({ preventScroll: true });
                card?.scrollIntoView({
                  block: "nearest",
                  behavior: window.matchMedia?.(
                    "(prefers-reduced-motion: reduce)",
                  ).matches
                    ? "instant"
                    : "smooth",
                });
              }}
            />
          )}
          <button
            className="icon-button settings-button"
            aria-label="Settings"
            aria-pressed={view === "settings"}
            onClick={() => navigate("settings")}
          >
            <GearSix size={25} weight="light" />
          </button>
        </div>
      </header>
      <main
        className={
          view === "worlds" && (layout === "shelf" || collection.length <= 4)
            ? "fit-home"
            : ""
        }
      >
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
                className="icon-button create-world-button"
                aria-label="Create World"
                title="Create world"
                onClick={openCreation}
              >
                <Plus size={24} />
              </button>
              <span />
            </div>
          )}
          {loading ? (
            <div className="empty-state" role="status">
              Gathering your worlds…
            </div>
          ) : error ? (
            <div className="empty-state">
              <p role="alert">{error}</p>
              <button className="text-action" onClick={load}>
                Try again
              </button>
            </div>
          ) : collection.length === 0 ? (
            <div className="welcome-state">
              <h1>Create Your First World</h1>
              <button className="primary-button" onClick={openCreation}>
                Create World
              </button>
            </div>
          ) : (
            <div
              className={`world-grid ${layout === "shelf" ? "world-shelf" : ""} ${collection.length <= 4 ? "short-collection" : ""}`}
              ref={shelfRef}
            >
              {collection.map((world) => (
                <article
                  tabIndex={0}
                  key={world.id}
                  className="world-card"
                  id={`world-card-${world.id}`}
                  aria-label={
                    world.id === pendingWorld?.id
                      ? `${attemptLabel(displayedAttempt!)} ${world.name}`
                      : `Preview ${world.name}`
                  }
                  onClick={
                    world.id === pendingWorld?.id ? openCreation : undefined
                  }
                  onKeyDown={(event) => {
                    if (
                      world.id === pendingWorld?.id &&
                      (event.key === "Enter" || event.key === " ")
                    ) {
                      event.preventDefault();
                      openCreation();
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
                      if (
                        !event.currentTarget.src.endsWith(
                          "/assets/frostwake.png",
                        )
                      )
                        event.currentTarget.src = "/assets/frostwake.png";
                    }}
                  />
                  <div className="card-shade" />
                  <h3>{world.name}</h3>
                  {world.id === pendingWorld?.id && attempt && (
                    <div className={`card-progress ${attempt.state}`}>
                      <strong>{attemptLabel(displayedAttempt!)}</strong>
                      <span>{attemptProgress(attempt)}</span>
                      <progress
                        aria-label={`Progress for ${world.name}`}
                        max={Math.max(
                          1,
                          attempt.phase === "embedding"
                            ? attempt.chunks_total
                            : attempt.books.length,
                        )}
                        value={
                          attempt.phase === "embedding"
                            ? attempt.chunks_done
                            : attempt.books.filter((book) =>
                                attempt.phase === "uploading"
                                  ? book.uploaded
                                  : ["prepared", "embedding", "done"].includes(
                                      book.state,
                                    ),
                              ).length
                        }
                      />
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
          <footer>Stories live longer here.</footer>
          {progressError && (
            <p role="status" className="progress-connection-error">
              {progressError}
            </p>
          )}
        </section>
        <CreateWorld
          key={draftKey}
          visible={creationOpen}
          attempt={attempt}
          onUploading={setUploading}
          onAttempt={(value) => {
            setAttempt(value);
            setCollectionPreview("saved");
            setSearchEpoch((epoch) => epoch + 1);
          }}
          onClose={() => setCreationOpen(false)}
          onManageKeys={() => {
            setCreationOpen(false);
            setManageKeys(true);
            setView("settings");
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
          onReturnToCreation={() => {
            setManageKeys(false);
            setView("worlds");
            setCreationOpen(true);
          }}
        />
      </main>
    </>
  );
}
