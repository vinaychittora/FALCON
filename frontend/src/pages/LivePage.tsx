import { useEffect, useMemo, useRef, useState } from "react";
import { useFullscreen } from "../components/fullscreen";
import DetectionBell from "../ui/DetectionBell";
import LiveListen from "../ui/LiveListen";
import { sensorHref } from "./SensorSettings";
import { api } from "../api/client";
import {
  fetchEncounters,
  liveSourceId,
  type Encounter,
} from "../api/encounters";
import { fetchSummary } from "../api/summary";
import { wetness } from "../api/environment";
import { formatAgo, formatElapsed } from "../api/format";
import {
  COMPONENT_LABELS,
  componentState,
  listNodes,
  nodeComponent,
  nodeWarnings,
  observeNode,
  slowedByHeat,
  streamState,
  thermalNotice,
  type ComponentName,
  type SensorNode,
} from "../api/nodes";
import Icon from "../components/Icon";
import { HelpLink } from "./HelpPage";
import {
  evidenceRecordingIssue,
  LivePreview,
  type CameraProfile,
} from "../components/LiveCamera";
import { usePoll } from "../hooks/usePoll";
import { usePersistentState } from "../hooks/usePersistentState";
import type { Config, EnvironmentReading, LiveState } from "../types";
import FeedRow from "../ui/FeedRow";
import { setDetectionPaused } from "../ui/PauseDetection";
import { splitLiveFeed } from "../api/liveFeed";
import Pill, { type Tone } from "../ui/Pill";
import type { Taxon } from "./Taxa";

const ACTIVE = ["connecting", "live", "reconnecting", "stopping"];

export function liveStatus(state: LiveState | null): {
  label: string;
  tone: Tone;
} {
  switch (state?.status) {
    case "live":
      return { label: "Observing", tone: "live" };
    case "connecting":
      return { label: "Connecting", tone: "neutral" };
    case "reconnecting":
      return { label: "Reconnecting", tone: "warn" };
    case "stopping":
      return { label: "Stopping", tone: "neutral" };
    case "failed":
      return { label: "Stopped with an error", tone: "bad" };
    default:
      return { label: "Not observing", tone: "muted" };
  }
}

type Source = {
  key: string;
  label: string;
  detail: string;
  available: boolean;
  node?: SensorNode;
};

export function liveSources(
  nodes: SensorNode[],
  profile: CameraProfile | null,
): Source[] {
  const sources: Source[] = nodes.map((node) => {
    const stream = streamState(node);
    const parts = node.status
      ? (["camera", "microphone"] as const).filter(
          (name) =>
            node.status?.components[name].present &&
            node.status?.components[name].enabled,
        )
      : [];
    return {
      key: `node:${node.node_id}`,
      label: node.name,
      detail: node.online
        ? `FALCON sensor node · ${parts.length ? parts.map((part) => COMPONENT_LABELS[part].label.toLowerCase()).join(" + ") : "no camera or microphone on"} · ${stream.label.toLowerCase()}`
        : "FALCON sensor node · offline",
      available: node.online && parts.length > 0,
      node,
    };
  });
  if (profile?.saved)
    sources.push({
      key: "camera",
      label: profile.name,
      detail: `IP camera (RTSP)${profile.audio_enabled ? " · with sound" : ""} · settings controlled on the camera`,
      available: true,
    });
  return sources;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

/** Dot colour for the Live bar's sound indicator: off, working or a problem. */
export function soundTone(
  active: boolean,
  status: string | null | undefined,
  stalledSince?: unknown,
): "off" | "good" | "bad" {
  if (!active || !status || status === "disabled") return "off";
  if (typeof stalledSince === "string" && stalledSince) return "bad";
  return /fail|error|unavailable|no audio|retrying/i.test(status)
    ? "bad"
    : "good";
}

/** "stalled since 08:40" when no sound has reached FALCON for a while, else "". */
export function soundStall(stalledSince: unknown): string {
  if (typeof stalledSince !== "string" || !stalledSince) return "";
  const time = new Date(stalledSince);
  return Number.isFinite(time.valueOf())
    ? `no sound since ${time.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}`
    : "no sound";
}

/** "11:38:12 · 15 fps · 1280×1024": the time, measured frame rate and picture size. */
export function stageInfo(now: Date, metrics: Record<string, unknown>): string {
  const time = now.toLocaleTimeString("en-GB", { hour12: false });
  const fps = Number(metrics.received_video_fps);
  const width = Number(metrics.width);
  const height = Number(metrics.height);
  return [
    time,
    Number.isFinite(fps) && fps > 0 ? `${Math.round(fps)} fps` : "– fps",
    width > 0 && height > 0 ? `${width}×${height}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The corner overlay on the Live picture; ticks every second, never changes width. */
function StageInfo({ metrics }: { metrics: Record<string, unknown> }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <span className="stage-info" aria-hidden="true">
      {stageInfo(now, metrics)}
    </span>
  );
}

/** A sensor reading, including zero and below (air temperature in winter). */
function reading(
  value: number | null | undefined,
  digits: number,
  unit: string,
): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(digits)}${unit}`
    : "—";
}

export default function LivePage({
  onOpen,
  onNavigate,
}: {
  taxa: Taxon[];
  onOpen: (encounter: Encounter) => void;
  onNavigate: (page: string) => void;
}) {
  const live = usePoll(() => api<LiveState>("/live/state"), 1000);
  const nodes = usePoll(listNodes, 5000);
  const profile = usePoll(() => api<CameraProfile>("/live/profile"), 20000);
  const environment = usePoll(
    () => api<EnvironmentReading>("/sensors/current"),
    15000,
  );
  // The source choice and the Live bar switches are remembered in this browser, so
  // they keep their position across pages, reloads and FALCON restarts.
  const [choice, setChoice] = usePersistentState<string>("live.source", "");
  const [overlays, setOverlays] = usePersistentState<boolean>(
    "live.boxes",
    true,
  );
  const [infoOverlay, setInfoOverlay] = usePersistentState<boolean>(
    "live.overlay",
    true,
  );
  const stage = useRef<HTMLElement>(null);
  const fullscreen = useFullscreen(stage);
  const [showUnresolved, setShowUnresolved] = usePersistentState<boolean>(
    "live.unresolved",
    false,
  );
  const [savedFilter, setFeedFilter] = usePersistentState<string>(
    "live.feed",
    "all",
  );
  const feedFilter: "all" | "unreviewed" =
    savedFilter === "unreviewed" ? "unreviewed" : "all";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const state = live.data;
  const active = !!state && ACTIVE.includes(state.status);
  const nodeList = useMemo(() => nodes.data?.nodes ?? [], [nodes.data]);
  const sources = useMemo(
    () => liveSources(nodeList, profile.data),
    [nodeList, profile.data],
  );
  const observing = nodeList.find((node) => node.observing);
  const selectedKey =
    choice ||
    (observing
      ? `node:${observing.node_id}`
      : sources.find((source) => source.available)?.key) ||
    "";
  const selected = sources.find((source) => source.key === selectedKey);
  const controlNode = observing ?? selected?.node;
  const sessionSource = active ? liveSourceId(state?.session_id) : undefined;
  // Newest visit on top and no reordering while an animal lingers; visits that
  // say nothing yet (no species, no group) stay hidden unless asked for.
  const feed = usePoll(
    () =>
      fetchEncounters({
        scope: "live",
        source_id: sessionSource,
        review_status: feedFilter === "unreviewed" ? "unreviewed" : undefined,
        resolved_only: !showUnresolved,
        order: "first_seen",
        limit: 80,
      }),
    active ? 3000 : 20000,
    `${sessionSource ?? "recent"}-${feedFilter}-${showUnresolved}`,
  );
  const counts = usePoll(
    () => fetchSummary({ scope: "live", source_id: sessionSource }),
    active ? 10000 : 60000,
    sessionSource ?? "recent",
  );
  const status = liveStatus(state);
  const metrics = state?.metrics ?? {};
  const audioOnly = Number(metrics.audio_only) === 1;
  // The sensor node pauses its stream itself when it gets too hot.
  const nodeStatus = controlNode?.online ? controlNode.status : null;
  const heat = thermalNotice(
    nodeStatus?.thermal,
    nodeStatus?.system.cpu_temperature_c,
  );
  const slowed = !heat && slowedByHeat(nodeStatus?.system.power);

  async function start() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      if (selected.node) await observeNode(selected.node.node_id);
      else if (profile.data) {
        const config = await api<Config>("/config");
        await api<LiveState>("/live/start", {
          method: "POST",
          body: JSON.stringify({
            name: profile.data.name,
            url: profile.data.url,
            username: profile.data.username || undefined,
            use_saved_credentials: true,
            save_profile: false,
            config: { ...config, audio_enabled: profile.data.audio_enabled },
          }),
        });
      }
      live.refresh();
      nodes.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    setError("");
    try {
      live.setData(await api<LiveState>("/live/stop", { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function toggle(
    node: SensorNode,
    component: ComponentName,
    enabled: boolean,
  ) {
    setError("");
    try {
      await nodeComponent(node.node_id, component, enabled);
      nodes.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  // Only confirmed and likely visits are listed; the rest wait on the Review page.
  const { shown, toReview } = splitLiveFeed(
    feed.data?.encounters ?? [],
    showUnresolved,
  );
  return (
    <div className="page live-page">
      <header className="page-header">
        <div>
          <h1>
            Live <HelpLink slug="user-guide" section="live" />
          </h1>
          <p>
            Watch the sensor node, check detections as they happen and correct
            them on the spot.
          </p>
        </div>
        <div className="source-control">
          {active ? (
            <>
              <div className="source-current">
                <Pill tone={status.tone}>{status.label}</Pill>
                <strong>{state?.name}</strong>
                <code>{formatElapsed(state?.session_timestamp_ms)}</code>
              </div>
              <button
                className="danger"
                onClick={() => void stop()}
                disabled={busy || state?.status === "stopping"}
              >
                <Icon name="stop" size={16} /> Stop
              </button>
            </>
          ) : (
            <>
              <label className="sr-only" htmlFor="live-source">
                Source to observe
              </label>
              <select
                id="live-source"
                value={selectedKey}
                onChange={(change) => setChoice(change.target.value)}
                disabled={!sources.length}
              >
                {!sources.length && <option value="">No sources yet</option>}
                {sources.map((source) => (
                  <option
                    key={source.key}
                    value={source.key}
                    disabled={!source.available}
                  >
                    {source.label}
                    {source.available ? "" : " (unavailable)"}
                  </option>
                ))}
              </select>
              <button
                className="primary"
                onClick={() => void start()}
                disabled={busy || !selected?.available}
              >
                <Icon name="play" size={16} />{" "}
                {busy ? "Starting…" : "Start observing"}
              </button>
            </>
          )}
        </div>
      </header>
      {(error || state?.error) && (
        <p className="banner banner-bad" role="alert">
          {error || state?.error}
        </p>
      )}
      {state?.detection_paused_since && (
        <p className="banner banner-warn" role="status">
          Detection paused for camera work: nothing is detected, recorded or
          rung.{" "}
          <button
            type="button"
            className="text-button"
            onClick={() =>
              void setDetectionPaused(false).then(() => live.refresh())
            }
          >
            Resume
          </button>
        </p>
      )}
      {active && evidenceRecordingIssue(metrics) && (
        <p className="banner banner-warn" role="alert">
          Clips are not being saved: {evidenceRecordingIssue(metrics)}{" "}
          Detections are still recorded.
        </p>
      )}
      {!sources.length && nodes.data && profile.data && (
        <section className="card empty-state">
          <Icon name="node" size={36} />
          <h2>Connect a sensor to begin</h2>
          <p>
            Pair a FALCON sensor node (Raspberry Pi with camera, microphone and
            weather sensors) or add an IP camera.
          </p>
          <button className="primary" onClick={() => onNavigate("sensors")}>
            <Icon name="plus" size={16} /> Add a sensor
          </button>
        </section>
      )}
      <div className="live-grid">
        <section
          className={`card live-stage${fullscreen.active ? " is-fullscreen" : ""}`}
          aria-label="Live view"
          ref={stage}
        >
          {active &&
          state &&
          state.preview_timestamp_ms !== null &&
          !audioOnly ? (
            <LivePreview
              state={state}
              show={overlays}
              showUnresolved={showUnresolved}
            >
              {infoOverlay && <StageInfo metrics={state.metrics} />}
            </LivePreview>
          ) : (
            <div className="stage-placeholder">
              <Icon
                name={audioOnly ? "sound" : active ? "camera" : "eye"}
                size={40}
              />
              <h2>
                {heat && active
                  ? heat
                  : audioOnly
                    ? "Listening (this source has no camera)"
                    : active
                      ? state?.status === "reconnecting"
                        ? "Reconnecting to the stream…"
                        : "Opening the stream…"
                      : selected
                        ? `Ready: ${selected.label}`
                        : "No source selected"}
              </h2>
              <p>
                {audioOnly
                  ? `Sound is analyzed in 9-second windows · ${String(state?.audio_status ?? "").replaceAll("_", " ")}`
                  : active
                    ? "Video and sound are connecting."
                    : (selected?.detail ??
                      "Pair a sensor node or add an IP camera in Sensors.")}
              </p>
            </div>
          )}
          <div className="stage-bar">
            <label className="switch-row">
              <input
                type="checkbox"
                role="switch"
                checked={overlays}
                onChange={(change) => setOverlays(change.target.checked)}
              />
              <span>Detection boxes</span>
            </label>
            <label
              className="switch-row"
              title="Time, frame rate and picture size in the corner of the video"
            >
              <input
                type="checkbox"
                role="switch"
                checked={infoOverlay}
                onChange={(change) => setInfoOverlay(change.target.checked)}
              />
              <span>Overlay</span>
            </label>
            <label
              className="switch-row"
              title="Also show boxes and cards for detections with no species and no group yet"
            >
              <input
                type="checkbox"
                role="switch"
                checked={showUnresolved}
                onChange={(change) => setShowUnresolved(change.target.checked)}
              />
              <span>Show unresolved</span>
            </label>
            {/* Fixed-width sound indicator; the full wording is in the tooltip and on
                System → Live status, so the bar never changes width. */}
            <span
              className={`sound-indicator tone-${soundTone(active, state?.audio_status, metrics.audio_stalled_since)}`}
              title={`Sound: ${
                !active
                  ? "not observing"
                  : soundStall(metrics.audio_stalled_since) ||
                    String(state?.audio_status ?? "waiting").replaceAll(
                      "_",
                      " ",
                    )
              }`}
            >
              <Icon name="sound" size={15} />
              <i aria-hidden="true" />
              Sound
            </span>
            <LiveListen
              available={active && state?.audio_status !== "disabled" && !heat}
            />
            <DetectionBell
              encounters={feed.data ? shown : null}
              resetKey={`${sessionSource ?? "recent"}-${feedFilter}-${showUnresolved}`}
            />
            {fullscreen.supported && (
              <button
                type="button"
                className="fullscreen-button"
                onClick={fullscreen.toggle}
                aria-pressed={fullscreen.active}
                aria-label={
                  fullscreen.active ? "Exit full screen" : "Full screen"
                }
                title={
                  fullscreen.active
                    ? "Exit full screen (Esc)"
                    : "Full screen (F). Esc leaves full screen."
                }
              >
                <Icon name={fullscreen.active ? "close" : "focus"} size={16} />
              </button>
            )}
          </div>
          {/* Conditions at the sensor. Technical details (frame rate, model, clips,
              clock) are on System → Live status. */}
          <div className="facts">
            <Fact
              label="Air temperature"
              value={reading(environment.data?.temperature_c, 1, " °C")}
            />
            <Fact
              label="Humidity"
              value={reading(environment.data?.humidity_percent, 0, " %")}
            />
            <Fact
              label="Pressure"
              value={reading(environment.data?.pressure_hpa, 1, " hPa")}
            />
            <Fact
              label="Rain plate"
              value={wetness(environment.data?.surface_wet)}
            />
            <Fact
              label="Node CPU"
              value={reading(nodeStatus?.system.cpu_temperature_c, 0, " °C")}
            />
            <Fact
              label="Heat protection"
              value={
                heat
                  ? "Paused (too hot)"
                  : slowed
                    ? "Slowed by heat"
                    : nodeStatus?.thermal
                      ? "Normal"
                      : "—"
              }
            />
          </div>
        </section>
        <aside className="card live-feed" aria-label="Recent detections">
          <div className="card-header">
            <div>
              <h2>
                {active ? "Detections this session" : "Recent detections"}
              </h2>
              <p className="muted">
                {feed.data
                  ? `${feed.data.total} visit${feed.data.total === 1 ? "" : "s"}`
                  : "Loading…"}
                {counts.data ? ` · ${counts.data.species_count} species` : ""}
              </p>
            </div>
            <div className="segmented" role="group" aria-label="Show">
              <button
                aria-pressed={feedFilter === "all"}
                onClick={() => setFeedFilter("all")}
              >
                All
              </button>
              <button
                aria-pressed={feedFilter === "unreviewed"}
                onClick={() => setFeedFilter("unreviewed")}
              >
                To review
              </button>
            </div>
          </div>
          <div className="feed-list compact">
            {shown.map((encounter) => (
              <FeedRow
                key={encounter.encounter_id}
                encounter={encounter}
                onOpen={onOpen}
              />
            ))}
            {feed.data && !shown.length && (
              <div className="feed-empty">
                <Icon name="leaf" size={28} />
                <p>
                  {toReview
                    ? "Nothing certain yet. Uncertain visits wait in Review."
                    : active
                      ? "No animals detected yet in this session."
                      : "No detections yet."}
                </p>
              </div>
            )}
            {feed.error && <p className="error">{feed.error}</p>}
          </div>
          <div className="feed-links">
            <button
              className="text-button feed-more"
              onClick={() => onNavigate("review")}
            >
              {toReview ? `${toReview} more to review` : "Open the full review"}{" "}
              <Icon name="arrow" size={15} />
            </button>
            <button
              className="text-button feed-more"
              onClick={() => onNavigate("summary")}
            >
              Counts and sessions <Icon name="arrow" size={15} />
            </button>
          </div>
        </aside>
      </div>
      <div className="live-lower">
        {controlNode && (
          <section
            className="card node-quick"
            aria-label={`${controlNode.name} controls`}
          >
            <div className="card-header">
              <div>
                <h2>
                  <Icon name="node" size={18} /> {controlNode.name}
                </h2>
                <p className="muted">
                  {controlNode.online
                    ? `${streamState(controlNode).label} · checked ${formatAgo(controlNode.checked_at)}`
                    : `Offline · last seen ${formatAgo(controlNode.last_seen)}`}
                </p>
              </div>
              <span className="sensor-links">
                {controlNode.status?.components.camera.present && (
                  <a
                    className="text-button"
                    href={sensorHref(controlNode.node_id, "camera")}
                  >
                    Camera settings
                  </a>
                )}
                <button
                  className="text-button"
                  onClick={() => onNavigate("sensors")}
                >
                  All node settings <Icon name="arrow" size={15} />
                </button>
              </span>
            </div>
            {nodeWarnings(controlNode.status).map((warning) => (
              <p className="banner banner-warn" key={warning}>
                {warning}
              </p>
            ))}
            {controlNode.status && (
              <div className="component-toggles">
                {(Object.keys(COMPONENT_LABELS) as ComponentName[]).map(
                  (name) => {
                    const component = controlNode.status!.components[name];
                    const shown = componentState(component);
                    return (
                      <label
                        key={name}
                        className={`component-toggle tone-${shown.tone}`}
                      >
                        <input
                          type="checkbox"
                          role="switch"
                          checked={component.present && component.enabled}
                          disabled={!component.present}
                          onChange={(change) =>
                            void toggle(
                              controlNode,
                              name,
                              change.target.checked,
                            )
                          }
                        />
                        <Icon name={COMPONENT_LABELS[name].icon} size={16} />
                        <span>
                          <strong>{COMPONENT_LABELS[name].label}</strong>
                          <small>{shown.label}</small>
                        </span>
                      </label>
                    );
                  },
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
