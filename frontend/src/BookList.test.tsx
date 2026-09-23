// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BookList } from "./BookList";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test.each(["drop", "cancel"])(
  "drag lifts a row and marks its destination before %s",
  (ending) => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    HTMLElement.prototype.setPointerCapture = vi.fn();
    const reorder = vi.fn();
    const { container } = render(
      <BookList
        books={[
          { id: "one", filename: "First.txt", size: 10 },
          { id: "two", filename: "Second.txt", size: 10 },
        ]}
        onReorder={reorder}
        onRemove={() => {}}
      />,
    );
    const rows = container.querySelectorAll<HTMLElement>(".selection-row");
    rows.forEach((row, index) =>
      vi
        .spyOn(row, "getBoundingClientRect")
        .mockReturnValue({ top: index * 70, height: 70 } as DOMRect),
    );
    const handle = screen.getByRole("button", { name: "Reorder First.txt" });
    fireEvent.pointerDown(handle, { button: 0, clientY: 30 });
    fireEvent.pointerMove(handle, { clientY: 140 });
    expect(rows[0].classList.contains("is-dragging")).toBe(true);
    expect(rows[1].getAttribute("data-drop-after")).toBe("true");
    expect(reorder).not.toHaveBeenCalled();
    if (ending === "drop") {
      fireEvent.pointerUp(handle);
      expect(reorder).toHaveBeenCalledWith("one", 1);
    } else {
      fireEvent.keyDown(handle, { key: "Escape" });
      expect(reorder).not.toHaveBeenCalled();
    }
    expect(container.querySelector(".is-dragging")).toBeNull();
    expect(container.querySelector("[data-drop-after]")).toBeNull();
  },
);
