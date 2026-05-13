import { Globe2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import {
  type CommittedWorldCardResponse,
  fetchCommittedWorldCards,
} from "./committed-world-api";
import logoUrl from "../../docs/assets/Butterfly_logo_compressed_centered.png";
import backgroundUrl from "../../app/assets/images/Main World Image.png";
import "./world-hub-page.css";

const WORLD_HUB_HERO_TITLE = "Create World";
const WORLD_HUB_HERO_DESCRIPTION =
  "Build a living setting for roleplay and simulation.";

type CommittedWorldCardState =
  | { status: "loading"; worlds: [] }
  | { status: "loaded"; worlds: CommittedWorldCardResponse[] }
  | { status: "error"; worlds: [] };

export function WorldHubPage() {
  const committedWorldState = useCommittedWorldCards();

  return (
    <main className="world-hub-shell">
      <div
        className="world-hub-background"
        style={{ backgroundImage: `url("${backgroundUrl}")` }}
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
      <section className="world-hub-hero" aria-labelledby="world-hub-title">
        <h1 id="world-hub-title">{WORLD_HUB_HERO_TITLE}</h1>
        <p>{WORLD_HUB_HERO_DESCRIPTION}</p>
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
  const shouldShowEmptyState =
    state.status === "loaded" && state.worlds.length === 0;

  return (
    <section className="world-hub-card-row" aria-label="Committed worlds">
      {state.worlds.map((world) => (
        <CommittedWorldCard key={world.world_id} world={world} />
      ))}
      {shouldShowEmptyState ? (
        <div className="world-hub-empty-card" aria-label="No committed worlds" />
      ) : null}
    </section>
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
