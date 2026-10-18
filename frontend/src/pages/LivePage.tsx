import { useMemo, useState } from "react";
import { api } from "../api/client";
import {
  fetchEncounters,
  liveSourceId,
  reviewEncounters,
  type Encounter,
} from "../api/encounters";
import { wetness } from "../api/environment";
import { formatAgo, formatElapsed } from "../api/format";
import {
  COMPONENT_LABELS,
  componentState,
  listNodes,
  nodeComponent,
  nodeWarnings,
  observeNode,
  streamState,
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
import type { Config, EnvironmentReading, LiveState } from "../types";
import CameraControls from "../ui/CameraControls";
import EncounterCard, { type DecisionHandler } from "../ui/EncounterCard";
import Pill, { type Tone } from "../ui/Pill";
import type { Taxon } from "./Taxa";

const ACTIVE = ["connecting", "live", "reconnecting", "stopping"];
const MODEL_NAMES: Record<string, string> = {
  bioclip_2: "BioCLIP 2",
  bioclip_2_5: "BioCLIP 2.5",
  ensemble: "BioCLIP 2 + 2.5",
};

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

function number(value: unknown, digits = 1, unit = ""): string {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? `${value.toFixed(digits)}${unit}`
    : "—";
}

export default function LivePage({
  taxa,
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
  const [choice, setChoice] = useState("");
  const [overlays, setOverlays] = useState(true);
  const [feedFilter, setFeedFilter] = useState<"all" | "unreviewed">("all");
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
  const feed = usePoll(
    () =>
      fetchEncounters({
        scope: "live",
        source_id: sessionSource,
        review_status: feedFilter === "unreviewed" ? "unreviewed" : undefined,
        limit: 24,
      }),
    active ? 3000 : 20000,
    `${sessionSource ?? "recent"}-${feedFilter}`,
  );
  const status = liveStatus(state);
  const metrics = state?.metrics ?? {};
  const audioOnly = Number(metrics.audio_only) === 1;

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

  const decide: DecisionHandler = async (encounter, next, taxonId) => {
    await reviewEncounters([encounter.encounter_id], next, { taxonId });
    feed.refresh();
  };

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

  const encounters = feed.data?.encounters ?? [];
  const unreviewed = encounters.filter(
    (item) => item.review_status === "unreviewed",
  ).length;
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
        <section className="card live-stage" aria-label="Live view">
          {active &&
          state &&
          state.preview_timestamp_ms !== null &&
          !audioOnly ? (
            <LivePreview state={state} show={overlays} />
          ) : (
            <div className="stage-placeholder">
              <Icon
                name={audioOnly ? "sound" : active ? "camera" : "eye"}
                size={40}
              />
              <h2>
                {audioOnly
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
            <span className="muted">
              {active
                ? `Sound: ${String(state?.audio_status ?? "waiting").replaceAll("_", " ")}`
                : "Idle"}
            </span>
          </div>
          {active && (
            <div className="facts">
              <Fact
                label="Video"
                value={`${number(metrics.received_video_fps, 1, " fps")} · ${metrics.width && metrics.height ? `${metrics.width}×${metrics.height}` : "—"}`}
              />
              <Fact
                label="Analysis"
                value={`${number(metrics.sample_fps, 1, " fps")} · lag ${number(Number(metrics.inference_lag_ms) / 1000, 1, " s")}`}
              />
              <Fact
                label="Model"
                value={`${MODEL_NAMES[String(metrics.classifier_mode)] ?? "—"} · ${String(metrics.device ?? "—").toUpperCase()}`}
              />
              <Fact
                label="Sound"
                value={`${String(metrics.audio_codec ?? "—")} · ${number(Number(metrics.audio_sample_rate) / 1000, 1, " kHz")}`}
              />
              <Fact
                label="Clips saved"
                value={String(
                  Number(metrics.evidence_ready_clips ?? 0) +
                    Number(metrics.audio_clips_saved ?? 0),
                )}
              />
              <Fact
                label="Clock"
                value={
                  metrics.clock_synchronized === "yes"
                    ? "Synchronized"
                    : metrics.clock_synchronized === "no"
                      ? "Not synchronized"
                      : "—"
                }
              />
            </div>
          )}
        </section>
        <aside className="card live-feed" aria-label="Recent detections">
          <div className="card-header">
            <div>
              <h2>
                {active ? "Detections this session" : "Recent detections"}
              </h2>
              <p className="muted">
                {feed.data
                  ? `${feed.data.total} encounter${feed.data.total === 1 ? "" : "s"}`
                  : "Loading…"}
                {unreviewed ? ` · ${unreviewed} to review` : ""}
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
          <p className="feed-help">
            One card per animal visit. <kbd>C</kbd> confirm · <kbd>E</kbd>{" "}
            correct · <kbd>U</kbd> unsure · <kbd>X</kbd> not an animal ·{" "}
            <kbd>D</kbd> discard
          </p>
          <div className="feed-list">
            {encounters.map((encounter) => (
              <EncounterCard
                key={encounter.encounter_id}
                encounter={encounter}
                taxa={taxa}
                onDecision={decide}
                onOpen={onOpen}
                compact
              />
            ))}
            {feed.data && !encounters.length && (
              <div className="feed-empty">
                <Icon name="leaf" size={28} />
                <p>
                  {active
                    ? "No animals detected yet in this session."
                    : "No detections yet."}
                </p>
              </div>
            )}
            {feed.error && <p className="error">{feed.error}</p>}
          </div>
          <button
            className="text-button feed-more"
            onClick={() => onNavigate("review")}
          >
            Open the full review <Icon name="arrow" size={15} />
          </button>
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
              <button
                className="text-button"
                onClick={() => onNavigate("sensors")}
              >
                All node settings <Icon name="arrow" size={15} />
              </button>
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
            {controlNode.online &&
              controlNode.status?.components.camera.present && (
                <details className="quick-camera">
                  <summary>
                    Camera picture: focus, brightness, white balance
                  </summary>
                  <CameraControls
                    node={controlNode}
                    quick
                    onChanged={() => nodes.refresh()}
                  />
                </details>
              )}
          </section>
        )}
        <section
          className="card environment"
          aria-label="Weather at the sensor"
        >
          <div className="card-header">
            <div>
              <h2>
                <Icon name="sun" size={18} /> Weather at the sensor
              </h2>
              <p className="muted">
                {environment.data?.status === "fresh"
                  ? `Measured ${formatAgo(environment.data.observed_at)}${environment.data.sensor_id ? ` · ${environment.data.sensor_id}` : ""}`
                  : environment.data?.status === "stale"
                    ? `Last reading ${formatAgo(environment.data.observed_at)} (stale)`
                    : environment.data?.status === "unavailable"
                      ? "No usable reading"
                      : "No weather sensor connected"}
              </p>
            </div>
          </div>
          <dl className="weather">
            <div>
              <dt>
                <Icon name="thermometer" size={16} /> Temperature
              </dt>
              <dd>
                {environment.data?.temperature_c?.toFixed(1) ?? "—"}{" "}
                <small>°C</small>
              </dd>
            </div>
            <div>
              <dt>
                <Icon name="drop" size={16} /> Humidity
              </dt>
              <dd>
                {environment.data?.humidity_percent?.toFixed(0) ?? "—"}{" "}
                <small>%</small>
              </dd>
            </div>
            <div>
              <dt>
                <Icon name="wind" size={16} /> Pressure
              </dt>
              <dd>
                {environment.data?.pressure_hpa?.toFixed(1) ?? "—"}{" "}
                <small>hPa</small>
              </dd>
            </div>
            <div>
              <dt>
                <Icon name="rain" size={16} /> Rain plate
              </dt>
              <dd>{wetness(environment.data?.surface_wet)}</dd>
            </div>
          </dl>
        </section>
      </div>
    </div>
  );
}
