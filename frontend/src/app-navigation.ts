const WORLD_HUB_URL = "/";

export function buildWorldHubUrl(): string {
  return WORLD_HUB_URL;
}

export function buildDraftWorldDetailUrl(draftId: string): string {
  const query = new URLSearchParams({
    mode: "draft",
    draftId,
  });

  return `/?${query.toString()}`;
}

export function buildCommittedWorldDetailUrl(worldId: string): string {
  const query = new URLSearchParams({
    mode: "committed",
    worldId,
  });

  return `/?${query.toString()}`;
}

export function navigateToWorldHub(): string {
  return navigateToAppUrl(buildWorldHubUrl());
}

export function navigateToDraftWorldDetail(draftId: string): string {
  return navigateToAppUrl(buildDraftWorldDetailUrl(draftId));
}

export function navigateToCommittedWorldDetail(worldId: string): string {
  return navigateToAppUrl(buildCommittedWorldDetailUrl(worldId));
}

function navigateToAppUrl(url: string): string {
  window.history.pushState(null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
  return url;
}
