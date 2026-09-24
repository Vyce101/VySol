// @vitest-environment jsdom
import {
  act,
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

const connection = {
  id: "google-connection",
  provider: "google",
  enabled: true,
  credentials: [],
  next_sequence: 1,
};

test("closes the chooser when clicking beside its button but keeps chooser clicks inside", async () => {
  vi.mocked(api).mockResolvedValue({ keys: [], connections: [] } as never);

  const { container } = render(<ProvidersView />);
  const button = await screen.findByRole("button", { name: "Select Connections" });
  const selector = container.querySelector(".connections-selector")!;
  const chooser = container.querySelector(".connection-chooser")!;

  fireEvent.click(button);
  fireEvent.pointerDown(chooser);
  expect(button.getAttribute("aria-expanded")).toBe("true");

  fireEvent.pointerDown(selector);
  expect(button.getAttribute("aria-expanded")).toBe("false");
});

test("selects Google and saves a numbered credential", async () => {
  let connected = false;
  const requests: { path: string; body?: Record<string, string> }[] = [];
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (path === "/providers" && !request) {
      return {
        keys: [],
        connections: connected ? [connection] : [],
      } as never;
    }
    if (path === "/providers/connections" && request?.method === "POST") {
      connected = true;
      requests.push({ path, body: JSON.parse(request.body as string) });
      return connection as never;
    }
    if (path.startsWith("/providers/keys/") && request?.method === "PUT") {
      const body = JSON.parse(request.body as string);
      requests.push({ path, body });
      return {
        id: path.split("/").at(-1),
        name: body.name,
        provider: "google",
        sequence: 1,
        connection_id: connection.id,
      } as never;
    }
    throw new Error(`Unexpected request ${path}`);
  });

  render(<ProvidersView />);
  fireEvent.click(await screen.findByRole("button", { name: "Select Connections" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Google" }));
  const google = await screen.findByRole("button", { name: "Google" });
  expect(google.getAttribute("aria-expanded")).toBe("true");

  fireEvent.click(screen.getByRole("button", { name: /Add Credential/ }));
  expect(await screen.findByText("Credential 1")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Connection Name"), {
    target: { value: "Worldsim 1" },
  });
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "synthetic-test-secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

  await screen.findByText("Worldsim 1");
  expect(requests[0]).toEqual({
    path: "/providers/connections",
    body: { provider: "google" },
  });
  expect(requests[1].path).toMatch(/^\/providers\/keys\/[0-9a-f-]+$/i);
  expect(requests[1].body).toEqual({
    name: "Worldsim 1",
    provider: "google",
    connection_id: connection.id,
    secret: "synthetic-test-secret",
  });
  expect(document.body.textContent).not.toContain("synthetic-test-secret");
  expect(document.body.textContent).not.toContain("credentials folder");
});

test("turns Google off without deleting its saved credentials", async () => {
  let enabled = true;
  const saved = {
    id: "key-1",
    name: "Personal",
    provider: "google",
    sequence: 1,
    connection_id: connection.id,
  };
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (path === "/providers" && !request)
      return {
        keys: [saved],
        connections: [{ ...connection, enabled, credentials: [saved] }],
      } as never;
    if (
      path === "/providers/connections/google-connection" &&
      request?.method === "PUT"
    ) {
      enabled = JSON.parse(request.body as string).enabled;
      return { ...connection, enabled, credentials: [saved] } as never;
    }
    throw new Error(`Unexpected request ${path}`);
  });

  render(<ProvidersView />);
  fireEvent.click(await screen.findByRole("button", { name: "Select Connections" }));
  const googleToggle = screen.getByRole("checkbox", { name: "Google" }) as HTMLInputElement;
  expect(googleToggle.checked).toBe(true);
  fireEvent.click(googleToggle);

  await waitFor(() => expect(googleToggle.checked).toBe(false));
  expect(screen.queryByRole("button", { name: "Done" })).toBeNull();
  fireEvent.pointerDown(document.body);
  expect(screen.getByRole("button", { name: "Select Connections" }).getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("button", { name: "Google" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Credential 1/ })).toBeNull();
  expect(vi.mocked(api).mock.calls.some(([path]) => path.endsWith("/key-1"))).toBe(false);

  fireEvent.click(screen.getByRole("button", { name: "Select Connections" }));
  fireEvent.click(googleToggle);
  await waitFor(() => expect(googleToggle.checked).toBe(true));
  fireEvent.pointerDown(document.body);
  fireEvent.click(screen.getByRole("button", { name: "Google" }));
  expect(await screen.findByRole("button", { name: /Credential 1/ })).toBeTruthy();
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.includes("/providers/connections/")))
    .toHaveLength(2);
});

test("reuses a deleted sequence for a new credential and keeps other numbers", async () => {
  const first = {
    id: "key-1",
    name: "First key",
    provider: "google",
    sequence: 1,
    connection_id: connection.id,
  };
  const tenth = {
    id: "key-10",
    name: "Tenth key",
    provider: "google",
    sequence: 10,
    connection_id: connection.id,
  };
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (path === "/providers" && !request)
      return {
        keys: [first, tenth],
        connections: [{ ...connection, next_sequence: 2, credentials: [first, tenth] }],
      } as never;
    if (path === "/providers/keys/key-1" && request?.method === "DELETE")
      return {} as never;
    throw new Error(`Unexpected request ${path}`);
  });

  render(<ProvidersView />);
  fireEvent.click(await screen.findByRole("button", { name: "Google" }));
  fireEvent.click(screen.getByRole("button", { name: "Credential 1 First key" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove Credential" }));

  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Credential 1 First key" })).toBeNull(),
  );
  expect(screen.getByRole("button", { name: "Credential 10 Tenth key" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Add Credential/ }));
  expect(await screen.findByRole("button", { name: "Credential 1" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Credential 10 Tenth key" })).toBeTruthy();
});

test("confirms credential removal and keeps the row when the server rejects it", async () => {
  const saved = {
    id: "key-1",
    name: "Personal",
    provider: "google",
    sequence: 1,
    connection_id: connection.id,
  };
  vi.mocked(api).mockImplementation(async (path, request) => {
    if (path === "/providers" && !request)
      return {
        keys: [saved],
        connections: [{ ...connection, credentials: [saved] }],
      } as never;
    if (path === "/providers/keys/key-1" && request?.method === "DELETE")
      throw new Error("Pause world creation before changing its API key.");
    throw new Error(`Unexpected request ${path}`);
  });

  render(<ProvidersView />);
  fireEvent.click(await screen.findByRole("button", { name: "Google" }));
  fireEvent.click(await screen.findByRole("button", { name: /Credential 1/ }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(screen.getByRole("alertdialog").textContent).toContain("Credential 1");
  fireEvent.click(screen.getByRole("button", { name: "Remove Credential" }));

  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toContain(
      "Pause world creation",
    ),
  );
  expect(screen.getByRole("button", { name: /Credential 1/ })).toBeTruthy();
  expect(vi.mocked(api).mock.calls.filter(([path]) => path === "/providers/keys/key-1"))
    .toHaveLength(1);
});
