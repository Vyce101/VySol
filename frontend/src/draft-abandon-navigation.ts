import { useCallback, useState } from "react";
import { navigateToWorldHub } from "./app-navigation";
import {
  confirmDraftWorldLeave,
  fetchDraftWorldLeaveState,
} from "./draft-world-api";

type DraftAbandonWorldMode = "draft" | "committed";

export function useDraftAbandonNavigation(
  mode: DraftAbandonWorldMode,
  draftId: string | null,
) {
  const [isCheckingLeaveState, setIsCheckingLeaveState] = useState(false);
  const [isDiscardingDraft, setIsDiscardingDraft] = useState(false);
  const [isAbandonDialogOpen, setIsAbandonDialogOpen] = useState(false);
  const [navigationErrorMessage, setNavigationErrorMessage] = useState<
    string | null
  >(null);
  const [dialogErrorMessage, setDialogErrorMessage] = useState<string | null>(
    null,
  );

  const confirmDraftWorldCanLeave = useCallback(
    async (currentDraftId: string) => {
      setIsCheckingLeaveState(true);
      setNavigationErrorMessage(null);
      setDialogErrorMessage(null);

      try {
        const leaveState = await fetchDraftWorldLeaveState(currentDraftId);

        if (!leaveState.should_warn_before_leave) {
          navigateToWorldHub();
          return;
        }

        setIsAbandonDialogOpen(true);
      } catch {
        setNavigationErrorMessage(
          "Draft leave state could not be checked. Keep editing and try again.",
        );
      } finally {
        setIsCheckingLeaveState(false);
      }
    },
    [],
  );

  const discardDraftAndNavigate = useCallback(
    async (currentDraftId: string) => {
      setIsDiscardingDraft(true);
      setDialogErrorMessage(null);

      try {
        await confirmDraftWorldLeave(currentDraftId);
        navigateToWorldHub();
      } catch {
        setDialogErrorMessage(
          "Draft discard failed. Keep editing and try again.",
        );
      } finally {
        setIsDiscardingDraft(false);
      }
    },
    [],
  );

  const handleWorldHubNavigation = useCallback(() => {
    if (mode !== "draft" || draftId === null) {
      navigateToWorldHub();
      return;
    }

    void confirmDraftWorldCanLeave(draftId);
  }, [confirmDraftWorldCanLeave, draftId, mode]);

  const closeAbandonDialog = useCallback(() => {
    if (isDiscardingDraft) {
      return;
    }

    setDialogErrorMessage(null);
    setIsAbandonDialogOpen(false);
  }, [isDiscardingDraft]);

  const confirmDraftAbandon = useCallback(() => {
    if (draftId === null) {
      navigateToWorldHub();
      return;
    }

    void discardDraftAndNavigate(draftId);
  }, [discardDraftAndNavigate, draftId]);

  return {
    closeAbandonDialog,
    confirmDraftAbandon,
    dialogErrorMessage,
    handleWorldHubNavigation,
    isAbandonDialogOpen,
    isCheckingLeaveState,
    isDiscardingDraft,
    navigationErrorMessage,
  };
}
