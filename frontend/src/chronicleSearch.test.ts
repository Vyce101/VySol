import { describe, expect, test } from "vitest";
import { rankChronicles } from "./chronicleSearch";

describe("rankChronicles", () => {
  test("ranks exact, word-prefix, contained, then fuzzy titles", () => {
    const recentFirst = [
      { id: "contains", title: "Tales of Northfrostwake" },
      { id: "prefix-later", title: "Frostwake: Winter" },
      { id: "exact", title: "Frostwake" },
      { id: "fuzzy", title: "Froestwake" },
      { id: "prefix-word", title: "Beyond the Frostwake" },
    ];

    expect(rankChronicles(recentFirst, "frostwake").map(({ id }) => id)).toEqual([
      "exact",
      "prefix-later",
      "prefix-word",
      "contains",
      "fuzzy",
    ]);
  });

  test("ignores case and accents and preserves recency within a rank", () => {
    const recentFirst = [
      { title: "Café at Dusk" },
      { title: "CAFÉ at Dawn" },
      { title: "The Café Journal" },
    ];

    expect(rankChronicles(recentFirst, "cafe")).toEqual(recentFirst);
    expect(rankChronicles(recentFirst, "CAFÉ")).toEqual(recentFirst);
  });

  test("does not use fuzzy matching for queries shorter than three characters", () => {
    const items = [{ title: "Frostwake" }, { title: "Fuzzy Harbor" }];
    expect(rankChronicles(items, "fz")).toEqual([]);
    expect(rankChronicles(items, "f z")).toEqual([]);
    expect(rankChronicles(items, "fr")).toEqual([items[0]]);
  });

  test("returns all items in their current order for an empty query", () => {
    const items = [{ title: "Second" }, { title: "First" }];
    expect(rankChronicles(items, "  ")).toEqual(items);
  });
});
