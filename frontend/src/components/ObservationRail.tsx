// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useState } from "react";
import { certaintyOf, leadingName } from "../api/certainty";
import { eventTime, formatTime } from "../api/timeline";
import type { AudioEvent, Detection, VisualEvent } from "../types";
import { AudioCards, VisualCards } from "./DetectionCards";
import Icon from "./Icon";
import { useTaxonNames } from "./TaxonNames";

/** What left the frame a moment ago; one tap seeks back to it. */
export function RecentList({
  events,
  onSeek,
  onInspect,
  windowSeconds,
}: {
  events: Detection[];
  onSeek?: (ms: number) => void;
  onInspect: (e: Detection) => void;
  windowSeconds: number;
}) {
  const taxonNames = useTaxonNames();
  if (!events.length) return null;
  return (
    <div className="recent-list" aria-label="Recently seen">
      <span className="eyebrow">Recently seen · last {windowSeconds} s</span>
      <ul>
        {events.map((e) => {
          const certainty = certaintyOf(e);
          return (
            <li
              key={e.event_id}
              className={certainty ? `certainty-${certainty.level}` : ""}
            >
              <button
                type="button"
                className="recent-row"
                title={onSeek ? "Jump to this moment" : "Open for review"}
                onClick={() => (onSeek ? onSeek(eventTime(e)) : onInspect(e))}
              >
                <i aria-hidden="true" />
                <strong>{leadingName(e, taxonNames)}</strong>
                <code>{formatTime(eventTime(e))}</code>
                <Icon
                  name={e.modality === "audio" ? "sound" : "camera"}
                  size={13}
                />
              </button>
              <button
                type="button"
                className="icon-button"
                aria-label={`Review ${leadingName(e, taxonNames)}`}
                onClick={() => onInspect(e)}
              >
                <Icon name="external" size={14} />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function ObservationRail({
  visual,
  audio,
  audioStatus,
  onInspect,
  live = false,
  audioOnly = false,
  recent = [],
  onSeek,
  recentWindowSeconds = 20,
}: {
  visual: VisualEvent[];
  audio: AudioEvent[];
  audioStatus: string;
  onInspect: (e: Detection) => void;
  live?: boolean;
  audioOnly?: boolean;
  /** Detections that left the frame within the recent window, newest first. */
  recent?: Detection[];
  onSeek?: (ms: number) => void;
  recentWindowSeconds?: number;
}) {
  const [channel, setChannel] = useState<"visual" | "audio">("visual");
  const activeChannel = audioOnly ? "audio" : channel;
  const recentForChannel = recent.filter((e) =>
    activeChannel === "visual"
      ? e.modality === "visual"
      : e.modality === "audio",
  );
  return (
    <aside className="observation-rail" aria-label="Current observations">
      <div className="rail-heading">
        <span className="eyebrow">
          {live && activeChannel === "audio"
            ? "LAST 60 SECONDS"
            : "CURRENT POSITION"}
        </span>
        <span className="quiet-dot" />
        <h3>{live ? "Live detections" : "Detections"}</h3>
      </div>
      <div
        className="channel-tabs"
        role="tablist"
        aria-label="Observation channel"
      >
        {!audioOnly && (
          <button
            role="tab"
            aria-selected={activeChannel === "visual"}
            className={activeChannel === "visual" ? "active" : ""}
            onClick={() => setChannel("visual")}
          >
            <Icon name="eye" size={17} /> Visual <span>{visual.length}</span>
          </button>
        )}
        <button
          role="tab"
          aria-selected={activeChannel === "audio"}
          className={activeChannel === "audio" ? "active" : ""}
          onClick={() => setChannel("audio")}
        >
          <Icon name="sound" size={17} /> Acoustic <span>{audio.length}</span>
        </button>
      </div>
      <div className="cards-scroll" role="tabpanel">
        {activeChannel === "visual" ? (
          <VisualCards events={visual} onInspect={onInspect} />
        ) : (
          <>
            <AudioCards events={audio} onInspect={onInspect} />
            <p className="acoustic-caption">
              Acoustic detections are independent of visible subjects.
            </p>
            <p className="audio-status">
              Audio · {audioStatus.replaceAll("_", " ")}
            </p>
          </>
        )}
        <RecentList
          events={recentForChannel}
          onSeek={onSeek}
          onInspect={onInspect}
          windowSeconds={recentWindowSeconds}
        />
      </div>
      {!audioOnly && (
        <p className="rail-note">
          Green likely · orange probable · red faint guess · gray unknown.
          Similarity is not a probability.
        </p>
      )}
    </aside>
  );
}
