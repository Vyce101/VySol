// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SettingsView } from "./SettingsView";
import { api } from "./api";

vi.mock("./api", async () => ({
  ...(await vi.importActual("./api")),
  api: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function renderSettings(overrides: Partial<Parameters<typeof SettingsView>[0]> = {}) {
  const onSaved = vi.fn();
  const onCollectionPreview = vi.fn();
  render(
    <SettingsView
      visible
      speed="normal"
      layout="shelf"
      chatAppearance="focused"
      onSaved={onSaved}
      collectionPreview="saved"
      onCollectionPreview={onCollectionPreview}
      {...overrides}
    />,
  );
  return { onSaved, onCollectionPreview };
}

test("shows General controls, four Developer previews, and AI Connections without descriptions", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/providers")
      return { keys: [], connections: [] } as never;
    throw new Error(`Unexpected request ${path}`);
  });
  const { onCollectionPreview } = renderSettings();

  expect(screen.getByRole("heading", { name: "Settings" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "General" })).toBeTruthy();
  expect(screen.getByLabelText(/World Display/).textContent).toContain("Shelf");
  expect(screen.getByLabelText(/Background Transition Speed/)).toBeTruthy();
  expect(screen.getByLabelText(/Chronicle Chat Appearance/)).toBeTruthy();
  expect(screen.queryByText(/Tailor VySol|Motion|Reduced/)).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Developer" }));
  const preview = screen.getByLabelText(/Homepage Preview/) as HTMLSelectElement;
  expect(Array.from(preview.options).map((option) => option.value)).toEqual([
    "saved",
    "four",
    "sample",
    "empty",
  ]);
  fireEvent.change(preview, { target: { value: "empty" } });
  expect(onCollectionPreview).toHaveBeenCalledWith("empty");

  fireEvent.click(screen.getByRole("button", { name: "AI Connections" }));
  expect(
    await screen.findByRole("heading", { name: "AI Connections" }),
  ).toBeTruthy();
  expect(
    screen.queryByText(/Connect and manage the AI providers/),
  ).toBeNull();
  expect(
    screen.queryByText(/Manage the AI services VySol uses/),
  ).toBeNull();
  expect(await screen.findByRole("button", { name: "Select Connections" })).toBeTruthy();
});

test("saves General preferences", async () => {
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (path === "/settings" && request) return JSON.parse(request.body as string);
    throw new Error(`Unexpected request ${path}`);
  });
  const { onSaved } = renderSettings();

  fireEvent.change(screen.getByLabelText(/Background Transition Speed/), {
    target: { value: "fast" },
  });
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    "/settings",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ background_speed: "fast", world_layout: "shelf", chat_appearance: "focused" }),
    }),
  );
  expect(onSaved).toHaveBeenCalledWith({
    background_speed: "fast",
    world_layout: "shelf",
    chat_appearance: "focused",
  });

  fireEvent.change(screen.getByLabelText(/Chronicle Chat Appearance/), {
    target: { value: "full_overlay" },
  });
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2));
  expect(onSaved).toHaveBeenLastCalledWith({
    background_speed: "normal",
    world_layout: "shelf",
    chat_appearance: "full_overlay",
  });

});
