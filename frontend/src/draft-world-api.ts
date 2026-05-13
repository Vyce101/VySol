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

export async function createDraftWorldDetailFlow(): Promise<string> {
  const draftWorld = await createDraftWorld();
  const draftWorldUrl = buildDraftWorldDetailUrl(draftWorld.draft_id);
  window.location.assign(draftWorldUrl);
  return draftWorldUrl;
}

export function buildDraftWorldDetailUrl(draftId: string): string {
  const query = new URLSearchParams({
    mode: "draft",
    draftId,
  });

  return `/?${query.toString()}`;
}

async function readDraftWorldResponse(
  response: Response,
): Promise<DraftWorldDetailResponse> {
  if (!response.ok) {
    throw new Error("Draft world request failed.");
  }

  return response.json() as Promise<DraftWorldDetailResponse>;
}
