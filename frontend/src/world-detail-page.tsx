import { ArrowLeft, Box, GitBranch } from "lucide-react";
import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { DraftAbandonConfirmationDialog } from "./draft-abandon-confirmation-dialog";
import { useDraftAbandonNavigation } from "./draft-abandon-navigation";
import {
  type DraftWorldDetailResponse,
  fetchDraftWorldDetail,
} from "./draft-world-api";
import logoUrl from "../../docs/assets/Butterfly_logo_compressed_centered.png";
import backgroundUrl from "../../app/assets/images/Main World Image.png";

type WorldMode = "draft" | "committed";
type WorldTab = "customize" | "ingestion";
type DraftWorldLoadState =
  | { status: "idle"; draftId: null; detail: null }
  | { status: "loading"; draftId: string; detail: null }
  | { status: "loaded"; draftId: string; detail: DraftWorldDetailResponse }
  | { status: "error"; draftId: string; detail: null };

const VALID_MODES = new Set<WorldMode>(["draft", "committed"]);

export function WorldDetailPage() {
  const mode = readWorldMode();
  const draftId = readDraftId();
  const draftWorldState = useDraftWorldDetail(mode, draftId);

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
      <WorldDetailTabs mode={mode} draftWorldState={draftWorldState} />
    </main>
  );
}

function WorldDetailTabs({
  mode,
  draftWorldState,
}: {
  mode: WorldMode;
  draftWorldState: DraftWorldLoadState;
}) {
  const draftId = draftWorldState.draftId;
  const draftAbandonNavigation = useDraftAbandonNavigation(mode, draftId);

  return (
    <>
      <Tabs defaultValue="customize" className="world-detail-tabs-root">
        <div
          className="world-detail-nav-list"
          aria-label="World detail navigation"
        >
          <button
            className="world-detail-up-button"
            type="button"
            onClick={draftAbandonNavigation.handleWorldHubNavigation}
            aria-label="Go to Worlds"
            aria-busy={draftAbandonNavigation.isCheckingLeaveState}
            disabled={
              draftAbandonNavigation.isCheckingLeaveState ||
              draftAbandonNavigation.isDiscardingDraft
            }
          >
            <ArrowLeft aria-hidden="true" />
            <span>Worlds</span>
          </button>
          <span className="world-detail-nav-separator" aria-hidden="true" />
          <TabsList
            aria-label="World detail sections"
            className="world-detail-tabs-list"
          >
            <TabsTrigger value="customize">
              <GitBranch aria-hidden="true" />
              <span>Customize</span>
            </TabsTrigger>
            <TabsTrigger value="ingestion">
              <Box aria-hidden="true" />
              <span>Ingestion</span>
            </TabsTrigger>
          </TabsList>
        </div>
        {draftAbandonNavigation.navigationErrorMessage !== null ? (
          <p className="world-detail-navigation-error" role="alert">
            {draftAbandonNavigation.navigationErrorMessage}
          </p>
        ) : null}
        <ShellPane
          tab="customize"
          mode={mode}
          draftWorldState={draftWorldState}
        />
        <ShellPane
          tab="ingestion"
          mode={mode}
          draftWorldState={draftWorldState}
        />
      </Tabs>
      {draftAbandonNavigation.isAbandonDialogOpen ? (
        <DraftAbandonConfirmationDialog
          errorMessage={draftAbandonNavigation.dialogErrorMessage}
          isDiscarding={draftAbandonNavigation.isDiscardingDraft}
          onCancel={draftAbandonNavigation.closeAbandonDialog}
          onConfirm={draftAbandonNavigation.confirmDraftAbandon}
        />
      ) : null}
    </>
  );
}

function ShellPane({
  tab,
  mode,
  draftWorldState,
}: {
  tab: WorldTab;
  mode: WorldMode;
  draftWorldState: DraftWorldLoadState;
}) {
  return (
    <TabsContent value={tab}>
      <section className="world-detail-pane" aria-label={`${mode} ${tab} shell`}>
        <p>{getPaneLabel(mode, tab, draftWorldState)}</p>
      </section>
    </TabsContent>
  );
}

function getPaneLabel(
  mode: WorldMode,
  tab: WorldTab,
  draftWorldState: DraftWorldLoadState,
): string {
  if (mode === "draft") {
    return getDraftPaneLabel(tab, draftWorldState);
  }

  const tabLabel = tab === "customize" ? "Customize" : "Ingestion";
  return `Committed world ${tabLabel} shell`;
}

function getDraftPaneLabel(
  tab: WorldTab,
  draftWorldState: DraftWorldLoadState,
): string {
  if (draftWorldState.status === "loading") {
    return "Loading draft world setup";
  }

  if (draftWorldState.status === "error") {
    return "Draft world setup could not be loaded";
  }

  if (draftWorldState.status !== "loaded") {
    const tabLabel = tab === "customize" ? "Customize" : "Ingestion";
    return `Draft world ${tabLabel} shell`;
  }

  if (tab === "customize") {
    const settings = draftWorldState.detail.splitter_settings;
    return `Draft world Customize shell. Splitter defaults loaded: ${settings.chunk_size}/${settings.max_lookback_size}/${settings.overlap_size}`;
  }

  return `Draft world Ingestion shell. ${draftWorldState.detail.staged_sources.length} staged sources`;
}

function useDraftWorldDetail(
  mode: WorldMode,
  draftId: string | null,
): DraftWorldLoadState {
  const [draftWorldState, setDraftWorldState] = useState<DraftWorldLoadState>(
    getInitialDraftWorldState(draftId),
  );

  useEffect(() => {
    if (mode !== "draft" || draftId === null) {
      setDraftWorldState(getInitialDraftWorldState(null));
      return;
    }

    const abortController = new AbortController();
    setDraftWorldState({ status: "loading", draftId, detail: null });

    fetchDraftWorldDetail(draftId, abortController.signal)
      .then((detail) => {
        setDraftWorldState({ status: "loaded", draftId, detail });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        setDraftWorldState({ status: "error", draftId, detail: null });
      });

    return () => {
      abortController.abort();
    };
  }, [draftId, mode]);

  return draftWorldState;
}

function getInitialDraftWorldState(draftId: string | null): DraftWorldLoadState {
  if (draftId === null) {
    return { status: "idle", draftId: null, detail: null };
  }

  return { status: "loading", draftId, detail: null };
}

function readWorldMode(): WorldMode {
  const queryMode = new URLSearchParams(window.location.search).get("mode");

  if (queryMode && VALID_MODES.has(queryMode as WorldMode)) {
    return queryMode as WorldMode;
  }

  return "draft";
}

function readDraftId(): string | null {
  const draftId = new URLSearchParams(window.location.search).get("draftId");

  if (draftId && draftId.trim()) {
    return draftId;
  }

  return null;
}
