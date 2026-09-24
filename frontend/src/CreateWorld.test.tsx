// @vitest-environment jsdom
import { useState } from "react";
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
  ...(await vi.importActual("./api")),
  api: vi.fn(),
}));

const providers = {
  keys: [{ id: "key", name: "Personal Gemini", provider: "google" }],
  models: [],
  defaults: { model: "gemini-embedding-2", key_id: "key" },
};
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.mocked(api).mockResolvedValue(providers);
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function show(attempt: CreationAttempt | null = null) {
  const onClose = vi.fn(),
    onManageKeys = vi.fn(),
    onAttempt = vi.fn();
  render(
    <CreateWorld
      visible
      attempt={attempt}
      onAttempt={onAttempt}
      onClose={onClose}
      onManageKeys={onManageKeys}
    />,
  );
  return { onClose, onManageKeys, onAttempt };
}
async function booksStep() {
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "Northern Tales" },
  });
  fireEvent.change(screen.getByLabelText("Choose books"), {
    target: {
      files: [new File(["A"], "First.txt"), new File(["B"], "Second.epub")],
    },
  });
  await waitFor(() => expect(api).toHaveBeenCalled());
}

test("no processing until review submission, with keyboard reorder and exact settings", async () => {
  show();
  await booksStep();
  fireEvent.keyDown(
    screen.getByRole("button", { name: "Reorder Second.epub" }),
    { key: "ArrowUp" },
  );
  expect(
    document.querySelectorAll(".book-selection-name > span")[0].textContent,
  ).toBe("Second");
  expect(screen.queryByText("Converting text…")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  expect(
    (screen.getByLabelText("Maximum chunk size") as HTMLInputElement).value,
  ).toBe("8000");
  expect(
    (screen.getByLabelText("Boundary search distance") as HTMLInputElement)
      .value,
  ).toBe("1000");
  fireEvent.click(screen.getByRole("button", { name: "Review →" }));
  expect(screen.getByText(/source text and book order are fixed/)).toBeTruthy();
  expect(
    vi.mocked(api).mock.calls.every(([, request]) => !request?.method),
  ).toBe(true);
});

test("requires books and validates the boundary search window", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  expect(screen.getByRole("alert").textContent).toContain("at least one book");
  await booksStep();
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  fireEvent.change(screen.getByLabelText("Boundary search distance"), {
    target: { value: "8000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Review →" }));
  expect(screen.getByRole("alert").textContent).toContain("smaller");
});

test("manage keys and close invoke their separate callbacks", async () => {
  const { onManageKeys, onClose } = show();
  await booksStep();
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  fireEvent.click(screen.getByRole("button", { name: "Manage API keys" }));
  expect(onManageKeys).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Close creation" }));
  expect(onClose).toHaveBeenCalledOnce();
});

test("the entire add-books area opens the file chooser", () => {
  show();
  const input = screen.getByLabelText("Choose books");
  const open = vi.spyOn(input, "click").mockImplementation(() => {});
  fireEvent.click(screen.getByText("Choose or drop TXT and EPUB files here."));
  expect(open).toHaveBeenCalledOnce();
  open.mockRestore();
});

test("chunking help opens on hover, focus, and tap; Escape dismisses only the help", async () => {
  const { onClose } = show();
  await booksStep();
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  const help = screen.getByRole("button", { name: "About chunking" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.pointerEnter(help);
  expect(screen.getByRole("tooltip").textContent).toContain(
    "Maximum chunk size",
  );
  fireEvent.pointerLeave(help.parentElement!);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.focus(help);
  expect(screen.getByRole("tooltip").textContent).toContain(
    "Boundary search distance",
  );
  fireEvent.keyDown(help, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(help);
  expect(screen.getByRole("tooltip")).toBeTruthy();
  fireEvent.blur(help);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

const saved: CreationAttempt = {
  id: "attempt",
  name: "Saved world",
  revision: 4,
  state: "failed",
  phase: "preparing",
  created_at: "",
  updated_at: "",
  message: "Some books need attention.",
  config: { model: "gemini-embedding-2", size: 8000, search: 1000 },
  key_id: "key",
  books_done: 0,
  chunks_total: 0,
  chunks_done: 0,
  books: [
    {
      id: "book",
      filename: "Lost.txt",
      size: 4,
      position: 1,
      state: "failed",
      message: "Unreadable text",
      uploaded: false,
      chunks_total: 0,
      chunks_done: 0,
    },
  ],
};
test("failed progress shows ordered counts and a single book error without editing", async () => {
  show({
    ...saved,
    message: "Google is unavailable. Resume later.",
    books: [
      { ...saved.books[0], message: "Google is unavailable. Resume later." },
    ],
  });
  expect(await screen.findByText("Google is unavailable.")).toBeTruthy();
  expect(screen.queryByText(/Resume later/)).toBeNull();
  expect(screen.queryByText("Some books need attention.")).toBeNull();
  expect(screen.queryByText("A world begins with its stories")).toBeNull();
  expect(screen.queryByRole("button", { name: "Edit attempt" })).toBeNull();
  const progress = document.querySelector(".creation-progress")!;
  expect(progress.children[0].textContent).toBe("0 of 1 books complete");
  expect(progress.children[1].textContent).toBe("0 of 0 chunks embedded");
});

test("discard requires a separate confirmation", async () => {
  show(saved);
  fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
  expect(
    screen.getByText(/Discard this attempt and its saved progress/),
  ).toBeTruthy();
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([, request]) => request?.method === "DELETE"),
  ).toBe(false);
});

test.each(["Close", "Close creation", "Escape"])(
  "%s clears unsubmitted selections without a server mutation",
  async (control) => {
    const { onClose } = show();
    await booksStep();
    expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull();
    if (control === "Escape")
      fireEvent(
        screen.getByRole("dialog"),
        new Event("cancel", { cancelable: true }),
      );
    else fireEvent.click(screen.getByRole("button", { name: control }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      (screen.getByLabelText("World name") as HTMLInputElement).value,
    ).toBe("");
    expect(document.querySelectorAll(".selection-row")).toHaveLength(0);
    expect(
      vi.mocked(api).mock.calls.every(([, request]) => !request?.method),
    ).toBe(true);
  },
);

test("Tab wraps between the first and last modal controls", async () => {
  show();
  const first = screen.getByRole("button", { name: "Close creation" });
  const last = screen.getByRole("button", { name: "Continue →" });
  const rectangles = vi
    .spyOn(HTMLElement.prototype, "getClientRects")
    .mockReturnValue([{}] as unknown as DOMRectList);
  try {
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  } finally {
    rectangles.mockRestore();
  }
});

test("recovers a lost manifest response and retries uploads with the same operation", async () => {
  let checkpoint: CreationAttempt | null = null;
  let manifestSaves = 0;
  const uploads: string[] = [];
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (path === "/providers") return providers;
    if (request?.method === "PUT" && !path.includes("/books/")) {
      const body = JSON.parse(request.body as string);
      expect(body.revision).toBe(checkpoint?.revision ?? 0);
      checkpoint = {
        ...saved,
        ...body,
        id: path.split("/").pop()!,
        revision: body.revision + 1,
        state: "paused",
        books: body.books.map((book: object) => ({
          ...book,
          uploaded: false,
          chunks_done: 0,
          chunks_total: 0,
          state: "waiting",
        })),
      };
      manifestSaves++;
      if (manifestSaves === 1) throw new Error("Connection interrupted");
      return checkpoint;
    }
    if (request?.method === "PUT") {
      uploads.push(path);
      if (uploads.length === 1) throw new Error("Upload response lost");
      const bookId = path.split("/books/")[1].split("?")[0];
      checkpoint = {
        ...checkpoint!,
        revision: checkpoint!.revision + 1,
        books: checkpoint!.books.map((book) =>
          book.id === bookId ? { ...book, uploaded: true } : book,
        ),
      };
      return checkpoint;
    }
    if (request?.method === "POST") return { ...checkpoint!, state: "running" };
    return checkpoint;
  });
  // Both automatic save responses are lost; GET recovers the saved revision.
  const implementation = vi.mocked(api).getMockImplementation()!;
  let firstSave = true;
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (
      request?.method === "PUT" &&
      !path.includes("/books/") &&
      firstSave &&
      checkpoint
    ) {
      firstSave = false;
      throw new Error("Connection interrupted");
    }
    return implementation(path, request);
  });
  function Flow() {
    const [attempt, setAttempt] = useState<CreationAttempt | null>(null);
    return (
      <CreateWorld
        visible
        attempt={attempt}
        onAttempt={setAttempt}
        onClose={() => {}}
        onManageKeys={() => {}}
      />
    );
  }
  render(<Flow />);
  await booksStep();
  fireEvent.click(screen.getByRole("button", { name: "Continue →" }));
  fireEvent.click(screen.getByRole("button", { name: "Review →" }));
  fireEvent.click(screen.getByRole("button", { name: "Create World" }));
  await screen.findByText("Connection interrupted");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Resume" }).hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Resume" }));
  await screen.findByRole("button", { name: "Pause" });
  expect(uploads).toHaveLength(3);
  expect(uploads[0]).toBe(uploads[1]);
});
