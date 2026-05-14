import { Globe2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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

type CommittedWorldCardState =
  | { status: "loading"; worlds: [] }
  | { status: "loaded"; worlds: CommittedWorldCardResponse[] }
  | { status: "error"; worlds: [] };

type WorldHubHero = {
  title: string;
  description: string;
  backgroundImageUrl: string;
  fontFamily: string;
};

export function WorldHubPage() {
  const committedWorldState = useCommittedWorldCards();
  const hero = useWorldHubHero(committedWorldState);

  return (
    <main className="world-hub-shell">
      <div
        className="world-hub-background"
        style={{ backgroundImage: `url("${hero.backgroundImageUrl}")` }}
        aria-hidden="true"
      />
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
        style={{ fontFamily: hero.fontFamily }}
      >
        <h1 id="world-hub-title">{hero.title}</h1>
        <p>{hero.description}</p>
      </section>
      <CommittedWorldCardRow state={committedWorldState} />
    </main>
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
}: {
  state: CommittedWorldCardState;
}) {
  const shouldShowErrorState = state.status === "error";

  return (
    <section className="world-hub-card-row" aria-label="Committed worlds">
      <CreateWorldCard committedWorldCount={state.worlds.length} />
      {state.worlds.map((world) => (
        <CommittedWorldCard key={world.world_id} world={world} />
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

function CommittedWorldCard({ world }: { world: CommittedWorldCardResponse }) {
  return (
    <article className="world-hub-world-card">
      <img
        className="world-hub-world-card-image"
        src={world.background_image_url}
        alt=""
        draggable={false}
      />
      <div className="world-hub-world-card-shade" aria-hidden="true" />
      <h2>{world.display_name}</h2>
    </article>
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

function useWorldHubHero(state: CommittedWorldCardState): WorldHubHero {
  const latestWorld =
    state.status === "loaded" && state.worlds.length > 0 ? state.worlds[0] : null;
  const fontFamily = useHeroFontFamily(latestWorld);

  if (latestWorld === null) {
    return {
      title: WORLD_HUB_HERO_TITLE,
      description: WORLD_HUB_HERO_DESCRIPTION,
      backgroundImageUrl: backgroundUrl,
      fontFamily: DEFAULT_HERO_FONT_FAMILY,
    };
  }

  return {
    title: latestWorld.display_name,
    description: latestWorld.description ?? "",
    backgroundImageUrl: latestWorld.background_image_url,
    fontFamily,
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
