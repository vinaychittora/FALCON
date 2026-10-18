import { useEffect, useRef, useState } from "react";
import { drawObservationOverlays, observationOverlays } from "../api/overlays";
import type { LiveState } from "../types";
import { contentRect } from "./VideoPlayer";
import { useTaxonNames } from "./TaxonNames";

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
}: {
  state: LiveState;
  show: boolean;
}) {
  const taxonNames = useTaxonNames();
  const image = useRef<HTMLImageElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const [tick, setTick] = useState(0),
    [loaded, setLoaded] = useState(0);
  const active = ["connecting", "live", "reconnecting"].includes(state.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((n) => n + 1), 500);
    return () => clearInterval(timer);
  }, [active]);
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
        observationOverlays(state.visual, taxonNames),
        rect,
        width,
      );
    }
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(img);
    return () => observer.disconnect();
  }, [state.visual, show, loaded, taxonNames]);
  return (
    <div className="player live-preview">
      <img
        ref={image}
        src={`/api/live/preview.jpg?t=${tick}`}
        alt={state.name ? `Live view from ${state.name}` : "Live camera view"}
        onLoad={() => setLoaded((n) => n + 1)}
      />
      <canvas ref={canvas} aria-hidden="true" />
      <span className="live-indicator">
        <i />
        {state.status === "live" ? "LIVE" : state.status.toUpperCase()}
      </span>
    </div>
  );
}
