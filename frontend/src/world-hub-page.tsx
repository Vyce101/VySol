import { Globe2, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import {
  type CommittedWorldCardResponse,
  fetchCommittedWorldCards,
} from "./committed-world-api";
import { createDraftWorldDetailFlow } from "./draft-world-api";
import logoUrl from "../../docs/assets/Butterfly_logo_compressed_centered.png";
import createWorldCardImageUrl from "../../docs/assets/New Create World Card.png";
import backgroundUrl from "../../app/assets/images/Main World Image.png";
import "./world-hub-page.css";

const WORLD_HUB_HERO_TITLE = "Create World";
const WORLD_HUB_HERO_DESCRIPTION =
  "Build a living setting for roleplay and simulation.";
const DEFAULT_HERO_FONT_FAMILY =
  '"VySol Default Inter", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const LAST_USED_TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;
const MILLISECONDS_PER_MINUTE = 60 * 1000;
const MILLISECONDS_PER_HOUR = 60 * MILLISECONDS_PER_MINUTE;
const MILLISECONDS_PER_DAY = 24 * MILLISECONDS_PER_HOUR;
const WORLD_HUB_SPLASH_EXIT_MILLISECONDS = 260;
const WORLD_HUB_HERO_CROSSFADE_MILLISECONDS = 180;
const WORLD_HUB_BACKGROUND_CROSSFADE_MILLISECONDS = 350;

type CommittedWorldCardState =
  | { status: "loading"; worlds: [] }
  | { status: "loaded"; worlds: CommittedWorldCardResponse[] }
  | { status: "error"; worlds: [] };

type WorldHubHero = {
  key: string;
  title: string;
  description: string;
  backgroundImageUrl: string | null;
  fontFamily: string;
};

export function WorldHubPage() {
  const committedWorldState = useCommittedWorldCards();
  const { hero, setActiveWorld } = useWorldHubHero(committedWorldState);
  const backgroundTransition = useCrossfade(
    hero,
    WORLD_HUB_BACKGROUND_CROSSFADE_MILLISECONDS,
  );
  const heroTransition = useCrossfade(
    hero,
    WORLD_HUB_HERO_CROSSFADE_MILLISECONDS,
  );
  const splashState = useWorldHubStartupSplash(
    committedWorldState.status === "loading",
  );

  return (
    <main className="world-hub-shell">
      <WorldHubBackground transition={backgroundTransition} />
      <div className="world-hub-shade" aria-hidden="true" />
      <header className="world-hub-header">
        <div className="world-hub-brand" aria-label="VySol">
          <img className="world-hub-brand-mark" src={logoUrl} alt="" />
          <span className="world-hub-brand-name">VySol</span>
        </div>
      </header>
      <WorldHubNav />
      <section
        className="world-hub-hero"
        aria-labelledby="world-hub-title"
      >
        <WorldHubHeroCopy transition={heroTransition} />
      </section>
      <CommittedWorldCardRow
        state={committedWorldState}
        onCommittedWorldHover={setActiveWorld}
      />
      {splashState.status !== "hidden" ? (
        <WorldHubStartupSplash isVisible={splashState.status === "visible"} />
      ) : null}
    </main>
  );
}

function WorldHubBackground({
  transition,
}: {
  transition: CrossfadeState<WorldHubHero>;
}) {
  return (
    <div className="world-hub-background" aria-hidden="true">
      {transition.previous !== null ? (
        <div
          key={transition.previous.key}
          className="world-hub-background-layer world-hub-background-layer-exit"
          style={buildWorldHubBackgroundStyle(transition.previous)}
        />
      ) : null}
      <div
        key={transition.current.key}
        className="world-hub-background-layer world-hub-background-layer-enter"
        style={buildWorldHubBackgroundStyle(transition.current)}
      />
    </div>
  );
}

function WorldHubHeroCopy({
  transition,
}: {
  transition: CrossfadeState<WorldHubHero>;
}) {
  return (
    <>
      {transition.previous !== null ? (
        <div
          key={transition.previous.key}
          className="world-hub-hero-copy world-hub-hero-copy-exit"
          style={{ fontFamily: transition.previous.fontFamily }}
          aria-hidden="true"
        >
          <h1>{transition.previous.title}</h1>
          <p>{transition.previous.description}</p>
        </div>
      ) : null}
      <div
        key={transition.current.key}
        className="world-hub-hero-copy world-hub-hero-copy-enter"
        style={{ fontFamily: transition.current.fontFamily }}
      >
        <h1 id="world-hub-title">{transition.current.title}</h1>
        <p>{transition.current.description}</p>
      </div>
    </>
  );
}

function WorldHubNav() {
  return (
    <Tabs defaultValue="worlds" className="world-hub-nav-root">
      <TabsList aria-label="World Hub sections" className="world-hub-nav-list">
        <TabsTrigger value="worlds" className="world-hub-nav-trigger">
          <Globe2 aria-hidden="true" />
          <span>Worlds</span>
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

function CommittedWorldCardRow({
  state,
  onCommittedWorldHover,
}: {
  state: CommittedWorldCardState;
  onCommittedWorldHover: (world: CommittedWorldCardResponse) => void;
}) {
  const shouldShowErrorState = state.status === "error";

  return (
    <section className="world-hub-card-row" aria-label="Committed worlds">
      <CreateWorldCard committedWorldCount={state.worlds.length} />
      {state.worlds.map((world) => (
        <CommittedWorldCard
          key={world.world_id}
          world={world}
          onHover={onCommittedWorldHover}
        />
      ))}
      {shouldShowErrorState ? (
        <div className="world-hub-load-error" role="status">
          Unable to load worlds.
        </div>
      ) : null}
    </section>
  );
}

function CreateWorldCard({
  committedWorldCount,
}: {
  committedWorldCount: number;
}) {
  return (
    <button
      className="world-hub-create-world-card"
      type="button"
      onClick={() => void createDraftWorldDetailFlow()}
      aria-label={`Create World. ${committedWorldCount} Worlds`}
    >
      <img
        className="world-hub-world-card-image"
        src={createWorldCardImageUrl}
        alt=""
        draggable={false}
      />
      <div className="world-hub-create-world-card-shade" aria-hidden="true" />
      <div className="world-hub-create-world-card-copy">
        <h2>Create World</h2>
        <p>{committedWorldCount} Worlds</p>
      </div>
    </button>
  );
}

function CommittedWorldCard({
  world,
  onHover,
}: {
  world: CommittedWorldCardResponse;
  onHover: (world: CommittedWorldCardResponse) => void;
}) {
  return (
    <article
      className="world-hub-world-card"
      onMouseEnter={() => onHover(world)}
      onMouseOver={() => onHover(world)}
      onPointerEnter={() => onHover(world)}
      onPointerOver={() => onHover(world)}
    >
      <img
        className="world-hub-world-card-image"
        src={world.background_image_url}
        alt=""
        draggable={false}
      />
      <div className="world-hub-world-card-shade" aria-hidden="true" />
      <button
        className="world-hub-world-card-manage"
        type="button"
        aria-label={`Manage World: ${world.display_name}`}
      >
        <SlidersHorizontal aria-hidden="true" />
      </button>
      <div className="world-hub-world-card-copy">
        <h2>{world.display_name}</h2>
        <p className="world-hub-world-card-last-used">
          Last Used: {formatLastUsedAt(world.last_used_at)}
        </p>
      </div>
    </article>
  );
}

function WorldHubStartupSplash({ isVisible }: { isVisible: boolean }) {
  return (
    <div
      className={
        isVisible
          ? "world-hub-startup-splash"
          : "world-hub-startup-splash world-hub-startup-splash-exit"
      }
      aria-hidden="true"
    >
      <img
        className="world-hub-startup-logo"
        src={logoUrl}
        alt=""
        draggable={false}
      />
      <div className="world-hub-startup-spinner" />
    </div>
  );
}

function useCommittedWorldCards(): CommittedWorldCardState {
  const [state, setState] = useState<CommittedWorldCardState>({
    status: "loading",
    worlds: [],
  });

  useEffect(() => {
    const abortController = new AbortController();

    fetchCommittedWorldCards(abortController.signal)
      .then((worlds) => {
        setState({ status: "loaded", worlds });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        setState({ status: "error", worlds: [] });
      });

    return () => {
      abortController.abort();
    };
  }, []);

  return state;
}

function useWorldHubHero(state: CommittedWorldCardState): {
  hero: WorldHubHero;
  setActiveWorld: (world: CommittedWorldCardResponse) => void;
} {
  const [activeWorld, setActiveWorld] =
    useState<CommittedWorldCardResponse | null>(null);
  const latestWorld = state.status === "loaded" ? state.worlds[0] ?? null : null;
  const heroWorld = activeWorld ?? latestWorld;
  const fontFamily = useHeroFontFamily(heroWorld);

  useEffect(() => {
    if (state.status !== "loaded") {
      setActiveWorld(null);
      return;
    }

    setActiveWorld((currentWorld) => {
      const matchingWorld =
        currentWorld === null
          ? null
          : state.worlds.find((world) => world.world_id === currentWorld.world_id);

      if (matchingWorld !== null && matchingWorld !== undefined) {
        return matchingWorld;
      }

      return state.worlds[0] ?? null;
    });
  }, [state]);

  if (state.status === "loading" || state.status === "error") {
    return {
      hero: {
        key: "neutral",
        title: "",
        description: "",
        backgroundImageUrl: null,
        fontFamily: DEFAULT_HERO_FONT_FAMILY,
      },
      setActiveWorld,
    };
  }

  if (heroWorld === null) {
    return {
      hero: {
        key: "empty",
        title: WORLD_HUB_HERO_TITLE,
        description: WORLD_HUB_HERO_DESCRIPTION,
        backgroundImageUrl: backgroundUrl,
        fontFamily: DEFAULT_HERO_FONT_FAMILY,
      },
      setActiveWorld,
    };
  }

  return {
    hero: {
      key: heroWorld.world_id,
      title: heroWorld.display_name,
      description: heroWorld.description ?? "",
      backgroundImageUrl: heroWorld.background_image_url,
      fontFamily,
    },
    setActiveWorld,
  };
}

function useHeroFontFamily(world: CommittedWorldCardResponse | null): string {
  const fontFamily = useMemo(() => {
    if (world === null) {
      return DEFAULT_HERO_FONT_FAMILY;
    }

    return `"${getHeroFontFamilyName(world.font_asset_id)}", ${DEFAULT_HERO_FONT_FAMILY}`;
  }, [world]);

  useEffect(() => {
    if (world === null) {
      return;
    }

    const styleElement = document.createElement("style");
    styleElement.dataset.worldHubHeroFont = world.font_asset_id;
    styleElement.textContent = buildHeroFontFaceRule(world);
    document.head.appendChild(styleElement);

    return () => {
      styleElement.remove();
    };
  }, [world]);

  return fontFamily;
}

type CrossfadeState<T> = {
  current: T;
  previous: T | null;
};

function useCrossfade<T extends { key: string }>(
  item: T,
  durationMilliseconds: number,
): CrossfadeState<T> {
  const currentRef = useRef(item);
  const [transition, setTransition] = useState<CrossfadeState<T>>({
    current: item,
    previous: null,
  });

  useEffect(() => {
    if (item.key === currentRef.current.key) {
      currentRef.current = item;
      setTransition((currentTransition) => ({
        ...currentTransition,
        current: item,
      }));
      return;
    }

    const previousItem = currentRef.current;
    currentRef.current = item;
    setTransition({
      current: item,
      previous: previousItem,
    });

    const crossfadeTimeout = window.setTimeout(() => {
      setTransition((currentTransition) => ({
        ...currentTransition,
        previous: null,
      }));
    }, durationMilliseconds);

    return () => {
      window.clearTimeout(crossfadeTimeout);
    };
  }, [durationMilliseconds, item.key]);

  return transition;
}

function useWorldHubStartupSplash(isLoading: boolean): {
  status: "visible" | "exiting" | "hidden";
} {
  const [status, setStatus] = useState<"visible" | "exiting" | "hidden">(
    isLoading ? "visible" : "hidden",
  );

  useEffect(() => {
    if (isLoading) {
      setStatus("visible");
      return;
    }

    setStatus((currentStatus) => {
      if (currentStatus === "visible") {
        return "exiting";
      }

      return currentStatus;
    });

    const splashExitTimeout = window.setTimeout(() => {
      setStatus("hidden");
    }, WORLD_HUB_SPLASH_EXIT_MILLISECONDS);

    return () => {
      window.clearTimeout(splashExitTimeout);
    };
  }, [isLoading]);

  return { status };
}

function buildWorldHubBackgroundStyle(hero: WorldHubHero) {
  if (hero.backgroundImageUrl === null) {
    return undefined;
  }

  return { backgroundImage: `url("${hero.backgroundImageUrl}")` };
}

function buildHeroFontFaceRule(world: CommittedWorldCardResponse): string {
  return `
@font-face {
  font-family: "${getHeroFontFamilyName(world.font_asset_id)}";
  src: url("${world.font_file_url}") format("truetype");
  font-display: swap;
}`;
}

function getHeroFontFamilyName(fontAssetId: string): string {
  return `VySol Hero ${fontAssetId.replaceAll(/[^A-Za-z0-9_-]/g, "-")}`;
}

function formatLastUsedAt(lastUsedAt: string): string {
  const parsedDate = parseUtcTimestamp(lastUsedAt);

  if (parsedDate === null) {
    return lastUsedAt;
  }

  const elapsedMilliseconds = Math.max(0, Date.now() - parsedDate.getTime());

  if (elapsedMilliseconds < MILLISECONDS_PER_MINUTE) {
    return "Just now";
  }

  if (elapsedMilliseconds < MILLISECONDS_PER_HOUR) {
    return formatRelativeTimeUnit(
      Math.floor(elapsedMilliseconds / MILLISECONDS_PER_MINUTE),
      "minute",
    );
  }

  if (elapsedMilliseconds < MILLISECONDS_PER_DAY) {
    return formatRelativeTimeUnit(
      Math.floor(elapsedMilliseconds / MILLISECONDS_PER_HOUR),
      "hour",
    );
  }

  return formatRelativeTimeUnit(
    Math.floor(elapsedMilliseconds / MILLISECONDS_PER_DAY),
    "day",
  );
}

function parseUtcTimestamp(timestamp: string): Date | null {
  const match = LAST_USED_TIMESTAMP_PATTERN.exec(timestamp);

  if (match === null) {
    return null;
  }

  const [, year, month, day, hour, minute, second] = match;
  return new Date(
    Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
    ),
  );
}

function formatRelativeTimeUnit(value: number, unit: string): string {
  const suffix = value === 1 ? unit : `${unit}s`;
  return `${value} ${suffix} ago`;
}
