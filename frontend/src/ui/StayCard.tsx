// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useState } from "react";
import Icon from "../components/Icon";
import { thumbnailUrl, type Encounter } from "../api/encounters";
import { hiddenMoreLine, recordingsLine, stayTimeLine, type StayGroup } from "../api/stays";
import type { Taxon } from "../pages/Taxa";
import EncounterCard, { type DecisionHandler } from "./EncounterCard";

/**
 * One stay: the animals seen in the same footage, each with its own row and its own four
 * decisions (the same card component in row mode, so one decision path). With two or
 * more rows in front a head says how many and when; the hidden visits the filter left out
 * wait behind a closed line. One row and nothing hidden is today's card, untouched.
 */
export default function StayCard({
  stay,
  taxa,
  onDecision,
  onOpen,
  selected,
  onSelect,
}: {
  stay: StayGroup;
  taxa: Taxon[];
  onDecision: DecisionHandler;
  onOpen: (encounter: Encounter) => void;
  selected: Set<string>;
  onSelect: (encounter: Encounter, selected: boolean) => void;
}) {
  const { front, attached } = stay;
  const [imageFailed, setImageFailed] = useState(false);
  const card = (item: Encounter, row: boolean) => (
    <EncounterCard
      key={item.encounter_id}
      encounter={item}
      taxa={taxa}
      onDecision={onDecision}
      onOpen={onOpen}
      selected={selected.has(item.encounter_id)}
      onSelect={onSelect}
      row={row}
    />
  );
  if (front.length === 1 && !attached.length) return card(front[0], false);
  const many = front.length >= 2;
  const headId = `stay-${stay.stayId}`;
  const recordings = (front[0] ?? attached[0])?.stay_recordings;
  const timeLine = stayTimeLine(front.length ? front : attached);
  return (
    <li
      className={`rl-stay${many ? "" : " rl-stay-one"}`}
      aria-labelledby={many ? headId : undefined}
      data-rows={many ? Math.min(front.length, 12) : undefined}
    >
      {many && (
        <div className="rl-stay-head">
          {!imageFailed ? (
            <img
              src={thumbnailUrl(front[0].thumbnail_event_id)}
              alt=""
              loading="lazy"
              onError={() => setImageFailed(true)}
            />
          ) : (
            <span className="c-noimg" aria-hidden="true">
              <Icon name="eye" size={22} />
            </span>
          )}
          <div className="rl-stay-t">
            <h3 id={headId}>{front.length} animals in one stay</h3>
            <span>{timeLine}</span>
            <span>{recordingsLine(recordings)}</span>
          </div>
        </div>
      )}
      <ul className="rl-stay-rows" aria-label={many ? `${front.length} animals` : undefined}>
        {front.map((item) => card(item, many))}
      </ul>
      {attached.length > 0 && (
        <details className="rl-stay-more">
          <summary>{hiddenMoreLine(attached.length)}</summary>
          <ul className="rl-stay-rows">{attached.map((item) => card(item, true))}</ul>
        </details>
      )}
    </li>
  );
}
