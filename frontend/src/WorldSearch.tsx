import { useEffect, useRef, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import type { PreviewWorld } from "./collectionPreview";
import { rankWorlds } from "./chronicleSearch";

const MINIMUM_SUGGESTION_QUERY_LENGTH = 1;

export function WorldSearch({
  worlds,
  disabled,
  onSelect,
}: {
  worlds: PreviewWorld[];
  disabled: boolean;
  onSelect: (world: PreviewWorld) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [active, setActive] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const usefulQueryLength = Array.from(query.trim().replace(/\s/g, "")).length;
  const hasUsefulQuery = usefulQueryLength >= MINIMUM_SUGGESTION_QUERY_LENGTH;
  const matches = rankWorlds(worlds, query);
  useEffect(
    () => () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
    },
    [],
  );
  const expanded = open && !disabled && hasUsefulQuery;
  const mounted = (open || closing) && !disabled && hasUsefulQuery;
  function showDropdown() {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = null;
    setClosing(false);
    setOpen(true);
  }
  function hideDropdown() {
    setOpen(false);
    setActive(-1);
    if (!mounted) return;
    setClosing(true);
    if (closeTimer.current) clearTimeout(closeTimer.current);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    closeTimer.current = setTimeout(() => {
      setClosing(false);
      closeTimer.current = null;
    }, reduced ? 0 : 105);
  }
  function select(world: PreviewWorld) {
    hideDropdown();
    setQuery("");
    setActive(-1);
    onSelect(world);
  }
  return (
    <div
      className="search-area"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) hideDropdown();
      }}
    >
      <label className={`search ${disabled ? "disabled" : ""}`}>
        <MagnifyingGlass size={20} weight="light" />
        <input
          ref={input}
          role="combobox"
          aria-label="Search worlds"
          placeholder="Search worlds…"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={expanded ? "world-search-results" : undefined}
          aria-activedescendant={
            expanded && active >= 0
              ? `world-search-option-${active}`
              : undefined
          }
          value={query}
          disabled={disabled}
          onFocus={showDropdown}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(-1);
            showDropdown();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              hideDropdown();
              return;
            }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              if (!hasUsefulQuery) return;
              event.preventDefault();
              setOpen(true);
              const next =
                event.key === "ArrowDown"
                  ? Math.min(active + 1, matches.length - 1)
                  : Math.max(active - 1, 0);
              setActive(next);
              requestAnimationFrame(() =>
                document
                  .getElementById(`world-search-option-${next}`)
                  ?.scrollIntoView?.({ block: "nearest" }),
              );
            }
            if (event.key === "Enter" && expanded && matches.length) {
              event.preventDefault();
              select(matches[active >= 0 ? active : 0]);
            }
          }}
        />
      </label>
      {mounted && (
        <div
          className="search-dropdown"
          data-open={open ? "true" : "false"}
          aria-hidden={!open}
          inert={!open}
        >
          <div
            id="world-search-results"
            role="listbox"
            aria-label="Matching worlds"
          >
            {matches.map((world, index) => (
              <button
                type="button"
                role="option"
                aria-selected={active === index}
                id={`world-search-option-${index}`}
                key={world.id}
                tabIndex={-1}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(world)}
              >
                {world.name}
              </button>
            ))}
          </div>
          {!matches.length && <p role="status">No matching worlds.</p>}
        </div>
      )}
    </div>
  );
}
