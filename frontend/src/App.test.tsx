// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "./App";
import type { CreationAttempt } from "./api";

const world = {
  id: "one",
  name: "Frostwake",
  created_at: "2026-01-01",
  last_used_at: null,
  artwork: "frostwake",
};
let records: unknown[];
let creationRecord: CreationAttempt | null;
beforeEach(() => {
  records = [world];
  creationRecord = null;
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const payload = url.includes("/creation")
        ? creationRecord
        : url.endsWith("/providers")
          ? {
              keys: [],
              models: [],
              defaults: { model: "gemini-embedding-2", key_id: "" },
            }
          : url.endsWith("/settings")
            ? {
                world_layout: init?.body
                  ? JSON.parse(init.body as string).world_layout
                  : "shelf",
                background_speed: init?.body
                  ? JSON.parse(init.body as string).background_speed
                  : "normal",
              }
            : init?.method === "POST"
              ? { ...world, ...JSON.parse(init.body as string) }
              : records;
      return { ok: true, json: async () => payload };
    }),
  );
});

test("pending card reopens creation and becomes a single completed card without navigation", async () => {
  creationRecord = {
    id: "pending",
    name: "Northern Tales",
    revision: 1,
    state: "paused",
    phase: "uploading",
    created_at: "",
    updated_at: "",
    message: "",
    config: { model: "gemini-embedding-2", size: 8000, search: 1000 },
    key_id: "key",
    books: [],
    books_done: 0,
    chunks_total: 0,
    chunks_done: 0,
  };
  render(<App />);
  const card = await screen.findByLabelText("Paused Northern Tales");
  fireEvent.keyDown(card, { key: "Enter" });
  expect(screen.getByRole("dialog", { name: "Northern Tales" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close creation" }));
  fireEvent.keyDown(card, { key: "Enter" });
  expect(screen.getByRole("dialog", { name: "Northern Tales" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Resume" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close creation" }));
  records = [world, { ...world, id: "pending", name: "Northern Tales" }];
  creationRecord = { ...creationRecord, state: "complete", phase: "complete" };
  await screen.findByLabelText("Preview Northern Tales", {}, { timeout: 2500 });
  expect(screen.getAllByRole("article")).toHaveLength(2);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("provider settings round trip preserves the setup step and files", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "Draft" },
  });
  fireEvent.change(screen.getByLabelText("Choose books"), {
    target: { files: [new File(["Text"], "Draft.txt")] },
  });
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  fireEvent.click(screen.getByRole("button", { name: "Manage API keys" }));
  expect(
    await screen.findByRole("heading", { name: "Providers" }),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "← Return to creation" }));
  expect(screen.getByLabelText("Maximum chunk size")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "← Back" }));
  expect(screen.getByText("Draft.txt")).toBeTruthy();
  expect((screen.getByLabelText("World name") as HTMLInputElement).value).toBe(
    "Draft",
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("search shows a dropdown without changing cards or the selected title", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.change(screen.getByLabelText("Search worlds"), {
    target: { value: "no match" },
  });
  expect(screen.getByText("No matching worlds.")).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "Frostwake", level: 1 }),
  ).toBeTruthy();
});

test("closing clears an unsubmitted name and validation error", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "New world" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  expect(screen.getByRole("alert").textContent).toContain("at least one book");
  fireEvent.click(screen.getByRole("button", { name: "Close creation" }));
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect((screen.getByLabelText("World name") as HTMLInputElement).value).toBe(
    "",
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

test("settings save speed without changing world preview", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.click(screen.getByRole("button", { name: "Developer" }));
  fireEvent.change(screen.getByLabelText(/Background transition speed/), {
    target: { value: "slow" },
  });
  await waitFor(() =>
    expect(
      (
        screen.getByLabelText(
          /Background transition speed/,
        ) as HTMLSelectElement
      ).value,
    ).toBe("slow"),
  );
  expect(
    vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "PUT"),
  ).toBe(true);
});

test("empty collection offers first-world action", async () => {
  records = [];
  render(<App />);
  await screen.findByRole("heading", { name: "Create Your First World" });
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect(screen.getByLabelText("World name")).toBeTruthy();
});

test("closing clears selected files and resets processing settings", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  const picker = document.querySelector("input[type=file]")!;
  fireEvent.change(picker, {
    target: {
      files: [new File(["Story"], "Story.txt", { type: "text/plain" })],
    },
  });
  expect(screen.getByText("Story.txt")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "Story" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  fireEvent.change(screen.getByLabelText("Maximum chunk size"), {
    target: { value: "4000" },
  });
  fireEvent.change(screen.getByLabelText("Boundary search distance"), {
    target: { value: "500" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Close creation" }));
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect(screen.queryByText("Story.txt")).toBeNull();
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "Another world" },
  });
  fireEvent.change(screen.getByLabelText("Choose books"), {
    target: { files: [new File(["New text"], "Another.txt")] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  expect(
    (screen.getByLabelText("Maximum chunk size") as HTMLInputElement).value,
  ).toBe("8000");
  expect(
    (screen.getByLabelText("Boundary search distance") as HTMLInputElement)
      .value,
  ).toBe("1000");
});

test("failed settings save retains the saved preference", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  vi.mocked(fetch).mockResolvedValueOnce({
    ok: false,
    json: async () => ({ detail: "Unavailable" }),
  } as Response);
  fireEvent.click(screen.getByRole("button", { name: "Developer" }));
  fireEvent.change(screen.getByLabelText(/Background transition speed/), {
    target: { value: "slow" },
  });
  await screen.findByText("Your setting could not be saved. Please try again.");
  expect(
    (screen.getByLabelText(/Background transition speed/) as HTMLSelectElement)
      .value,
  ).toBe("normal");
});

test("Developer collection previews never mutate saved worlds", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.click(screen.getByRole("button", { name: "Developer" }));
  fireEvent.change(screen.getByLabelText(/Homepage preview/), {
    target: { value: "sample" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Worlds" }));
  expect(screen.getAllByRole("article")).toHaveLength(12);
  fireEvent.change(screen.getByLabelText("Search worlds"), {
    target: { value: "harbor" },
  });
  expect(screen.getAllByRole("article")).toHaveLength(12);
  expect(screen.getAllByRole("option")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.change(screen.getByLabelText(/Homepage preview/), {
    target: { value: "empty" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Worlds" }));
  expect(
    screen.getByRole("heading", { name: "Create Your First World" }),
  ).toBeTruthy();
  expect(screen.queryByText("Your Worlds")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.change(screen.getByLabelText(/Homepage preview/), {
    target: { value: "saved" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Worlds" }));
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByLabelText("Preview Frostwake")).toBeTruthy();
  expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.method)).toBe(
    true,
  );
});

test("hovering and keyboard-browsing search results do not change the preview", async () => {
  records = [world, { ...world, id: "two", name: "Moon Harbor" }];
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  const search = screen.getByRole("combobox", { name: "Search worlds" });
  fireEvent.change(search, { target: { value: "Moon" } });
  fireEvent.mouseEnter(screen.getByRole("option", { name: "Moon Harbor" }));
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    "Frostwake",
  );
  expect(screen.getAllByRole("article")).toHaveLength(2);
  fireEvent.keyDown(search, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
});

test("world display saves and switches the collection layout", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  expect(document.querySelector(".world-shelf")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.change(screen.getByLabelText(/World display/), {
    target: { value: "grid" },
  });
  await waitFor(() =>
    expect(
      (screen.getByLabelText(/World display/) as HTMLSelectElement).value,
    ).toBe("grid"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Worlds" }));
  expect(document.querySelector(".world-shelf")).toBeNull();
});

test.each([false, true])(
  "shelf respects reduced motion (%s) and leaves browser zoom alone",
  async (reducedMotion) => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: reducedMotion })),
    );
    render(<App />);
    await screen.findByLabelText("Preview Frostwake");
    const shelf = document.querySelector(".world-shelf") as HTMLElement;
    Object.defineProperty(shelf, "scrollWidth", { value: 1800 });
    Object.defineProperty(shelf, "clientWidth", { value: 800 });
    shelf.scrollTo = vi.fn((options?: ScrollToOptions | number) => {
      shelf.scrollLeft =
        typeof options === "number" ? options : (options?.left ?? 0);
    });
    const home = document.querySelector(".worlds-view")!;
    const wheel = new WheelEvent("wheel", {
      deltaY: 120,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(home, wheel);
    expect(shelf.scrollLeft).toBe(180);
    expect(wheel.defaultPrevented).toBe(true);
    expect(shelf.scrollTo).toHaveBeenLastCalledWith({
      left: 180,
      behavior: reducedMotion ? "instant" : "smooth",
    });
    fireEvent.wheel(home, { deltaY: 2, deltaMode: 1 });
    expect(shelf.scrollLeft).toBe(252);
    fireEvent.wheel(home, { deltaY: 120, ctrlKey: true });
    expect(shelf.scrollLeft).toBe(252);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.wheel(home, { deltaY: 120 });
    expect(shelf.scrollLeft).toBe(252);
  },
);
