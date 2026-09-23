// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CreateWorld, CreationProgress } from "./CreateWorld";
import { api, sendBook, type CreationAttempt } from "./api";
vi.mock("./api", () => ({
  api: vi.fn(),
  sendBook: vi.fn(),
  jsonRequest: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("retry imports only failed books into the same world", async () => {
  const world = {
    id: "one",
    name: "World",
    created_at: "now",
    last_used_at: null,
    artwork: "frostwake",
  };
  vi.mocked(api).mockResolvedValue(world);
  vi.mocked(sendBook)
    .mockResolvedValueOnce({ status: "done", error: null })
    .mockResolvedValueOnce({
      status: "done",
      error: "invalid_encoding",
      message: "Unreadable book",
    })
    .mockResolvedValueOnce({ status: "done", error: null });
  render(<CreateWorld visible onCreated={vi.fn()} onFinished={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("World name"), {
    target: { value: "World" },
  });
  fireEvent.change(document.querySelector("input[type=file]")!, {
    target: {
      files: [new File(["ok"], "Good.txt"), new File(["bad"], "Bad.txt")],
    },
  });
  fireEvent.submit(document.querySelector("form")!);
  await screen.findByText("Unreadable book");
  fireEvent.click(screen.getByRole("button", { name: "Retry Failed Books" }));
  await screen.findByText("Your world and books are ready.");
  expect(api).toHaveBeenCalledTimes(1);
  expect(sendBook).toHaveBeenCalledTimes(3);
  expect(
    vi.mocked(sendBook).mock.calls.map(([id, , file]) => [id, file.name]),
  ).toEqual([
    ["one", "Good.txt"],
    ["one", "Bad.txt"],
    ["one", "Bad.txt"],
  ]);
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
  render(<CreationProgress attempt={{
    ...saved,
    message: "Google is unavailable. Resume later.",
    books: [
      { ...saved.books[0], message: "Google is unavailable. Resume later." },
    ],
  }} />);
  expect(await screen.findByText("Google is unavailable.")).toBeTruthy();
  expect(screen.queryByText(/Resume later/)).toBeNull();
  expect(screen.queryByText("Some books need attention.")).toBeNull();
  expect(screen.queryByText("A world begins with its stories")).toBeNull();
  expect(screen.queryByRole("button", { name: "Edit attempt" })).toBeNull();
  const progress = document.querySelector(".creation-progress")!;
  expect(progress.children[0].textContent).toBe("0 of 1 books complete");
  expect(progress.children[1].textContent).toBe("0 of 0 chunks embedded");
});

