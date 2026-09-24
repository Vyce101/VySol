// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { within } from "@testing-library/react";
import { App } from "./App";
import type { CreationAttempt, World, WorldDetail } from "./api";

const frostwake: World = {
  id: "one",
  name: "Frostwake",
  created_at: "2026-01-01",
  last_used_at: null,
  artwork: "frostwake",
  book_count: 2,
};
let records: World[];
let creationRecord: CreationAttempt | null;
let extraCreationRecords: CreationAttempt[];
let details: Record<string, WorldDetail>;
const allCreationRecords = () => [
  ...(creationRecord ? [creationRecord] : []),
  ...extraCreationRecords,
];

function readyDetail(world: World): WorldDetail {
  return {
    ...world,
    sources_locked: true,
    state: "complete",
    books: [
      {
        id: "book-one",
        filename: "The Rise of Kyoshi.txt",
        position: 1,
        state: "done",
        chunks_done: 12,
        chunks_total: 12,
      },
      {
        id: "book-two",
        filename: "The Shadow of Kyoshi.txt",
        position: 2,
        state: "done",
        chunks_done: 10,
        chunks_total: 10,
      },
    ],
    progress: { books_done: 2, books_total: 2, chunks_done: 22, chunks_total: 22 },
    processing: {
      model: "gemini-embedding-2",
      max_chunk_size: 8000,
      boundary_search_distance: 1000,
    },
  };
}

function response(payload: unknown) {
  return { ok: true, json: async () => payload } as Response;
}

beforeEach(() => {
  records = [frostwake];
  creationRecord = null;
  extraCreationRecords = [];
  details = { one: readyDetail(frostwake) };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace("/api", "");
      if (path === "/providers")
        return response({
          keys: [{ id: "key", name: "World Sim 1", provider: "google" }],
          models: [{ id: "gemini-embedding-2", name: "Gemini Embedding 2", provider: "google" }],
          defaults: { model: "gemini-embedding-2", key_id: "key" },
        });
      if (path === "/settings")
        return response({ background_speed: "normal", world_layout: "shelf" });
      if (path === "/creations") return response(allCreationRecords());
      if (path === "/creation") return response(creationRecord);
      if (path.startsWith("/creation/") && path.endsWith("/pause")) {
        const id = path.split("/")[2];
        const updated = allCreationRecords().find((item) => item.id === id);
        if (!updated) return response({});
        const value = { ...updated, state: "pausing" as const };
        if (creationRecord?.id === id) creationRecord = value;
        extraCreationRecords = extraCreationRecords.map((item) => item.id === id ? value : item);
        return response(value);
      }
      if (path.startsWith("/creation/") && path.endsWith("/start")) {
        const id = path.split("/")[2];
        const updated = allCreationRecords().find((item) => item.id === id);
        if (!updated) return response({});
        const value = { ...updated, state: "running" as const };
        if (creationRecord?.id === id) creationRecord = value;
        extraCreationRecords = extraCreationRecords.map((item) => item.id === id ? value : item);
        return response(value);
      }
      if (path.startsWith("/creation/") && init?.method === "DELETE") {
        const id = path.split("/")[2];
        if (creationRecord?.id === id) creationRecord = null;
        extraCreationRecords = extraCreationRecords.filter((item) => item.id !== id);
        return response({ discarded: true });
      }
      if (path.startsWith("/creation/") && !init?.method) {
        const id = path.split("/")[2];
        return response(allCreationRecords().find((item) => item.id === id) ?? {});
      }
      if (path.startsWith("/worlds/") && !path.endsWith("/artwork")) {
        const id = path.split("/")[2];
        if (details[id]) return response(details[id]);
        const matchingAttempt = allCreationRecords().find((item) => item.id === id);
        if (matchingAttempt) {
          const pending: WorldDetail = {
            id,
            name: matchingAttempt.name,
            created_at: matchingAttempt.created_at,
            last_used_at: null,
            artwork: "frostwake",
            book_count: matchingAttempt.books.length,
            sources_locked: true,
            state: matchingAttempt.state,
            books: matchingAttempt.books.map((book) => ({
              id: book.id,
              filename: book.filename,
              position: book.position,
              state: book.state,
              chunks_done: book.chunks_done,
              chunks_total: book.chunks_total,
            })),
            progress: {
              books_done: matchingAttempt.books_done,
              books_total: matchingAttempt.books.length,
              chunks_done: matchingAttempt.chunks_done,
              chunks_total: matchingAttempt.chunks_total,
            },
            processing: {
              model: matchingAttempt.config.model,
              max_chunk_size: matchingAttempt.config.size,
              boundary_search_distance: matchingAttempt.config.search,
            },
          };
          return response(pending);
        }
      }
      if (path === "/worlds") return response(records);
      return response({});
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("home cards show book counts and Ready, and saved cards open Overview", async () => {
  render(<App />);
  const card = await screen.findByRole("button", {
    name: "Frostwake, Ready, 2 Books",
  });
  expect(screen.getByText("Stories live longer here.")).toBeTruthy();
  expect(screen.queryByText(/A world of ice/)).toBeNull();
  fireEvent.click(card);
  const overview = document.querySelector<HTMLElement>(".world-overview-view.is-visible")!;
  expect(await within(overview).findByRole("heading", { name: "Frostwake", level: 1 })).toBeTruthy();
  expect(overview.querySelector("main")).toBeNull();
  expect(within(overview).getByRole("navigation", { name: "World sections" })).toBeTruthy();
  expect(within(overview).getByRole("button", { name: "Overview" }).getAttribute("aria-current")).toBe("page");
  expect(within(overview).getByText("Ready")).toBeTruthy();
  expect(within(overview).getByText("2 Books")).toBeTruthy();
  expect(within(overview).getByText("The Rise of Kyoshi")).toBeTruthy();
  expect(within(overview).getByText("The Shadow of Kyoshi")).toBeTruthy();
  expect(screen.queryByText("TXT")).toBeNull();
  expect(screen.queryByText(/KB/)).toBeNull();
  expect(screen.queryByRole("button", { name: /Add Books/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "World Details" }));
  expect(screen.getByText("8000 characters")).toBeTruthy();
  expect(screen.getByText("1000 characters")).toBeTruthy();
  expect(within(overview).getByText("Gemini Embedding 2", { selector: "dd" })).toBeTruthy();
  expect([...overview.querySelectorAll(".world-details-grid dt")].map((node) => node.textContent)).toEqual([
    "Embedding Model",
    "Maximum Chunk Size",
    "Boundary Search Distance",
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Back to Worlds" }));
  expect(await screen.findByRole("button", { name: "Frostwake, Ready, 2 Books" })).toBeTruthy();
});

test("Create World is a full page with breadcrumbs and its draft survives Settings", async () => {
  render(<App />);
  await screen.findByRole("button", { name: "Frostwake, Ready, 2 Books" });
  fireEvent.click(screen.getByRole("button", { name: "New World" }));
  expect(await screen.findByRole("heading", { name: "Create World" })).toBeTruthy();
  expect(screen.queryByRole("combobox", { name: "Search worlds" })).toBeNull();
  expect(screen.getByRole("button", { name: "Worlds" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("World Name"), { target: { value: "Draft World" } });
  fireEvent.click(await screen.findByRole("button", { name: "Manage API Connections" }));
  expect(await screen.findByRole("heading", { name: "AI Connections" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Worlds" })).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Search worlds" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Close Settings" }));
  expect((await screen.findByLabelText("World Name") as HTMLInputElement).value).toBe("Draft World");
});

test("creating cards open Overview with chunk counts and Discard left of Pause", async () => {
  creationRecord = {
    id: "pending",
    name: "Northern Tales",
    revision: 2,
    state: "running",
    phase: "embedding",
    created_at: "2026-01-02",
    updated_at: "2026-01-02",
    message: "",
    config: { model: "gemini-embedding-2", size: 8000, search: 1000 },
    key_id: "key",
    books_done: 0,
    chunks_total: 7,
    chunks_done: 3,
    books: [
      {
        id: "book-one",
        filename: "The Rise of Kyoshi.txt",
        size: 100,
        position: 1,
        uploaded: true,
        state: "embedding",
        message: "",
        chunks_total: 7,
        chunks_done: 3,
      },
    ],
  };
  details.pending = {
    id: "pending",
    name: "Northern Tales",
    created_at: "2026-01-02",
    last_used_at: null,
    artwork: "frostwake",
    book_count: 1,
    sources_locked: true,
    state: "running",
    books: [
      {
        id: "book-one",
        filename: "The Rise of Kyoshi.txt",
        position: 1,
        state: "embedding",
        chunks_done: 1,
        chunks_total: 7,
      },
    ],
    progress: { books_done: 0, books_total: 1, chunks_done: 1, chunks_total: 7 },
    processing: {
      model: "gemini-embedding-2",
      max_chunk_size: 8000,
      boundary_search_distance: 1000,
    },
  };
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Northern Tales, Creating, 1 Book" }));
  expect(await screen.findByRole("heading", { name: "Northern Tales", level: 1 })).toBeTruthy();
  const overview = document.querySelector<HTMLElement>(".world-overview-view.is-visible")!;
  expect(within(overview).getAllByText("3 of 7 chunks embedded")).toHaveLength(2);
  expect(within(overview).queryByText("1 of 7 chunks embedded")).toBeNull();
  expect(within(overview).getByText("3 of 7 chunks embedded", { selector: "small" })).toBeTruthy();
  const actions = screen.getByRole("button", { name: "Pause" }).parentElement!;
  expect(actions.textContent?.indexOf("Discard World")).toBeLessThan(actions.textContent?.indexOf("Pause") ?? -1);
});

test("multiple active attempts have separate cards and actions target the selected world", async () => {
  const makeAttempt = (id: string, name: string): CreationAttempt => ({
    id,
    name,
    revision: 2,
    state: "running",
    phase: "embedding",
    created_at: "2026-01-02",
    updated_at: "2026-01-02",
    message: "",
    config: { model: "gemini-embedding-2", size: 8000, search: 1000 },
    key_id: "key",
    books_done: 0,
    chunks_total: 7,
    chunks_done: 3,
    books: [{
      id: `book-${id}`,
      filename: `${name}.txt`,
      size: 100,
      position: 1,
      uploaded: true,
      state: "embedding",
      message: "",
      chunks_total: 7,
      chunks_done: 3,
    }],
  });
  creationRecord = makeAttempt("first", "Northern Tales");
  extraCreationRecords = [makeAttempt("second", "Southern Tales")];

  render(<App />);
  const firstCard = await screen.findByRole("button", {
    name: "Northern Tales, Creating, 1 Book",
  });
  const secondCard = screen.getByRole("button", {
    name: "Southern Tales, Creating, 1 Book",
  });
  expect(firstCard).toBeTruthy();
  fireEvent.click(secondCard);
  const overview = document.querySelector<HTMLElement>(".world-overview-view.is-visible")!;
  expect(await within(overview).findByRole("heading", { name: "Southern Tales", level: 1 })).toBeTruthy();
  const buttons = [...overview.querySelectorAll<HTMLButtonElement>(".world-overview-actions > button")];
  expect(buttons.map((button) => button.textContent)).toEqual(["Discard World", "Pause"]);
  fireEvent.click(screen.getByRole("button", { name: "Pause" }));
  await waitFor(() => {
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/creation/second/pause"))).toBe(true);
  });
  fireEvent.click(screen.getByRole("button", { name: "Back to Worlds" }));
  expect(screen.getByRole("button", { name: "Northern Tales, Creating, 1 Book" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Southern Tales, Pausing…, 1 Book" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "New World" }));
  expect(await screen.findByRole("heading", { name: "Create World" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Close Create World" })).toBeTruthy();
});

test("sample homepage cards are clearly marked and cannot open nonexistent worlds", async () => {
  const { fetch: fetchMock } = globalThis;
  render(<App />);
  await screen.findByRole("button", { name: "Frostwake, Ready, 2 Books" });
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.click(await screen.findByRole("button", { name: "Developer" }));
  fireEvent.change(screen.getByRole("combobox", { name: /Homepage Preview/ }), { target: { value: "sample" } });
  fireEvent.click(screen.getByRole("button", { name: "Close Settings" }));

  const sampleCard = document.querySelector<HTMLElement>("#world-card-sample-0")!;
  expect(sampleCard.getAttribute("aria-label")).toBe("Northern Tales, sample preview");
  expect(sampleCard.querySelector(".world-card-preview-label")?.textContent).toBe("Preview");
  expect(sampleCard.getAttribute("role")).toBeNull();
  fireEvent.click(sampleCard);
  expect(document.querySelector(".world-overview-view.is-visible")).toBeNull();
  expect(vi.mocked(fetchMock).mock.calls.some(([url]) => String(url).includes("/worlds/sample-0"))).toBe(false);
});

test("empty collection opens the same Create World page", async () => {
  records = [];
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Create World" }));
  expect(await screen.findByRole("heading", { name: "Create World" })).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("Search filters choices and Escape closes the dropdown without opening a world", async () => {
  records = [frostwake, { ...frostwake, id: "two", name: "Moon Harbor", book_count: 1 }];
  details.two = readyDetail(records[1]);
  render(<App />);
  const search = await screen.findByRole("combobox", { name: "Search worlds" });
  fireEvent.change(search, { target: { value: "Moon" } });
  expect(screen.getByRole("option", { name: "Moon Harbor" })).toBeTruthy();
  fireEvent.keyDown(search, { key: "Escape" });
  expect(search.getAttribute("aria-expanded")).toBe("false");
  expect(screen.getByRole("heading", { level: 1, name: "Frostwake" })).toBeTruthy();
});
