import { useState } from "react";
import type { AudioEvent, Detection, VisualEvent } from "../types";
import { AudioCards, VisualCards } from "./DetectionCards";
import Icon from "./Icon";

export default function ObservationRail({
  visual,
  audio,
  audioStatus,
  onInspect,
  live = false,
  audioOnly = false,
}: {
  visual: VisualEvent[];
  audio: AudioEvent[];
  audioStatus: string;
  onInspect: (e: Detection) => void;
  live?: boolean;
  audioOnly?: boolean;
}) {
  const [channel, setChannel] = useState<"visual" | "audio">("visual");
  const activeChannel = audioOnly ? "audio" : channel;
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
      </div>
      {!audioOnly && (
        <p className="rail-note">
          Visual similarity is not a calibrated probability.
        </p>
      )}
    </aside>
  );
}
