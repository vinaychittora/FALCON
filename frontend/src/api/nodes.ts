import { api } from "./client";
import type { LiveState } from "../types";

export type ComponentName = "camera" | "microphone" | "climate" | "rain";

export interface NodeComponent {
  present: boolean;
  enabled: boolean;
  description: string | null;
  state?: string;
  error?: string | null;
  kind?: string | null;
  controls?: string[];
  resolutions?: string[];
  connected?: boolean;
  chip?: string;
  /** Rain plate (watched twice a second): held 10 min after the last wet moment. */
  raining?: boolean;
  last_wet?: string | null;
  wet_pulses_last_hour?: number;
}

export interface CameraSettings {
  resolution: string;
  framerate: number;
  bitrate_kbps: number;
  focus_mode: "continuous" | "manual" | "auto";
  lens_position: number;
  exposure: "normal" | "sport" | "long";
  ev: number;
  shutter_us: number;
  gain: number;
  awb: string;
  metering: string;
  brightness: number;
  contrast: number;
  saturation: number;
  sharpness: number;
  denoise: string;
  hdr: boolean;
  hflip: boolean;
  vflip: boolean;
  /** Night picture: greyscale while IR light makes a webcam's picture magenta. */
  night_mode?: "auto" | "colour" | "mono";
  /** h264: the node encodes; mjpeg: the webcam's frames pass through, FALCON decodes them. */
  video_codec?: "h264" | "mjpeg";
}

export interface PowerFlags {
  under_voltage_now: boolean;
  throttled_now: boolean;
  under_voltage_since_boot: boolean;
  throttled_since_boot: boolean;
  /** The Pi firmware's own heat protection (soft limit at 80 °C). */
  soft_temp_limit_now?: boolean;
  frequency_capped_now?: boolean;
}

export interface ThermalState {
  enabled: boolean;
  state: "normal" | "camera paused" | "stream stopped";
  temperature_c: number | null;
  pause_c: number;
  stop_c: number;
  resume_c: number;
  since: string | null;
  events: number;
}

export interface NodeExtra {
  name: "hotspot" | "bluetooth";
  label: string;
  note: string;
  available: boolean;
  on: boolean;
  at_boot: boolean;
}

export interface NodeExtras {
  extras: NodeExtra[];
  thermal: ThermalState;
  cpu_temperature_c: number | null;
  power: PowerFlags | null;
}

export const nodeExtras = (id: string) =>
  api<NodeExtras>(`/nodes/${encodeURIComponent(id)}/extras`);

export const setNodeExtra = (
  id: string,
  change: { name: NodeExtra["name"]; on?: boolean; at_boot?: boolean },
) =>
  api<NodeExtras>(`/nodes/${encodeURIComponent(id)}/extras`, {
    method: "PUT",
    body: JSON.stringify(change),
  });

/** "Paused: node too hot (86 °C), resumes below 75 °C", or null when running normally. */
export function thermalNotice(
  thermal: ThermalState | undefined,
  temperature?: number | null,
): string | null {
  if (!thermal || thermal.state === "normal") return null;
  const now = thermal.temperature_c ?? temperature;
  const what = thermal.state === "camera paused" ? "Camera paused" : "Paused";
  return `${what}: node too hot${now != null ? ` (${Math.round(now)} °C)` : ""}, resumes below ${thermal.resume_c} °C`;
}

/** The Pi's firmware is slowing the processor to protect itself from heat right now. */
export function slowedByHeat(power: PowerFlags | null | undefined): boolean {
  return Boolean(power?.soft_temp_limit_now || power?.throttled_now);
}

export interface NodeStatus {
  software: "falcon-node";
  version: string;
  node_id: string;
  name: string;
  time: string;
  clock: {
    synchronized: boolean | null;
    source: "ntp" | "falcon" | "none";
    adopted_at: string | null;
  };
  agent_uptime_seconds: number;
  system: {
    board: string;
    hostname: string;
    addresses: string[];
    uptime_seconds: number | null;
    cpu_temperature_c: number | null;
    load_1m: number;
    cpu_count: number;
    memory_used_percent: number | null;
    disk_free_bytes: number;
    disk_total_bytes: number;
    wifi_signal_dbm: number | null;
    power: PowerFlags | null;
  };
  /** The node's heat protection (absent on nodes installed before it existed). */
  thermal?: ThermalState;
  /** Added by FALCON: its own clock speed measured against this node's uptime. */
  falcon_clock?: {
    drift_percent: number | null;
    measured_seconds: number;
    warning: boolean;
  };
  stream: {
    state:
      "off" | "starting" | "streaming" | "retrying" | "no sources" | "too hot";
    since: string | null;
    restarts: number;
    error: string | null;
    rtsp_port: number;
    rtsp_path: string;
    video: boolean;
    audio: boolean;
    tracks: string[];
    readers: number;
  };
  components: Record<ComponentName, NodeComponent>;
  camera_settings: CameraSettings;
  microphone_settings: {
    audio_channel: "average" | "left" | "right";
    audio_gain_percent: number | null;
  };
  last_reading: {
    observed_at: string;
    temperature_c?: number;
    humidity_percent?: number;
    pressure_hpa?: number;
    surface_wet?: boolean;
  } | null;
  readings_queued: number;
  reading_interval_seconds: number;
}

export interface SensorNode {
  node_id: string;
  name: string;
  address: string;
  audio_analysis: boolean;
  /** "node": this node's camera; "ip": the saved IP camera, sound still from this node. */
  video_source?: "node" | "ip";
  created_at: string;
  updated_at: string;
  online: boolean;
  checked_at: string | null;
  last_seen: string | null;
  error: string | null;
  readings_collected: number;
  observing: boolean;
  status: NodeStatus | null;
}

export const listNodes = () => api<{ nodes: SensorNode[] }>("/nodes");

export const pairNode = (address: string, pairingKey: string, name?: string) =>
  api<SensorNode>("/nodes", {
    method: "POST",
    body: JSON.stringify({
      address,
      pairing_key: pairingKey,
      name: name?.trim() || null,
    }),
  });

export const updateNode = (
  id: string,
  changes: {
    name?: string;
    audio_analysis?: boolean;
    video_source?: "node" | "ip";
  },
) =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });

export const forgetNode = (id: string) =>
  api<{ nodes: SensorNode[] }>(`/nodes/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

export const refreshNode = (id: string) =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}/refresh`, {
    method: "POST",
  });

export const nodeStream = (id: string, action: "start" | "stop" | "restart") =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}/stream`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });

export const nodeComponent = (
  id: string,
  component: ComponentName,
  enabled: boolean,
) =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}/components/${component}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

export const nodeCamera = (id: string, changes: Partial<CameraSettings>) =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}/camera`, {
    method: "PUT",
    body: JSON.stringify(changes),
  });

/** One USB webcam picture control, as the sensor node reports it. */
export interface PictureControl {
  name: string;
  type: "int" | "bool" | "menu";
  min: number;
  max: number;
  step: number;
  default: number;
  value: number;
  /** Greyed out by the camera, e.g. manual exposure while exposure is automatic. */
  inactive: boolean;
  menu?: [number, string][];
}

export interface PictureControls {
  controls: PictureControl[];
  saved: Record<string, number>;
}

export const nodePicture = (id: string) =>
  api<PictureControls>(`/nodes/${encodeURIComponent(id)}/camera/controls`);

/** Applies immediately on the webcam (no stream restart) and is remembered by the node. */
export const setNodePicture = (
  id: string,
  change: { values: Record<string, number> } | { reset: true },
) =>
  api<PictureControls>(`/nodes/${encodeURIComponent(id)}/camera/controls`, {
    method: "PUT",
    body: JSON.stringify(change),
  });

export const nodeMicrophone = (
  id: string,
  changes: Partial<NodeStatus["microphone_settings"]>,
) =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}/microphone`, {
    method: "PUT",
    body: JSON.stringify(changes),
  });

export const nodeSystem = (
  id: string,
  action: "reboot" | "shutdown" | "rescan",
) =>
  api<SensorNode>(`/nodes/${encodeURIComponent(id)}/system`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });

export const observeNode = (id: string) =>
  api<LiveState>(`/nodes/${encodeURIComponent(id)}/observe`, {
    method: "POST",
  });

export const COMPONENT_LABELS: Record<
  ComponentName,
  { label: string; icon: "camera" | "sound" | "sun" | "rain" }
> = {
  camera: { label: "Camera", icon: "camera" },
  microphone: { label: "Microphone", icon: "sound" },
  climate: { label: "Weather sensor", icon: "sun" },
  rain: { label: "Rain plate", icon: "rain" },
};

export type Tone = "good" | "warn" | "bad" | "muted" | "neutral";

export function componentState(component: NodeComponent | undefined): {
  label: string;
  tone: Tone;
} {
  if (!component || !component.present)
    return { label: "Not detected", tone: "muted" };
  if (!component.enabled) return { label: "Switched off", tone: "muted" };
  const state = component.state ?? "ready";
  if (state === "error")
    return { label: component.error ?? "Error", tone: "bad" };
  if (state === "not connected")
    return { label: "Not connected", tone: "warn" };
  if (state === "wet") return { label: "Wet", tone: "neutral" };
  if (state === "dry") return { label: "Dry", tone: "neutral" };
  if (state === "starting") return { label: "Starting", tone: "neutral" };
  return {
    label: state === "ok" ? "Working" : state[0].toUpperCase() + state.slice(1),
    tone: "good",
  };
}

export function streamState(node: SensorNode): {
  label: string;
  tone: Tone;
  detail?: string;
} {
  if (!node.online || !node.status)
    return { label: "Offline", tone: "bad", detail: node.error ?? undefined };
  const stream = node.status.stream;
  switch (stream.state) {
    case "streaming":
      return { label: "Streaming", tone: "good" };
    case "off":
      return { label: "Stream off", tone: "muted" };
    case "no sources":
      return {
        label: "Nothing to stream",
        tone: "warn",
        detail: "Switch on the camera or microphone.",
      };
    case "retrying":
      return {
        label: "Retrying",
        tone: "warn",
        detail: stream.error ?? undefined,
      };
    case "too hot":
      return {
        label: "Paused (too hot)",
        tone: "warn",
        detail:
          thermalNotice(
            node.status.thermal,
            node.status.system.cpu_temperature_c,
          ) ?? undefined,
      };
    default:
      return { label: "Starting", tone: "neutral" };
  }
}

/** Health warnings a field technician should act on. */
export function nodeWarnings(status: NodeStatus | null): string[] {
  if (!status) return [];
  const warnings: string[] = [];
  const power = status.system.power;
  if (power?.under_voltage_now)
    warnings.push(
      "Power supply voltage is too low right now. Use a stronger supply or shorter cable.",
    );
  else if (power?.under_voltage_since_boot)
    warnings.push(
      "The power supply dipped below safe voltage since the last start.",
    );
  const hot = thermalNotice(status.thermal, status.system.cpu_temperature_c);
  if (hot) warnings.push(hot);
  else if (slowedByHeat(power))
    warnings.push(
      "Slowed by heat: the processor is slowing down to protect itself.",
    );
  if ((status.system.cpu_temperature_c ?? 0) >= 75)
    warnings.push("The node is hot. Check shade and ventilation.");
  if (status.clock.synchronized === false)
    warnings.push(
      "The node clock is not synchronized yet; FALCON will set it.",
    );
  if (status.system.disk_free_bytes < 1024 ** 3)
    warnings.push("Less than 1 GB of storage is free on the node.");
  if (status.readings_queued > 200)
    warnings.push(
      `${status.readings_queued} weather readings are waiting to be collected.`,
    );
  return warnings;
}
