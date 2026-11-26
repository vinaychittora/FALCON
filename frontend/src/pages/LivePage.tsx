// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useMemo, useRef, useState } from "react";
import { useFullscreen } from "../components/fullscreen";
import DetectionBell from "../ui/DetectionBell";
import { HoverTip } from "../ui/Floating";
import LiveListen from "../ui/LiveListen";
import { sensorHref } from "./SensorSettings";
import { api } from "../api/client";
import {
  fetchEncounters,
  liveSourceId,
  reviewEncounters,
  withDecision,
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
import {
  evidenceRecordingIssue,
  LivePreview,
  type CameraProfile,
} from "../components/LiveCamera";
import { usePoll } from "../hooks/usePoll";
import { usePersistentState } from "../hooks/usePersistentState";
import type { Config, EnvironmentReading, LiveState } from "../types";
import EncounterCard, { type DecisionHandler } from "../ui/EncounterCard";
import { keepDecided } from "./ReviewPage";
import "./live-page.css";
import { setDetectionPaused } from "../ui/PauseDetection";
import { liveFeedFilters, splitLiveFeed } from "../api/liveFeed";
import { type Tone } from "../ui/Pill";
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

/** "camera picture damaged since 10:13" while the self-heal could not fix it, else "". */
export function cameraDamage(since: unknown): string {
  if (typeof since !== "string" || !since) return "";
  const time = new Date(since).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `camera picture damaged since ${time}. Restarting the node's camera did not help; restart the node (Sensors → More → Restart the node).`;
}

/** Dot colour for the Live bar's sound indicator: off, working or a problem. */
export function soundTone(
  active: boolean,
  status: string | null | undefined,
  stalledSince?: unknown,
  rateFault?: unknown,
  clockFault?: string,
): "off" | "good" | "bad" {
  if (!active || !status || status === "disabled") return "off";
  if (typeof stalledSince === "string" && stalledSince) return "bad";
  if (clockFault) return "bad";
  // The microphone running at the wrong speed (saved sound has gaps).
  if (typeof rateFault === "string" && rateFault) return "bad";
  return /fail|error|unavailable|no audio|retrying/i.test(status)
    ? "bad"
    : "good";
}

/**
 * This computer's clock against the sensor node's (measured over 5 minutes): when it
 * runs more than 1 % off, every time and duration FALCON records is off with it.
 * 14 Nov: after two days of uptime the WSL clock ran 8 % fast; only restarting WSL
 * fixed it. Whole percent only, so the tooltip text stays put.
 */
export function pcClockFault(
  clock: { drift_percent: number | null; warning: boolean } | undefined,
): string {
  if (!clock?.warning || clock.drift_percent === null) return "";
  const off = Math.round(Math.abs(clock.drift_percent));
  return (
    `this computer's clock runs about ${off} % ${clock.drift_percent > 0 ? "fast" : "slow"} ` +
    "compared with the sensor node, so recorded times and picture-to-sound timing are off. " +
    "Fix: restart WSL (make stop, then wsl --shutdown in Windows, then make start)."
  );
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

/** Phone held sideways (landscape, at most 600 CSS px tall): in full screen the
 * picture takes the whole height and the status and switches go down the sides. */
export const PHONE_LANDSCAPE = "(orientation: landscape) and (max-height: 600px)";

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.(query).matches,
  );
  useEffect(() => {
    const list = window.matchMedia?.(query);
    if (!list) return;
    const update = () => setMatches(list.matches);
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** Time and frame rate on two short lines for the side column (no picture size). */
function SideInfo({ metrics }: { metrics: Record<string, unknown> }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  const [time, fps] = stageInfo(now, metrics).split(" · ");
  return (
    <span className="fs-info" aria-hidden="true">
      <span>{time}</span>
      <span>{fps}</span>
    </span>
  );
}

/** The corner overlay on the Live picture; ticks every second, never changes width. */
function StageInfo({ metrics }: { metrics: Record<string, unknown> }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  // Time, then frame rate and picture size: one line, or two short ones on a phone.
  const [time, ...rest] = stageInfo(now, metrics).split(" · ");
  return (
    <span className="stage-info" aria-hidden="true">
      <span>{time}</span>
      {rest.length > 0 && (
        <span className="stage-info-rest">
          <span className="stage-info-dot"> · </span>
          {rest.join(" · ")}
        </span>
      )}
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
  taxa,
  onOpen,
  onNavigate,
  onCounts,
}: {
  taxa: Taxon[];
  onOpen: (encounter: Encounter) => void;
  onNavigate: (page: string) => void;
  /** A decision here changed the to-review counts: the navigation badge counts again. */
  onCounts?: () => void;
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
  // Stream stats (time, frame rate, picture size) on the video: off at every page load,
  // like "stats for nerds"; never remembered, and an old stored Overlay value is ignored.
  const [infoOverlay, setInfoOverlay] = useState(false);
  const stage = useRef<HTMLElement>(null);
  const fullscreen = useFullscreen(stage);
  const phoneLandscape = useMediaQuery(PHONE_LANDSCAPE);
  const sideLayout = fullscreen.active && phoneLandscape;
  // Live shows what FALCON recognised; unresolved pictures wait on the Review page.
  const showUnresolved = false;
  const [savedFilter, setFeedFilter] = usePersistentState<string>(
    "live.feed",
    "all",
  );
  const feedFilter: "all" | "unreviewed" =
    savedFilter === "unreviewed" ? "unreviewed" : "all";
  const [busy, setBusy] = useState(false);
  // Cards decided here stay where they are until the switch or the page changes.
  const [kept, setKept] = useState<
    Map<string, { index: number; encounter: Encounter }>
  >(new Map());
  function changeFeed(next: "all" | "unreviewed") {
    setKept(new Map());
    setFeedFilter(next);
  }
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
      fetchEncounters(liveFeedFilters(sessionSource, feedFilter, showUnresolved)),
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
  const clockFault = pcClockFault(nodeStatus?.falcon_clock);

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
  const decide: DecisionHandler = async (encounter, next, taxonId, notes) => {
    await reviewEncounters([encounter.encounter_id], next, { taxonId, notes });
    const index = keepDecided(shown, kept).findIndex(
      (item) => item.encounter_id === encounter.encounter_id,
    );
    setKept((current) =>
      new Map(current).set(encounter.encounter_id, {
        index: index < 0 ? (current.get(encounter.encounter_id)?.index ?? 0) : index,
        encounter: withDecision(encounter, next, { taxonId, notes, taxa }),
      }),
    );
    onCounts?.();
  };

  // The stage's pieces: one bar under the picture, or two side columns when a phone
  // is held sideways in full screen (short labels there).
  const boxesSwitch = (
    <label className="switch-row">
      <input
        type="checkbox"
        role="switch"
        checked={overlays}
        onChange={(change) => setOverlays(change.target.checked)}
      />
      <span>{fullscreen.active && !sideLayout ? "Detection boxes" : "Boxes"}</span>
    </label>
  );
  const overlaySwitch = (
    <label
      className="switch-row"
      title="Time, frame rate and picture size in the corner of the video"
    >
      <input
        type="checkbox"
        role="switch"
        aria-label="Show stream stats on the video"
        checked={infoOverlay}
        onChange={(change) => setInfoOverlay(change.target.checked)}
      />
      <span>Stats</span>
    </label>
  );
  const soundDot = (
    <HoverTip
      className={`sound-indicator tone-${soundTone(active, state?.audio_status, metrics.audio_stalled_since, metrics.audio_rate_fault, clockFault)}`}
      tip={`Sound: ${
        !active
          ? "not observing"
          : soundStall(metrics.audio_stalled_since) ||
            clockFault ||
            (typeof metrics.audio_rate_fault === "string" && metrics.audio_rate_fault) ||
            String(state?.audio_status ?? "waiting").replaceAll("_", " ")
      }`}
    >
      <Icon name="sound" size={15} />
      <i aria-hidden="true" />
      Sound
    </HoverTip>
  );
  const cameraDot = active && !audioOnly && (
    <HoverTip
      className={`sound-indicator tone-${cameraDamage(metrics.camera_damaged_since) ? "warn" : "good"}`}
      tip={`Camera: ${cameraDamage(metrics.camera_damaged_since) || "picture arriving whole"}`}
    >
      <Icon name="camera" size={15} />
      <i aria-hidden="true" />
      Camera
    </HoverTip>
  );
  const listen = (
    <LiveListen
      available={active && state?.audio_status !== "disabled" && !heat}
    />
  );
  const bell = (
    <DetectionBell
      quiet
      encounters={feed.data ? shown : null}
      resetKey={`${sessionSource ?? "recent"}-${feedFilter}-${showUnresolved}`}
    />
  );
  const fullscreenButton = fullscreen.supported && (
    <button
      type="button"
      className="fullscreen-button"
      onClick={fullscreen.toggle}
      aria-pressed={fullscreen.active}
      aria-label={fullscreen.active ? "Exit full screen" : "Full screen"}
      title={
        fullscreen.active
          ? "Exit full screen (Esc)"
          : "Full screen (F). Esc leaves full screen."
      }
    >
      <Icon name={fullscreen.active ? "close" : "focus"} size={16} />
    </button>
  );
  const facts = [
    {
      label: "Air temperature",
      short: "Air",
      value: reading(environment.data?.temperature_c, 1, " °C"),
    },
    {
      label: "Humidity",
      short: "Humidity",
      value: reading(environment.data?.humidity_percent, 0, " %"),
    },
    {
      label: "Pressure",
      short: "Pressure",
      value: reading(environment.data?.pressure_hpa, 1, " hPa"),
    },
    {
      label: "Rain plate",
      short: "Rain",
      value: wetness(environment.data?.surface_wet),
    },
    {
      label: "Node CPU",
      short: "Node CPU",
      value: reading(nodeStatus?.system.cpu_temperature_c, 0, " °C"),
    },
    {
      label: "Heat protection",
      short: "Heat",
      value: heat
        ? "Paused (too hot)"
        : slowed
          ? "Slowed by heat"
          : nodeStatus?.thermal
            ? "Normal"
            : "—",
    },
  ];
  const shownHere = keepDecided(shown, kept);
  const stationSummary = facts
    .filter((fact) => fact.value !== "—")
    .map((fact) => `${fact.short} ${fact.value}`)
    .join(" · ");
  const cameraState = audioOnly
    ? { tone: "off", text: "none on this source" }
    : cameraDamage(metrics.camera_damaged_since)
      ? { tone: "warn", text: cameraDamage(metrics.camera_damaged_since) }
      : { tone: "good", text: "picture arriving whole" };
  const microphoneState = {
    tone: soundTone(active, state?.audio_status, metrics.audio_stalled_since, metrics.audio_rate_fault, clockFault),
    text:
      soundStall(metrics.audio_stalled_since) ||
      clockFault ||
      (typeof metrics.audio_rate_fault === "string" && metrics.audio_rate_fault) ||
      String(state?.audio_status ?? "waiting").replaceAll("_", " "),
  };
  const warnings = controlNode ? nodeWarnings(controlNode.status) : [];
  return (
    <div className="page live-page lv">
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
      <div className="lv-a">
        <section
          className={`card live-stage lv-stage${fullscreen.active ? " is-fullscreen" : ""}${sideLayout ? " side-layout" : ""}`}
          aria-label="Live view"
          ref={stage}
        >
          {sideLayout && (
            <aside className="fs-side fs-status" aria-label="Status">
              <span className="live-indicator fs-live">
                <i />
                {String(state?.status ?? "off").toUpperCase()}
              </span>
              {soundDot}
              {cameraDot}
              {infoOverlay && state && <SideInfo metrics={state.metrics} />}
              <div className="fs-facts">
                {facts.map((fact) => (
                  <Fact key={fact.short} label={fact.short} value={fact.value} />
                ))}
              </div>
            </aside>
          )}
          <div className={fullscreen.active ? "lv-frame-fs" : "lv-frame"}>
            {active &&
            state &&
            state.preview_timestamp_ms !== null &&
            !audioOnly ? (
              <LivePreview
                state={state}
                show={overlays}
                showUnresolved={showUnresolved}
              >
                {infoOverlay && !sideLayout && <StageInfo metrics={state.metrics} />}
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
            {!fullscreen.active && <span className="lv-full">{fullscreenButton}</span>}
          </div>
          {sideLayout ? (
            <aside className="fs-side fs-actions" aria-label="Actions">
              {fullscreenButton}
              {boxesSwitch}
              {overlaySwitch}
              {listen}
              {bell}
            </aside>
          ) : fullscreen.active ? (
            <>
              <div className="stage-bar">
                {boxesSwitch}
                {overlaySwitch}
                {soundDot}
                {cameraDot}
                {listen}
                {bell}
                {fullscreenButton}
              </div>
              <div className="facts">
                {facts.map((fact) => (
                  <Fact key={fact.label} label={fact.label} value={fact.value} />
                ))}
              </div>
            </>
          ) : (
            <div
              className="lv-tools"
              role="group"
              aria-label="Live picture and alert options"
            >
              {boxesSwitch}
              {overlaySwitch}
            </div>
          )}
        </section>
        <div className="lv-st">
          <div className="lv-st-a">
            {active ? (
              <>
                {status.label} · {state?.name} ·{" "}
                <span className="lv-time">
                  {formatElapsed(state?.session_timestamp_ms)}
                </span>
              </>
            ) : (
              status.label
            )}
          </div>
          <div className="lv-st-b">
            {active ? (
              <>
                <span className="lv-part">
                  <i className={`lv-dot tone-${cameraState.tone}`} aria-hidden="true" />
                  Camera {cameraState.text}
                </span>{" "}
                ·{" "}
                <span className="lv-part">
                  <i className={`lv-dot tone-${microphoneState.tone}`} aria-hidden="true" />
                  Microphone {microphoneState.text.split(": ")[0]}
                </span>
              </>
            ) : (
              (selected?.detail ?? "Pair a sensor node or add an IP camera in Sensors.")
            )}
          </div>
          <div className="lv-st-act">
            {active ? (
              <button
                type="button"
                className="lv-stop"
                onClick={() => void stop()}
                disabled={busy || state?.status === "stopping"}
              >
                <Icon name="stop" size={16} /> Stop
              </button>
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
                  type="button"
                  className="lv-stop lv-start"
                  onClick={() => void start()}
                  disabled={busy || !selected?.available}
                >
                  <Icon name="play" size={16} />{" "}
                  {busy ? "Starting…" : "Start observing"}
                </button>
              </>
            )}
          </div>
        </div>
        {warnings.map((warning) => (
          <p className="banner banner-warn lv-warn" key={warning} role="status">
            {warning}
          </p>
        ))}
        <details className="lv-xp">
          <summary>
            <span className="lv-xp-t">Station now</span>
            <span className="lv-xp-s">{stationSummary || "No readings yet"}</span>
          </summary>
          <dl className="lv-kv">
            {facts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
            {active && (
              <>
                <div>
                  <dt>Camera</dt>
                  <dd>{cameraState.text}</dd>
                </div>
                <div>
                  <dt>Microphone</dt>
                  <dd>{microphoneState.text}</dd>
                </div>
              </>
            )}
          </dl>
        </details>
        {controlNode && (
          <details className="lv-xp">
            <summary>
              <span className="lv-xp-t">{controlNode.name}</span>
              <span className="lv-xp-s">
                {controlNode.online
                  ? `${streamState(controlNode).label} · checked ${formatAgo(controlNode.checked_at)}`
                  : `Offline · last seen ${formatAgo(controlNode.last_seen)}`}
              </span>
            </summary>
            <div className="lv-node" aria-label={`${controlNode.name} controls`}>
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
              {controlNode.status && (
                <div className="component-toggles">
                  {(Object.keys(COMPONENT_LABELS) as ComponentName[]).map(
                    (name) => {
                      const component = controlNode.status!.components[name];
                      const shownState = componentState(component);
                      return (
                        <label
                          key={name}
                          className={`component-toggle tone-${shownState.tone}`}
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
                            <small>{shownState.label}</small>
                          </span>
                        </label>
                      );
                    },
                  )}
                </div>
              )}
            </div>
          </details>
        )}
      </div>
      <section className="lv-b" aria-labelledby="lv-h">
        <div className="lv-sec-h">
          <h2 id="lv-h">{active ? "This session" : "Recent detections"}</h2>
          <div className="lv-seg" role="group" aria-label="Show">
            <button
              type="button"
              aria-pressed={feedFilter === "all"}
              onClick={() => changeFeed("all")}
            >
              All
            </button>
            <button
              type="button"
              aria-pressed={feedFilter === "unreviewed"}
              onClick={() => changeFeed("unreviewed")}
            >
              To review
            </button>
          </div>
        </div>
        <p className="lv-count">
          {feed.data
            ? `${feed.data.total} record${feed.data.total === 1 ? "" : "s"}`
            : "Loading…"}
          {counts.data ? ` · ${counts.data.species_count} species` : ""}
          {feed.data ? ` · ${toReview} to review` : ""}
        </p>
        <ul className="rl-cards" aria-labelledby="lv-h">
          {shownHere.map((encounter) => (
            <EncounterCard
              key={encounter.encounter_id}
              encounter={encounter}
              taxa={taxa}
              onDecision={decide}
              onOpen={onOpen}
            />
          ))}
        </ul>
        {feed.data && !shownHere.length && (
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
        <div className="lv-links">
          <button
            type="button"
            className="tlink"
            onClick={() => onNavigate("review")}
          >
            {toReview ? `${toReview} more to review` : "Open the full review"}
          </button>
          <button
            type="button"
            className="tlink"
            onClick={() => onNavigate("summary")}
          >
            Counts and sessions
          </button>
        </div>
        <p className="lv-about">
          Watch the sensor node, check detections as they happen and correct
          them on the spot.
        </p>
      </section>
    </div>
  );
}
