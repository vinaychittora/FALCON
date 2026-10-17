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

export default function EvidencePlayer({
  eventId,
  initialEvidence,
  autoPlay = false,
  legacy = false,
}: {
  eventId: string;
  initialEvidence?: EvidenceSummary[];
  autoPlay?: boolean;
  legacy?: boolean;
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
                <video
                  controls
                  autoPlay={autoPlay}
                  playsInline
                  preload="metadata"
                  src={url}
                  aria-label="Saved encounter video"
                  onError={playbackError}
                />
              ) : (
                <audio
                  controls
                  autoPlay={autoPlay}
                  preload="metadata"
                  src={url}
                  aria-label="Saved encounter audio"
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
