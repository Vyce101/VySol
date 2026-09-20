// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CreateWorld } from "./CreateWorld";
import { api, sendBook } from "./api";
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
