import Fuse from "fuse.js";

type ChronicleTitle = { title: string };
type WorldTitle = { name: string };

const FUZZY_THRESHOLD = 0.35;
const MINIMUM_FUZZY_QUERY_LENGTH = 3;

function normalizeTitle(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, " ");
}

function startsAtWordPrefix(title: string, queryWords: string[]): boolean {
  const titleWords = title.split(/\s+/);
  return titleWords.some((_, start) =>
    queryWords.every((word, offset) => {
      const titleWord = titleWords[start + offset];
      return titleWord !== undefined && titleWord.startsWith(word);
    }),
  );
}

/** Rank names and titles while preserving the caller's recency order in each rank. */
export function rankByTitle<T>(
  items: T[],
  query: string,
  getTitle: (item: T) => string,
): T[] {
  const normalizedQuery = normalizeTitle(query);
  if (!normalizedQuery) return [...items];

  const indexed = items.map((item, index) => ({
    item,
    searchableTitle: normalizeTitle(getTitle(item)),
  }));
  const queryWords = normalizedQuery.split(" ");
  const exact: typeof indexed = [];
  const prefixes: typeof indexed = [];
  const contains: typeof indexed = [];
  const remaining: typeof indexed = [];

  for (const entry of indexed) {
    if (entry.searchableTitle === normalizedQuery) {
      exact.push(entry);
    } else if (
      entry.searchableTitle.startsWith(normalizedQuery) ||
      startsAtWordPrefix(entry.searchableTitle, queryWords)
    ) {
      prefixes.push(entry);
    } else if (entry.searchableTitle.includes(normalizedQuery)) {
      contains.push(entry);
    } else {
      remaining.push(entry);
    }
  }

  let fuzzy: typeof indexed = [];
  const fuzzyQueryLength = Array.from(normalizedQuery.replace(/\s/g, "")).length;
  if (fuzzyQueryLength >= MINIMUM_FUZZY_QUERY_LENGTH && remaining.length) {
    const fuse = new Fuse(remaining, {
      keys: ["searchableTitle"],
      threshold: FUZZY_THRESHOLD,
      ignoreLocation: true,
      shouldSort: false,
    });
    const matches = new Set(fuse.search(normalizedQuery).map((result) => result.item));
    fuzzy = remaining.filter((entry) => matches.has(entry));
  }

  return [...exact, ...prefixes, ...contains, ...fuzzy].map(({ item }) => item);
}

export function rankChronicles<T extends ChronicleTitle>(
  items: T[],
  query: string,
): T[] {
  return rankByTitle(items, query, (item) => item.title);
}

export function rankWorlds<T extends WorldTitle>(items: T[], query: string): T[] {
  return rankByTitle(items, query, (item) => item.name);
}
