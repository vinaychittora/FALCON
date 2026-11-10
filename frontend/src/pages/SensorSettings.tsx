import { useRef, useState, type ReactNode } from "react";
import { useListen } from "../api/listenStore";
import LiveListen from "../ui/LiveListen";
import { formatAgo } from "../api/format";
import {
  componentState,
  nodeComponent,
  nodeMicrophone,
  streamState,
  updateNode,
  type ComponentName,
  type SensorNode,
} from "../api/nodes";
import Icon from "../components/Icon";
import { api } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import CameraControls from "../ui/CameraControls";
import PauseDetection from "../ui/PauseDetection";
import NodePower from "../ui/NodePower";
import PictureControls from "../ui/PictureControls";
import Pill from "../ui/Pill";

export const SENSOR_SECTIONS = [
  { key: "camera", label: "Camera", icon: "camera" },
  { key: "microphone", label: "Microphone", icon: "sound" },
  { key: "climate", label: "Weather", icon: "thermometer" },
  { key: "rain", label: "Rain", icon: "rain" },
  { key: "power", label: "Node power", icon: "power" },
] as const;
export type SensorSection = (typeof SENSOR_SECTIONS)[number]["key"];

/** "#/sensors/<node>/<section>" → its parts, or null for the Sensors overview. */
export function sensorRoute(
  hash: string,
): { nodeId: string; section: SensorSection } | null {
  const match = hash.match(/^#\/?sensors\/([^/?#]+)\/([a-z]+)/);
  if (!match) return null;
  const section = SENSOR_SECTIONS.find((item) => item.key === match[2]);
  return section
    ? { nodeId: decodeURIComponent(match[1]), section: section.key }
    : null;
}

export const sensorHref = (nodeId: string, section: SensorSection) =>
  `#/sensors/${encodeURIComponent(nodeId)}/${section}`;

/** "Raining · last wet 13:42 · 4 wet moments in the last hour" from the node's rain status. */
export function rainDetail(rain: {
  raining?: boolean;
  last_wet?: string | null;
  wet_pulses_last_hour?: number;
}): string {
  const parts: string[] = [];
  if (rain.raining) parts.push("Raining");
  parts.push(
    rain.last_wet
      ? `last wet ${new Date(rain.last_wet).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
      : "not wet since the node started",
  );
  if (rain.wet_pulses_last_hour)
    parts.push(
      `${rain.wet_pulses_last_hour} wet moment${rain.wet_pulses_last_hour === 1 ? "" : "s"} in the last hour`,
    );
  const text = parts.join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Which camera supplies the picture when observing this node; sound stays on the node. */
function VideoSource({
  node,
  onChanged,
}: {
  node: SensorNode;
  onChanged: () => void;
}) {
  const profile = usePoll(
    () => api<{ saved: boolean; name: string }>("/live/profile"),
    30000,
  );
  const [error, setError] = useState("");
  const value = node.video_source ?? "node";
  return (
    <label className="setting">
      <span className="setting-label">Video source</span>
      <select
        value={value}
        onChange={async (change) => {
          setError("");
          try {
            await updateNode(node.node_id, {
              video_source: change.target.value as "node" | "ip",
            });
            onChanged();
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        }}
      >
        <option value="node">This node's camera</option>
        <option value="ip" disabled={!profile.data?.saved}>
          IP camera
          {profile.data?.saved
            ? ` (${profile.data.name})`
            : " (save one under Sensors first)"}
        </option>
      </select>
      <small className="muted">
        IP camera: the picture comes from the IP camera saved under Sensors → IP
        camera (RTSP); sound, weather and rain still come from this node. Takes
        effect when observation next starts.
      </small>
      {error && <small className="error">{error}</small>}
    </label>
  );
}

/** "Today: sunrise 06:39 · sunset 17:38": when Automatic night picture switches. */
function SunNote() {
  const sun = usePoll(
    () => api<{ sunrise: string | null; sunset: string | null }>("/sun"),
    600000,
  );
  if (!sun.data?.sunrise || !sun.data.sunset) return null;
  const time = (value: string) =>
    new Date(value).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  return (
    <p className="muted small-note">
      Night picture "Automatic" follows the site's sun: today sunrise{" "}
      {time(sun.data.sunrise)} · sunset {time(sun.data.sunset)} (within 45
      minutes of these, the picture colour decides).
    </p>
  );
}

/** The node page's tabs: Status (the node overview) and one per sensor. */
export function NodeTabs({
  nodeId,
  active,
}: {
  nodeId: string;
  active: SensorSection | "status";
}) {
  const tabs = [
    { key: "status", label: "Status", icon: "node", href: "#/sensors" },
    ...SENSOR_SECTIONS.map((item) => ({
      ...item,
      href: sensorHref(nodeId, item.key),
    })),
  ] as const;
  return (
    <nav className="sensor-tabs" aria-label="Sensor node">
      {tabs.map((item) => (
        <a
          key={item.key}
          href={item.href}
          className={item.key === active ? "active" : ""}
          aria-current={item.key === active ? "page" : undefined}
        >
          <Icon name={item.icon} size={16} /> {item.label}
        </a>
      ))}
    </nav>
  );
}

/**
 * The DA7212 audio HAT's mixer gain: the node maps 0–100 % onto 16 steps of 1.5 dB
 * from −4.5 dB. Shown in dB so the effect is easy to judge.
 */
export function micGainDb(percent: number): number {
  return -4.5 + Math.round((percent / 100) * 15) * 1.5;
}

/** "−37 dBFS" for the level next to the meter. */
export function levelText(dbfs: number): string {
  return Number.isFinite(dbfs) ? `${Math.round(dbfs)} dBFS` : "silent";
}

function Section({
  title,
  status,
  children,
}: {
  title: string;
  status: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card sensor-settings">
      <div className="card-header">
        <h2>{title}</h2>
        <div className="sensor-status">{status}</div>
      </div>
      {children}
    </section>
  );
}

function ComponentSwitch({
  node,
  name,
  label,
  onChanged,
}: {
  node: SensorNode;
  name: ComponentName;
  label: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const component = node.status?.components[name];
  if (!component?.present) return null;
  return (
    <>
      <label className="switch-row">
        <input
          type="checkbox"
          role="switch"
          checked={component.enabled}
          disabled={busy || !node.online}
          onChange={async (event) => {
            setBusy(true);
            setError("");
            try {
              await nodeComponent(node.node_id, name, event.target.checked);
              onChanged();
            } catch (reason) {
              setError(
                reason instanceof Error ? reason.message : String(reason),
              );
            } finally {
              setBusy(false);
            }
          }}
        />
        <span>{label}</span>
      </label>
      {error && <p className="error">{error}</p>}
    </>
  );
}

function MicrophoneSettings({
  node,
  onChanged,
}: {
  node: SensorNode;
  onChanged: () => void;
}) {
  const status = node.status!;
  const saved = status.microphone_settings;
  const listen = useListen();
  const [gain, setGain] = useState<number>(saved.audio_gain_percent ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const gainTimer = useRef<number | undefined>(undefined);
  // Applied shortly after each move, so the change is heard while listening.
  function changeGain(value: number) {
    setGain(value);
    window.clearTimeout(gainTimer.current);
    gainTimer.current = window.setTimeout(
      () => void save({ audio_gain_percent: value }),
      350,
    );
  }
  async function save(
    change: Parameters<typeof nodeMicrophone>[1] | { audio_analysis: boolean },
  ) {
    setBusy(true);
    setError("");
    try {
      if ("audio_analysis" in change) await updateNode(node.node_id, change);
      else await nodeMicrophone(node.node_id, change);
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="control-grid">
      <ComponentSwitch
        node={node}
        name="microphone"
        label="Microphone on"
        onChanged={onChanged}
      />
      <label className="switch-row">
        <input
          type="checkbox"
          role="switch"
          checked={node.audio_analysis}
          disabled={busy}
          onChange={(event) =>
            void save({ audio_analysis: event.target.checked })
          }
        />
        <span>Identify bird calls in FALCON (BirdNET, 9-second windows)</span>
      </label>
      <div className="control control-range">
        <div className="listen-row">
          <LiveListen />
          {listen.on && <span className="muted">{levelText(listen.rms)}</span>}
        </div>
        <label htmlFor={`${node.node_id}-gain`}>
          Microphone gain (sensitivity)
          <output htmlFor={`${node.node_id}-gain`}>
            {saved.audio_gain_percent == null && gain === 0
              ? "as installed"
              : `${micGainDb(gain) > 0 ? "+" : ""}${micGainDb(gain).toFixed(1)} dB`}
          </output>
        </label>
        <input
          id={`${node.node_id}-gain`}
          type="range"
          min={0}
          max={100}
          step={7}
          value={gain}
          disabled={!node.online}
          onChange={(event) => changeGain(Number(event.target.value))}
        />
        <small>
          Switch on Listen and move the slider to hear the difference. Higher
          picks up fainter calls but also more hiss. Listen's noise reduction
          only changes what you hear; bird-call detection and saved clips keep
          the original sound.
        </small>
      </div>
      <div className="control">
        <label htmlFor={`${node.node_id}-channel-page`}>
          Microphone channel
        </label>
        <select
          id={`${node.node_id}-channel-page`}
          value={saved.audio_channel}
          disabled={busy || !node.online}
          onChange={(event) =>
            void save({
              audio_channel: event.target.value as "average" | "left" | "right",
            })
          }
        >
          <option value="average">Both, averaged</option>
          <option value="left">Left only (microphone 1)</option>
          <option value="right">
            Right only (microphone 2, the audio HAT)
          </option>
        </select>
        <small>
          The audio HAT feeds its onboard microphone to the right channel.
          Restarts the stream for a few seconds.
        </small>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default function SensorSettings({
  node,
  section,
  onChanged,
}: {
  node: SensorNode;
  section: SensorSection;
  onChanged: () => void;
}) {
  const status = node.status;
  const stream = streamState(node);
  const reading = status?.last_reading;
  const pill = (name: ComponentName) => {
    const state = componentState(status?.components[name]);
    return <Pill tone={state.tone}>{state.label}</Pill>;
  };

  return (
    <div className="sensor-settings-page">
      <NodeTabs nodeId={node.node_id} active={section} />
      {!node.online || !status ? (
        <p className="banner banner-bad">
          {node.error ?? "The node is not answering."} Settings come back when
          it is reachable again.
        </p>
      ) : section === "camera" ? (
        <Section
          title={status.components.camera.description ?? "Camera"}
          status={
            <>
              {pill("camera")}
              <Pill tone={stream.tone}>{stream.label}</Pill>
            </>
          }
        >
          <ComponentSwitch
            node={node}
            name="camera"
            label="Camera on"
            onChanged={onChanged}
          />
          <PauseDetection />
          <VideoSource node={node} onChanged={onChanged} />
          {status.components.camera.kind === "v4l2" && (
            <>
              <h3 className="section-title">Picture</h3>
              <p className="muted small-note">
                Changes show in the live picture immediately and are remembered.
              </p>
              <PictureControls nodeId={node.node_id} />
            </>
          )}
          <h3 className="section-title">
            {status.components.camera.kind === "v4l2" ? "Stream" : "Picture"}
          </h3>
          <p className="muted small-note">
            Changing these restarts the stream for a few seconds; Live
            reconnects by itself.
          </p>
          <SunNote />
          <CameraControls node={node} onChanged={onChanged} />
        </Section>
      ) : section === "microphone" ? (
        <Section
          title={status.components.microphone.description ?? "Microphone"}
          status={pill("microphone")}
        >
          <MicrophoneSettings node={node} onChanged={onChanged} />
        </Section>
      ) : section === "climate" ? (
        <Section
          title={status.components.climate.description ?? "Weather sensor"}
          status={pill("climate")}
        >
          <ComponentSwitch
            node={node}
            name="climate"
            label="Weather sensor on"
            onChanged={onChanged}
          />
          {reading ? (
            <dl className="sensor-readings">
              <div>
                <dt>Temperature</dt>
                <dd>{reading.temperature_c?.toFixed(1) ?? "—"} °C</dd>
              </div>
              <div>
                <dt>Humidity</dt>
                <dd>{reading.humidity_percent?.toFixed(0) ?? "—"} %</dd>
              </div>
              <div>
                <dt>Pressure</dt>
                <dd>{reading.pressure_hpa?.toFixed(1) ?? "—"} hPa</dd>
              </div>
              <div>
                <dt>Measured</dt>
                <dd>{formatAgo(reading.observed_at)}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">No reading yet.</p>
          )}
          <p className="muted small-note">
            A reading every {status.reading_interval_seconds} s
            (READING_INTERVAL_SECONDS in the node's node.conf). For true air
            temperature, keep the sensor in shade and away from the warm node
            box.
          </p>
        </Section>
      ) : section === "rain" ? (
        <Section
          title={status.components.rain.description ?? "Rain plate"}
          status={pill("rain")}
        >
          <ComponentSwitch
            node={node}
            name="rain"
            label="Rain plate on"
            onChanged={onChanged}
          />
          <p>
            {reading?.surface_wet == null
              ? "No rain reading yet."
              : reading.surface_wet
                ? "The plate is wet."
                : "The plate is dry."}
          </p>
          <p className="muted">{rainDetail(status.components.rain)}</p>
          <p className="muted small-note">
            The plate is checked twice a second: wet means water in the last
            minute, raining is shown for 10 minutes after the last wet moment.
            Sensitivity is set with the small screw on the rain module's blue
            board. If wet and dry come out reversed, set RAIN_WET_WHEN_LOW=false
            in the node's node.conf. Mount the plate tilted so drops run off.
          </p>
        </Section>
      ) : (
        <Section
          title="Node power and heat"
          status={
            <Pill
              tone={
                (status.system.cpu_temperature_c ?? 0) >= 80 ? "warn" : "good"
              }
            >
              {status.system.cpu_temperature_c != null
                ? `${Math.round(status.system.cpu_temperature_c)} °C`
                : "—"}
            </Pill>
          }
        >
          <NodePower nodeId={node.node_id} />
          <p className="muted small-note">
            Heat protection thresholds are THERMAL_STOP_C (84 °C) and
            THERMAL_RESUME_C (75 °C) in the node's node.conf.
          </p>
        </Section>
      )}
    </div>
  );
}
