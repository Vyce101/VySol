export type CommittedWorldCardResponse = {
  world_id: string;
  display_name: string;
  description: string | null;
  background_asset_id: string;
  background_image_url: string;
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
