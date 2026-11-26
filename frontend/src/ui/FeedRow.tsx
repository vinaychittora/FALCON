// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useState } from "react";
import Icon from "../components/Icon";
import { useTaxonNames } from "../components/TaxonNames";
import {
  encounterNames,
  thumbnailUrl,
  type Encounter,
} from "../api/encounters";
import { formatClock } from "../api/format";
import {
  FEED_MARK_TITLES,
  feedMark,
  feedName,
  feedScore,
} from "../api/liveFeed";

/**
 * One line of the Live sidebar: thumbnail, name, time, status dot and confidence.
 * Review decisions live in the detail dialog that a click opens.
 */
export default function FeedRow({
  encounter,
  onOpen,
}: {
  encounter: Encounter;
  onOpen: (encounter: Encounter) => void;
}) {
  const names = useTaxonNames();
  const [imageFailed, setImageFailed] = useState(false);
  const primary = feedName(
    encounterNames(encounter.event, names).primary,
    encounter,
  );
  const mark = feedMark(encounter) ?? "unknown";
  const score = feedScore(encounter);
  const when = formatClock(encounter.first_captured_at);
  const sound = encounter.modality === "audio";
  return (
    <button
      type="button"
      className="feed-row"
      data-mark={mark}
      onClick={() => onOpen(encounter)}
      title={`${FEED_MARK_TITLES[mark]}. Open for clip, details and review.`}
      aria-label={`${primary}, ${FEED_MARK_TITLES[mark]}, ${when}. Open details`}
    >
      <span className="feed-row-thumb">
        {!imageFailed ? (
          <img
            src={thumbnailUrl(encounter.thumbnail_event_id)}
            alt=""
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <Icon name={sound ? "sound" : "eye"} size={18} />
        )}
      </span>
      <Icon name={sound ? "sound" : "camera"} size={13} />
      <strong>{primary}</strong>
      <time>{when}</time>
      <i className={`feed-dot feed-dot-${mark}`} aria-hidden="true" />
      <span className="feed-score">
        {score === null ? "—" : score.toFixed(2)}
      </span>
    </button>
  );
}
