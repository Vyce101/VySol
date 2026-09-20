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

const world = {
  id: "one",
  name: "Frostwake",
  created_at: "2026-01-01",
  last_used_at: null,
  artwork: "frostwake",
};
let records: unknown[];
beforeEach(() => {
  records = [world];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const payload = url.endsWith("/settings")
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

test("draft survives tabs and empty world creation succeeds", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect(screen.queryByLabelText("Search worlds")).toBeNull();
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "New world" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Worlds" }));
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect((screen.getByLabelText("World name") as HTMLInputElement).value).toBe(
    "New world",
  );
  fireEvent.submit(screen.getByLabelText("World name").closest("form")!);
  await screen.findByLabelText("Preview New world");
  expect(
    screen.getByRole("button", { name: "Worlds" }).getAttribute("aria-current"),
  ).toBe("page");
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
  fireEvent.click(screen.getAllByRole("button", { name: "Create World" })[1]);
  expect(screen.getByLabelText("World name")).toBeTruthy();
});

test("selected files survive clearing the native picker and tab navigation", async () => {
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
  fireEvent.click(screen.getByRole("button", { name: "Worlds" }));
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect(screen.getByText("Story.txt")).toBeTruthy();
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

test("wheel scrolls the shelf from the homepage and leaves browser zoom alone", async () => {
  render(<App />);
  await screen.findByLabelText("Preview Frostwake");
  const shelf = document.querySelector(".world-shelf") as HTMLElement;
  Object.defineProperty(shelf, "scrollWidth", { value: 1800 });
  Object.defineProperty(shelf, "clientWidth", { value: 800 });
  shelf.scrollTo = vi.fn((options?: ScrollToOptions | number) => {
    shelf.scrollLeft = typeof options === "number" ? options : options?.left ?? 0;
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
    behavior: "smooth",
  });
  fireEvent.wheel(home, { deltaY: 2, deltaMode: 1 });
  expect(shelf.scrollLeft).toBe(252);
  fireEvent.wheel(home, { deltaY: 120, ctrlKey: true });
  expect(shelf.scrollLeft).toBe(252);
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  fireEvent.wheel(home, { deltaY: 120 });
  expect(shelf.scrollLeft).toBe(252);
});
