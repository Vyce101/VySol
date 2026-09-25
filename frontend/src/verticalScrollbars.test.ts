// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
import { installVerticalScrollbarVisibility } from "./verticalScrollbars";

let uninstall: (() => void) | undefined;

afterEach(() => {
  uninstall?.();
  uninstall = undefined;
  document.body.replaceChildren();
  vi.useRealTimers();
});

function makeScrollArea() {
  const area = document.createElement("div");
  area.style.overflowY = "auto";
  document.body.append(area);
  return area;
}

test("shows a vertical scrollbar only while the area is moving", () => {
  vi.useFakeTimers();
  uninstall = installVerticalScrollbarVisibility();
  const area = makeScrollArea();

  area.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 40 }));
  area.scrollTop = 24;
  area.dispatchEvent(new Event("scroll", { bubbles: true }));

  expect(area.classList.contains("show-vertical-scrollbar")).toBe(true);
  vi.advanceTimersByTime(850);
  expect(area.classList.contains("show-vertical-scrollbar")).toBe(false);
  expect(area.classList.contains("fade-vertical-scrollbar")).toBe(true);
  vi.advanceTimersByTime(250);
  expect(area.classList.contains("fade-vertical-scrollbar")).toBe(false);
});

test("does not reveal a scrollbar on hover or horizontal movement", () => {
  uninstall = installVerticalScrollbarVisibility();
  const area = makeScrollArea();

  area.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  expect(area.classList.contains("show-vertical-scrollbar")).toBe(false);

  area.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
  area.scrollLeft = 24;
  area.dispatchEvent(new Event("scroll", { bubbles: true }));
  expect(area.classList.contains("show-vertical-scrollbar")).toBe(false);
});
