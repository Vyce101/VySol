// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BookList } from "./BookList";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("editable story rows show a title and support keyboard reordering and removal", () => {
  const reorder = vi.fn();
  const remove = vi.fn();
  const { container } = render(
    <BookList
      books={[
        { id: "one", filename: "First.txt", size: 10 },
        { id: "two", filename: "Second.epub", size: 10 },
      ]}
      onReorder={reorder}
      onRemove={remove}
    />,
  );
  fireEvent.keyDown(screen.getByRole("button", { name: "Reorder Second.epub" }), {
    key: "ArrowUp",
  });
  expect(reorder).toHaveBeenCalledWith("two", 0);
  expect(container.querySelectorAll(".book-number")[0].textContent).toBe("01");
  expect(container.querySelectorAll(".book-selection-name > span:first-child")[0].textContent).toBe("First");
  expect(screen.queryByText("0.00 MB")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Remove First.txt" }));
  expect(remove).toHaveBeenCalledWith("one");
});

test.each(["drop", "cancel"])(
  "drag lifts a row and reorders without a white destination line when it ends by %s",
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
    expect(rows[1].style.transform).toBe("translateY(-70px)");
    expect(container.querySelector("[data-drop-before], [data-drop-after]")).toBeNull();
    expect(reorder).not.toHaveBeenCalled();
    if (ending === "drop") {
      fireEvent.pointerUp(handle);
      expect(reorder).toHaveBeenCalledWith("one", 1);
    } else {
      fireEvent.keyDown(handle, { key: "Escape" });
      expect(reorder).not.toHaveBeenCalled();
    }
    expect(container.querySelector(".is-dragging")).toBeNull();
  },
);

test("accepted stories are dimmed and cannot be removed or reordered", () => {
  const { container } = render(
    <BookList
      locked
      books={[
        {
          id: "one",
          filename: "The Rise of Kyoshi.txt",
          size: 1000,
          state: "done",
          status: "Complete",
          chunksDone: 10,
          chunksTotal: 10,
        },
      ]}
    />,
  );
  expect(screen.getByText("The Rise of Kyoshi")).toBeTruthy();
  expect(screen.getByText("Complete")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Reorder/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  expect(container.querySelector(".selection-row")?.classList.contains("is-locked")).toBe(true);
  expect(screen.getByLabelText("Chunks embedded for The Rise of Kyoshi.txt")).toBeTruthy();
});
