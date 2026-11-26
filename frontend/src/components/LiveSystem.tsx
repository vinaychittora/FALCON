// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState, type ReactNode } from "react";
import SceneryView from "./SceneryView";
import {
  emptySystemSnapshot,
  finiteNumber,
  startSystemPolling,
  type LiveSystemSnapshot,
  type Reading,
} from "../api/liveSystem";
import { wetness } from "../api/environment";
import { rodentNights } from "../api/rodentNights";
import { classifierLabels } from "../api/models";
import {
  listNodes,
  slowedByHeat,
  streamState,
  thermalNotice,
} from "../api/nodes";
import { usePoll } from "../hooks/usePoll";
import type { ClassifierMode } from "../types";
import Icon, { type IconName } from "./Icon";
import { formatRunDuration, formatRunNumber } from "./RunDetails";
import RecordingsLine from "./RecordingsLine";
import "./live-system.css";

const number = (value: unknown, unit = "", whole = false) => {
  const rendered = formatRunNumber(value, whole);
  return rendered === "—" || !unit ? rendered : `${rendered} ${unit}`;
};
const scaled = (value: unknown, divisor: number) => {
  const valid = finiteNumber(value);
  return valid === null ? null : valid / divisor;
};
const memory = (value: unknown) => number(scaled(value, 1024 ** 3), "GiB");
const bitrate = (value: unknown) => {
  const valid = finiteNumber(value);
  if (valid === null || valid < 0) return "—";
  return valid >= 1_000_000
    ? number(valid / 1_000_000, "Mb/s")
    : number(valid / 1000, "kb/s");
};
const codec = (value: unknown) =>
  typeof value === "string" && /^[a-z0-9_]{1,24}$/i.test(value)
    ? value.toUpperCase()
    : "—";
const clock = (value: string | null | undefined) => {
  const date = value ? new Date(value) : null;
  return date && Number.isFinite(date.valueOf())
    ? date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "medium",
      })
    : "—";
};

/** "Purple Sunbird 0.62 · Asian Koel 0.31" from the latest window's candidates. */
export function topCandidates(value: unknown, limit = 3): string {
  if (typeof value !== "string") return "—";
  try {
    const items = JSON.parse(value) as {
      common_name?: string;
      scientific_name?: string;
      score?: number;
    }[];
    if (!Array.isArray(items) || !items.length) return "Nothing bird-like";
    return items
      .slice(0, limit)
      .map(
        (item) =>
          `${item.common_name || item.scientific_name} ${Number(item.score).toFixed(2)}`,
      )
      .join(" · ");
  } catch {
    return "—";
  }
}

/** The paired sensor node's own health: stream, temperature, heat protection, load. */
function SensorNodeGroup() {
  const nodes = usePoll(listNodes, 10000);
  const node =
    nodes.data?.nodes.find((item) => item.observing) ?? nodes.data?.nodes[0];
  if (!node) return null;
  const status = node.online ? node.status : null;
  const stream = streamState(node);
  const heat = thermalNotice(status?.thermal, status?.system.cpu_temperature_c);
  return (
    <Group
      icon="node"
      title={`Sensor node · ${node.name}`}
      status={
        <Status tone={stream.tone === "good" ? "good" : "warn"}>
          {stream.label}
        </Status>
      }
    >
      <Row
        label="CPU temperature"
        value={number(status?.system.cpu_temperature_c, "°C")}
      />
      <Row
        label="Heat protection"
        value={
          heat ??
          (slowedByHeat(status?.system.power)
            ? "Slowed by heat (firmware)"
            : status?.thermal
              ? `Normal · pauses at ${status.thermal.stop_c} °C`
              : "—")
        }
      />
      <Row label="CPU load (1 min)" value={number(status?.system.load_1m)} />
      <Row
        label="Memory in use"
        value={number(status?.system.memory_used_percent, "%")}
      />
      <Row
        label="Camera stream"
        value={
          status
            ? `${status.camera_settings.resolution.replace("x", " × ")} · ${status.camera_settings.framerate} fps · ${
                status.camera_settings.video_codec === "mjpeg"
                  ? "MJPEG, decoded on this PC"
                  : `${status.camera_settings.bitrate_kbps} kb/s H.264`
              }`
            : "—"
        }
      />
      <Row
        label="FALCON clock vs node"
        value={clockDrift(status?.falcon_clock)}
      />
    </Group>
  );
}

/** "+0.0 %" or "+9.9 % · too fast: times and sound windows are off" (over ≥ 5 minutes). */
export function clockDrift(
  clock: { drift_percent: number | null; warning: boolean } | undefined,
): string {
  if (!clock || clock.drift_percent === null) return "Measuring (5 min)…";
  const value = `${clock.drift_percent >= 0 ? "+" : ""}${clock.drift_percent.toFixed(1)} %`;
  if (!clock.warning) return value;
  return `${value} · ${clock.drift_percent > 0 ? "too fast" : "too slow"}: times and sound windows are off`;
}

function freshness(reading: Reading<unknown>, now: number | null) {
  if (!reading.value) return reading.failed ? "Unavailable" : "Checking…";
  if (
    reading.failed ||
    (now !== null &&
      reading.receivedAt !== null &&
      now - reading.receivedAt > 15000)
  )
    return "Stale · last received values";
  return "Current";
}

function Status({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "good" | "warn" | "neutral";
}) {
  return (
    <span className={`live-system-status live-system-status-${tone}`}>
      <i />
      {children}
    </span>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="live-system-row">
      <dt>{label}</dt>
      <dd title={typeof value === "string" ? value : undefined}>{value}</dd>
    </div>
  );
}

function Group({
  icon,
  title,
  status,
  children,
  caption,
}: {
  icon: IconName;
  title: string;
  status?: ReactNode;
  children: ReactNode;
  caption?: string;
}) {
  return (
    <section className="live-system-group">
      <header>
        <h4>
          <Icon name={icon} size={18} />
          {title}
        </h4>
        {status}
      </header>
      <dl>{children}</dl>
      {caption && <p className="live-system-caption">{caption}</p>}
    </section>
  );
}

function Gauge({
  icon,
  label,
  value,
  percent,
  detail,
}: {
  icon: IconName;
  label: string;
  value: string;
  percent: unknown;
  detail: string;
}) {
  const valid = finiteNumber(percent);
  return (
    <div className="live-system-gauge">
      <dt>
        <Icon name={icon} size={17} />
        {label}
      </dt>
      <dd>{value}</dd>
      <div className="live-system-meter" aria-hidden="true">
        <span
          style={{
            width:
              valid === null ? "0%" : `${Math.max(0, Math.min(100, valid))}%`,
          }}
        />
      </div>
      <span className="live-system-caption">{detail}</span>
    </div>
  );
}

const sessionLabels: Record<string, string> = {
  live: "Observing",
  connecting: "Connecting",
  reconnecting: "Reconnecting",
  stopping: "Stopping",
  stopped: "Stopped",
  failed: "Connection failed",
  idle: "Not observing",
};
const inferenceLabels: Record<string, string> = {
  processing: "Processing",
  "loading models": "Loading models",
  "waiting for camera": "Waiting for camera",
  stopping: "Stopping",
  stopped: "Stopped",
};

function audioAnalysis(value: string | undefined) {
  if (value === "disabled") return "Disabled";
  if (value === "stopped") return "Stopped";
  if (value?.startsWith("analyzing recent audio")) return "Analyzing · CPU";
  if (value?.startsWith("listening:")) return "Collecting audio";
  if (value?.startsWith("audio analysis failed")) return "Analysis error";
  if (value?.includes("reconnecting")) return "Reconnecting";
  if (value?.startsWith("waiting")) return "Waiting for audio";
  return "—";
}

export function LiveSystemView({ snapshot }: { snapshot: LiveSystemSnapshot }) {
  const live = snapshot.live.value;
  const m = live?.metrics ?? {};
  const host = snapshot.host.value;
  const sensors = snapshot.sensors.value;
  const liveFresh = freshness(snapshot.live, snapshot.checkedAt);
  const hostFresh = freshness(snapshot.host, snapshot.checkedAt);
  const sensorsFresh = freshness(snapshot.sensors, snapshot.checkedAt);
  const active = live?.status === "live" && liveFresh === "Current";
  const liveDelay = Math.max(
    0,
    (snapshot.checkedAt ?? 0) -
      (snapshot.live.receivedAt ?? snapshot.checkedAt ?? 0),
  );
  const frameAge = finiteNumber(m.frame_age_ms);
  const receivingAge = frameAge === null ? null : frameAge + liveDelay;
  const cameraStatus =
    liveFresh !== "Current"
      ? liveFresh
      : !active
        ? (sessionLabels[live?.status ?? "idle"] ?? "Unavailable")
        : receivingAge !== null && receivingAge > 5000
          ? "Frames delayed"
          : receivingAge !== null
            ? "Receiving"
            : "Waiting for frames";
  const audioStatus =
    liveFresh !== "Current"
      ? liveFresh
      : live?.audio_status === "disabled"
        ? "Disabled"
        : !active
          ? "Not receiving"
          : m.audio_error
            ? "Input error"
            : snapshot.audioPacketsArriving === true
              ? "Receiving"
              : snapshot.audioPacketsArriving === false
                ? "No new audio packets"
                : "Measuring input…";
  const frameRate =
    active && receivingAge !== null && receivingAge <= 5000
      ? m.received_video_fps
      : null;
  const sensorStatus =
    sensorsFresh !== "Current"
      ? sensorsFresh
      : {
          fresh: "Connected",
          stale: "Reading stale",
          not_connected: "Not connected",
          unavailable: "Unavailable",
        }[sensors?.status ?? "unavailable"];
  const gpu = host?.gpu.devices[0];
  const sampledAge = finiteNumber(host?.sample_age_seconds);
  const hostDelay = Math.max(
    0,
    (snapshot.checkedAt ?? 0) -
      (snapshot.host.receivedAt ?? snapshot.checkedAt ?? 0),
  );
  const hostAge = sampledAge === null ? null : sampledAge + hostDelay / 1000;
  const hostStale = hostFresh !== "Current" || hostAge === null || hostAge > 15;
  const mode = m.classifier_mode;
  const model =
    typeof mode === "string" && mode in classifierLabels
      ? classifierLabels[mode as ClassifierMode]
      : "—";
  const scope =
    host?.scope === "wsl"
      ? "WSL Linux environment · CPU and RAM are not Windows host totals" +
        // WSL's "tsc" clock source was measured 10 % fast; see "FALCON clock vs node".
        (host.clocksource === "tsc"
          ? " · clock source tsc: check the clock row under Sensor node"
          : "")
      : host?.scope === "linux"
        ? "Linux inference server"
        : host?.scope === "windows"
          ? "Windows inference server"
          : "Inference server environment";
  const evidenceState =
    typeof m.evidence_recorder_status === "string"
      ? m.evidence_recorder_status
      : "";
  const evidenceFault = [
    m.evidence_error,
    m.evidence_capture_fault,
    m.evidence_recording_fault,
  ].some((value) => typeof value === "string" && !!value);
  const evidenceLabel = !active
    ? "Not recording"
    : evidenceFault
      ? "Recorder needs attention"
      : evidenceState === "buffering"
        ? "Rolling buffer active"
        : evidenceState === "starting"
          ? "Starting buffer"
          : "Waiting for recorder";
  const cameraName =
    live?.name && !/[:/@\\\r\n]/.test(live.name)
      ? live.name.slice(0, 100)
      : "Camera";
  const hostMetric = (value: unknown) => (hostStale ? null : value);
  return (
    <section className="live-system" aria-label="Live system status">
      <header className="live-system-heading">
        <div>
          <span className="live-system-eyebrow">Live system</span>
          <h3>{live?.session_id ? cameraName : "Field monitoring"}</h3>
          <p>Camera, sound, sensors and inference server</p>
        </div>
        <div className="live-system-update">
          <Status
            tone={
              active
                ? "good"
                : liveFresh === "Current" && live?.status !== "failed"
                  ? "neutral"
                  : "warn"
            }
          >
            {liveFresh === "Current"
              ? sessionLabels[live?.status ?? "idle"]
              : liveFresh}
          </Status>
          <span>Refreshes every 5 seconds</span>
        </div>
      </header>
      <div className="live-system-inputs">
        <Group
          icon="camera"
          title="Camera input"
          status={
            <Status tone={cameraStatus === "Receiving" ? "good" : "neutral"}>
              {cameraStatus}
            </Status>
          }
          caption="Received FPS and video bitrate use the camera's rolling 5-second window."
        >
          <Row label="Received frame rate" value={number(frameRate, "fps")} />
          <Row
            label="Video bitrate · measured"
            value={bitrate(
              active && receivingAge !== null && receivingAge <= 5000
                ? m.measured_video_bitrate_bps
                : null,
            )}
          />
          <Row
            label="Resolution / codec"
            value={`${finiteNumber(m.width) !== null && finiteNumber(m.height) !== null ? `${number(m.width, "", true)} × ${number(m.height, "", true)}` : "—"} / ${codec(m.video_codec)}`}
          />
          <Row
            label="Camera frame rate · reported"
            value={number(m.nominal_video_fps, "fps")}
          />
          <Row
            label="Latest frame age"
            value={number(active ? scaled(receivingAge, 1000) : null, "s")}
          />
          <Row
            label="Reconnects this session"
            value={number(m.reconnects, "", true)}
          />
        </Group>
        <Group
          icon="sound"
          title="Audio input"
          status={
            <Status
              tone={
                audioStatus === "Receiving"
                  ? "good"
                  : audioStatus === "Input error" ||
                      audioStatus === "No new audio packets"
                    ? "warn"
                    : "neutral"
              }
            >
              {audioStatus}
            </Status>
          }
          caption="Packet activity and sound recognition are separate. Quiet audio can still be received normally."
        >
          <Row label="Codec" value={codec(m.audio_codec)} />
          <Row
            label="Sample rate / channels"
            value={`${number(m.audio_sample_rate, "Hz", true)} / ${number(m.audio_channels, "", true)}`}
          />
          <Row
            label="Audio bitrate · reported"
            value={bitrate(m.reported_audio_bitrate_bps)}
          />
          <Row
            label="BirdNET"
            value={
              liveFresh === "Current"
                ? audioAnalysis(live?.audio_status)
                : "Status unavailable"
            }
          />
          <Row
            label="Latest result lag"
            value={number(
              active ? scaled(m.audio_result_lag_ms, 1000) : null,
              "s",
            )}
          />
          <Row
            label="Audio gaps / reconnects"
            value={`${number(m.audio_discontinuities, "", true)} / ${number(m.audio_reconnects, "", true)}`}
          />
          {/* Sound analysis: what BirdNET heard in the latest window, even below the
              confidence needed to record an observation. */}
          <Row
            label="Last sound window"
            value={
              typeof m.audio_last_window_at === "string"
                ? clock(m.audio_last_window_at)
                : "—"
            }
          />
          <Row label="Sound level" value={number(m.audio_level_dbfs, "dBFS")} />
          <Row
            label="Sound analysis"
            value={
              typeof m.audio_stalled_since === "string" && m.audio_stalled_since
                ? `Stalled since ${clock(m.audio_stalled_since)}${Number(m.audio_stall_restarts) ? ` · node stream restarted ${m.audio_stall_restarts}×` : ""}`
                : "Running"
            }
          />
          <Row
            label="Top candidates"
            value={topCandidates(m.audio_top_candidates)}
          />
        </Group>
      </div>
      <section className="live-system-host" aria-label="Processing computer">
        <header className="live-system-section-heading">
          <div>
            <h4>
              <Icon name="chip" size={18} />
              Processing computer
            </h4>
            <p>{scope}</p>
          </div>
          <span className="live-system-updated">
            {hostStale
              ? host
                ? "Telemetry stale · live values unavailable"
                : hostFresh
              : `Sample ${number(hostAge, "s")} ago`}
          </span>
        </header>
        <dl className="live-system-gauges">
          <Gauge
            icon="activity"
            label="CPU utilization"
            value={number(hostMetric(host?.cpu.percent), "%")}
            percent={hostMetric(host?.cpu.percent)}
            detail={`${number(host?.cpu.logical_count, "", true)} logical CPUs · ${number(hostMetric(host?.cpu.temperature_c), "°C")}`}
          />
          <Gauge
            icon="chip"
            label={
              host?.gpu.devices.length && host.gpu.devices.length > 1
                ? `GPU ${gpu?.index} utilization`
                : "GPU utilization"
            }
            value={number(hostMetric(gpu?.utilization_percent), "%")}
            percent={hostMetric(gpu?.utilization_percent)}
            detail={
              gpu
                ? `${number(hostMetric(gpu.temperature_c), "°C")} · ${number(hostMetric(gpu.power_watts), "W")}`
                : "GPU telemetry unavailable"
            }
          />
          <Gauge
            icon="library"
            label="Memory in use"
            value={memory(hostMetric(host?.memory.used_bytes))}
            percent={hostMetric(host?.memory.percent)}
            detail={`of ${memory(host?.memory.total_bytes)} · ${number(hostMetric(host?.memory.percent), "%")}`}
          />
          <Gauge
            icon="download"
            label="Data storage free"
            value={memory(hostMetric(host?.storage.free_bytes))}
            percent={hostMetric(host?.storage.percent)}
            detail={`of ${memory(host?.storage.total_bytes)} · ${number(hostMetric(host?.storage.percent), "%")} used`}
          />
        </dl>
        <div className="live-system-compute-meta">
          <span>
            Server uptime{" "}
            <strong>
              {hostStale
                ? "—"
                : formatRunDuration(host?.process.uptime_seconds)}
            </strong>
          </span>
          <span>
            Server process memory{" "}
            <strong>{memory(hostMetric(host?.process.rss_bytes))}</strong>
          </span>
          <span>
            GPU memory{" "}
            <strong>
              {number(hostMetric(gpu?.memory_used_mib), "MiB")} /{" "}
              {number(gpu?.memory_total_mib, "MiB")}
            </strong>
          </span>
        </div>
        {gpu ? (
          <p className="live-system-caption">
            GPU {gpu.index}: {gpu.name}. Measurements shown are for this device
            and include other processes using it.
          </p>
        ) : (
          <p className="live-system-caption">
            Unavailable hardware measurements remain blank. Server process
            memory excludes separate workers.
          </p>
        )}
        <RecordingsLine />
      </section>
      <div className="live-system-inputs live-system-bottom">
        <Group
          icon="eye"
          title="Live inference"
          status={
            <Status
              tone={
                active &&
                m.inference_status === "processing" &&
                receivingAge !== null &&
                receivingAge <= 5000
                  ? "good"
                  : "neutral"
              }
            >
              {liveFresh !== "Current"
                ? "Status unavailable"
                : !active
                  ? (sessionLabels[live?.status ?? "idle"] ?? "Not running")
                  : active && receivingAge !== null && receivingAge > 5000
                    ? "Waiting for fresh frames"
                    : (inferenceLabels[String(m.inference_status)] ??
                      "Not running")}
            </Status>
          }
          caption="Processing FPS counts analyzed frames between updates. Counts below belong to this live session."
        >
          <Row label="Species model" value={model} />
          <Row
            label="Inference device"
            value={
              m.device === "cuda" ? "CUDA" : m.device === "cpu" ? "CPU" : "—"
            }
          />
          <Row
            label="Camera day/night switching"
            value={
              Number(m.camera_flicker) === 1
                ? "Camera switching day/night · detections paused"
                : `Steady${Number(m.camera_flicker_episodes) ? ` · ${m.camera_flicker_episodes} pause(s) this session, ${Number(m.flicker_suppressed) || 0} detections held back` : ""}`
            }
          />
          <Row
            label="Camera picture"
            value={
              typeof m.camera_damaged_since === "string" && m.camera_damaged_since
                ? `Damaged since ${clock(m.camera_damaged_since)} · camera restarted ${Number(m.camera_restarts) || 0}× · restart the node (Sensors → More → Restart the node)`
                : `Whole${Number(m.broken_frames_dropped) ? ` · ${m.broken_frames_dropped} broken frames refused this session` : ""}`
            }
          />
          <SceneryView
            boxes={Number(m.scenery_boxes) || 0}
            heldBack={Number(m.still_object_suppressed) || 0}
          />
          <Row label="Rats and mice at night" value={rodentNights(m.rodents_recent)} />
          <Row label="Pictures with no score at night" value={rodentNights(m.noscore_recent)} />
          <Row
            label="Processing / target rate"
            value={`${number(snapshot.processedFps, "fps")} / ${number(m.sample_fps, "fps")}`}
          />
          <Row
            label="Latest visual result lag"
            value={number(
              active ? scaled(m.inference_lag_ms, 1000) : null,
              "s",
            )}
          />
          <Row
            label="Analyzed frames / audio windows"
            value={`${number(m.visual_frames, "", true)} / ${number(m.audio_chunks_analyzed, "", true)}`}
          />
          <Row
            label="Visual / acoustic observations"
            value={`${number(m.visual_detections, "", true)} / ${number(m.audio_detections, "", true)}`}
          />
          <Row
            label="Session started · local time"
            value={clock(live?.started_at)}
          />
        </Group>
        <Group
          icon="library"
          title="Evidence capture"
          status={
            <Status
              tone={
                evidenceFault
                  ? "warn"
                  : active && evidenceState === "buffering"
                    ? "good"
                    : "neutral"
              }
            >
              {liveFresh !== "Current" ? "Status unavailable" : evidenceLabel}
            </Status>
          }
          caption="One continuous recording per stay of an animal, with the microphone sound, and a sound record for each calling stretch. Recordings are kept or removed by the retention rules."
        >
          <Row
            label="Video clips ready"
            value={number(m.evidence_ready_clips, "", true)}
          />
          <Row
            label="Video clips pending"
            value={number(m.evidence_pending_clips, "", true)}
          />
          <Row
            label="Partial / failed video clips"
            value={`${number(m.evidence_partial_clips, "", true)} / ${number(m.evidence_failed_clips, "", true)}`}
          />
          <Row
            label="Audio clips saved"
            value={number(m.audio_clips_saved, "", true)}
          />
          <Row
            label="Rolling buffer size"
            value={number(scaled(m.evidence_buffer_bytes, 1024 ** 2), "MiB")}
          />
          <Row
            label="Dropped audio windows"
            value={number(m.dropped_audio_chunks, "", true)}
          />
          <Row label="Observation clock" value="Server receive time" />
        </Group>
        <SensorNodeGroup />
      </div>
      <section
        className="live-system-environment"
        aria-label="Incoming sensor readings"
      >
        <header>
          <h4>
            <Icon name="leaf" size={18} />
            Environment
          </h4>
          <Status
            tone={
              sensorStatus === "Connected"
                ? "good"
                : sensorStatus.includes("stale")
                  ? "warn"
                  : "neutral"
            }
          >
            {sensorStatus}
          </Status>
        </header>
        <dl>
          <div>
            <dt>
              <Icon name="sun" size={17} />
              Temperature
            </dt>
            <dd>{number(sensors?.temperature_c, "°C")}</dd>
          </div>
          <div>
            <dt>
              <Icon name="drop" size={17} />
              Humidity
            </dt>
            <dd>{number(sensors?.humidity_percent, "%")}</dd>
          </div>
          <div>
            <dt>
              <Icon name="wind" size={17} />
              Pressure
            </dt>
            <dd>{number(sensors?.pressure_hpa, "hPa")}</dd>
          </div>
          <div>
            <dt>
              <Icon name="rain" size={17} />
              Rain plate
            </dt>
            <dd>{wetness(sensors?.surface_wet)}</dd>
          </div>
        </dl>
        <p className="live-system-caption">
          {sensors?.observed_at
            ? `Last reading: ${clock(sensors.observed_at)} · age ${number(sensors.age_seconds, "s")}${sensorStatus !== "Connected" ? " · retained reading, not a current measurement" : ""}`
            : "No sensor readings received. Values appear when a sensor node sends measurements."}
        </p>
      </section>
      <p className="live-system-footer">
        {snapshot.checkedAt
          ? `Last status check: ${new Date(snapshot.checkedAt).toLocaleTimeString()}`
          : "Reading local system status…"}{" "}
        · No device addresses or credentials are shown here.
      </p>
    </section>
  );
}

export default function LiveSystem() {
  const [snapshot, setSnapshot] = useState(emptySystemSnapshot);
  useEffect(() => startSystemPolling(setSnapshot), []);
  return <LiveSystemView snapshot={snapshot} />;
}
