import { ArrowLeft, Box, GitBranch } from "lucide-react";
import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import {
  type CommittedWorldDetailResponse,
  fetchCommittedWorldDetail,
} from "./committed-world-api";
import { DraftAbandonConfirmationDialog } from "./draft-abandon-confirmation-dialog";
import { useDraftAbandonNavigation } from "./draft-abandon-navigation";
import {
  type DraftWorldDetailResponse,
  fetchDraftWorldDetail,
} from "./draft-world-api";
import {
  type CustomizeWorldState,
  WorldDetailCustomizeTab,
} from "./world-detail-customize-tab";
import logoUrl from "../../docs/assets/Butterfly_logo_compressed_centered.png";
import backgroundUrl from "../../app/assets/images/Main World Image.png";

type WorldMode = "draft" | "committed";
type WorldTab = "customize" | "ingestion";
type DraftWorldLoadState =
  | { status: "idle"; draftId: null; detail: null }
  | { status: "loading"; draftId: string; detail: null }
  | { status: "loaded"; draftId: string; detail: DraftWorldDetailResponse }
  | { status: "error"; draftId: string; detail: null };
type CommittedWorldLoadState =
  | { status: "idle"; worldId: null; detail: null }
  | { status: "loading"; worldId: string; detail: null }
  | { status: "loaded"; worldId: string; detail: CommittedWorldDetailResponse }
  | { status: "error"; worldId: string; detail: null };

const VALID_MODES = new Set<WorldMode>(["draft", "committed"]);

export function WorldDetailPage() {
  const mode = readWorldMode();
  const draftId = readDraftId();
  const worldId = readWorldId();
  const draftWorldState = useDraftWorldDetail(mode, draftId);
  const committedWorldState = useCommittedWorldDetail(mode, worldId);
  const worldBackgroundUrl = getWorldBackgroundUrl(
    mode,
    committedWorldState,
  );

  return (
    <main className="world-detail-shell">
      <div
        className="world-detail-background"
        style={{ backgroundImage: `url("${worldBackgroundUrl}")` }}
        aria-hidden="true"
      />
      <div className="world-detail-shade" aria-hidden="true" />
      <header className="world-detail-header">
        <div className="world-detail-brand" aria-label="VySol">
          <img className="world-detail-brand-mark" src={logoUrl} alt="" />
          <span className="world-detail-brand-name">VySol</span>
        </div>
      </header>
      <WorldDetailTabs
        mode={mode}
        draftWorldState={draftWorldState}
        committedWorldState={committedWorldState}
      />
    </main>
  );
}

function WorldDetailTabs({
  mode,
  draftWorldState,
  committedWorldState,
}: {
  mode: WorldMode;
  draftWorldState: DraftWorldLoadState;
  committedWorldState: CommittedWorldLoadState;
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
          committedWorldState={committedWorldState}
        />
        <ShellPane
          tab="ingestion"
          mode={mode}
          draftWorldState={draftWorldState}
          committedWorldState={committedWorldState}
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
  committedWorldState,
}: {
  tab: WorldTab;
  mode: WorldMode;
  draftWorldState: DraftWorldLoadState;
  committedWorldState: CommittedWorldLoadState;
}) {
  if (tab === "customize") {
    return (
      <TabsContent value={tab} className="customize-tabs-content">
        <WorldDetailCustomizeTab
          state={getCustomizeWorldState(
            mode,
            draftWorldState,
            committedWorldState,
          )}
        />
      </TabsContent>
    );
  }

  return (
    <TabsContent value={tab}>
      <section className="world-detail-pane" aria-label={`${mode} ${tab} shell`}>
        <p>{getPaneLabel(mode, tab, draftWorldState, committedWorldState)}</p>
      </section>
    </TabsContent>
  );
}

function getWorldBackgroundUrl(
  mode: WorldMode,
  committedWorldState: CommittedWorldLoadState,
): string {
  if (mode === "committed" && committedWorldState.status === "loaded") {
    return committedWorldState.detail.background_image_url;
  }

  return backgroundUrl;
}

function getCustomizeWorldState(
  mode: WorldMode,
  draftWorldState: DraftWorldLoadState,
  committedWorldState: CommittedWorldLoadState,
): CustomizeWorldState {
  if (mode === "draft") {
    if (draftWorldState.status === "loaded") {
      return {
        mode,
        status: "loaded",
        detail: draftWorldState.detail,
      };
    }

    return {
      mode,
      status: draftWorldState.status,
    };
  }

  if (committedWorldState.status === "loaded") {
    return {
      mode,
      status: "loaded",
      detail: committedWorldState.detail,
    };
  }

  return {
    mode,
    status: committedWorldState.status,
  };
}

function getPaneLabel(
  mode: WorldMode,
  tab: WorldTab,
  draftWorldState: DraftWorldLoadState,
  committedWorldState: CommittedWorldLoadState,
): string {
  if (mode === "draft") {
    return getDraftPaneLabel(tab, draftWorldState);
  }

  return getCommittedPaneLabel(tab, committedWorldState);
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

function getCommittedPaneLabel(
  tab: WorldTab,
  committedWorldState: CommittedWorldLoadState,
): string {
  if (committedWorldState.status === "loading") {
    return "Loading committed world setup";
  }

  if (committedWorldState.status === "error") {
    return "Committed world setup could not be loaded";
  }

  if (committedWorldState.status !== "loaded") {
    const tabLabel = tab === "customize" ? "Customize" : "Ingestion";
    return `Committed world ${tabLabel} shell`;
  }

  if (tab === "customize") {
    return `Committed world Customize shell. Saved values loaded for ${committedWorldState.detail.display_name}`;
  }

  return `Committed world Ingestion shell. ${committedWorldState.detail.committed_sources.length} committed sources`;
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

function useCommittedWorldDetail(
  mode: WorldMode,
  worldId: string | null,
): CommittedWorldLoadState {
  const [committedWorldState, setCommittedWorldState] =
    useState<CommittedWorldLoadState>(getInitialCommittedWorldState(worldId));

  useEffect(() => {
    if (mode !== "committed" || worldId === null) {
      setCommittedWorldState(getInitialCommittedWorldState(null));
      return;
    }

    const abortController = new AbortController();
    setCommittedWorldState({ status: "loading", worldId, detail: null });

    fetchCommittedWorldDetail(worldId, abortController.signal)
      .then((detail) => {
        setCommittedWorldState({ status: "loaded", worldId, detail });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        setCommittedWorldState({ status: "error", worldId, detail: null });
      });

    return () => {
      abortController.abort();
    };
  }, [mode, worldId]);

  return committedWorldState;
}

function getInitialDraftWorldState(draftId: string | null): DraftWorldLoadState {
  if (draftId === null) {
    return { status: "idle", draftId: null, detail: null };
  }

  return { status: "loading", draftId, detail: null };
}

function getInitialCommittedWorldState(
  worldId: string | null,
): CommittedWorldLoadState {
  if (worldId === null) {
    return { status: "idle", worldId: null, detail: null };
  }

  return { status: "loading", worldId, detail: null };
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

function readWorldId(): string | null {
  const worldId = new URLSearchParams(window.location.search).get("worldId");

  if (worldId && worldId.trim()) {
    return worldId;
  }

  return null;
}
