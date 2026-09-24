// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { WorldSearch } from "./WorldSearch";

const worlds = [
  { id: "one", name: "Frostwake", created_at: "", last_used_at: null, artwork: "frostwake" },
  { id: "two", name: "Moon Harbor", created_at: "", last_used_at: null, artwork: "frostwake" },
];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

test("search keeps its keyboard and listbox behavior when a world is selected", () => {
  const onSelect = vi.fn();
  render(<WorldSearch worlds={worlds} disabled={false} onSelect={onSelect} />);
  const search = screen.getByRole("combobox", { name: "Search worlds" });
  fireEvent.change(search, { target: { value: "moon" } });
  expect(screen.getByRole("listbox", { name: "Matching worlds" })).toBeTruthy();
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(screen.getByRole("option", { name: "Moon Harbor" }).getAttribute("aria-selected")).toBe("true");
  fireEvent.keyDown(search, { key: "Enter" });
  expect(onSelect).toHaveBeenCalledWith(worlds[1]);
  expect(screen.queryByRole("listbox")).toBeNull();
});

test("search dropdown closes with its short exit animation", () => {
  vi.useFakeTimers();
  render(<WorldSearch worlds={worlds} disabled={false} onSelect={() => {}} />);
  const search = screen.getByRole("combobox", { name: "Search worlds" });
  fireEvent.change(search, { target: { value: "Frost" } });
  fireEvent.blur(search);
  expect(document.querySelector('.search-dropdown[data-open="false"]')).toBeTruthy();
  act(() => vi.advanceTimersByTime(105));
  expect(document.querySelector(".search-dropdown")).toBeNull();
});

test("Escape closes the listbox and clears the active option", () => {
  render(<WorldSearch worlds={worlds} disabled={false} onSelect={() => {}} />);
  const search = screen.getByRole("combobox", { name: "Search worlds" });
  fireEvent.change(search, { target: { value: "Frost" } });
  fireEvent.keyDown(search, { key: "ArrowDown" });
  fireEvent.keyDown(search, { key: "Escape" });
  expect(search.getAttribute("aria-expanded")).toBe("false");
  expect(search.getAttribute("aria-activedescendant")).toBeNull();
});
