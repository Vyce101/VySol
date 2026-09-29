// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "./api";
import { EmbeddingProfiles } from "./EmbeddingProfiles";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));

afterEach(() => { cleanup(); vi.resetAllMocks(); });

const embeddingModel = {
  id: "embed-v2",
  name: "Vector V2",
  provider: "openai_compatible",
  tested: false,
  capabilities: {
    chat: null,
    embeddings: true,
    input_limit: 8192,
    output_limit: null,
    reasoning_levels: null,
    reasoning_default: null,
    reasoning_off: null,
    thinking_levels: null,
    thinking_default: null,
    thinking_off: null,
    embedding: { dimensions: [1536], max_dimensions: 1536, input_limit: 8192 },
  },
};

const providers = {
  connections: [{ id: "compatible", provider: "openai_compatible", enabled: true }],
  keys: [
    { id: "key-current", name: "Current", provider: "openai_compatible", connection_id: "compatible", base_url: "https://vectors.example/v1", models: [embeddingModel] },
    { id: "key-equivalent", name: "Equivalent", provider: "openai_compatible", connection_id: "compatible", base_url: "https://vectors.example/v1", models: [embeddingModel] },
    { id: "key-other-url", name: "Other Endpoint", provider: "openai_compatible", connection_id: "compatible", base_url: "https://other.example/v1", models: [embeddingModel] },
  ],
  models: [embeddingModel],
};

const primaryProfile = {
  id: "profile-primary",
  name: "Primary Profile",
  key_id: "key-current",
  provider: "openai_compatible",
  model: "embed-v2",
  model_name: "Vector V2",
  dimensions: 1536,
  max_input_tokens: 8192,
  input_format_version: 1,
  is_default: true,
  usable: true,
  credential_name: "Current",
  base_url: "https://vectors.example/v1",
  world_count: 1,
  in_use: true,
  worlds: [{ id: "world-1", name: "World One" }],
};

function setApi(profiles = [primaryProfile]) {
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/providers") return providers as never;
    if (path === "/embedding-profiles") return { profiles, default_profile_id: primaryProfile.id, last_used_profile_id: null } as never;
    if (path === "/embedding-profiles/profile-primary" && init?.method === "PUT") {
      return { ...primaryProfile, key_id: "key-equivalent", credential_name: "Equivalent" } as never;
    }
    throw new Error(`Unexpected request ${path}`);
  });
}

test("shows profile use by World name and prevents removing a profile in use", async () => {
  setApi();
  render(<EmbeddingProfiles />);
  fireEvent.click(await screen.findByRole("button", { name: /Primary Profile/ }));

  expect(screen.queryByText("Choose how each World stores searchable book text.")).toBeNull();
  expect(screen.getByText("Used By")).toBeTruthy();
  expect(screen.getByText("World One")).toBeTruthy();
  expect(screen.queryByText("Default")).toBeNull();
  expect(screen.queryByRole("button", { name: /Make Default|Default Profile/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Move" })).toBeNull();
  expect(screen.queryByLabelText("Move World One to profile")).toBeNull();
  expect(screen.getByRole("button", { name: "Remove" }).hasAttribute("disabled")).toBe(true);
});

test("keeps multiple profile disclosures open independently", async () => {
  const secondProfile = {
    ...primaryProfile,
    id: "profile-secondary",
    name: "Secondary Profile",
    world_count: 0,
    in_use: false,
    worlds: [],
  };
  setApi([primaryProfile, secondProfile]);
  render(<EmbeddingProfiles />);

  const primary = await screen.findByRole("button", { name: /Primary Profile/ });
  const secondary = screen.getByRole("button", { name: /Secondary Profile/ });
  fireEvent.click(primary);
  fireEvent.click(secondary);

  expect(primary.getAttribute("aria-expanded")).toBe("true");
  expect(secondary.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("World One")).toBeTruthy();
  expect(document.querySelectorAll(".embedding-profile-card-body.is-open")).toHaveLength(2);
});

test("allows an in-use profile to switch only to a same-model matching endpoint credential", async () => {
  setApi();
  render(<EmbeddingProfiles />);
  fireEvent.click(await screen.findByRole("button", { name: /Primary Profile/ }));
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));

  const connection = screen.getByLabelText("API Connection");
  expect(screen.getByRole("heading", { name: "Edit Embedding Profile" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Primary Profile" })).toBeNull();
  expect(screen.getByLabelText("Embedding Model").tagName).toBe("OUTPUT");
  expect(screen.queryByLabelText("Dimensions")).toBeNull();
  expect(screen.queryByLabelText("Maximum Input")).toBeNull();
  expect(within(connection).getByRole("option", { name: "OpenAI-compatible · Equivalent" })).toBeTruthy();
  expect(within(connection).queryByRole("option", { name: "OpenAI-compatible · Other Endpoint" })).toBeNull();

  fireEvent.change(connection, { target: { value: "key-equivalent" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Profile" }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith(
    "/embedding-profiles/profile-primary",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ name: "Primary Profile", key_id: "key-equivalent", model: "embed-v2", dimensions: 1536 }),
    }),
  ));
  expect(screen.queryByRole("heading", { name: "Edit Embedding Profile" })).toBeNull();
  expect(screen.queryByLabelText("Profile Name")).toBeNull();
  expect(screen.getByRole("button", { name: "Embedding Profiles" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("button", { name: "Primary Profile" })).toBeTruthy();
});

test("starts dimensions at the model maximum and saves a smaller value", async () => {
  setApi([]);
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/providers") return providers as never;
    if (path === "/embedding-profiles" && init?.method === "POST") return { ...primaryProfile, id: "new-profile", dimensions: 768, usable: true } as never;
    if (path === "/embedding-profiles") return { profiles: [], default_profile_id: null, last_used_profile_id: null } as never;
    throw new Error(`Unexpected request ${path}`);
  });
  render(<EmbeddingProfiles />);
  fireEvent.click(await screen.findByRole("button", { name: "Add Profile" }));
  const dimensions = screen.getByLabelText("Dimensions") as HTMLInputElement;
  expect(dimensions.value).toBe("1536");
  fireEvent.change(screen.getByLabelText("Profile Name"), { target: { value: "Small" } });
  fireEvent.change(dimensions, { target: { value: "768" } });
  fireEvent.click(screen.getByRole("button", { name: "Save Profile" }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledWith(
    "/embedding-profiles",
    expect.objectContaining({ method: "POST", body: JSON.stringify({
      name: "Small", key_id: "key-current", model: "embed-v2", dimensions: 768,
    }) }),
  ));
  expect(screen.queryByLabelText("Profile Name")).toBeNull();
  expect(screen.getByRole("button", { name: "Embedding Profiles" }).getAttribute("aria-expanded")).toBe("true");
});

test("canceling profile edits keeps the Embedding Profiles section open", async () => {
  setApi([]);
  render(<EmbeddingProfiles />);
  fireEvent.click(await screen.findByRole("button", { name: "Add Profile" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(screen.queryByLabelText("Profile Name")).toBeNull();
  expect(screen.getByRole("button", { name: "Embedding Profiles" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("button", { name: "Add Profile" })).toBeTruthy();
});

test("shows an in-progress profile connection as locked while allowing a name edit", async () => {
  const pendingProfile = {
    ...primaryProfile,
    id: "profile-pending",
    name: "Pending Profile",
    world_count: 0,
    pending_count: 1,
    worlds: [{ id: "attempt-1", name: "World in progress" }],
  };
  setApi([pendingProfile]);
  render(<EmbeddingProfiles />);
  fireEvent.click(await screen.findByRole("button", { name: "Pending Profile" }));
  expect(screen.getByText("World in progress")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));

  expect(screen.getByLabelText("API Connection").tagName).toBe("OUTPUT");
  expect(screen.getByLabelText("Profile Name")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Pending Profile" })).toBeNull();
});
