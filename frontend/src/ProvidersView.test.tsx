// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProvidersView } from "./ProvidersView";
import { api } from "./api";

vi.mock("./api", async () => ({
  ...(await vi.importActual("./api")),
  api: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

test("saves a write-only secret and renames without sending it again", async () => {
  const requests: Record<string, string>[] = [];
  vi.mocked(api).mockImplementation(async (_path, request) => {
    if (!request) return { keys: [] };
    const body = JSON.parse(request.body as string);
    requests.push(body);
    return { id: "key", name: body.name, provider: "google" };
  });
  render(<ProvidersView />);
  fireEvent.click(await screen.findByRole("button", { name: /Add API key/ }));
  fireEvent.change(screen.getByLabelText("Key name"), {
    target: { value: "Personal" },
  });
  fireEvent.change(screen.getByLabelText("API key"), {
    target: { value: "synthetic-test-secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  fireEvent.click(await screen.findByRole("button", { name: "Edit Personal" }));
  expect(
    (
      screen.getByLabelText(
        "Replacement API key (optional)",
      ) as HTMLInputElement
    ).value,
  ).toBe("");
  fireEvent.change(screen.getByLabelText("Key name"), {
    target: { value: "Renamed" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  await screen.findByRole("button", { name: "Edit Renamed" });
  expect(requests[0].secret).toBe("synthetic-test-secret");
  expect(requests[1]).not.toHaveProperty("secret");
  expect(document.body.textContent).not.toContain("synthetic-test-secret");
});

test("confirms deletion and explains when running work blocks it", async () => {
  vi.mocked(api).mockImplementation(async (_path, request) => {
    if (!request)
      return { keys: [{ id: "key", name: "Personal", provider: "google" }] };
    throw new Error("Pause world creation before changing its API key.");
  });
  render(<ProvidersView />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Remove Personal" }),
  );
  expect(vi.mocked(api).mock.calls).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Remove key" }));
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toContain(
      "Pause world creation",
    ),
  );
  expect(screen.getByRole("button", { name: "Edit Personal" })).toBeTruthy();
});
