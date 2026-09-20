import { useEffect, useRef, useState } from "react";
import { GearSix } from "@phosphor-icons/react";
import {
  api,
  type Settings,
  type Speed,
  type WorldLayout,
  type World,
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

type View = "worlds" | "create" | "settings";
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
  const [created, setCreated] = useState(false);
  const [searchEpoch, setSearchEpoch] = useState(0);
  async function load() {
    setError("");
    setLoading(true);
    try {
      const [records, settings] = await Promise.all([
        api<World[]>("/worlds"),
        api<Settings>("/settings"),
      ]);
      setWorlds(records);
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
    if (next === "create" && view !== "create" && created) {
      setDraftKey((key) => key + 1);
      setCreated(false);
    }
    setView(next);
  }
  const collection =
    collectionPreview === "empty"
      ? []
      : collectionPreview === "four"
        ? sampleWorlds(worlds).slice(0, 4)
        : collectionPreview === "sample"
          ? sampleWorlds(worlds)
          : worlds;
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
          <button
            className={view === "create" ? "active" : ""}
            aria-current={view === "create" ? "page" : undefined}
            onClick={() => navigate("create")}
          >
            Create World
          </button>
        </nav>
        <div className="header-tools">
          {view !== "create" && (
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
              <button
                className="primary-button"
                onClick={() => navigate("create")}
              >
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
                  aria-label={`Preview ${world.name}`}
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
                </article>
              ))}
            </div>
          )}
          <footer>Stories live longer here.</footer>
        </section>
        <CreateWorld
          key={draftKey}
          visible={view === "create"}
          onCreated={(world) => {
            setWorlds((previous) => [
              world,
              ...previous.filter((item) => item.id !== world.id),
            ]);
          }}
          onFinished={setCreated}
          onComplete={(world) => {
            setPreview(world);
            setCollectionPreview("saved");
            setSearchEpoch((value) => value + 1);
            setView("worlds");
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
        />
      </main>
    </>
  );
}
