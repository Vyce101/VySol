// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CreateWorld, WorldOverview } from "./CreateWorld";
import { api, type CreationAttempt, type WorldDetail } from "./api";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));

const profiles = {
  profiles: [
    { id: "profile-google", name: "Gemini Embedding 2", key_id: "key-a", provider: "google", model: "gemini-embedding-2", model_name: "Gemini Embedding 2", dimensions: 3072, max_input_tokens: 8192, is_default: true, usable: true, credential_name: "World Sim 1" },
    { id: "profile-openai", name: "OpenAI Embedding", key_id: "disabled-key", provider: "openai", model: "openai-embedding", model_name: "OpenAI Embedding", dimensions: 1536, max_input_tokens: 8192, is_default: false, usable: false, credential_name: "Disabled Key" },
    { id: "profile-real", name: "Real", key_id: "key-a", provider: "google", model: "gemini-embedding-2", model_name: "Gemini Embedding 2", dimensions: 3072, max_input_tokens: 8192, is_default: false, usable: true, credential_name: "World Sim 1" },
  ],
  default_profile_id: "profile-google",
  last_used_profile_id: "profile-google",
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
    if (path === "/embedding-profiles") return profiles as never;
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
  expect(document.querySelectorAll(".provider-logo-mark")).toHaveLength(0);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByLabelText("World Name")).toBeTruthy();
  expect((screen.getByLabelText("World Name") as HTMLInputElement).autocomplete).toBe("off");
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
  expect(manifest.config).toEqual({ size: 8000, search: 1000 });
  expect(manifest.embedding_profile_id).toBe("profile-google");
  expect(manifest.key_id).toBeUndefined();
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).includes("/books/"))).toBe(true);
  expect(vi.mocked(api).mock.calls.some(([path]) => String(path).endsWith("/start"))).toBe(true);
  expect((screen.getByLabelText("World Name") as HTMLInputElement).value).toBe("");
  expect(screen.getByRole("button", { name: "Create World" }).hasAttribute("disabled")).toBe(false);
});

test("submits the explicitly selected profile when it differs from the last-used profile", async () => {
  const { onCreated } = show();
  fireEvent.click(await screen.findByRole("button", { name: "Embedding profile" }));
  fireEvent.click(screen.getByRole("option", { name: /Real/ }));
  expect(screen.getByRole("button", { name: "Embedding profile" }).textContent).toContain("Real");
  await addStory();
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: expect.any(String) })));

  const manifestCall = vi.mocked(api).mock.calls.find(([path, request]) =>
    typeof path === "string" && path.startsWith("/creation/") && request?.method === "PUT",
  );
  expect(manifestCall).toBeTruthy();
  const manifest = JSON.parse(manifestCall![1]!.body as string);
  expect(manifest.embedding_profile_id).toBe("profile-real");
});

test("unusable embedding profiles cannot be selected for a new World", async () => {
  show();
  await screen.findByText("Gemini Embedding 2");
  fireEvent.click(screen.getByRole("button", { name: "Embedding profile" }));
  expect(screen.getByRole("option", { name: /^Gemini Embedding 2 / })).toBeTruthy();
  expect(screen.getByRole("option", { name: /OpenAI Embedding/ }).hasAttribute("disabled")).toBe(true);
});

test("Create World asks the user to choose a profile when none was used before", async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/embedding-profiles") return { ...profiles, last_used_profile_id: null } as never;
    return {} as never;
  });
  show();
  const picker = await screen.findByRole("button", { name: "Embedding profile" });
  expect(picker.textContent).toContain("Choose a profile");
  expect(picker.textContent).toContain("Choose a profile for this World");
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

test("World Details separates embeddings from chunking and keeps the embedding source read only", async () => {
  const current = { ...profiles.profiles[0], input_format_version: 2, base_url: null };
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/embedding-profiles") return { profiles: [current] } as never;
    throw new Error(`Unexpected request ${path}`);
  });
  const detail = {
    id: "world-1", name: "Example World", state: "complete", books: [],
    progress: { chunks_done: 1, chunks_total: 1 }, processing: { max_chunk_size: 8000, boundary_search_distance: 1000 },
    embedding_profile: current,
  } as unknown as WorldDetail;
  render(<WorldOverview visible handoffTransition={false} world={detail} detail={detail} attempt={null}
    uploading={false} busy={false} onPause={vi.fn()} onResume={vi.fn()} onDiscard={vi.fn()}
    onChronicles={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "World Details" }));
  expect(screen.getByRole("heading", { name: "Embedding" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Chunking" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Change Embedding Profile" })).toBeNull();
  expect(screen.getByText(current.name)).toBeTruthy();
  expect(screen.getByText(/Google ·/)).toBeTruthy();
  expect(vi.mocked(api)).not.toHaveBeenCalledWith("/worlds/world-1/embedding-profile", expect.anything());
});
