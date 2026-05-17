export type CommittedWorldCardResponse = {
  world_id: string;
  display_name: string;
  description: string | null;
  background_asset_id: string;
  background_image_url: string;
  font_asset_id: string;
  font_file_url: string;
  last_used_at: string;
};

export type CommittedWorldSplitterSettingsResponse = {
  chunk_size: number;
  max_lookback_size: number;
  overlap_size: number;
  splitter_version: string;
  is_locked: boolean;
};

export type CommittedSourceSummaryResponse = {
  source_id: string;
  original_filename: string;
  source_file_type: string;
  book_number: number;
  committed_at: string;
};

export type CommittedWorldDetailResponse = CommittedWorldCardResponse & {
  splitter_settings: CommittedWorldSplitterSettingsResponse;
  committed_sources: CommittedSourceSummaryResponse[];
};

const COMMITTED_WORLDS_ENDPOINT = "/worlds";

export async function fetchCommittedWorldCards(
  signal?: AbortSignal,
): Promise<CommittedWorldCardResponse[]> {
  const response = await fetch(COMMITTED_WORLDS_ENDPOINT, {
    headers: {
      Accept: "application/json",
    },
    signal,
  });

  if (!response.ok) {
    throw new Error("Committed world card request failed.");
  }

  return response.json() as Promise<CommittedWorldCardResponse[]>;
}

export async function fetchCommittedWorldDetail(
  worldId: string,
  signal?: AbortSignal,
): Promise<CommittedWorldDetailResponse> {
  const response = await fetch(
    `${COMMITTED_WORLDS_ENDPOINT}/${encodeURIComponent(worldId)}/detail`,
    {
      headers: {
        Accept: "application/json",
      },
      signal,
    },
  );

  if (!response.ok) {
    throw new Error("Committed world detail request failed.");
  }

  return response.json() as Promise<CommittedWorldDetailResponse>;
}
