// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef, useState } from "react";
import {
  filmstripUrl,
  pickable,
  withArticle,
  pickedId,
  visitClip,
  type VisitClip,
} from "../api/inaturalist";

const FRAME = 1 / 15; // the recording's frame step

/** "1:47" for seconds in the recording. */
export function clockAt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
const TILE = 160;

/** Step through the visit's recording and choose frames for the post.
 * Arrow keys: one frame; Shift+arrow: one second. */
export default function FramePicker({
  encounterId,
  canAdd,
  onUse,
  onClose,
  species,
}: {
  encounterId: string;
  canAdd: boolean;
  /** The visit's species, named in the warning outside the visit. */
  species?: string;
  onUse: (id: string) => void;
  onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [clip, setClip] = useState<VisitClip | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(0);
  const [duration, setDuration] = useState(0);
  useEffect(() => {
    let alive = true;
    visitClip(encounterId)
      .then((value) => alive && setClip(value))
      .catch((reason) => alive && setError(String(reason?.message ?? reason)));
    return () => {
      alive = false;
    };
  }, [encounterId]);
  function seek(seconds: number) {
    const element = video.current;
    if (!element || !clip) return;
    element.pause();
    element.currentTime = Math.max(clip.start_s, Math.min(clip.end_s, seconds));
    setNow(element.currentTime);
  }
  function onKey(event: React.KeyboardEvent) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = (event.shiftKey ? 1 : FRAME) * (event.key === "ArrowLeft" ? -1 : 1);
    seek((video.current?.currentTime ?? now) + step);
  }
  if (error) return <p className="banner banner-bad">{error}</p>;
  if (!clip) return <p className="muted">Opening the recording…</p>;
  const near = (t: number) => clip.detections.some((d) => Math.abs(d.t - t) < 0.6);
  // The recording may be longer than the visit: only moments of this visit can be posted.
  const { inside, allowed } = pickable(clip, now);
  return (
    <div className="frame-picker" tabIndex={0} onKeyDown={onKey}>
      <video
        ref={video}
        src={`/api/evidence/${encodeURIComponent(clip.evidence_id)}/media`}
        controls
        muted
        playsInline
        preload="auto"
        onLoadedMetadata={(event) => {
          setDuration(event.currentTarget.duration || 0);
          seek(clip.start_s); // open at the start of this visit, not at 0:00
        }}
        onTimeUpdate={(event) => setNow(event.currentTarget.currentTime)}
      />
      {duration > 0 && (
        <div className="visit-span" aria-hidden="true">
          <span
            className="visit-span-range"
            style={{ left: `${(clip.start_s / duration) * 100}%`, width: `${((clip.end_s - clip.start_s) / duration) * 100}%` }}
          />
          <span className="visit-span-now" style={{ left: `${(now / duration) * 100}%` }} />
        </div>
      )}
      <p className="visit-span-words">
        This visit: {clockAt(clip.start_s)} to {clockAt(clip.end_s)} of the recording
        {duration > 0 ? ` (${clockAt(duration)} long)` : ""}. Green dot: an animal was
        detected in that second.
      </p>
      <div className="filmstrip" role="list" aria-label="Frames of the visit, one per second">
        {clip.filmstrip.map((t, index) => (
          <button
            key={t}
            type="button"
            role="listitem"
            className={`filmstrip-tile${Math.abs(now - t) < 0.5 ? " active" : ""}${near(t) ? " detected" : ""}${t < clip.start_s - 0.5 || t > clip.end_s + 0.5 ? " outside" : ""}`}
            style={{
              backgroundImage: `url(${filmstripUrl(encounterId)})`,
              backgroundPosition: `-${index * TILE}px 0`,
            }}
            title={`${t.toFixed(1)} s${near(t) ? " · animal detected" : ""}`}
            aria-label={`Frame at ${t.toFixed(1)} seconds`}
            onClick={() => seek(t)}
          />
        ))}
      </div>
      <div className="posting-actions">
        <button
          type="button"
          className="primary"
          disabled={!canAdd || !allowed}
          onClick={() => onUse(pickedId(video.current?.currentTime ?? now))}
        >
          Use this frame
        </button>
        <span className="muted">
          {clockAt(now)} ({now.toFixed(2)} s) · ← → one frame · Shift one second
          {allowed && !canAdd ? " · 3 pictures chosen: remove one to add another" : ""}
        </span>
        {!inside && (
          <>
            {allowed ? (
              <span className="visit-outside" role="status">
                Outside this visit ({clockAt(clip.start_s)} to {clockAt(clip.end_s)}). Another
                animal can be in the picture here. Use it only if it shows{" "}
                {species ? withArticle(species) : "the animal of this visit"}.
              </span>
            ) : (
              <span className="visit-outside" role="status">
                This moment is outside this visit. Pick a frame between {clockAt(clip.start_s)} and{" "}
                {clockAt(clip.end_s)}.
              </span>
            )}
            <button type="button" className="pp-btn" onClick={() => seek(clip.start_s)}>
              Go to the visit
            </button>
          </>
        )}
        <button type="button" className="text-button" onClick={onClose}>
          Done
        </button>
      </div>
    </div>
  );
}
