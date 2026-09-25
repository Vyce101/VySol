// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api, streamChronicleMessage, type ChronicleMessage, type ChronicleSettings, type ChronicleStreamEvent } from "./api";
import { ChronicleChat } from "./ChronicleChat";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
  streamChronicleMessage: vi.fn(),
}));

const settingsBase: ChronicleSettings = {
  model: "gemini-3.8-flash",
  key_id: "11111111-1111-4111-8111-111111111111",
  chunk_count: 3,
  minimum_similarity: 0.6,
  chunk_overlap: 150,
  streaming_speed: 0,
  chat_history_prefix: "<chat_history>",
  chat_history_suffix: "</chat_history>",
  rag_chunks_prefix: "<rag_chunks>",
  rag_chunks_suffix: "</rag_chunks>",
  sections: { ai: true, retrieval: true, response: true, section_tags: true },
};

const providers = {
  keys: [{ id: settingsBase.key_id, name: "Default Key", provider: "google", connection_id: "google" }],
  connections: [{ id: "google", provider: "google", enabled: true }],
  chat_models: [{ id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", provider: "google", series: "Flash" }],
  models: [],
  defaults: { model: settingsBase.model, key_id: settingsBase.key_id },
};

const userMessage: ChronicleMessage = {
  id: "user-message-1",
  role: "user",
  text: "I look at the map.",
  thinking: null,
  created_at: "2026-06-10T10:00:00Z",
  status: "complete",
};

let currentSettings: ChronicleSettings;
let history: ChronicleMessage[];
let eventHandler: ((event: ChronicleStreamEvent) => void) | null;
let resolveStream: (() => void) | null;
let callOrder: string[];

beforeEach(() => {
  vi.mocked(api).mockClear();
  vi.mocked(streamChronicleMessage).mockClear();
  currentSettings = { ...settingsBase, sections: { ...settingsBase.sections } };
  history = [];
  eventHandler = null;
  resolveStream = null;
  callOrder = [];
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/chronicle-settings" && init?.method === "PUT") {
      currentSettings = JSON.parse(String(init.body)) as ChronicleSettings;
      callOrder.push("save-settings");
      return currentSettings as never;
    }
    if (path === "/chronicle-settings") return currentSettings as never;
    if (path === "/providers") return providers as never;
    if (path.endsWith("/messages")) return history as never;
    if (path.includes("/generations/") && path.endsWith("/stop")) {
      const answer: ChronicleMessage = {
        id: "assistant-message-1",
        role: "assistant",
        text: "The response was saved before stopping.",
        thinking: null,
        created_at: "2026-06-10T10:00:01Z",
        status: "stopped",
      };
      history = [userMessage, answer];
      return { stopped: true, status: "stopped", message: answer } as never;
    }
    return undefined as never;
  });
  vi.mocked(streamChronicleMessage).mockImplementation((_id, _request, _text, onEvent, signal) => {
    callOrder.push("stream");
    eventHandler = onEvent;
    return new Promise<void>((resolve, reject) => {
      resolveStream = resolve;
      signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    });
  });
});

afterEach(cleanup);

function emit(event: ChronicleStreamEvent) {
  if (!eventHandler) throw new Error("The response stream has not started.");
  act(() => eventHandler?.(event));
}

function renderChat() {
  return render(<ChronicleChat visible worldId="world-1" worldName="Frostwake" chronicleId="chronicle-1" chronicleName="A New Chronicle" />);
}

test("opens thinking as it arrives, freezes the send-time reveal speed, and saves shared drawer state before sending", async () => {
  renderChat();
  await screen.findByRole("heading", { name: "Frostwake" });

  fireEvent.click(screen.getByRole("button", { name: "Open Settings" }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith("/providers"));
  fireEvent.click(screen.getByRole("button", { name: "AI" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Close Settings" }).at(-1)!);

  fireEvent.change(screen.getByRole("textbox", { name: "What do you do?" }), { target: { value: "I look at the map." } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(eventHandler).toBeTruthy());
  expect(callOrder.slice(0, 2)).toEqual(["save-settings", "stream"]);
  expect(currentSettings.sections.ai).toBe(false);

  emit({ type: "user_message", message: userMessage });
  emit({ type: "thinking_delta", text: "Check the supplies first." });
  expect(screen.getByText("Check the supplies first.")).toBeTruthy();
  emit({ type: "answer_delta", text: "A measured reply." });
  expect(screen.queryByText("A measured reply.")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Open Settings" }));
  const speed = screen.getByRole("slider", { name: "Streaming speed" });
  fireEvent.change(speed, { target: { value: "100" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Close Settings" }).at(-1)!);
  expect(screen.queryByText("A measured reply.")).toBeNull();

  const assistant: ChronicleMessage = {
    id: "assistant-message-1",
    role: "assistant",
    text: "A measured reply.",
    thinking: "Check the supplies first.",
    created_at: "2026-06-10T10:00:01Z",
    status: "complete",
  };
  history = [userMessage, assistant];
  emit({ type: "completed", message: assistant });
  expect(await screen.findByText("A measured reply.")).toBeTruthy();
  resolveStream?.();
});

test("Stop preserves the partial answer and does not add an interruption label", async () => {
  currentSettings = { ...currentSettings, streaming_speed: 100 };
  renderChat();
  await screen.findByRole("heading", { name: "Frostwake" });

  fireEvent.change(screen.getByRole("textbox", { name: "What do you do?" }), { target: { value: "Continue." } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(eventHandler).toBeTruthy());
  emit({ type: "answer_delta", text: "The response was saved before stopping." });
  expect(screen.getByText("The response was saved before stopping.")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Stop response" }));

  expect(await screen.findByText("The response was saved before stopping.")).toBeTruthy();
  expect(screen.queryByText("Partial response")).toBeNull();
  expect(await screen.findByRole("button", { name: "Send message" })).toBeTruthy();
  resolveStream?.();
});

test("Stop during the local reveal tail shows the completed answer without calling the provider stop endpoint", async () => {
  currentSettings = { ...currentSettings, streaming_speed: 25 };
  renderChat();
  await screen.findByRole("heading", { name: "Frostwake" });

  fireEvent.change(screen.getByRole("textbox", { name: "What do you do?" }), { target: { value: "Continue." } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(eventHandler).toBeTruthy());
  emit({ type: "answer_delta", text: "The complete reply is still revealing." });
  const assistant: ChronicleMessage = {
    id: "assistant-message-2",
    role: "assistant",
    text: "The complete reply is still revealing.",
    thinking: null,
    created_at: "2026-06-10T10:00:01Z",
    status: "complete",
  };
  history = [userMessage, assistant];
  emit({ type: "completed", message: assistant });

  fireEvent.click(screen.getByRole("button", { name: "Stop response" }));

  expect(await screen.findByText("The complete reply is still revealing.")).toBeTruthy();
  expect(vi.mocked(api)).not.toHaveBeenCalledWith(expect.stringContaining("/generations/"), expect.objectContaining({ method: "POST" }));
  resolveStream?.();
});

test("keeps the chat layout while loading and lets the user draft during generation", async () => {
  let resolveHistory: ((value: ChronicleMessage[]) => void) | undefined;
  const originalApi = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, init) => {
    if (path.endsWith("/messages")) return new Promise<ChronicleMessage[]>((resolve) => { resolveHistory = resolve; }) as never;
    return originalApi(path, init);
  });
  renderChat();

  expect(screen.getByRole("heading", { name: "Frostwake" })).toBeTruthy();
  expect(screen.getByRole("textbox", { name: "What do you do?" })).toBeTruthy();
  expect(screen.getByRole("status", { name: "" }).textContent).toContain("Loading messages");
  await act(async () => resolveHistory?.([]));
  expect(screen.queryByText("Loading messages…")).toBeNull();

  const composer = screen.getByRole("textbox", { name: "What do you do?" }) as HTMLTextAreaElement;
  fireEvent.change(composer, { target: { value: "Start the scene." } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(eventHandler).toBeTruthy());
  expect(document.activeElement).toBe(composer);
  fireEvent.change(composer, { target: { value: "My next action." } });
  fireEvent.keyDown(composer, { key: "Enter" });
  expect(composer.value).toBe("My next action.");
  expect(vi.mocked(streamChronicleMessage)).toHaveBeenCalledTimes(1);
});

test("keeps an unsent draft with its Chronicle while switching between chats", async () => {
  const { rerender } = render(<ChronicleChat visible worldId="world-1" worldName="Frostwake" chronicleId="chronicle-1" chronicleName="First Chronicle" />);
  await screen.findByRole("heading", { name: "First Chronicle" });
  const composer = screen.getByRole("textbox", { name: "What do you do?" });
  fireEvent.change(composer, { target: { value: "First Chronicle draft." } });

  rerender(<ChronicleChat visible worldId="world-1" worldName="Frostwake" chronicleId="chronicle-2" chronicleName="Second Chronicle" />);
  await screen.findByRole("heading", { name: "Second Chronicle" });
  expect((screen.getByRole("textbox", { name: "What do you do?" }) as HTMLTextAreaElement).value).toBe("");
  fireEvent.change(screen.getByRole("textbox", { name: "What do you do?" }), { target: { value: "Second Chronicle draft." } });

  rerender(<ChronicleChat visible worldId="world-1" worldName="Frostwake" chronicleId="chronicle-1" chronicleName="First Chronicle" />);
  await screen.findByRole("heading", { name: "First Chronicle" });
  expect((screen.getByRole("textbox", { name: "What do you do?" }) as HTMLTextAreaElement).value).toBe("First Chronicle draft.");
});

test("caps long drafts and shrinks the composer after editing or sending", async () => {
  renderChat();
  await waitFor(() => expect(screen.queryByText("Loading messages…")).toBeNull());
  const composer = screen.getByRole("textbox", { name: "What do you do?" }) as HTMLTextAreaElement;
  composer.style.maxHeight = "120px";
  Object.defineProperty(composer, "scrollHeight", {
    configurable: true,
    get: () => 38 + (composer.value.split("\n").length - 1) * 23,
  });

  const longDraft = Array.from({ length: 10 }, (_, index) => `Line ${index + 1}`).join("\n");
  fireEvent.change(composer, { target: { value: longDraft } });
  expect(composer.style.height).toBe("120px");
  expect(composer.style.overflowY).toBe("auto");

  fireEvent.change(composer, { target: { value: "Short draft" } });
  expect(composer.style.height).toBe("38px");
  expect(composer.style.overflowY).toBe("hidden");

  fireEvent.change(composer, { target: { value: longDraft } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  expect(composer.value).toBe("");
  expect(composer.style.height).toBe("38px");
  expect(composer.style.overflowY).toBe("hidden");
});
