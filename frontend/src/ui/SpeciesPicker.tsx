import { useEffect, useId, useMemo, useRef, useState } from "react";
import { scientificSubtitle } from "../api/names";
import { reviewSpeciesOptions } from "../components/Inspector";
import type { Taxon } from "../pages/Taxa";
import type { Detection } from "../types";

/** Compact species search: model alternatives first, then any local taxon by name. */
export default function SpeciesPicker({
  event,
  taxa,
  onPick,
  onCancel,
}: {
  event: Detection;
  taxa: Taxon[];
  onPick: (taxon: Taxon) => void;
  onCancel: () => void;
}) {
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const { options, context } = useMemo(
    () => reviewSpeciesOptions(event, taxa, 0, search),
    [event, taxa, search],
  );
  useEffect(() => input.current?.focus(), []);
  return (
    <div
      className="species-popover"
      role="group"
      aria-label="Choose the correct species"
    >
      <input
        ref={input}
        role="combobox"
        aria-expanded={options.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          options[active] ? `${listId}-${options[active].taxon_id}` : undefined
        }
        placeholder="Type a common or scientific name"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setActive(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            onCancel();
          } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) =>
              Math.max(
                0,
                Math.min(
                  options.length - 1,
                  index + (event.key === "ArrowDown" ? 1 : -1),
                ),
              ),
            );
          } else if (event.key === "Enter" && options[active]) {
            event.preventDefault();
            onPick(options[active]);
          }
          event.stopPropagation();
        }}
      />
      <small>
        {context === "search"
          ? "Best matches"
          : context === "model"
            ? "Model alternatives · type to search"
            : "Type to search all species"}
      </small>
      <ul id={listId} role="listbox" aria-label="Species">
        {options.map((taxon, index) => (
          <li
            key={taxon.taxon_id}
            id={`${listId}-${taxon.taxon_id}`}
            role="option"
            aria-selected={index === active}
          >
            <button
              type="button"
              tabIndex={-1}
              className={index === active ? "active" : ""}
              onMouseEnter={() => setActive(index)}
              onClick={() => onPick(taxon)}
            >
              <strong>{taxon.common_name || taxon.scientific_name}</strong>
              {scientificSubtitle(
                taxon.common_name || taxon.scientific_name,
                taxon.scientific_name,
              ) && <em>{taxon.scientific_name}</em>}
            </button>
          </li>
        ))}
      </ul>
      {!options.length && context === "search" && (
        <p className="muted">No matching species in the local list.</p>
      )}
      <button type="button" className="text-button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
