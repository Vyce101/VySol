// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api, type ChronicleSettings } from "./api";
import { ChronicleSettingsDrawer } from "./ChronicleSettingsDrawer";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

test("shows supported chat models before an API connection is enabled", async () => {
  vi.mocked(api).mockResolvedValue({
    keys: [],
    connections: [],
    models: [],
    chat_models: [
      { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", provider: "google", series: "Flash" },
      { id: "gemini-3.5-flash-lite", name: "Gemini 3.5 Flash-Lite", provider: "google", series: "Flash Lite" },
      { id: "gemma-4-31b-it", name: "Gemma 4 31B IT", provider: "google", series: "Gemma" },
    ],
    defaults: { model: "gemini-3.8-flash", key_id: "" },
  } as never);
  const settings: ChronicleSettings = {
    model: "gemini-3.8-flash", key_id: "", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };

  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click((await screen.findByText("Gemini 3.8 Flash")).closest("button")!);
  expect(screen.getByRole("option", { name: "Gemini 3.8 Flash" })).toBeTruthy();
  expect(screen.getByRole("option", { name: "Gemini 3.5 Flash-Lite" })).toBeTruthy();
  expect(screen.getByRole("option", { name: "Gemma 4 31B IT" })).toBeTruthy();
  expect(screen.getByRole("listbox", { name: "Chat Model" }).closest(".chronicle-settings-section")?.classList.contains("has-open-select-menu")).toBe(true);
});

test("closes the model menu when a different setting is clicked and hides save confirmations", async () => {
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "key-1", name: "Default Key", provider: "google", connection_id: "google" }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [],
    chat_models: [
      { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", provider: "google", series: "Flash" },
    ],
    defaults: { model: "gemini-3.8-flash", key_id: "" },
  } as never);
  const settings: ChronicleSettings = {
    model: "gemini-3.8-flash", key_id: "", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };

  render(<ChronicleSettingsDrawer open settings={settings} saveState="saved" onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  const modelButton = (await screen.findByText("Gemini 3.8 Flash")).closest("button")!;
  fireEvent.click(modelButton);
  fireEvent.pointerDown(screen.getByText("Flash", { exact: true }));
  expect(screen.getByRole("listbox", { name: "Chat Model" })).toBeTruthy();

  const connectionButton = screen.getByText("Select a connection").closest("button")!;
  fireEvent.click(screen.getByText("API Connection", { exact: true }));
  expect(connectionButton.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("listbox", { name: "API Connection" })).toBeNull();
  fireEvent.pointerDown(connectionButton);
  fireEvent.click(connectionButton);
  expect(screen.queryByRole("listbox", { name: "Chat Model" })).toBeNull();
  expect(connectionButton.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(modelButton);
  fireEvent.pointerDown(screen.getByText("Chat Model"));
  expect(screen.queryByRole("listbox", { name: "Chat Model" })).toBeNull();
  expect(screen.queryByText("Saving changes…")).toBeNull();
  expect(screen.queryByText("Changes saved")).toBeNull();
});

test("refreshes API connections whenever the drawer reopens", async () => {
  const initialProviders = {
    keys: [{ id: "key-1", name: "First Key", provider: "google", connection_id: "google" }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    chat_models: [], models: [], defaults: { model: "", key_id: "" },
  };
  const refreshedProviders = {
    ...initialProviders,
    keys: [...initialProviders.keys, { id: "key-2", name: "New Key", provider: "google", connection_id: "google" }],
  };
  vi.mocked(api).mockResolvedValueOnce(initialProviders as never).mockResolvedValueOnce(refreshedProviders as never);
  const settings: ChronicleSettings = {
    model: "", key_id: "", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };

  const view = render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledTimes(1));
  view.rerender(<ChronicleSettingsDrawer open={false} settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  view.rerender(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledTimes(2));

  fireEvent.click(screen.getByText("Select a connection").closest("button")!);
  expect(await screen.findByRole("option", { name: /New Key/ })).toBeTruthy();
});
