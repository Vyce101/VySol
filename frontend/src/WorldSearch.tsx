import { useRef, useState } from "react";
import { MagnifyingGlass } from "@phosphor-icons/react";
import type { PreviewWorld } from "./collectionPreview";

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
  const [active, setActive] = useState(-1);
  const input = useRef<HTMLInputElement>(null);
  const matches = worlds.filter((world) =>
    world.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  const expanded = open && !disabled && !!query.trim();
  function select(world: PreviewWorld) {
    setOpen(false);
    setQuery("");
    setActive(-1);
    onSelect(world);
  }
  return (
    <div
      className="search-area"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
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
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(-1);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
              setActive(-1);
              return;
            }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
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
      {expanded && (
        <div className="search-dropdown">
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
