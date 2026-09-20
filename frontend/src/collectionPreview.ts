import type { World } from "./api";

export type CollectionPreview = "saved" | "sample" | "four" | "empty";
export type PreviewWorld = World & { artworkUrl?: string };
const sampleNames = [
  "Northern Tales",
  "The Glass Harbor",
  "Moonlit Kingdom",
  "Winter Letters",
  "The Last Lighthouse",
  "A Garden of Stars",
  "Northern Skies",
  "The Quiet Sea",
  "Letters from the Moon",
  "The Amber Forest",
  "Winter at the Harbor",
  "Beyond the Stars",
];

// These are temporary visual fixtures, never persisted as actual worlds.
export function sampleWorlds(worlds: World[]): PreviewWorld[] {
  return sampleNames.map((name, index) => ({
    id: `sample-${index}`,
    name,
    created_at: "",
    last_used_at: null,
    artwork: "frostwake",
    artworkUrl: worlds.length
      ? `/api/worlds/${worlds[index % worlds.length].id}/artwork`
      : "/assets/frostwake.png",
  }));
}
export function artworkUrl(world: PreviewWorld | null) {
  return (
    world?.artworkUrl ??
    (world ? `/api/worlds/${world.id}/artwork` : "/assets/frostwake.png")
  );
}
