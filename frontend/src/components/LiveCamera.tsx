import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { drawObservationOverlays, observationOverlays } from "../api/overlays";
import { formatTime } from "../api/timeline";
import type { Config, Detection, LiveState } from "../types";
import Icon from "./Icon";
import ObservationRail from "./ObservationRail";
import SourceTechnical from "./SourceTechnical";
import { contentRect } from "./VideoPlayer";
import { useTaxonNames } from "./TaxonNames";
import "./evidence.css";

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

function LivePreview({ state, show }: { state: LiveState; show: boolean }) {
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

export default function LiveCamera({
  visible,
  fileBusy,
  config,
  onInspect,
  onBusy,
  onSettings,
}: {
  visible: boolean;
  fileBusy: boolean;
  config: Config | null;
  onInspect: (e: Detection) => void;
  onBusy: (active: boolean) => void;
  onSettings: () => void;
}) {
  const [state, setState] = useState<LiveState | null>(null),
    [error, setError] = useState(""),
    [connectionError, setConnectionError] = useState("");
  const [name, setName] = useState("Backyard camera"),
    [url, setUrl] = useState(""),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState("");
  const [audio, setAudio] = useState(true),
    [show, setShow] = useState(true),
    [submitting, setSubmitting] = useState(false);
  const [profile, setProfile] = useState<CameraProfile | null>(null),
    [savedNotice, setSavedNotice] = useState("");
  const edited = useRef(false);
  const reusePassword = canReuseCameraPassword(
    profile,
    url,
    username,
    password,
  );
  useEffect(() => {
    let alive = true;
    api<CameraProfile>("/live/profile")
      .then((next) => {
        if (!alive) return;
        setProfile(next);
        if (next.saved && !edited.current) {
          setName(next.name);
          setUrl(next.url);
          setUsername(next.username);
          setAudio(next.audio_enabled);
        }
      })
      .catch(() => {
        if (alive) setError("Saved camera settings could not be loaded.");
      });
    return () => {
      alive = false;
    };
  }, []);
  const active =
    !!state &&
    ["connecting", "live", "reconnecting", "stopping"].includes(state.status);
  useEffect(() => {
    let alive = true;
    let polling = false;
    const load = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await api<LiveState>("/live/state");
        if (alive) {
          setState(next);
          setConnectionError("");
        }
      } catch {
        if (alive)
          setConnectionError(
            "The camera service is unavailable. Check that FALCON is running, then try again.",
          );
      } finally {
        polling = false;
      }
    };
    void load();
    const timer = setInterval(() => void load(), 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    onBusy(active);
  }, [active, onBusy]);
  async function connect() {
    const validation = validateCameraUrl(url);
    if (validation) {
      setError(validation);
      return;
    }
    if (!config) return;
    setSubmitting(true);
    setError("");
    try {
      const next = await api<LiveState>("/live/start", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim() || "Backyard camera",
          url: url.trim(),
          username: username || undefined,
          password: password || undefined,
          use_saved_credentials: reusePassword,
          save_profile: true,
          config: { ...config, audio_enabled: audio },
        }),
      });
      setState(next);
      setPassword("");
      setProfile(await api<CameraProfile>("/live/profile"));
      setSavedNotice("Camera saved on this device.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }
  async function saveCamera() {
    const validation = validateCameraUrl(url);
    if (validation) {
      setError(validation);
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const next = await api<CameraProfile>("/live/profile", {
        method: "PUT",
        body: JSON.stringify({
          name: name.trim() || "Backyard camera",
          url: url.trim(),
          username,
          ...(reusePassword ? {} : { password }),
          audio_enabled: audio,
        }),
      });
      setProfile(next);
      setPassword("");
      setSavedNotice("Camera saved on this device.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }
  async function forgetCamera() {
    setSubmitting(true);
    setError("");
    try {
      await api<CameraProfile>("/live/profile", { method: "DELETE" });
      setProfile(null);
      setUsername("");
      setPassword("");
      setSavedNotice("Saved camera removed.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }
  async function stop() {
    setSubmitting(true);
    try {
      setState(await api<LiveState>("/live/stop", { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <>
      <div className="workspace">
        <section className="media-stage camera-stage" aria-label="Live camera">
          <div className="stage-heading">
            <div>
              <span className="source-type">
                <Icon name="camera" size={15} /> LIVE CAMERA
              </span>
              <h3>{active ? state?.name : "RTSP camera"}</h3>
            </div>
            {active && (
              <code>
                {formatTime(
                  state?.session_timestamp_ms ??
                    state?.preview_timestamp_ms ??
                    0,
                )}
              </code>
            )}
          </div>
          {visible &&
          active &&
          state?.preview_timestamp_ms !== null &&
          state ? (
            <LivePreview state={state} show={show} />
          ) : active ? (
            <div className="camera-wait">
              <div className="camera-orbit">
                <Icon name="camera" size={34} />
              </div>
              <h3>
                {state?.status === "stopping"
                  ? "Closing the connection"
                  : state?.status === "reconnecting"
                    ? "Reconnecting to your camera"
                    : "Opening your camera"}
              </h3>
              <p>Connecting video and audio.</p>
              <span className="loading-line" />
            </div>
          ) : (
            <form
              className="camera-form"
              onSubmit={(e) => {
                e.preventDefault();
                void connect();
              }}
            >
              <p className="form-intro">
                Connect a local RTSP stream for visual and acoustic analysis.
              </p>
              <div className="form-field">
                <label htmlFor="camera-name">Camera name</label>
                <input
                  id="camera-name"
                  value={name}
                  onChange={(e) => {
                    edited.current = true;
                    setName(e.target.value);
                  }}
                  maxLength={80}
                  placeholder="Backyard camera"
                  autoComplete="off"
                />
              </div>
              <div className="form-field">
                <label htmlFor="camera-url">RTSP address</label>
                <input
                  id="camera-url"
                  type="text"
                  value={url}
                  onChange={(e) => {
                    edited.current = true;
                    setUrl(e.target.value);
                    setSavedNotice("");
                  }}
                  placeholder="rtsp://camera.local/stream1"
                  spellCheck={false}
                  autoComplete="off"
                  required
                />
                <small>
                  Use the camera's local stream address. Add credentials below.
                </small>
              </div>
              <div className="credentials-row">
                <div className="form-field">
                  <label htmlFor="camera-user">Camera username</label>
                  <input
                    id="camera-user"
                    value={username}
                    onChange={(e) => {
                      edited.current = true;
                      setUsername(e.target.value);
                      setSavedNotice("");
                    }}
                    autoComplete="off"
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="camera-password">Camera password</label>
                  <input
                    id="camera-password"
                    type="password"
                    value={password}
                    onChange={(e) => {
                      edited.current = true;
                      setPassword(e.target.value);
                      setSavedNotice("");
                    }}
                    placeholder={
                      reusePassword
                        ? "Saved · leave blank to keep"
                        : "Camera password"
                    }
                    aria-describedby="camera-storage-note"
                    autoComplete="new-password"
                  />
                </div>
              </div>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={audio}
                  onChange={(e) => setAudio(e.target.checked)}
                />
                <Icon name="sound" size={18} /> Analyze camera audio
              </label>
              <div className="form-actions">
                <button
                  className="primary"
                  type="submit"
                  disabled={!config || submitting || fileBusy}
                >
                  {submitting ? "Please wait…" : "Start observation"}
                  <Icon name="arrow" size={17} />
                </button>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => void saveCamera()}
                >
                  Save camera
                </button>
                {profile?.saved && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={submitting}
                    onClick={() => void forgetCamera()}
                  >
                    Forget saved camera
                  </button>
                )}
              </div>
              <small id="camera-storage-note">
                The camera password is encrypted and saved on this device.
              </small>
              {savedNotice && (
                <p role="status" className="muted">
                  {savedNotice}
                </p>
              )}
              {fileBusy && (
                <p className="camera-busy-note">
                  A recording is being analyzed. You can start the camera when
                  it finishes, or pause the analysis in Sources.
                </p>
              )}
            </form>
          )}
          {(error || connectionError || state?.error) && (
            <p role="alert" className="error camera-error">
              {error || connectionError || state?.error}
            </p>
          )}
          {active && (
            <div className="toolbar playback-toolbar">
              <button
                className="stop-button"
                onClick={() => void stop()}
                disabled={submitting || state?.status === "stopping"}
              >
                Stop observation
              </button>
              <label>
                <input
                  type="checkbox"
                  checked={show}
                  onChange={(e) => setShow(e.target.checked)}
                />{" "}
                Show detections
              </label>
              <button
                className="icon-button"
                aria-label="Camera analysis settings"
                onClick={onSettings}
              >
                <Icon name="settings" />
              </button>
            </div>
          )}
          <div className="camera-footnote">
            <Icon name="leaf" size={16} />
            <span>
              {active
                ? `Camera audio · ${(state?.audio_status ?? "waiting").replaceAll("_", " ")}`
                : profile?.saved
                  ? "Saved camera available"
                  : "No camera connected"}
            </span>
            <button className="text-button" onClick={onSettings}>
              Analysis settings
            </button>
          </div>
          <SourceTechnical live={state} />
          {state &&
          (state.metrics.evidence_policy ||
            evidenceRecordingIssue(state.metrics)) ? (
            <div
              className="live-evidence-summary"
              aria-label="Encounter recording status"
            >
              <Icon name="library" size={17} />
              <strong>5-second encounter clips</strong>
              <span>Short rolling buffer · no continuous archive</span>
              {evidenceRecordingIssue(state.metrics) ? (
                <span className="error" role="alert">
                  {evidenceRecordingIssue(state.metrics)}
                </span>
              ) : (
                <span>
                  {Number(state.metrics.evidence_ready_clips || 0) +
                    Number(state.metrics.audio_clips_saved || 0)}{" "}
                  saved · {Number(state.metrics.evidence_pending_clips || 0)}{" "}
                  pending
                </span>
              )}
              <span>Review and export from Observations</span>
            </div>
          ) : null}
        </section>
        <ObservationRail
          visual={state?.visual ?? []}
          audio={state?.audio ?? []}
          audioStatus={state?.audio_status ?? "Waiting for camera"}
          onInspect={onInspect}
          live
        />
      </div>
      {!!state?.messages.length && (
        <details className="technical-detail">
          <summary>Camera connection details</summary>
          <ul className="job-messages">
            {state.messages.map((message, index) => (
              <li key={index}>{message}</li>
            ))}
          </ul>
          <div className="metric-grid">
            {Object.entries(state.metrics).map(([key, value]) => (
              <div key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </details>
      )}
    </>
  );
}
