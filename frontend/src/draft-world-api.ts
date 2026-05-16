import {
  buildDraftWorldDetailUrl,
  navigateToDraftWorldDetail,
} from "./app-navigation";

export type SplitterSettingsResponse = {
  chunk_size: number;
  max_lookback_size: number;
  overlap_size: number;
  splitter_version: string;
};

export type StagedSourceResponse = {
  staging_entry_id: string;
  source_file_type: string;
  is_valid: boolean;
  error_message: string | null;
};

export type DraftWorldDetailResponse = {
  draft_id: string;
  splitter_settings: SplitterSettingsResponse;
  staged_sources: StagedSourceResponse[];
  has_unsaved_customization_changes: boolean;
};

export type DraftWorldLeaveStateResponse = {
  should_warn_before_leave: boolean;
  should_discard_on_confirmed_leave: boolean;
  is_safe_to_leave: boolean;
  has_unsaved_customization_changes: boolean;
  attempt_status: string;
  attempt_phase: string;
};

export type DraftWorldConfirmedLeaveResponse = DraftWorldLeaveStateResponse & {
  was_discarded: boolean;
};

const DRAFT_WORLDS_ENDPOINT = "/draft-worlds";

export async function createDraftWorld(): Promise<DraftWorldDetailResponse> {
  const response = await fetch(DRAFT_WORLDS_ENDPOINT, {
    method: "POST",
    headers: {
      Accept: "application/json",
    },
  });

  return readDraftWorldResponse(response);
}

export async function fetchDraftWorldDetail(
  draftId: string,
  signal?: AbortSignal,
): Promise<DraftWorldDetailResponse> {
  const response = await fetch(
    `${DRAFT_WORLDS_ENDPOINT}/${encodeURIComponent(draftId)}`,
    {
      headers: {
        Accept: "application/json",
      },
      signal,
    },
  );

  return readDraftWorldResponse(response);
}

export async function updateDraftWorldUnsavedCustomizationChanges(
  draftId: string,
  hasUnsavedCustomizationChanges: boolean,
): Promise<DraftWorldDetailResponse> {
  const response = await fetch(
    `${DRAFT_WORLDS_ENDPOINT}/${encodeURIComponent(draftId)}/unsaved-customization-changes`,
    {
      method: "PATCH",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        has_unsaved_customization_changes: hasUnsavedCustomizationChanges,
      }),
    },
  );

  return readDraftWorldResponse(response);
}

export async function fetchDraftWorldLeaveState(
  draftId: string,
  signal?: AbortSignal,
): Promise<DraftWorldLeaveStateResponse> {
  const response = await fetch(
    `${DRAFT_WORLDS_ENDPOINT}/${encodeURIComponent(draftId)}/leave-state`,
    {
      headers: {
        Accept: "application/json",
      },
      signal,
    },
  );

  return readJsonResponse<DraftWorldLeaveStateResponse>(
    response,
    "Draft world leave-state request failed.",
  );
}

export async function confirmDraftWorldLeave(
  draftId: string,
): Promise<DraftWorldConfirmedLeaveResponse> {
  const response = await fetch(
    `${DRAFT_WORLDS_ENDPOINT}/${encodeURIComponent(draftId)}/confirmed-leave`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    },
  );

  return readJsonResponse<DraftWorldConfirmedLeaveResponse>(
    response,
    "Draft world confirmed-leave request failed.",
  );
}

export async function createDraftWorldDetailFlow(): Promise<string> {
  const draftWorld = await createDraftWorld();
  return navigateToDraftWorldDetail(draftWorld.draft_id);
}

export { buildDraftWorldDetailUrl };

async function readDraftWorldResponse(
  response: Response,
): Promise<DraftWorldDetailResponse> {
  return readJsonResponse<DraftWorldDetailResponse>(
    response,
    "Draft world request failed.",
  );
}

async function readJsonResponse<ResponseBody>(
  response: Response,
  errorMessage: string,
): Promise<ResponseBody> {
  if (!response.ok) {
    throw new Error(errorMessage);
  }

  return response.json() as Promise<ResponseBody>;
}
