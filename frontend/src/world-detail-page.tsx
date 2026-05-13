import { Box, GitBranch } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import logoUrl from "../../docs/assets/Butterfly_logo_compressed_centered.png";
import backgroundUrl from "../../app/assets/images/Main World Image.png";

type WorldMode = "draft" | "committed";
type WorldTab = "customize" | "ingestion";

const VALID_MODES = new Set<WorldMode>(["draft", "committed"]);

export function WorldDetailPage() {
  const mode = readWorldMode();

  return (
    <main className="world-detail-shell">
      <div
        className="world-detail-background"
        style={{ backgroundImage: `url("${backgroundUrl}")` }}
        aria-hidden="true"
      />
      <div className="world-detail-shade" aria-hidden="true" />
      <header className="world-detail-header">
        <div className="world-detail-brand" aria-label="VySol">
          <img className="world-detail-brand-mark" src={logoUrl} alt="" />
          <span className="world-detail-brand-name">VySol</span>
        </div>
      </header>
      <WorldDetailTabs mode={mode} />
    </main>
  );
}

function WorldDetailTabs({ mode }: { mode: WorldMode }) {
  return (
    <Tabs defaultValue="customize" className="world-detail-tabs-root">
      <TabsList aria-label="World detail sections">
        <TabsTrigger value="customize">
          <GitBranch aria-hidden="true" />
          <span>Customize</span>
        </TabsTrigger>
        <TabsTrigger value="ingestion">
          <Box aria-hidden="true" />
          <span>Ingestion</span>
        </TabsTrigger>
      </TabsList>
      <ShellPane tab="customize" mode={mode} />
      <ShellPane tab="ingestion" mode={mode} />
    </Tabs>
  );
}

function ShellPane({ tab, mode }: { tab: WorldTab; mode: WorldMode }) {
  return (
    <TabsContent value={tab}>
      <section className="world-detail-pane" aria-label={`${mode} ${tab} shell`}>
        <p>{getPaneLabel(mode, tab)}</p>
      </section>
    </TabsContent>
  );
}

function getPaneLabel(mode: WorldMode, tab: WorldTab): string {
  const modeLabel = mode === "draft" ? "Draft world" : "Committed world";
  const tabLabel = tab === "customize" ? "Customize" : "Ingestion";
  return `${modeLabel} ${tabLabel} shell`;
}

function readWorldMode(): WorldMode {
  const queryMode = new URLSearchParams(window.location.search).get("mode");

  if (queryMode && VALID_MODES.has(queryMode as WorldMode)) {
    return queryMode as WorldMode;
  }

  return "draft";
}
