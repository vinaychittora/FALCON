import { useEffect, useRef, useState, type ReactNode } from "react";
import { drawObservationOverlays, observationOverlays } from "../api/overlays";
import type { LiveState } from "../types";
import { contentRect } from "./VideoPlayer";
import { useTaxonNames } from "./TaxonNames";

/** Matches the server's preview rate (preview_max_fps 5). */
const PREVIEW_INTERVAL_MS = 200;

export interface CameraProfile {
  saved: boolean;
  name: string;
  url: string;
  username: string;
  has_password: boolean;
  audio_enabled: boolean;
  updated_at: string | null;
}

export function canReuseCameraPassword(
  profile: CameraProfile | null,
  url: string,
  username: string,
  password: string,
): boolean {
  return (
    !!profile?.saved &&
    profile.has_password &&
    !password &&
    profile.url === url.trim() &&
    profile.username === username
  );
}

export function validateCameraUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (!["rtsp:", "rtsps:"].includes(parsed.protocol) || !parsed.hostname)
      return "Enter an RTSP camera address, beginning with rtsp://.";
    if (parsed.username || parsed.password)
      return "Put the camera username and password in the separate fields below.";
    return null;
  } catch {
    return "Enter a complete RTSP camera address.";
  }
}

export function evidenceRecordingIssue(metrics: LiveState["metrics"]): string {
  return (
    [
      metrics.evidence_error,
      metrics.evidence_capture_fault,
      metrics.evidence_recording_fault,
    ].find((value): value is string => typeof value === "string" && !!value) ||
    ""
  );
}

export function LivePreview({
  state,
  show,
  showUnresolved = false,
  children,
}: {
  state: LiveState;
  show: boolean;
  /** Also draw boxes that have no species and no group yet. */
  showUnresolved?: boolean;
  /** Extra overlays on the picture (time and frame rate). */
  children?: ReactNode;
}) {
  const taxonNames = useTaxonNames();
  const image = useRef<HTMLImageElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState(0),
    [frame, setFrame] = useState<string | null>(null),
    [waiting, setWaiting] = useState(false);
  const active = ["connecting", "live", "reconnecting"].includes(state.status);
  // Fetch the next preview once the current one has arrived, at most every
  // PREVIEW_INTERVAL_MS (the server renders about 5 previews a second). While no
  // fresh frame is available (the camera or sensor node is restarting), keep the
  // last picture on screen and keep asking once a second until frames return.
  useEffect(() => {
    if (!active) return;
    let stopped = false,
      timer: number | undefined,
      current: string | null = null;
    async function poll() {
      let delay = PREVIEW_INTERVAL_MS;
      try {
        const response = await fetch(`/api/live/preview.jpg?t=${Date.now()}`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(String(response.status));
        const url = URL.createObjectURL(await response.blob());
        if (stopped) {
          URL.revokeObjectURL(url);
          return;
        }
        if (current) URL.revokeObjectURL(current);
        current = url;
        setFrame(url);
        setWaiting(false);
      } catch {
        if (stopped) return;
        setWaiting(true);
        delay = 1000;
      }
      if (!stopped) timer = window.setTimeout(poll, delay);
    }
    poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      if (current) URL.revokeObjectURL(current);
      setFrame(null);
    };
  }, [active]);
  const reconnecting = active && (waiting || state.status === "reconnecting");
  useEffect(() => {
    const img = image.current,
      c = canvas.current;
    if (!img || !c) return;
    function draw() {
      if (!img || !c) return;
      const width = img.clientWidth,
        height = img.clientHeight,
        ratio = window.devicePixelRatio || 1;
      c.width = width * ratio;
      c.height = height * ratio;
      const ctx = c.getContext("2d")!;
      ctx.scale(ratio, ratio);
      if (!show || !img.naturalWidth) return;
      const rect = contentRect(
        width,
        height,
        img.naturalWidth,
        img.naturalHeight,
      );
      drawObservationOverlays(
        ctx,
        observationOverlays(state.visual, taxonNames, { showUnresolved }),
        rect,
        width,
      );
    }
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(img);
    return () => observer.disconnect();
  }, [state.visual, show, showUnresolved, loaded, taxonNames]);
  return (
    <div className="player live-preview">
      <img
        ref={image}
        src={frame ?? undefined}
        hidden={!frame}
        alt={state.name ? `Live view from ${state.name}` : "Live camera view"}
        onLoad={() => setLoaded((n) => n + 1)}
      />
      <canvas ref={canvas} aria-hidden="true" />
      <span className="live-indicator">
        <i />
        {reconnecting
          ? "RECONNECTING"
          : state.status === "live"
            ? "LIVE"
            : state.status.toUpperCase()}
      </span>
      {reconnecting && (
        <span className="live-reconnecting" role="status">
          {frame
            ? "Waiting for the camera. Showing the last picture; it resumes by itself."
            : "Waiting for the camera picture…"}
        </span>
      )}
      {children}
    </div>
  );
}
