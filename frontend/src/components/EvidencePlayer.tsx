import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { captureTime } from "../api/observations";
import type { EvidenceSummary } from "../types";
import Icon from "./Icon";
import "./evidence.css";

export interface SavedEvidence {
  evidence_id: string;
  media_kind: "video" | "audio";
  status: "pending" | "ready" | "partial" | "failed";
  captured_at: string;
  duration_ms: number | null;
  audio_present: boolean;
  message: string | null;
}

/** The cleaned copy of a sound clip: rumble and steady noise down, level raised. */
export function cleanSoundUrl(evidenceId: string): string {
  return `/api/evidence/${encodeURIComponent(evidenceId)}/clean.wav`;
}

/**
 * A saved sound clip with a "Clean" switch (for faint calls at night, such as owls)
 * and its spectrogram (0–8 kHz). The saved clip itself is never changed.
 */
export function SoundClip({
  evidenceId,
  url,
  autoPlay,
  onError,
}: {
  evidenceId: string;
  url: string;
  autoPlay?: boolean;
  onError: () => void;
}) {
  const [cleaned, setCleaned] = useState(false);
  return (
    <div className="sound-clip">
      <audio
        key={cleaned ? "clean" : "original"}
        controls
        autoPlay={autoPlay || cleaned}
        preload="metadata"
        src={cleaned ? cleanSoundUrl(evidenceId) : url}
        aria-label={
          cleaned ? "Saved encounter audio, cleaned" : "Saved encounter audio"
        }
        onError={onError}
      />
      <label
        className="switch-row"
        title="Turns down traffic rumble and steady noise and raises the level, to hear faint calls. The saved clip is not changed."
      >
        <input
          type="checkbox"
          role="switch"
          checked={cleaned}
          onChange={(event) => setCleaned(event.target.checked)}
        />
        <span>Clean</span>
      </label>
      <img
        className="sound-spectrogram"
        src={`/api/evidence/${encodeURIComponent(evidenceId)}/spectrogram.png`}
        alt="Spectrogram of the sound clip, 0 to 8 kHz"
        loading="lazy"
      />
    </div>
  );
}

export function evidenceDescription(item: SavedEvidence): string {
  const duration = !item.duration_ms
    ? ""
    : `${(item.duration_ms / 1000).toFixed(2)} s · `;
  return (
    duration +
    (item.media_kind === "audio"
      ? "Acoustic clip"
      : item.audio_present
        ? "Video + audio"
        : "Silent video")
  );
}

/** The detected animal's box on a saved clip: where, what, and when (wall-clock time). */
export interface ClipBox {
  bbox: [number, number, number, number];
  label: string;
  capturedAt: string | null;
}

/** Milliseconds from the clip start to the detection, or null when unknown. */
export function boxOffsetMs(
  clipStart: string | null,
  detection: string | null,
): number | null {
  if (!clipStart || !detection) return null;
  const offset = Date.parse(detection) - Date.parse(clipStart);
  return Number.isFinite(offset) ? offset : null;
}

/** Show the box around the detected moment; with no timing, show it throughout. */
export function boxVisible(
  offsetMs: number | null,
  currentMs: number,
): boolean {
  return offsetMs === null || Math.abs(currentMs - offsetMs) <= 1500;
}

function ClipVideo({
  url,
  autoPlay,
  box,
  offsetMs,
  onError,
}: {
  url: string;
  autoPlay: boolean;
  box?: ClipBox;
  offsetMs: number | null;
  onError: () => void;
}) {
  const [currentMs, setCurrentMs] = useState(0);
  const [x1, y1, x2, y2] = box?.bbox ?? [0, 0, 0, 0];
  return (
    <div className="clip-frame">
      <video
        controls
        autoPlay={autoPlay}
        playsInline
        preload="metadata"
        src={url}
        aria-label="Saved encounter video"
        onError={onError}
        onLoadedMetadata={(event) => {
          // Open on the detected moment, so the box is on screen straight away.
          if (offsetMs !== null && offsetMs > 0 && !autoPlay)
            event.currentTarget.currentTime = offsetMs / 1000;
        }}
        onTimeUpdate={(event) =>
          setCurrentMs(event.currentTarget.currentTime * 1000)
        }
      />
      {box && x2 > x1 && y2 > y1 && boxVisible(offsetMs, currentMs) && (
        <span
          className="clip-box"
          style={{
            left: `${x1 * 100}%`,
            top: `${y1 * 100}%`,
            width: `${(x2 - x1) * 100}%`,
            height: `${(y2 - y1) * 100}%`,
          }}
        >
          <b>{box.label}</b>
        </span>
      )}
    </div>
  );
}

export default function EvidencePlayer({
  eventId,
  initialEvidence,
  autoPlay = false,
  legacy = false,
  box,
}: {
  eventId: string;
  initialEvidence?: EvidenceSummary[];
  autoPlay?: boolean;
  legacy?: boolean;
  box?: ClipBox;
}) {
  const [playbackErrors, setPlaybackErrors] = useState<string[]>([]);
  const [snapshot, setSnapshot] = useState<{
    key: string;
    items: SavedEvidence[];
    error: string;
  }>({
    key: initialEvidence ? eventId : "",
    items: initialEvidence ?? [],
    error: "",
  });
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let tries = 0;
    async function load() {
      try {
        const data = await api<{ evidence: SavedEvidence[] }>(
          `/evidence?event_id=${encodeURIComponent(eventId)}`,
        );
        if (!alive) return;
        setSnapshot({ key: eventId, items: data.evidence, error: "" });
        if (
          ++tries < 30 &&
          (!data.evidence.length ||
            data.evidence.some((item) => item.status === "pending"))
        )
          timer = setTimeout(() => void load(), 2000);
      } catch (error) {
        if (!alive) return;
        setSnapshot({
          key: eventId,
          items: [],
          error:
            error instanceof ApiError && error.status === 404
              ? ""
              : "Saved evidence could not be loaded.",
        });
      }
    }
    void load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [eventId]);
  if (snapshot.key !== eventId)
    return <p className="review-source-note">Loading saved evidence…</p>;
  if (snapshot.error)
    return (
      <p className="error" role="alert">
        {snapshot.error}
      </p>
    );
  if (!snapshot.items.length)
    return (
      <p className="review-source-note">
        {legacy
          ? "No media was retained for this older session."
          : "No saved media is available for this observation."}
      </p>
    );
  return (
    <section className="saved-evidence" aria-label="Saved encounter evidence">
      {snapshot.items.map((item) => {
        const url = `/api/evidence/${encodeURIComponent(item.evidence_id)}/media`;
        const playable = item.status === "ready" || item.status === "partial";
        const captured = captureTime(item.captured_at);
        const playbackError = () =>
          setPlaybackErrors((previous) =>
            previous.includes(item.evidence_id)
              ? previous
              : [...previous, item.evidence_id],
          );
        return (
          <figure key={item.evidence_id}>
            <figcaption>
              <span>
                <Icon
                  name={item.media_kind === "audio" ? "sound" : "camera"}
                  size={17}
                />
                {evidenceDescription(item)}
              </span>
              {playable && (
                <a href={url} download>
                  <Icon name="download" size={15} />
                  Save clip
                </a>
              )}
            </figcaption>
            {playable ? (
              item.media_kind === "video" ? (
                <ClipVideo
                  url={url}
                  autoPlay={autoPlay}
                  box={box}
                  offsetMs={boxOffsetMs(
                    item.captured_at,
                    box?.capturedAt ?? null,
                  )}
                  onError={playbackError}
                />
              ) : (
                <SoundClip
                  evidenceId={item.evidence_id}
                  url={url}
                  autoPlay={autoPlay}
                  onError={playbackError}
                />
              )
            ) : (
              <p role="status">
                {item.status === "pending"
                  ? "Finishing the encounter clip…"
                  : item.message || "This encounter clip could not be saved."}
              </p>
            )}
            {playbackErrors.includes(item.evidence_id) && (
              <p className="error" role="alert">
                This clip could not be played. Try Save clip to open it in a
                media player.
              </p>
            )}
            {item.status === "partial" && (
              <p className="evidence-note">
                Partial clip ·{" "}
                {item.message ||
                  "The full five-second interval was unavailable."}
              </p>
            )}
            <small>
              {captured ? (
                <>
                  Clip starts{" "}
                  <time dateTime={captured.utc} title={captured.utc}>
                    {captured.date} · {captured.time}
                  </time>{" "}
                  · server receive time
                </>
              ) : (
                "Clip time unavailable"
              )}
            </small>
          </figure>
        );
      })}
    </section>
  );
}
