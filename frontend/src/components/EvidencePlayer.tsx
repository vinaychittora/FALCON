// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { api, ApiError } from "../api/client";
import { fetchEncounters } from "../api/encounters";
import type { TaxonNameIndex } from "../api/names";
import { captureTime } from "../api/observations";
import { trackOf, visitName } from "../api/stayChips";
import { usePersistentState } from "../hooks/usePersistentState";
import type { EvidenceSummary } from "../types";
import Icon from "./Icon";
import "./evidence.css";

export interface SavedEvidence {
  evidence_id: string;
  media_kind: "video" | "audio";
  status: "pending" | "ready" | "partial" | "failed" | "removed";
  captured_at: string;
  duration_ms: number | null;
  audio_present: boolean;
  message: string | null;
}

export interface EvidenceState {
  loading: boolean;
  error: string;
  items: SavedEvidence[];
}

export const evidenceUrl = (evidenceId: string) =>
  `/api/evidence/${encodeURIComponent(evidenceId)}/media`;

/** The cleaned copy of a sound clip: rumble and steady noise down, level raised. */
export function cleanSoundUrl(evidenceId: string): string {
  return `/api/evidence/${encodeURIComponent(evidenceId)}/clean.wav`;
}

export function evidenceDescription(item: SavedEvidence): string {
  const duration = !item.duration_ms
    ? ""
    : `${(item.duration_ms / 1000).toFixed(2)} s · `;
  return duration + evidenceKind(item);
}

export function evidenceKind(item: SavedEvidence): string {
  return item.media_kind === "audio"
    ? "Acoustic clip"
    : item.audio_present
      ? "Video + audio"
      : "Silent video";
}

/** The detected animal's box on a saved clip: where, what, and when (wall-clock time). */
export interface ClipBox {
  bbox: [number, number, number, number];
  label: string;
  capturedAt: string | null;
  /** After Confirm or Correct: green, labelled with the final name. */
  final?: boolean;
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

/** One stored detection inside a recording, timed from its start. */
export interface StoredBox {
  t: number;
  bbox: [number, number, number, number];
  track: string;
  own: boolean;
  tone: "likely" | "probable" | "faint";
  label: string;
}

/** The boxes to draw at a moment: each track's detection nearest to it (within 0.4 s). */
export function boxesAt(boxes: StoredBox[], currentMs: number): StoredBox[] {
  const nearest = new Map<string, StoredBox>();
  for (const box of boxes) {
    const gap = Math.abs(box.t - currentMs);
    if (gap > 400) continue;
    const seen = nearest.get(box.track);
    if (!seen || gap < Math.abs(seen.t - currentMs)) nearest.set(box.track, box);
  }
  return [...nearest.values()];
}

/** While a stay is being recorded: "Recording, 42 s so far…". */
export function recordingNote(
  item: { media_kind: string; captured_at: string },
  now = Date.now(),
): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(item.captured_at)) / 1000));
  return item.media_kind === "video"
    ? `Recording, ${seconds} s so far… the whole stay appears here when the animal has left.`
    : `Recording the calls, ${seconds} s so far…`;
}

/** "Whole stay · 4:15 · 07:25:03" for the list of a visit's pieces. */
export function pieceLabel(item: SavedEvidence): string {
  const seconds = Math.round((item.duration_ms ?? 0) / 1000);
  const length = seconds >= 60 ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}` : `${seconds} s`;
  const kind =
    item.media_kind === "audio"
      ? "Sound"
      : (item.message ?? "").startsWith("Whole stay")
        ? "Whole stay"
        : "Clip";
  const at = captureTime(item.captured_at);
  return `${kind} · ${item.status === "pending" ? "recording…" : length}${at ? ` · ${at.time}` : ""}`;
}

export function useSavedEvidence(
  eventId: string,
  initialEvidence?: EvidenceSummary[],
): EvidenceState {
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
        // A stay recording stays pending while the animal is there: keep looking
        // (every 5 s, up to 15 minutes) so it appears when it is saved.
        if (
          ++tries < 180 &&
          (!data.evidence.length ||
            data.evidence.some((item) => item.status === "pending"))
        )
          timer = setTimeout(() => void load(), tries < 15 ? 2000 : 5000);
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
  return {
    loading: snapshot.key !== eventId,
    error: snapshot.key === eventId ? snapshot.error : "",
    items: snapshot.key === eventId ? snapshot.items : [],
  };
}

export const clockText = (seconds: number) => {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
};

function useMediaClock(ref: RefObject<HTMLMediaElement | null>, sourceKey: string) {
  const [clock, setClock] = useState({
    playing: false,
    waiting: false,
    muted: false,
    current: 0,
    duration: 0,
  });
  useEffect(() => {
    const media = ref.current;
    if (!media) return;
    let frame = 0;
    const read = (waiting?: boolean) =>
      setClock((previous) => ({
        playing: !media.paused && !media.ended,
        waiting: waiting ?? previous.waiting,
        muted: media.muted,
        current: media.currentTime,
        duration: Number.isFinite(media.duration) ? media.duration : 0,
      }));
    const tick = () => {
      if (!media.paused) read();
      frame = requestAnimationFrame(tick);
    };
    const plain = () => read();
    const busy = () => read(true);
    const free = () => read(false);
    const events: [string, () => void][] = [
      ["loadedmetadata", free],
      ["durationchange", plain],
      ["play", plain],
      ["pause", plain],
      ["ended", plain],
      ["timeupdate", plain],
      ["seeked", free],
      ["volumechange", plain],
      ["waiting", busy],
      ["stalled", busy],
      ["playing", free],
      ["canplay", free],
    ];
    events.forEach(([name, handler]) => media.addEventListener(name, handler));
    frame = requestAnimationFrame(tick);
    read();
    return () => {
      cancelAnimationFrame(frame);
      events.forEach(([name, handler]) =>
        media.removeEventListener(name, handler),
      );
    };
  }, [ref, sourceKey]);
  return clock;
}

function seekMedia(element: HTMLMediaElement | null, seconds: number) {
  if (element) element.currentTime = seconds;
}

function toggleMute(element: HTMLMediaElement | null) {
  if (element) element.muted = !element.muted;
}

function MediaControls({
  media,
  clock,
  stretch,
  label,
  onFullscreen,
  inside,
}: {
  media: RefObject<HTMLMediaElement | null>;
  clock: ReturnType<typeof useMediaClock>;
  stretch: [number, number] | null;
  label: string;
  onFullscreen?: () => void;
  inside: boolean;
}) {
  const duration = clock.duration;
  const from = stretch && duration ? Math.min(100, (stretch[0] / 1000 / duration) * 100) : 0;
  const to = stretch && duration
    ? Math.min(100, Math.max(from + 1, (stretch[1] / 1000 / duration) * 100))
    : 0;
  const plain = "rgba(255,255,255,.32)";
  const track = stretch && duration
    ? `linear-gradient(to right, ${plain} 0 ${from}%, var(--accent-fill) ${from}% ${to}%, ${plain} ${to}%)`
    : plain;
  return (
    <div className={`rv-controls rv-gut${inside ? " inside" : ""}`}>
      <button
        type="button"
        className="rv-icon"
        aria-label={clock.playing ? "Pause" : "Play"}
        onClick={() => {
          const element = media.current;
          if (!element) return;
          if (element.paused) void element.play().catch(() => undefined);
          else element.pause();
        }}
      >
        <Icon name={clock.playing ? "pause" : "play"} />
      </button>
      <span className="rv-time">
        {clock.waiting
          ? "Loading…"
          : `${clockText(clock.current)} / ${clockText(duration)}`}
      </span>
      <input
        className="rv-seek"
        type="range"
        min={0}
        max={duration || 0}
        step={0.1}
        value={Math.min(clock.current, duration || 0)}
        disabled={!duration}
        aria-label={label}
        aria-valuetext={`${clockText(clock.current)} of ${clockText(duration)}`}
        style={{ "--rv-track": track } as CSSProperties}
        onChange={(change) =>
          seekMedia(media.current, Number(change.target.value))
        }
      />
      <button
        type="button"
        className="rv-icon"
        aria-label={clock.muted ? "Unmute" : "Mute"}
        onClick={() => toggleMute(media.current)}
      >
        <Icon name={clock.muted ? "volumeOff" : "volume"} />
      </button>
      {onFullscreen && (
        <button
          type="button"
          className="rv-icon"
          aria-label="Full screen"
          onClick={onFullscreen}
        >
          <Icon name="focus" />
        </button>
      )}
    </div>
  );
}

function RecordSwitch({
  label,
  checked,
  title,
  onChange,
}: {
  label: string;
  checked: boolean;
  title: string;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      className="rv-switch"
      role="switch"
      aria-checked={checked}
      title={title}
      onClick={() => onChange(!checked)}
    >
      <span className="rv-switch-track" aria-hidden="true" />
      {label}
    </button>
  );
}

function ToolsRow({
  jumpLabel,
  onJump,
  children,
}: {
  jumpLabel: string;
  onJump?: () => void;
  children: ReactNode;
}) {
  return (
    <div className="rv-tools rv-gut">
      {onJump ? (
        <button type="button" className="rv-tool" onClick={onJump}>
          <Icon name="chevronDown" size={16} /> {jumpLabel}
        </button>
      ) : (
        <span />
      )}
      {children}
    </div>
  );
}

/** The chosen animal's boxes and stretch on a recording, worked out here so that picking
 * another animal of the stay changes them without loading anything again. */
export function ownBoxes(
  boxes: StoredBox[],
  ownTrack: string | null,
  serverSpan: [number, number] | null,
): { boxes: StoredBox[]; span: [number, number] | null } {
  if (ownTrack === null) return { boxes, span: serverSpan };
  const marked = boxes.map((b) => ({ ...b, own: b.track === ownTrack }));
  const times = marked.filter((b) => b.own).map((b) => b.t);
  return { boxes: marked, span: times.length ? [Math.min(...times), Math.max(...times)] : null };
}

/** The boxes drawn at a moment: none with the Boxes switch off (their names go with them,
 * as each name sits inside its box), and none for a discarded visit; Undo of the
 * discard takes the visit out of dropTracks, so its box comes back at once. */
export function drawnBoxes(
  boxes: StoredBox[],
  currentMs: number,
  boxesOn: boolean,
  dropTracks?: Set<string>,
): StoredBox[] {
  if (!boxesOn) return [];
  return boxesAt(boxes, currentMs).filter((b) => !dropTracks?.has(b.track));
}

/** The visits seen on a recording, by box track, named as Review names them (rule 1). */
function useVisitNames(
  tracks: string[],
  known: ((track: string) => string | undefined) | undefined,
  clip: { sourceId: string; capturedAt: string; durationMs: number | null } | undefined,
  names?: TaxonNameIndex,
): Map<string, string> {
  const [fetched, setFetched] = useState<Map<string, string>>(new Map());
  const missing = tracks.filter((track) => !known?.(track)).sort().join("|");
  const sourceId = clip?.sourceId;
  const capturedAt = clip?.capturedAt;
  const durationMs = clip?.durationMs ?? 0;
  useEffect(() => {
    if (!missing || !sourceId || !capturedAt) return;
    const start = Date.parse(capturedAt);
    if (!Number.isFinite(start)) return;
    let alive = true;
    fetchEncounters({
      scope: "all",
      source_id: sourceId,
      modality: "visual",
      captured_from: new Date(start - 120_000).toISOString(),
      captured_to: new Date(start + durationMs + 5000).toISOString(),
      limit: 200,
    })
      .then((page) => {
        if (!alive) return;
        setFetched(new Map(page.encounters.map((item) => [trackOf(item.encounter_id), visitName(item, names)])));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [missing, sourceId, capturedAt, durationMs, names]);
  return fetched;
}

function ClipVideo({
  url,
  evidenceId,
  eventId,
  autoPlay,
  box,
  offsetMs,
  pieces,
  onError,
  ownKey = null,
  labelFor,
  clip,
  names,
  onTracks,
  dropTracks,
}: {
  url: string;
  evidenceId: string;
  eventId: string;
  autoPlay: boolean;
  box?: ClipBox;
  offsetMs: number | null;
  pieces: ReactNode;
  onError: () => void;
  /** The animal of the stay the view describes now (a chip); null: the opened record. */
  ownKey?: string | null;
  /** A name for a box's visit that the view already knows (rule 1). */
  labelFor?: (track: string) => string | undefined;
  clip?: { sourceId: string; capturedAt: string; durationMs: number | null };
  names?: TaxonNameIndex;
  /** The visits that have boxes on this recording, once they are loaded. */
  onTracks?: (tracks: Set<string>) => void;
  dropTracks?: Set<string>;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  // The same switch as "Detection boxes" on Live: one setting, remembered.
  const [boxesOn, setBoxesOn] = usePersistentState<boolean>("live.boxes", true);
  const [ratio, setRatio] = useState("16 / 9");
  const [native, setNative] = useState(false);
  const [stored, setStored] = useState<{ boxes: StoredBox[]; own_span: [number, number] | null } | null>(null);
  const clock = useMediaClock(video, url);
  // The boxes are asked for once per recording; picking another animal of the stay
  // works on what is here.
  const firstEvent = useRef(eventId);
  useEffect(() => {
    let alive = true;
    api<{ boxes: StoredBox[]; own_span: [number, number] | null }>(
      `/evidence/${encodeURIComponent(evidenceId)}/boxes?event_id=${encodeURIComponent(firstEvent.current)}`,
    )
      .then((value) => {
        if (alive) setStored(value);
      })
      .catch(() => {
        if (alive) setStored(null);
      });
    return () => {
      alive = false;
    };
  }, [evidenceId]);
  const tracks = [...new Set((stored?.boxes ?? []).map((b) => b.track))];
  const trackKey = tracks.sort().join("|");
  useEffect(() => {
    if (stored) onTracks?.(new Set(trackKey ? trackKey.split("|") : []));
  }, [stored, trackKey, onTracks]);
  const fetchedNames = useVisitNames(tracks, labelFor, clip, names);
  const own = ownBoxes(stored?.boxes ?? [], ownKey === null ? null : trackOf(ownKey), stored?.own_span ?? null);
  const currentMs = clock.current * 1000;
  const span = own.span;
  const start = span ? span[0] : offsetMs;
  // Picking another animal: the recording goes to its first moment, as "Jump to this
  // animal" does; a paused player stays paused, a playing one goes on from there.
  const shownKey = useRef(ownKey);
  useEffect(() => {
    if (shownKey.current === ownKey) return;
    shownKey.current = ownKey;
    if (video.current && start !== null)
      video.current.currentTime = Math.max(0, start - 1000) / 1000;
  }, [ownKey, start]);
  // Stored detections when there are any; otherwise the one box of this record.
  const shown: StoredBox[] = !boxesOn
    ? []
    : stored?.boxes.length
      ? drawnBoxes(own.boxes, currentMs, boxesOn, dropTracks)
      : box && boxVisible(offsetMs, currentMs)
        ? [{ t: 0, bbox: box.bbox, track: "own", own: true, tone: "probable", label: box.label }]
        : [];
  const nameOf = (b: StoredBox) =>
    b.own && box?.final ? box.label : labelFor?.(b.track) ?? fetchedNames.get(b.track) ?? (b.own ? box?.label : undefined) ?? b.label;
  const jump = start === null
    ? undefined
    : () => {
        if (video.current)
          video.current.currentTime = Math.max(0, start - 1000) / 1000;
      };
  return (
    <>
      <div className="rv-frame" ref={frame} style={{ aspectRatio: ratio }}>
        <video
          ref={video}
          autoPlay={autoPlay}
          playsInline
          preload="metadata"
          src={url}
          controls={native}
          aria-label="Saved encounter video"
          onError={() => {
            setNative(true);
            onError();
          }}
          onClick={(event) => {
            if (event.currentTarget.paused)
              void event.currentTarget.play().catch(() => undefined);
            else event.currentTarget.pause();
          }}
          onLoadedMetadata={(event) => {
            const { videoWidth, videoHeight } = event.currentTarget;
            if (videoWidth && videoHeight)
              setRatio(`${videoWidth} / ${videoHeight}`);
            // Open where this animal is, so its box is on screen straight away.
            if (start !== null && start > 0 && !autoPlay)
              event.currentTarget.currentTime = Math.max(0, start - 1000) / 1000;
          }}
        />
        {shown.map((b) => {
          const [x1, y1, x2, y2] = b.bbox;
          if (!(x2 > x1 && y2 > y1)) return null;
          const tone = b.own && box?.final ? "likely" : b.tone;
          // Widened by 25 % of the box (at least 16 px) on every side, kept in the picture.
          const padX = `max(${((x2 - x1) * 25).toFixed(2)}%, 16px)`;
          const padY = `max(${((y2 - y1) * 25).toFixed(2)}%, 16px)`;
          return (
            <span
              key={b.track}
              className={`clip-box tone-${tone}${b.own ? " own" : ""}${y1 < 0.12 ? " label-below" : ""}`}
              style={{
                left: `max(0%, calc(${(x1 * 100).toFixed(2)}% - ${padX}))`,
                right: `max(0%, calc(${((1 - x2) * 100).toFixed(2)}% - ${padX}))`,
                top: `max(0%, calc(${(y1 * 100).toFixed(2)}% - ${padY}))`,
                bottom: `max(0%, calc(${((1 - y2) * 100).toFixed(2)}% - ${padY}))`,
              }}
            >
              <b>{nameOf(b)}</b>
            </span>
          );
        })}
        {!native && <MediaControls
          inside
          media={video}
          clock={clock}
          stretch={span}
          label="Position in the recording. The marked stretch is this animal"
          onFullscreen={() => {
            const element = video.current as (HTMLVideoElement & {
              webkitEnterFullscreen?: () => void;
            }) | null;
            if (frame.current?.requestFullscreen)
              void frame.current.requestFullscreen().catch(() => undefined);
            else element?.webkitEnterFullscreen?.();
          }}
        />}
      </div>
      {pieces}
      <ToolsRow jumpLabel="Jump to this animal" onJump={jump}>
        <RecordSwitch
          label="Boxes"
          checked={boxesOn}
          title="Show or hide the detection boxes (same switch as on Live)"
          onChange={setBoxesOn}
        />
      </ToolsRow>
    </>
  );
}

/**
 * A saved sound clip with its spectrogram (0–8 kHz) and a "Clean" switch (for faint
 * calls at night, such as owls). The saved clip itself is never changed.
 */
export function SoundClip({
  evidenceId,
  url,
  autoPlay,
  offsetMs = null,
  lengthMs = 3000,
  pieces,
  onError,
}: {
  evidenceId: string;
  url: string;
  autoPlay?: boolean;
  offsetMs?: number | null;
  lengthMs?: number;
  pieces?: ReactNode;
  onError: () => void;
}) {
  const [cleaned, setCleaned] = useState(false);
  const [native, setNative] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const resume = useRef<{ time: number; play: boolean } | null>(null);
  const src = cleaned ? cleanSoundUrl(evidenceId) : url;
  const clock = useMediaClock(audio, src);
  return (
    <>
      <div className="rv-frame spec">
        <img
          src={`/api/evidence/${encodeURIComponent(evidenceId)}/spectrogram.png`}
          alt="Spectrogram of the sound clip, 0 to 8 kHz"
          loading="lazy"
        />
      </div>
      <audio
        key={src}
        ref={audio}
        autoPlay={autoPlay}
        preload="metadata"
        src={src}
        controls={native}
        className={native ? "rv-native-audio" : undefined}
        aria-label={
          cleaned ? "Saved encounter audio, cleaned" : "Saved encounter audio"
        }
        onError={() => {
          setNative(true);
          onError();
        }}
        onLoadedMetadata={(event) => {
          const saved = resume.current;
          resume.current = null;
          if (saved) {
            event.currentTarget.currentTime = saved.time;
            if (saved.play) void event.currentTarget.play().catch(() => undefined);
          } else if (offsetMs !== null && offsetMs > 0 && !autoPlay) {
            event.currentTarget.currentTime = Math.max(0, offsetMs - 1000) / 1000;
          }
        }}
      />
      {!native && <MediaControls
        inside={false}
        media={audio}
        clock={clock}
        stretch={offsetMs === null ? null : [offsetMs, offsetMs + lengthMs]}
        label="Position in the recording. The marked stretch is this call"
      />}
      {pieces}
      <ToolsRow
        jumpLabel="Jump to the call"
        onJump={
          offsetMs === null
            ? undefined
            : () => {
                if (audio.current)
                  audio.current.currentTime = Math.max(0, offsetMs - 1000) / 1000;
              }
        }
      >
        <RecordSwitch
          label="Clean"
          checked={cleaned}
          title="Turns down traffic rumble and steady noise and raises the level, to hear faint calls. The saved clip is not changed."
          onChange={(value) => {
            resume.current = {
              time: audio.current?.currentTime ?? 0,
              play: audio.current ? !audio.current.paused : false,
            };
            setCleaned(value);
          }}
        />
      </ToolsRow>
    </>
  );
}

export default function RecordMedia({
  eventId,
  evidence,
  current,
  onChoose,
  autoPlay = false,
  legacy = false,
  box,
  sound,
  ownKey = null,
  labelFor,
  sourceId,
  names,
  onTracks,
  dropTracks,
}: {
  eventId: string;
  evidence: EvidenceState;
  current: SavedEvidence | null;
  onChoose: (evidenceId: string) => void;
  autoPlay?: boolean;
  legacy?: boolean;
  box?: ClipBox;
  sound?: { capturedAt: string | null; lengthMs: number };
  /** The stay's chosen animal (chips); null: the opened record. */
  ownKey?: string | null;
  labelFor?: (track: string) => string | undefined;
  sourceId?: string;
  names?: TaxonNameIndex;
  onTracks?: (evidenceId: string, tracks: Set<string>) => void;
  /** Visits discarded since the boxes loaded: not drawn, as the server leaves them out. */
  dropTracks?: Set<string>;
}) {
  const [failed, setFailed] = useState<string[]>([]);
  if (evidence.loading)
    return <p className="rv-media-note">Loading saved evidence…</p>;
  if (evidence.error)
    return (
      <p className="rv-media-note error" role="alert">
        {evidence.error}
      </p>
    );
  if (!current)
    return (
      <p className="rv-media-note">
        {legacy
          ? "No media was retained for this older session."
          : "No saved media is available for this observation."}
      </p>
    );
  const url = evidenceUrl(current.evidence_id);
  const playable = current.status === "ready" || current.status === "partial";
  const onError = () =>
    setFailed((previous) =>
      previous.includes(current.evidence_id)
        ? previous
        : [...previous, current.evidence_id],
    );
  const pieces =
    evidence.items.length > 1 ? (
      <div className="rv-pieces rv-gut" aria-label="Recordings of this visit">
        {evidence.items.map((item) => (
          <button
            key={item.evidence_id}
            type="button"
            aria-pressed={item.evidence_id === current.evidence_id}
            onClick={() => onChoose(item.evidence_id)}
          >
            {pieceLabel(item)}
          </button>
        ))}
      </div>
    ) : null;
  return (
    <>
      {playable ? (
        current.media_kind === "video" ? (
          <ClipVideo
            key={current.evidence_id}
            url={url}
            evidenceId={current.evidence_id}
            eventId={eventId}
            autoPlay={autoPlay}
            box={box}
            offsetMs={boxOffsetMs(current.captured_at, box?.capturedAt ?? null)}
            pieces={pieces}
            onError={onError}
            ownKey={ownKey}
            labelFor={labelFor}
            clip={sourceId ? { sourceId, capturedAt: current.captured_at, durationMs: current.duration_ms } : undefined}
            names={names}
            onTracks={onTracks ? (tracks) => onTracks(current.evidence_id, tracks) : undefined}
            dropTracks={dropTracks}
          />
        ) : (
          <SoundClip
            key={current.evidence_id}
            evidenceId={current.evidence_id}
            url={url}
            autoPlay={autoPlay}
            offsetMs={boxOffsetMs(current.captured_at, sound?.capturedAt ?? null)}
            lengthMs={sound?.lengthMs}
            pieces={pieces}
            onError={onError}
          />
        )
      ) : (
        <>
          <p className="rv-media-note" role="status">
            {current.status === "pending"
              ? recordingNote(current)
              : current.message || "This encounter clip could not be saved."}
          </p>
          {pieces}
        </>
      )}
      {failed.includes(current.evidence_id) && (
        <p className="rv-media-note error" role="alert">
          This clip could not be played. Try Save clip under Recording to open
          it in a media player.
        </p>
      )}
      {current.status === "partial" && (
        <p className="rv-media-note warning">
          Partial clip ·{" "}
          {current.message || "The full five-second interval was unavailable."}
        </p>
      )}
    </>
  );
}
