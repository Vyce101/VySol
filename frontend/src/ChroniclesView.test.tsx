// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "./api";
import { ChroniclesView } from "./ChroniclesView";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));

const row = (id: string, title: string, preview = "No messages yet") => ({
  id,
  world_id: "world-1",
  title,
  created_at: "2026-06-10T10:00:00Z",
  last_message_at: null,
  message_count: 0,
  preview,
  not_started: true,
});

let items: ReturnType<typeof row>[];
let created: ReturnType<typeof row>;

beforeEach(() => {
  items = [row("chronicle-1", "Café by the Sea"), row("chronicle-2", "The Northern Road")];
  created = row("chronicle-3", "New Chronicle");
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/worlds/world-1/chronicles" && init?.method === "POST") {
      items = [created, ...items];
      return created as never;
    }
    if (path === "/worlds/world-1/chronicles") return items as never;
    return undefined as never;
  });
});

afterEach(cleanup);

test("creates a Chronicle at the top of the list without opening it", async () => {
  const onOpenChronicle = vi.fn();
  render(<ChroniclesView visible worldId="world-1" worldName="Frostwake" isWorldReady onOpenChronicle={onOpenChronicle} />);

  const list = await screen.findByLabelText("Frostwake Chronicles");
  fireEvent.click(screen.getByRole("button", { name: "New Chronicle" }));

  expect(await within(list).findByText("New Chronicle")).toBeTruthy();
  expect(list.firstElementChild?.textContent).toContain("New Chronicle");
  const createdRow = within(list).getByText("New Chronicle").closest("article");
  expect(createdRow).not.toBeNull();
  expect(within(createdRow!).getByText("No messages yet")).toBeTruthy();
  expect(within(createdRow!).getByText("Not started")).toBeTruthy();
  expect(within(createdRow!).getByText("0 messages")).toBeTruthy();
  expect(onOpenChronicle).not.toHaveBeenCalled();
  expect(vi.mocked(api)).toHaveBeenCalledWith("/worlds/world-1/chronicles", expect.objectContaining({ method: "POST" }));
});

test("filters Chronicle names with accent insensitive matching", async () => {
  render(<ChroniclesView visible worldId="world-1" worldName="Frostwake" isWorldReady onOpenChronicle={vi.fn()} />);
  await screen.findByText("Café by the Sea");

  fireEvent.change(screen.getByRole("searchbox", { name: "Search Chronicles" }), { target: { value: "cafe" } });

  expect(await screen.findByText("Café by the Sea")).toBeTruthy();
  await waitFor(() => expect(screen.queryByText("The Northern Road")).toBeNull());
});

test("does not bring a removed row back on the next search character", async () => {
  render(<ChroniclesView visible worldId="world-1" worldName="Frostwake" isWorldReady onOpenChronicle={vi.fn()} />);
  await screen.findByText("Café by the Sea");

  const search = screen.getByRole("searchbox", { name: "Search Chronicles" });
  fireEvent.change(search, { target: { value: "no" } });
  fireEvent.change(search, { target: { value: "nor" } });

  expect(screen.queryByText("Café by the Sea")).toBeNull();
  expect(screen.getByText("The Northern Road")).toBeTruthy();
});

test("keeps an unfinished World's Chronicle on the list and explains why chat is unavailable", async () => {
  const onPendingChronicleAttempt = vi.fn();
  const onOpenChronicle = vi.fn();
  render(<ChroniclesView visible worldId="world-1" worldName="Frostwake" isWorldReady={false} onOpenChronicle={onOpenChronicle} onPendingChronicleAttempt={onPendingChronicleAttempt} />);
  const title = await screen.findByText("Café by the Sea");

  fireEvent.click(title.closest("article")!.querySelector(".chronicle-row-main")!);

  expect(screen.getByRole("status").textContent).toContain("completed book embeddings");
  expect(onPendingChronicleAttempt).toHaveBeenCalledOnce();
  expect(onOpenChronicle).not.toHaveBeenCalled();
});

test("keeps the Chronicle preview, status, count, and menu in place while renaming", async () => {
  render(<ChroniclesView visible worldId="world-1" worldName="Frostwake" isWorldReady onOpenChronicle={vi.fn()} />);
  const title = await screen.findByText("Café by the Sea");
  const row = title.closest("article")!;

  fireEvent.click(within(row).getByRole("button", { name: "Options for Café by the Sea" }));
  fireEvent.click(within(row).getByRole("menuitem", { name: "Rename" }));

  const renameForm = row.querySelector<HTMLFormElement>(".chronicle-rename-form")!;
  expect(renameForm.classList.contains("chronicle-row-main")).toBe(true);
  expect(renameForm.querySelector(".chronicle-preview")?.textContent).toBe("No messages yet");
  expect(row.children[1].classList.contains("chronicle-row-meta")).toBe(true);
  expect(row.children[2].classList.contains("chronicle-menu-anchor")).toBe(true);
  expect(within(row).getByText("Not started")).toBeTruthy();
  expect(within(row).getByText("0 messages")).toBeTruthy();
});

test("clears the unfinished World notice after leaving Chronicles", async () => {
  const props = { worldId: "world-1", worldName: "Frostwake", isWorldReady: false, onOpenChronicle: vi.fn() };
  const view = render(<ChroniclesView visible {...props} />);
  const title = await screen.findByText("Café by the Sea");
  fireEvent.click(title.closest("article")!.querySelector(".chronicle-row-main")!);
  expect(screen.getByText(/Chat needs completed book embeddings/)).toBeTruthy();

  view.rerender(<ChroniclesView visible={false} {...props} />);
  view.rerender(<ChroniclesView visible {...props} />);
  expect(screen.queryByText(/Chat needs completed book embeddings/)).toBeNull();
});
