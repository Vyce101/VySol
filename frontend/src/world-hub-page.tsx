import { Globe2 } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import logoUrl from "../../docs/assets/Butterfly_logo_compressed_centered.png";
import backgroundUrl from "../../app/assets/images/Main World Image.png";
import "./world-hub-page.css";

const WORLD_HUB_HERO_TITLE = "Create World";
const WORLD_HUB_HERO_DESCRIPTION =
  "Build a living setting for roleplay and simulation.";

export function WorldHubPage() {
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
      <section className="world-hub-card-row" aria-label="World card row" />
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
