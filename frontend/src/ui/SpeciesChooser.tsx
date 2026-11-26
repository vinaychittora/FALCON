// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { SpeciesLike } from "../api/recordView";
import {
  enterChoice,
  MODEL_SUGGESTIONS,
  speciesChoices,
  type ConfirmedSpecies,
} from "../api/speciesChoice";
import Icon from "../components/Icon";
import "../components/record-view.css";
import { useBackToClose } from "../hooks/useBackToClose";
import type { Detection } from "../types";

export default function SpeciesChooser<T extends SpeciesLike>({
  event,
  taxa,
  onPick,
  onCancel,
  title = "Correct the species",
  withModelSuggestions = true,
}: {
  event: Detection;
  taxa: readonly T[];
  onPick: (taxon: T) => void;
  onCancel: () => void;
  title?: string;
  withModelSuggestions?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [confirmedHere, setConfirmedHere] = useState<ConfirmedSpecies[]>([]);
  useBackToClose(onCancel);
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    input.current?.focus();
    return () => element.close();
  }, []);
  useEffect(() => {
    let alive = true;
    api<{ species: ConfirmedSpecies[] }>("/summary?scope=live&review=verified")
      .then((data) => {
        if (alive) setConfirmedHere(data.species ?? []);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  const choices = useMemo(
    () => speciesChoices(event, taxa, confirmedHere, query),
    [event, taxa, confirmedHere, query],
  );
  const groups = withModelSuggestions
    ? choices.groups
    : choices.groups.filter((group) => group.title !== MODEL_SUGGESTIONS);
  const rows = groups.flatMap((group) => group.rows);
  const current = active < 0 ? -1 : Math.min(active, rows.length - 1);
  const optionId = (taxonId: number) => `${id}-option-${taxonId}`;
  const activeRow = enterChoice(rows, current);
  useEffect(() => {
    if (!activeRow) return;
    document
      .getElementById(optionId(activeRow.taxon.taxon_id))
      ?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRow?.taxon.taxon_id]);
  const rowIndex = new Map(rows.map((row, index) => [row.taxon.taxon_id, index]));
  return (
    <dialog
      ref={dialog}
      className="rv-sheet"
      aria-labelledby={`${id}-title`}
      onCancel={(change) => {
        change.preventDefault();
        change.stopPropagation();
        onCancel();
      }}
      onKeyDown={(change) => change.stopPropagation()}
      onClick={(change) => {
        change.stopPropagation();
        if (change.target === change.currentTarget) onCancel();
      }}
    >
      <div className="rv-sheet-top rv-gut">
        <h2 id={`${id}-title`}>{title}</h2>
        <button
          type="button"
          className="rv-icon"
          aria-label="Close without changing the species"
          onClick={onCancel}
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="rv-search rv-gut">
        <Icon name="search" />
        <label className="rv-sr" htmlFor={`${id}-search`}>
          Search by common or scientific name
        </label>
        <input
          ref={input}
          id={`${id}-search`}
          type="text"
          inputMode="search"
          enterKeyHint="search"
          placeholder="Common or scientific name"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={rows.length > 0}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={
            activeRow ? optionId(activeRow.taxon.taxon_id) : undefined
          }
          value={query}
          onChange={(change) => {
            setQuery(change.target.value);
            setActive(-1);
          }}
          onKeyDown={(change) => {
            const last = rows.length - 1;
            if (change.key === "ArrowDown") {
              change.preventDefault();
              setActive(Math.min(last, current + 1));
            } else if (change.key === "ArrowUp") {
              change.preventDefault();
              setActive(Math.max(0, current - 1));
            } else if (change.key === "Home") {
              change.preventDefault();
              setActive(0);
            } else if (change.key === "End") {
              change.preventDefault();
              setActive(Math.max(0, last));
            } else if (change.key === "Enter") {
              change.preventDefault();
              if (activeRow) onPick(activeRow.taxon);
              else input.current?.blur();
            }
          }}
        />
      </div>
      <div
        ref={list}
        className="rv-options rv-gut"
        id={`${id}-list`}
        role="listbox"
        aria-label="Species"
      >
        {groups.map((group) => (
          <div
            role="group"
            aria-labelledby={`${id}-${group.id}`}
            key={group.id}
          >
            <div className="rv-group-title" id={`${id}-${group.id}`}>
              {group.title}
            </div>
            {group.rows.map((row) => {
              const index = rowIndex.get(row.taxon.taxon_id) ?? 0;
              return (
                <div
                  key={row.taxon.taxon_id}
                  id={optionId(row.taxon.taxon_id)}
                  role="option"
                  aria-selected={index === current}
                  className={`rv-option${index === current ? " active" : ""}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => onPick(row.taxon)}
                >
                  <span>
                    <span className="rv-option-name">
                      {row.taxon.common_name || row.taxon.scientific_name}
                    </span>
                    {row.taxon.common_name && (
                      <span className="rv-option-sci">
                        {row.taxon.scientific_name}
                      </span>
                    )}
                  </span>
                  <span className="rv-option-right">{row.right}</span>
                </div>
              );
            })}
          </div>
        ))}
        {choices.searching && !rows.length && (
          <p className="rv-none" role="status">
            No species with that name. Try fewer letters or the scientific name.
          </p>
        )}
        {!choices.searching && !rows.length && (
          <p className="rv-none">Type a common or scientific name.</p>
        )}
        {choices.total > rows.length && (
          <p className="rv-none">
            Showing the first {rows.length}. Keep typing to narrow the list.
          </p>
        )}
      </div>
    </dialog>
  );
}
