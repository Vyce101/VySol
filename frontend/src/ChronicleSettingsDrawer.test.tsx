// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api, type ChronicleSettings } from "./api";
import { ChronicleSettingsDrawer } from "./ChronicleSettingsDrawer";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));

afterEach(() => { cleanup(); window.localStorage.clear(); vi.resetAllMocks(); });

test("shows discovered chat models for the selected connection", async () => {
  const chatModels = [
    { id: "gemini-3.9-flash", name: "Gemini 3.9 Flash", provider: "google", series: "Flash", tested: false, capabilities: { chat: true } },
    { id: "gemini-3.7-flash", name: "Gemini 3.7 Flash", provider: "google", series: "Flash", tested: true, capabilities: { chat: true } },
    { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", provider: "google", series: "Flash", tested: true, capabilities: { chat: true } },
    { id: "gemini-3.5-flash-lite", name: "Gemini 3.5 Flash-Lite", provider: "google", series: "Flash Lite", tested: false, capabilities: { chat: true } },
    { id: "gemini-2.5-flash-lite", name: "Gemini 2.5 Flash-Lite", provider: "google", series: "Flash Lite", tested: true, capabilities: { chat: true } },
    { id: "gemini-4-flash-lite", name: "Gemini 4 Flash-Lite", provider: "google", series: "Flash Lite", tested: true, capabilities: { chat: true } },
    { id: "gemma-4-31b-it", name: "Gemma 4 31B IT", provider: "google", series: "Gemma", tested: false, capabilities: { chat: true } },
    { id: "gemini-3-pro-preview", name: "Gemini 3 Pro Preview", provider: "google", series: "Pro", tested: true, capabilities: { chat: true } },
    { id: "gemini-3.8-flash-tts", name: "Gemini 3.8 Flash TTS", provider: "google", series: "Flash", tested: true, capabilities: { chat: false } },
    { id: "gpt-4o", name: "GPT-4o", provider: "openai", series: "GPT", tested: true, capabilities: { chat: false } },
  ];
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "key-1", name: "Google Key", provider: "google", connection_id: "google", models: chatModels }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [],
    chat_models: chatModels,
    defaults: { model: "gemini-3.8-flash", key_id: "key-1" },
  } as never);
  const settings: ChronicleSettings = {
    model: "gemini-3.8-flash", key_id: "key-1", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };

  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click((await screen.findByText("Gemini 3.8 Flash")).closest("button")!);
  expect(screen.getByRole("option", { name: "Gemini 3.8 Flash" })).toBeTruthy();
  expect(screen.getByRole("option", { name: /Gemini 3.5 Flash-Lite/ })).toBeTruthy();
  expect(screen.getByRole("option", { name: /Gemma 4 31B IT/ })).toBeTruthy();
  expect(screen.queryByRole("option", { name: /TTS|GPT-4o/ })).toBeNull();
  expect(screen.getAllByText("Untested").length).toBeGreaterThan(0);
  expect([...screen.getByRole("listbox", { name: "Chat Model" }).querySelectorAll(".chronicle-model-group > span")].map((heading) => heading.textContent)).toEqual([
    "Google", "Untested",
  ]);
  expect(within(screen.getByRole("listbox", { name: "Chat Model" })).getAllByRole("option").map((option) => option.textContent?.trim())).toEqual([
    "Gemini 3 Pro Preview",
    "Gemini 3.8 Flash",
    "Gemini 3.7 Flash",
    "Gemini 4 Flash-Lite",
    "Gemini 2.5 Flash-Lite",
    "Gemini 3.5 Flash-LiteUntested",
    "Gemini 3.9 FlashUntested",
    "Gemma 4 31B ITUntested",
  ]);
  expect(screen.getByRole("listbox", { name: "Chat Model" }).closest(".chronicle-settings-section")?.classList.contains("has-open-select-menu")).toBe(true);
});

test("groups models by provider, keeps Untested models last, and orders GPT-6 variants explicitly", async () => {
  const chatModels = [
    { id: "gpt-6-luna", name: "GPT-6 Luna", provider: "openai", series: "GPT", tested: true, capabilities: { chat: true } },
    { id: "gpt-6-terra", name: "GPT-6 Terra", provider: "openai", series: "GPT", tested: true, capabilities: { chat: true } },
    { id: "gpt-6-sol", name: "GPT-6 Sol", provider: "openai", series: "GPT", tested: true, capabilities: { chat: true } },
    { id: "gpt-6-astra", name: "GPT-6 Astra", provider: "openai", series: "GPT", tested: true, capabilities: { chat: true } },
    { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", provider: "deepseek", series: "DeepSeek Pro", tested: true, capabilities: { chat: true } },
    { id: "deepseek-flash", name: "DeepSeek V4.1 Flash", provider: "deepseek", series: "Flash", tested: true, capabilities: { chat: true } },
    { id: "gemini-4-flash", name: "Gemini 4 Flash", provider: "google", series: "Flash", tested: false, capabilities: { chat: true } },
  ];
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "openai-key", name: "Work", provider: "openai", connection_id: "openai", models: chatModels }],
    connections: [{ id: "openai", provider: "openai", enabled: true }],
    models: chatModels, chat_models: chatModels, defaults: { model: "gpt-6-astra", key_id: "openai-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: "gpt-6-astra", key_id: "openai-key", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  const { container } = render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click((await screen.findByText("GPT-6 Astra")).closest("button")!);
  const listbox = screen.getByRole("listbox", { name: "Chat Model" });
  expect([...listbox.querySelectorAll(".chronicle-model-group > span")].map((heading) => heading.textContent)).toEqual([
    "DeepSeek", "OpenAI", "Untested",
  ]);
  expect(listbox.querySelector(":scope > .chronicle-model-search + .chronicle-model-menu-list")).toBeTruthy();
  expect(within(listbox).getAllByRole("option").map((option) => option.textContent?.trim())).toEqual([
    "DeepSeek V4 Pro",
    "DeepSeek V4.1 Flash",
    "GPT-6 Astra",
    "GPT-6 Sol",
    "GPT-6 Terra",
    "GPT-6 Luna",
    "Gemini 4 FlashUntested",
  ]);
  expect(container.querySelector("img")).toBeNull();
});

test("orders OpenAI generations and variants from strongest to weakest and hides the duplicate GPT-5.6 alias", async () => {
  const ids = [
    "o3", "gpt-4.1-mini", "gpt-5-nano", "gpt-5-mini", "gpt-5", "gpt-5-pro",
    "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4", "gpt-5.4-pro",
    "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6",
    "gpt-6-luna", "gpt-6-terra", "gpt-6-sol", "gpt-6-astra", "gpt-4.1", "o3-pro",
  ];
  const chatModels = ids.map((id) => ({
    id,
    name: id.replace("gpt", "Gpt").replaceAll("-", " "),
    provider: "openai",
    series: id.startsWith("o") ? "o Series" : "GPT",
    tested: true,
    capabilities: { chat: true },
  }));
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "openai-key", name: "Work", provider: "openai", connection_id: "openai", models: chatModels }],
    connections: [{ id: "openai", provider: "openai", enabled: true }],
    models: chatModels, chat_models: chatModels, defaults: { model: "gpt-6-astra", key_id: "openai-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: "gpt-6-astra", key_id: "openai-key", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click((await screen.findByText("GPT 6 astra")).closest("button")!);

  expect(within(screen.getByRole("listbox", { name: "Chat Model" })).getAllByRole("option").map((option) => option.textContent?.trim())).toEqual([
    "GPT 6 astra", "GPT 6 sol", "GPT 6 terra", "GPT 6 luna",
    "GPT 5.6 sol", "GPT 5.6 terra", "GPT 5.6 luna",
    "GPT 5.4 pro", "GPT 5.4", "GPT 5.4 mini", "GPT 5.4 nano",
    "GPT 5 pro", "GPT 5", "GPT 5 mini", "GPT 5 nano",
    "GPT 4.1", "GPT 4.1 mini", "o3 pro", "o3",
  ]);
});

test("places the selected check before the Untested label and shows provider defaults for unknown controls", async () => {
  const model = {
    id: "future-model", name: "Future Model", provider: "google", tested: false, capability_source: "unknown",
    capabilities: { chat: true, output_limit: null, thinking_levels: null, thinking_budget: null },
  };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "google-key", name: "Work", provider: "google", connection_id: "google", models: [model] }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: model.id, key_id: "google-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: model.id, key_id: "google-key", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  fireEvent.click((await screen.findByText("Future Model")).closest("button")!);
  const option = screen.getByRole("option", { name: /Future Model, Untested/ });
  expect([...option.children].map((child) => child.classList.contains("chronicle-untested-label") ? "label" : child.tagName)).toEqual(["SPAN", "svg", "label"]);
  expect((screen.getByLabelText("Output Limit") as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText("Thinking") as HTMLSelectElement).value).toBe("default");
});

test("opens the model list scrolled to its selected model", async () => {
  const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
  const scrollIntoView = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
  try {
    const model = { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", provider: "google", series: "Flash", tested: true, capabilities: { chat: true } };
    vi.mocked(api).mockResolvedValue({
      keys: [{ id: "google-key", name: "Work", provider: "google", connection_id: "google", models: [model] }],
      connections: [{ id: "google", provider: "google", enabled: true }],
      models: [model], chat_models: [model], defaults: { model: model.id, key_id: "google-key" },
    } as never);
    const settings: ChronicleSettings = {
      model: model.id, key_id: "google-key", chunk_count: 3, minimum_similarity: 0.6,
      chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
      chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
      rag_chunks_suffix: "</rag_chunks>",
      sections: { ai: true, retrieval: true, response: true, section_tags: true },
    };
    render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click((await screen.findByText(model.name)).closest("button")!);
    expect(await screen.findByRole("listbox", { name: "Chat Model" })).toBeTruthy();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  } finally {
    if (descriptor) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", descriptor);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});

test("closes the model menu when a different setting is clicked and hides save confirmations", async () => {
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "key-1", name: "Default Key", provider: "google", connection_id: "google" }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [],
    chat_models: [
      { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash", provider: "google", series: "Flash", tested: true },
    ],
    defaults: { model: "gemini-3.8-flash", key_id: "key-1" },
  } as never);
  const settings: ChronicleSettings = {
    model: "gemini-3.8-flash", key_id: "key-1", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };

  render(<ChronicleSettingsDrawer open settings={settings} saveState="saved" onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  const modelButton = (await screen.findByText("Gemini 3.8 Flash")).closest("button")!;
  fireEvent.click(modelButton);
  fireEvent.pointerDown(screen.getByText("Google", { exact: true }));
  expect(screen.getByRole("listbox", { name: "Chat Model" })).toBeTruthy();

  const connectionButton = screen.getByRole("button", { name: /Google · Default Key/ });
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

test("shows capability supported output and reasoning controls for a selected model", async () => {
  const capabilities = {
    chat: true, embeddings: false, input_limit: 100000, output_limit: 16377,
    reasoning_levels: ["low", "medium", "high"], reasoning_default: "medium", reasoning_off: true,
    thinking_levels: null, thinking_default: null, thinking_off: null, embedding: null,
  };
  const model = { id: "gpt-5-mini", name: "GPT-5 mini", provider: "openai", series: "GPT", tested: true, capabilities };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "openai-key", name: "Work", provider: "openai", connection_id: "openai", models: [model] }],
    connections: [{ id: "openai", provider: "openai", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: model.id, key_id: "openai-key" },
  } as never);
  const onSettingsChange = vi.fn();
  const settings: ChronicleSettings = {
    model: model.id, key_id: "openai-key", output_limit: "max", reasoning: "auto",
    chunk_count: 3, minimum_similarity: 0.6, chunk_overlap: 150, streaming_speed: 50,
    chat_history_prefix: "<chat_history>", chat_history_suffix: "</chat_history>",
    rag_chunks_prefix: "<rag_chunks>", rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };

  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={onSettingsChange} onClose={vi.fn()} />);
  expect(await screen.findByLabelText("Output Limit")).toBeTruthy();
  expect(screen.getByLabelText("Reasoning")).toBeTruthy();
  expect(screen.getByRole("option", { name: "Off" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Reasoning"), { target: { value: "high" } });
  expect(onSettingsChange).toHaveBeenCalledWith(expect.objectContaining({ reasoning: "high" }));
});

test("does not expose undocumented thinking levels for Gemini 2.5 Flash", async () => {
  const capabilities = {
    chat: true, embeddings: false, input_limit: 100000, output_limit: 8192,
    reasoning_levels: null, reasoning_default: null, reasoning_off: null,
    thinking_levels: [], thinking_default: "auto", thinking_off: false, embedding: null,
  };
  const model = { id: "gemini-2.5-flash", name: "Gemini 2.5 Flash", provider: "google", series: "Flash", tested: true, capabilities };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "google-key", name: "Work", provider: "google", connection_id: "google", models: [model] }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: model.id, key_id: "google-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: model.id, key_id: "google-key", output_limit: "max", reasoning: "auto",
    chunk_count: 3, minimum_similarity: 0.6, chunk_overlap: 150, streaming_speed: 50,
    chat_history_prefix: "<chat_history>", chat_history_suffix: "</chat_history>",
    rag_chunks_prefix: "<rag_chunks>", rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  expect(await screen.findByText("Gemini 2.5 Flash")).toBeTruthy();
  expect(screen.queryByLabelText("Thinking Level")).toBeNull();
  expect(screen.queryByLabelText("Reasoning")).toBeNull();
});

test("shows Gemini 2.5 Pro numeric Thinking Budget with a dynamic default", async () => {
  const model = {
    id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", provider: "google", series: "Pro", tested: true,
    capabilities: {
      chat: true, input_limit: 1_048_576, output_limit: 65_536,
      thinking_levels: [], thinking_default: "dynamic", thinking_off: false,
      thinking_budget: { minimum: 128, maximum: 32_768, default: "dynamic" },
    },
  };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "google-key", name: "Work", provider: "google", connection_id: "google", models: [model] }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: model.id, key_id: "google-key" },
  } as never);
  const onSettingsChange = vi.fn();
  const settings: ChronicleSettings = {
    model: model.id, key_id: "google-key", output_limit: "max", reasoning: "high",
    chunk_count: 3, minimum_similarity: 0.6, chunk_overlap: 150, streaming_speed: 50,
    chat_history_prefix: "<chat_history>", chat_history_suffix: "</chat_history>",
    rag_chunks_prefix: "<rag_chunks>", rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  const { rerender } = render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={onSettingsChange} onClose={vi.fn()} />);
  const budget = await screen.findByLabelText("Thinking Budget") as HTMLInputElement;
  expect(budget.value).toBe("");
  expect(budget.placeholder).toBe("Dynamic (default)");
  expect(budget.min).toBe("128");
  expect(budget.max).toBe("32768");
  expect(screen.queryByLabelText("Thinking Level")).toBeNull();
  expect(screen.queryByLabelText("Reasoning")).toBeNull();
  expect(screen.getByText(/Leave blank to use Google’s dynamic default/)).toBeTruthy();
  fireEvent.change(budget, { target: { value: "128" } });
  fireEvent.blur(budget);
  expect(onSettingsChange).toHaveBeenCalledWith(expect.objectContaining({ thinking_budget: 128, reasoning: "high" }));

  rerender(<ChronicleSettingsDrawer open settings={{ ...settings, thinking_budget: 128 }} onSettingsChange={onSettingsChange} onClose={vi.fn()} />);
  const dynamicBudget = await screen.findByLabelText("Thinking Budget");
  fireEvent.change(dynamicBudget, { target: { value: "" } });
  fireEvent.blur(dynamicBudget);
  expect(onSettingsChange).toHaveBeenCalledWith(expect.objectContaining({ thinking_budget: null, reasoning: "high" }));
});

test.each([
  ["gemini-2.5-flash", 0, 24_576, "dynamic", "Dynamic (default)"],
  ["gemini-2.5-flash-lite", 512, 24_576, "off", "Off (default)"],
] as const)("shows the documented numeric Thinking Budget for %s", async (id, minimum, maximum, defaultValue, placeholder) => {
  const model = {
    id, name: id, provider: "google", tested: true,
    capabilities: {
      chat: true, output_limit: 65_536, thinking_levels: [], thinking_default: defaultValue,
      thinking_off: true, thinking_budget: { minimum, maximum, default: defaultValue, allow_zero: true },
    },
  };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "google-key", name: "Work", provider: "google", connection_id: "google", models: [model] }],
    connections: [{ id: "google", provider: "google", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: id, key_id: "google-key" },
  } as never);
  const onSettingsChange = vi.fn();
  const settings: ChronicleSettings = {
    model: id, key_id: "google-key", output_limit: "max", reasoning: "auto",
    chunk_count: 3, minimum_similarity: 0.6, chunk_overlap: 150, streaming_speed: 50,
    chat_history_prefix: "<chat_history>", chat_history_suffix: "</chat_history>",
    rag_chunks_prefix: "<rag_chunks>", rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={onSettingsChange} onClose={vi.fn()} />);
  const budget = await screen.findByLabelText("Thinking Budget") as HTMLInputElement;
  expect(budget.min).toBe("0");
  expect(budget.max).toBe(String(maximum));
  expect(budget.placeholder).toBe(placeholder);
  fireEvent.change(budget, { target: { value: "0" } });
  fireEvent.blur(budget);
  expect(onSettingsChange).toHaveBeenCalledWith(expect.objectContaining({ thinking_budget: 0 }));
});

test("does not show a Reasoning selector for non-reasoning models", async () => {
  const model = {
    id: "gpt-4.1", name: "GPT-4.1", provider: "openai", series: "GPT", tested: true,
    capabilities: { chat: true, output_limit: 32_768, reasoning_levels: [], reasoning_default: null, reasoning_off: false },
  };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "openai-key", name: "Work", provider: "openai", connection_id: "openai", models: [model] }],
    connections: [{ id: "openai", provider: "openai", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: model.id, key_id: "openai-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: model.id, key_id: "openai-key", reasoning: "high", chunk_count: 3,
    minimum_similarity: 0.6, chunk_overlap: 150, streaming_speed: 50,
    chat_history_prefix: "<chat_history>", chat_history_suffix: "</chat_history>",
    rag_chunks_prefix: "<rag_chunks>", rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  expect(await screen.findByText("GPT-4.1")).toBeTruthy();
  expect(screen.queryByLabelText("Reasoning")).toBeNull();
  expect(screen.queryByLabelText("Thinking Level")).toBeNull();
  expect(screen.queryByText(/does not support a Reasoning control/)).toBeNull();
});

test("maps a wire none level to Off and keeps Provider Default for unknown output limits", async () => {
  const capabilities = {
    chat: true, embeddings: false, input_limit: 100000, output_limit: null,
    reasoning_levels: ["none", "low", "medium", "high"], reasoning_default: "none", reasoning_off: true,
    thinking_levels: null, thinking_default: null, thinking_off: null, embedding: null,
  };
  const model = { id: "deepseek-v4-pro", name: "DeepSeek V4 Pro", provider: "deepseek", series: "V4", tested: true, capabilities };
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "deepseek-key", name: "Work", provider: "deepseek", connection_id: "deepseek", models: [model] }],
    connections: [{ id: "deepseek", provider: "deepseek", enabled: true }],
    models: [model], chat_models: [model], defaults: { model: model.id, key_id: "deepseek-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: model.id, key_id: "deepseek-key", output_limit: 2048, reasoning: "none",
    chunk_count: 3, minimum_similarity: 0.6, chunk_overlap: 150, streaming_speed: 50,
    chat_history_prefix: "<chat_history>", chat_history_suffix: "</chat_history>",
    rag_chunks_prefix: "<rag_chunks>", rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  expect(await screen.findByText("DeepSeek V4 Pro")).toBeTruthy();
  expect(screen.getByText("Output Limit")).toBeTruthy();
  const output = await screen.findByLabelText("Output Limit");
  expect((output as HTMLInputElement).value).toBe("");
  expect((output as HTMLInputElement).disabled).toBe(true);
  expect((output as HTMLInputElement).placeholder).toBe("Provider Default");
  expect(screen.getByText(/Provider Default is used for this model/)).toBeTruthy();

  const reasoning = screen.getByLabelText("Reasoning");
  expect((reasoning as HTMLSelectElement).value).toBe("off");
  expect(within(reasoning).getByRole("option", { name: "Model Default (off)" })).toBeTruthy();
  expect(within(reasoning).getByRole("option", { name: "Off" })).toBeTruthy();
  expect(within(reasoning).queryByRole("option", { name: "None" })).toBeNull();
});

test("Developer preview opens documented models without a key and shows the maximum output in an input", async () => {
  const model = {
    id: "gpt-6-astra", name: "GPT-6 Astra", provider: "openai", series: "GPT", tested: true,
    capabilities: { chat: true, output_limit: 128000, reasoning_levels: ["low", "medium", "high"], reasoning_default: "high", reasoning_off: false },
  };
  vi.mocked(api).mockResolvedValue({
    keys: [], connections: [], models: [], chat_models: [], preview_chat_models: [model],
    defaults: { model: "", key_id: "" },
  } as never);
  const onSettingsChange = vi.fn();
  const settings: ChronicleSettings = {
    model: "", key_id: "", output_limit: "max", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  const { rerender } = render(<ChronicleSettingsDrawer open modelPreview settings={settings} onSettingsChange={onSettingsChange} onClose={vi.fn()} />);
  expect(await screen.findByText("Preview · no connection")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Select a model/ }));
  fireEvent.click(screen.getByRole("option", { name: "GPT-6 Astra" }));
  expect(onSettingsChange).toHaveBeenCalledWith(expect.objectContaining({ model: "gpt-6-astra", key_id: "" }));
  rerender(<ChronicleSettingsDrawer open modelPreview settings={{ ...settings, model: "gpt-6-astra" }} onSettingsChange={onSettingsChange} onClose={vi.fn()} />);
  const output = await screen.findByLabelText("Output Limit") as HTMLInputElement;
  expect(output.value).toBe("128000");
  fireEvent.change(output, { target: { value: "4096" } });
  fireEvent.blur(output);
  expect(onSettingsChange).toHaveBeenCalledWith(expect.objectContaining({ output_limit: 4096 }));
});

test("searches models, formats provider names, and keeps the three most recent models at the top", async () => {
  const chatModels = [
    { id: "claude-haiku-4-5-20251001", name: "Claude Haiku 4 5 20251001", provider: "anthropic", series: "Haiku", tested: true, capabilities: { chat: true } },
    { id: "claude-sonnet-4-5-20250929", name: "Claude Sonnet 4 5 20250929", provider: "anthropic", series: "Sonnet", tested: true, capabilities: { chat: true } },
    { id: "claude-opus-5-5", name: "Claude Opus 5 5", provider: "anthropic", series: "Opus", tested: true, capabilities: { chat: true } },
    { id: "claude-fable-5-1", name: "Claude Fable 5 1", provider: "anthropic", series: "Fable", tested: true, capabilities: { chat: true } },
    { id: "claude-opus-4-5-20251101", name: "Claude Opus 4 5 20251101", provider: "anthropic", series: "Opus", tested: true, capabilities: { chat: true } },
    { id: "gpt-5-mini", name: "Gpt-5 mini", provider: "openai", series: "GPT", tested: true, capabilities: { chat: true } },
  ];
  vi.mocked(api).mockResolvedValue({
    keys: [{ id: "anthropic-key", name: "Work", provider: "anthropic", connection_id: "anthropic", models: chatModels }],
    connections: [{ id: "anthropic", provider: "anthropic", enabled: true }],
    models: chatModels, chat_models: chatModels, defaults: { model: "claude-fable-5-1", key_id: "anthropic-key" },
  } as never);
  const settings: ChronicleSettings = {
    model: "claude-fable-5-1", key_id: "anthropic-key", chunk_count: 3, minimum_similarity: 0.6,
    chunk_overlap: 150, streaming_speed: 50, chat_history_prefix: "<chat_history>",
    chat_history_suffix: "</chat_history>", rag_chunks_prefix: "<rag_chunks>",
    rag_chunks_suffix: "</rag_chunks>",
    sections: { ai: true, retrieval: true, response: true, section_tags: true },
  };
  render(<ChronicleSettingsDrawer open settings={settings} onSettingsChange={vi.fn()} onClose={vi.fn()} />);
  const modelButton = await screen.findByRole("button", { name: "Claude Fable 5.1" });
  fireEvent.click(modelButton);
  const listbox = screen.getByRole("listbox", { name: "Chat Model" });
  expect([...listbox.querySelectorAll(".chronicle-model-group > span")].map((heading) => heading.textContent)).toEqual(["Anthropic", "OpenAI"]);
  expect(within(listbox).getAllByRole("option").map((option) => option.textContent?.trim())).toEqual([
    "Claude Fable 5.1",
    "Claude Opus 5.5",
    "Claude Opus 4.5",
    "Claude Sonnet 4.5",
    "Claude Haiku 4.5",
    "GPT-5 mini",
  ]);

  fireEvent.change(screen.getByRole("searchbox", { name: "Search models" }), { target: { value: "4.5" } });
  expect(within(listbox).getAllByRole("option").map((option) => option.textContent?.trim())).toEqual([
    "Claude Opus 4.5",
    "Claude Sonnet 4.5",
    "Claude Haiku 4.5",
  ]);
  fireEvent.change(screen.getByRole("searchbox", { name: "Search models" }), { target: { value: "" } });

  for (const modelName of ["Claude Opus 5.5", "Claude Sonnet 4.5", "Claude Haiku 4.5", "GPT-5 mini"]) {
    fireEvent.click(screen.getByRole("option", { name: modelName }));
    fireEvent.click(modelButton);
  }
  const recentListbox = screen.getByRole("listbox", { name: "Chat Model" });
  const recentGroup = [...recentListbox.querySelectorAll(".chronicle-model-group")].find((group) => group.querySelector("span")?.textContent === "Recent");
  expect(recentGroup).toBeTruthy();
  expect(within(recentGroup as HTMLElement).getAllByRole("option").map((option) => option.textContent?.trim())).toEqual([
    "GPT-5 mini", "Claude Haiku 4.5", "Claude Sonnet 4.5",
  ]);
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
