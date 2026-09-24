// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CreateWorld } from "./CreateWorld";
import { api, type CreationAttempt } from "./api";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));

const providers = {
  keys: [
    { id: "key-b", name: "World Sim 2", provider: "google", connection_id: "google" },
    { id: "key-a", name: "World Sim 1", provider: "google", connection_id: "google" },
    { id: "disabled-key", name: "Disabled Key", provider: "openai", connection_id: "openai" },
  ],
  connections: [
    { id: "google", provider: "google", enabled: true },
    { id: "openai", provider: "openai", enabled: false },
  ],
  models: [
    { id: "gemini-embedding-2", name: "Gemini Embedding 2", provider: "google" },
    { id: "openai-embedding", name: "OpenAI Embedding", provider: "openai" },
  ],
  defaults: { model: "gemini-embedding-2", key_id: "key-a" },
};

const starting: CreationAttempt = {
  id: "attempt",
  name: "Northern Tales",
  revision: 1,
  state: "paused",
  phase: "uploading",
  created_at: "",
  updated_at: "",
  message: "",
  config: { model: "gemini-embedding-2", size: 8000, search: 1000 },
  key_id: "key-a",
  books_done: 0,
  chunks_total: 0,
  chunks_done: 0,
  books: [
    {
      id: "book-one",
      filename: "First.txt",
      size: 4,
      position: 1,
      uploaded: false,
      state: "waiting",
      message: "",
      chunks_total: 0,
      chunks_done: 0,
    },
  ],
};

let resumeHandler: ((attempt: CreationAttempt) => Promise<CreationAttempt>) | null;
let created: CreationAttempt;
let failUpload: boolean;
beforeEach(() => {
  resumeHandler = null;
  created = starting;
  failUpload = false;
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/providers") return providers as never;
    if (path.startsWith("/creation/") && path.includes("/books/")) {
      if (failUpload) throw new Error("Upload interrupted");
      created = {
        ...created,
        revision: 2,
        books: created.books.map((book) => ({ ...book, uploaded: true, state: "uploaded" })),
      };
      return created as never;
    }
    if (path.endsWith("/start")) {
      created = { ...created, revision: 3, state: "running", phase: "preparing" };
      return created as never;
    }
    if (init?.method === "PUT" && path.startsWith("/creation/")) {
      const manifest = JSON.parse(String(init.body));
      created = {
        ...starting,
        id: path.split("/")[2],
        name: manifest.name,
        revision: 1,
        state: "paused",
        books: manifest.books.map((book: { id: string; filename: string; size: number }, index: number) => ({
          ...starting.books[0],
          id: book.id,
          filename: book.filename,
          size: book.size,
          position: index + 1,
          uploaded: false,
        })),
      };
      return created as never;
    }
    if (path.startsWith("/creation/")) return created as never;
    return {} as never;
  });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function show() {
  const onAttempt = vi.fn();
  const onCreated = vi.fn();
  const onManageKeys = vi.fn();
  render(
    <CreateWorld
      visible
      handoffTransition={false}
      onAttempt={onAttempt}
      onCreated={onCreated}
      onManageKeys={onManageKeys}
      onResumeHandler={(handler) => (resumeHandler = handler)}
    />,
  );
  return { onAttempt, onCreated, onManageKeys };
}

async function addStory(name = "The Rise of Kyoshi.txt") {
  fireEvent.change(screen.getByLabelText("World Name"), {
    target: { value: "Northern Tales" },
  });
  fireEvent.change(screen.getByLabelText("Choose books"), {
    target: { files: [new File(["Story"], name)] },
  });
  await screen.findByText(name.replace(/\.(txt|epub)$/i, ""));
}

test("Create World is a page with compact ordered story rows and no file metadata", async () => {
  show();
  expect(await screen.findByRole("heading", { name: "Create World" })).toBeTruthy();
  await screen.findByText("Gemini Embedding 2");
  expect(document.querySelectorAll(".provider-logo-mark")).toHaveLength(2);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByLabelText("World Name")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Stories" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add Books" })).toBeTruthy();
  await addStory();
  expect(screen.getByText("The Rise of Kyoshi")).toBeTruthy();
  expect(screen.queryByText("0.00 MB")).toBeNull();
  expect(screen.getByRole("button", { name: "Remove The Rise of Kyoshi.txt" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Create World" })).toBeTruthy();
  expect(screen.queryByText("TXT or EPUB")).toBeNull();
});

test("story order can be changed by keyboard and there is no drop marker line", async () => {
  show();
  fireEvent.change(screen.getByLabelText("World Name"), {
    target: { value: "Northern Tales" },
  });
  fireEvent.change(screen.getByLabelText("Choose books"), {
    target: {
      files: [new File(["A"], "First.txt"), new File(["B"], "Second.epub")],
    },
  });
  const handle = await screen.findByRole("button", { name: "Reorder Second.epub" });
  fireEvent.keyDown(handle, { key: "ArrowUp" });
  expect(document.querySelectorAll(".book-selection-name > span:first-child")[0].textContent).toBe("Second");
  expect(document.querySelector("[data-drop-before], [data-drop-after]")).toBeNull();
});

test("Advanced Settings reveals the processing fields and validates chunk boundaries", async () => {
  show();
  expect(document.getElementById("advanced-settings-content")?.getAttribute("aria-hidden")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Advanced Settings" }));
  expect((await screen.findByLabelText("Maximum chunk size") as HTMLInputElement).value).toBe("8000");
  expect((screen.getByLabelText("Boundary search distance") as HTMLInputElement).value).toBe("1000");
  fireEvent.change(screen.getByLabelText("Boundary search distance"), { target: { value: "8000" } });
  fireEvent.change(screen.getByLabelText("World Name"), { target: { value: "Northern Tales" } });
  fireEvent.change(screen.getByLabelText("Choose books"), { target: { files: [new File(["Text"], "Story.txt")] } });
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  expect((await screen.findByRole("alert")).textContent).toContain("smaller");
});

test("Create World saves the manifest, uploads stories, and hands off to Overview", async () => {
  const { onAttempt, onCreated } = show();
  await addStory();
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: expect.any(String) })));
  expect(onAttempt).toHaveBeenCalledWith(expect.objectContaining({ name: "Northern Tales" }));
  const manifestCall = vi.mocked(api).mock.calls.find(([path, request]) =>
    typeof path === "string" && path.startsWith("/creation/") && request?.method === "PUT",
  );
  expect(manifestCall).toBeTruthy();
  const manifest = JSON.parse(manifestCall![1]!.body as string);
  expect(manifest.books).toHaveLength(1);
  expect(manifest.config).toEqual({ model: "gemini-embedding-2", size: 8000, search: 1000 });
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).includes("/books/"))).toBe(true);
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).endsWith("/start"))).toBe(true);
  expect((screen.getByLabelText("World Name") as HTMLInputElement).value).toBe("");
  expect(screen.getByRole("button", { name: "Create World" }).hasAttribute("disabled")).toBe(false);
});

test("disabled connections are unavailable to new model and API connection choices", async () => {
  show();
  await screen.findByText("Gemini Embedding 2");
  fireEvent.click(screen.getByRole("button", { name: "API connection" }));
  expect(screen.getByRole("option", { name: /World Sim 1/ })).toBeTruthy();
  expect(screen.queryByRole("option", { name: /Disabled Key/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Embedding model" }));
  expect(screen.getByRole("option", { name: /Gemini Embedding 2/ })).toBeTruthy();
  expect(screen.queryByRole("option", { name: /OpenAI Embedding/ })).toBeNull();
});

test("a saved attempt retains selected files so interrupted uploads can resume", async () => {
  const { onCreated } = show();
  await addStory("Retry.txt");
  await waitFor(() => expect(resumeHandler).toBeTypeOf("function"));
  failUpload = true;
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
  failUpload = false;
  await resumeHandler!(created);
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).includes("/books/"))).toBe(true);
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).endsWith("/start"))).toBe(true);
});
