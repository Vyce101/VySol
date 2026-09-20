// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { Background } from "./Background";

let images: FakeImage[];
class FakeImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src = "";
  constructor() {
    images.push(this);
  }
}
beforeEach(() => {
  images = [];
  vi.useFakeTimers();
  vi.stubGlobal("Image", FakeImage);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("late image completion cannot replace the latest preview", () => {
  const { container, rerender } = render(
    <Background url="/first.png" speed="normal" />,
  );
  const lateFirst = images[0].onload!;
  rerender(<Background url="/second.png" speed="normal" />);
  act(() => images[1].onload!());
  act(() => lateFirst());
  act(() => vi.advanceTimersByTime(400));
  const layers = container.querySelectorAll(".backdrop-image");
  expect(layers.length).toBe(1);
  expect((layers[0] as HTMLElement).style.backgroundImage).toContain(
    "/second.png",
  );
});

test("rapid return to a previous image keeps layers until the new fade finishes", () => {
  const { container, rerender } = render(
    <Background url="/first.png" speed="slow" />,
  );
  act(() => images[0].onload!());
  rerender(<Background url="/second.png" speed="slow" />);
  act(() => images[1].onload!());
  rerender(<Background url="/first.png" speed="slow" />);
  act(() => images[2].onload!());
  expect(container.querySelectorAll(".backdrop-image").length).toBe(4);
  act(() => vi.advanceTimersByTime(700));
  expect(container.querySelectorAll(".backdrop-image").length).toBe(1);
  expect(
    container.querySelector<HTMLElement>(".backdrop-image")!.style
      .backgroundImage,
  ).toContain("/first.png");
});

test.each([
  ["fast", 150],
  ["normal", 300],
  ["slow", 600],
] as const)(
  "uses %s timing and falls back on failed artwork",
  (speed, duration) => {
    const { container } = render(
      <Background url="/missing.png" speed={speed} />,
    );
    act(() => images[0].onerror!());
    expect(
      container
        .querySelector<HTMLElement>(".backdrop")!
        .style.getPropertyValue("--background-duration"),
    ).toBe(`${duration}ms`);
    expect(
      container.querySelector<HTMLElement>(".backdrop-image")!.style
        .backgroundImage,
    ).toContain("frostwake.png");
  },
);
