// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { formatAgo, formatBytes, formatDuration } from "../api/format";
import { wetness } from "../api/environment";
import {
  COMPONENT_LABELS,
  componentState,
  forgetNode,
  listNodes,
  nodeComponent,
  nodeStream,
  nodeSystem,
  nodeWarnings,
  observeNode,
  pairNode,
  refreshNode,
  streamState,
  updateNode,
  type ComponentName,
  type SensorNode,
} from "../api/nodes";
import CameraSpot from "../components/CameraSpot";
import Icon from "../components/Icon";
import {
  canReuseCameraPassword,
  validateCameraUrl,
  type CameraProfile,
} from "../components/LiveCamera";
import SensorHistory from "../components/SensorHistory";
import { usePoll } from "../hooks/usePoll";
import Pill from "../ui/Pill";
import SensorSettings, { NodeTabs, sensorRoute } from "./SensorSettings";

type Appliance = {
  auto_observe: boolean;
  camera_saved: boolean;
  state: string;
  message: string;
  source: string;
  source_name: string | null;
};

function useAction(onDone: () => void) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  /** Runs the action; true when it succeeded, so a caller never reports a failed save. */
  async function run(label: string, action: () => Promise<unknown>): Promise<boolean> {
    setBusy(label);
    setError("");
    try {
      await action();
      onDone();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return false;
    } finally {
      setBusy("");
    }
  }
  return { busy, error, run, setError };
}

function Metric({
  label,
  value,
  warn = false,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className={`metric${warn ? " warn" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function NodePanel({
  node,
  onChanged,
  onLive,
}: {
  node: SensorNode;
  onChanged: () => void;
  onLive: () => void;
}) {
  const { busy, error, run } = useAction(onChanged);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(node.name);
  const status = node.status;
  const stream = streamState(node);
  const system = status?.system;
  const confirmThen = (
    message: string,
    label: string,
    action: () => Promise<unknown>,
  ) => {
    if (window.confirm(message)) void run(label, action);
  };
  return (
    <section className="card node-panel" aria-label={node.name}>
      <div className="node-head">
        <div className="node-title">
          <Icon name="node" size={22} />
          <div>
            {renaming ? (
              <form
                className="inline-form"
                onSubmit={(submit) => {
                  submit.preventDefault();
                  void run("rename", () =>
                    updateNode(node.node_id, { name }),
                  ).then(() => setRenaming(false));
                }}
              >
                <input
                  value={name}
                  maxLength={80}
                  onChange={(change) => setName(change.target.value)}
                  aria-label="Node name"
                  autoFocus
                />
                <button
                  className="primary"
                  type="submit"
                  disabled={!!busy || !name.trim()}
                >
                  Save
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setRenaming(false)}
                >
                  Cancel
                </button>
              </form>
            ) : (
              <h2>
                {node.name}
                <button
                  className="icon-button"
                  onClick={() => setRenaming(true)}
                  aria-label="Rename node"
                  title="Rename"
                >
                  <Icon name="edit" size={14} />
                </button>
              </h2>
            )}
            <p className="muted">
              <code>{node.node_id}</code> ·{" "}
              {node.address.replace("http://", "")}
              {status
                ? ` · ${status.system.board} · software ${status.version}`
                : ""}
            </p>
          </div>
        </div>
        <div className="node-state">
          <Pill tone={stream.tone} title={stream.detail}>
            {stream.label}
          </Pill>
          {node.observing && <Pill tone="live">Being observed</Pill>}
          <small className="muted">
            {node.online
              ? `checked ${formatAgo(node.checked_at)}`
              : `last seen ${formatAgo(node.last_seen)}`}
          </small>
        </div>
      </div>
      <NodeTabs nodeId={node.node_id} active="status" />
      {!node.online && (
        <p className="banner banner-bad">
          {node.error ?? "The node is not answering."} Check that it is powered,
          on the same network, and that its address has not changed.
        </p>
      )}
      {stream.detail && node.online && (
        <p className="banner banner-warn">{stream.detail}</p>
      )}
      {nodeWarnings(status).map((warning) => (
        <p className="banner banner-warn" key={warning}>
          {warning}
        </p>
      ))}
      {error && (
        <p className="banner banner-bad" role="alert">
          {error}
        </p>
      )}
      <div className="node-actions">
        {status?.stream.state === "off" ? (
          <button
            className="primary"
            disabled={!!busy || !node.online}
            onClick={() =>
              void run("start", () => nodeStream(node.node_id, "start"))
            }
          >
            <Icon name="play" size={15} /> Start streaming
          </button>
        ) : (
          <button
            disabled={!!busy || !node.online}
            onClick={() =>
              void run("stop", () => nodeStream(node.node_id, "stop"))
            }
          >
            <Icon name="pause" size={15} /> Stop streaming
          </button>
        )}
        <button
          disabled={!!busy || !node.online}
          onClick={() =>
            void run("restart", () => nodeStream(node.node_id, "restart"))
          }
        >
          <Icon name="refresh" size={15} /> Restart stream
        </button>
        <button
          disabled={!!busy || !node.online || node.observing}
          onClick={() =>
            void run("observe", async () => {
              await observeNode(node.node_id);
              onLive();
            })
          }
        >
          <Icon name="eye" size={15} /> Observe live
        </button>
        <button
          disabled={!!busy}
          onClick={() => void run("refresh", () => refreshNode(node.node_id))}
        >
          <Icon name="refresh" size={15} /> Check now
        </button>
        <details className="menu">
          <summary>
            <Icon name="menu" size={15} /> More
          </summary>
          <div className="menu-body">
            <button
              disabled={!!busy || !node.online}
              onClick={() =>
                void run("rescan", () => nodeSystem(node.node_id, "rescan"))
              }
            >
              Find attached hardware again
            </button>
            <button
              disabled={!!busy || !node.online}
              onClick={() =>
                confirmThen(
                  `Restart ${node.name}? It is back in about a minute.`,
                  "reboot",
                  () => nodeSystem(node.node_id, "reboot"),
                )
              }
            >
              Restart the node
            </button>
            <button
              disabled={!!busy || !node.online}
              onClick={() =>
                confirmThen(
                  `Shut down ${node.name}? It stays off until its power is switched off and on again.`,
                  "shutdown",
                  () => nodeSystem(node.node_id, "shutdown"),
                )
              }
            >
              Shut down the node
            </button>
            <button
              className="danger-text"
              disabled={!!busy}
              onClick={() =>
                confirmThen(
                  `Forget ${node.name}? FALCON stops collecting its readings. Saved observations are kept; pair it again with its key to reconnect.`,
                  "forget",
                  () => forgetNode(node.node_id),
                )
              }
            >
              Forget this node
            </button>
          </div>
        </details>
      </div>
      <CameraSpot nodeId={node.node_id} />
      {status && (
        <>
          <h3 className="section-title">Sensors</h3>
          <div className="component-list">
            {(Object.keys(COMPONENT_LABELS) as ComponentName[]).map(
              (component) => {
                const item = status.components[component];
                const shown = componentState(item);
                return (
                  <div
                    className={`component-row tone-${shown.tone}`}
                    key={component}
                  >
                    <Icon name={COMPONENT_LABELS[component].icon} size={20} />
                    <div>
                      <strong>{COMPONENT_LABELS[component].label}</strong>
                      <small>
                        {item.present
                          ? item.description
                          : "Not detected on this node"}
                      </small>
                    </div>
                    <Pill tone={shown.tone}>{shown.label}</Pill>
                    <label
                      className="switch-row"
                      title={item.present ? "Switch on or off" : "Not detected"}
                    >
                      <input
                        type="checkbox"
                        role="switch"
                        aria-label={`${COMPONENT_LABELS[component].label} on`}
                        checked={item.present && item.enabled}
                        disabled={!item.present || !!busy || !node.online}
                        onChange={(change) =>
                          void run(component, () =>
                            nodeComponent(
                              node.node_id,
                              component,
                              change.target.checked,
                            ),
                          )
                        }
                      />
                    </label>
                  </div>
                );
              },
            )}
          </div>
          <div className="node-columns">
            <div>
              <h3 className="section-title">Health</h3>
              <div className="metrics">
                <Metric
                  label="Processor temperature"
                  value={
                    system?.cpu_temperature_c !== null &&
                    system?.cpu_temperature_c !== undefined
                      ? `${system.cpu_temperature_c.toFixed(1)} °C`
                      : "—"
                  }
                  warn={(system?.cpu_temperature_c ?? 0) >= 75}
                />
                <Metric
                  label="Load (1 min)"
                  value={
                    system
                      ? `${system.load_1m.toFixed(2)} / ${system.cpu_count} cores`
                      : "—"
                  }
                />
                <Metric
                  label="Memory used"
                  value={
                    system?.memory_used_percent !== null &&
                    system?.memory_used_percent !== undefined
                      ? `${system.memory_used_percent.toFixed(0)} %`
                      : "—"
                  }
                />
                <Metric
                  label="Storage free"
                  value={
                    system
                      ? `${formatBytes(system.disk_free_bytes)} of ${formatBytes(system.disk_total_bytes)}`
                      : "—"
                  }
                  warn={(system?.disk_free_bytes ?? Infinity) < 1024 ** 3}
                />
                <Metric
                  label="Network"
                  value={
                    system?.wifi_signal_dbm !== null &&
                    system?.wifi_signal_dbm !== undefined
                      ? `Wi-Fi ${system.wifi_signal_dbm} dBm`
                      : "Wired"
                  }
                  warn={
                    (system?.wifi_signal_dbm ?? 0) < -75 &&
                    system?.wifi_signal_dbm !== null
                  }
                />
                <Metric
                  label="Running for"
                  value={formatDuration((system?.uptime_seconds ?? 0) * 1000)}
                />
                <Metric
                  label="Clock"
                  value={
                    status.clock.synchronized
                      ? status.clock.source === "falcon"
                        ? "Set by FALCON"
                        : "Internet time"
                      : "Not synchronized"
                  }
                  warn={status.clock.synchronized === false}
                />
                <Metric
                  label="Power"
                  value={
                    system?.power
                      ? system.power.under_voltage_now
                        ? "Too low now"
                        : system.power.under_voltage_since_boot
                          ? "Dipped since start"
                          : "OK"
                      : "—"
                  }
                  warn={!!system?.power?.under_voltage_now}
                />
              </div>
            </div>
            <div>
              <h3 className="section-title">Stream</h3>
              <div className="metrics">
                <Metric label="State" value={stream.label} />
                <Metric
                  label="Contents"
                  value={
                    status.stream.tracks.length
                      ? status.stream.tracks.join(" + ")
                      : "—"
                  }
                />
                <Metric
                  label="Readers"
                  value={
                    status.stream.readers
                      ? `${status.stream.readers} (FALCON connected)`
                      : "none"
                  }
                />
                <Metric
                  label="Restarts"
                  value={String(status.stream.restarts)}
                  warn={status.stream.restarts > 5}
                />
                <Metric
                  label="Address"
                  value={`rtsp :${status.stream.rtsp_port}/${status.stream.rtsp_path}`}
                />
              </div>
            </div>
            <div>
              <h3 className="section-title">Weather readings</h3>
              <div className="metrics">
                <Metric
                  label="Temperature"
                  value={
                    status.last_reading?.temperature_c != null
                      ? `${status.last_reading.temperature_c} °C`
                      : "—"
                  }
                />
                <Metric
                  label="Humidity"
                  value={
                    status.last_reading?.humidity_percent != null
                      ? `${status.last_reading.humidity_percent} %`
                      : "—"
                  }
                />
                <Metric
                  label="Pressure"
                  value={
                    status.last_reading?.pressure_hpa != null
                      ? `${status.last_reading.pressure_hpa} hPa`
                      : "—"
                  }
                />
                <Metric
                  label="Rain plate"
                  value={
                    status.last_reading
                      ? wetness(status.last_reading.surface_wet)
                      : "—"
                  }
                />
                <Metric
                  label="Measured"
                  value={
                    status.last_reading
                      ? formatAgo(status.last_reading.observed_at)
                      : "—"
                  }
                />
                <Metric
                  label="Every"
                  value={`${status.reading_interval_seconds} s`}
                />
                <Metric
                  label="Waiting on node"
                  value={String(status.readings_queued)}
                />
                <Metric
                  label="Collected this run"
                  value={String(node.readings_collected)}
                />
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function PairNodeDialog({
  onClose,
  onPaired,
}: {
  onClose: () => void;
  onPaired: (node: SensorNode) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [address, setAddress] = useState("");
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);
  async function submit() {
    setBusy(true);
    setError("");
    try {
      onPaired(await pairNode(address, key, name));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="modal panel pair-dialog"
      aria-labelledby="pair-title"
      onCancel={onClose}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="panel-heading">
          <h3 id="pair-title">Add a FALCON sensor node</h3>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="Close"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
        <ol className="steps">
          <li>
            Install the node software on the Raspberry Pi (one command, or
            prepare the SD card; see the README).
          </li>
          <li>
            The installer prints the node's address and pairing key. They are
            also in <code>PAIRING.txt</code> on the SD card.
          </li>
        </ol>
        <div className="form-field">
          <label htmlFor="pair-address">Node address</label>
          <input
            id="pair-address"
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder="falcon-node.local or its IP address"
            autoComplete="off"
            spellCheck={false}
            required
          />
          <small>
            IP address or host name. Port 8780 is used unless you add another
            (for example host:8790).
          </small>
        </div>
        <div className="form-field">
          <label htmlFor="pair-key">Pairing key</label>
          <input
            id="pair-key"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="ABCD-EFGH-IJKL-MNOP-QRST-UVWX"
            autoComplete="off"
            spellCheck={false}
            required
          />
          <small>
            The key never leaves this computer; requests to the node are signed
            with it.
          </small>
        </div>
        <div className="form-field">
          <label htmlFor="pair-name">Name (optional)</label>
          <input
            id="pair-name"
            value={name}
            maxLength={80}
            onChange={(event) => setName(event.target.value)}
            placeholder="Uses the node's own name"
          />
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="form-row">
          <button
            className="primary"
            type="submit"
            disabled={busy || !address.trim() || !key.trim()}
          >
            {busy ? "Connecting…" : "Connect node"}
          </button>
          <button type="button" className="text-button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </dialog>
  );
}

function IpCameraCard() {
  const profile = usePoll(() => api<CameraProfile>("/live/profile"), 0);
  const [draft, setDraft] = useState<{
    name: string;
    url: string;
    username: string;
    password: string;
    audio: boolean;
  } | null>(null);
  const { busy, error, run, setError } = useAction(() => profile.refresh());
  const [notice, setNotice] = useState("");
  const saved = profile.data;
  const form = draft ?? {
    name: saved?.name ?? "IP camera",
    url: saved?.url ?? "",
    username: saved?.username ?? "",
    password: "",
    audio: saved?.audio_enabled ?? true,
  };
  const reuse = canReuseCameraPassword(
    saved ?? null,
    form.url,
    form.username,
    form.password,
  );
  async function save() {
    const problem = validateCameraUrl(form.url.trim());
    if (problem) {
      setError(problem);
      return;
    }
    const stored = await run("save", () =>
      api<CameraProfile>("/live/profile", {
        method: "PUT",
        body: JSON.stringify({
          name: form.name.trim() || "IP camera",
          url: form.url.trim(),
          username: form.username,
          ...(reuse ? {} : { password: form.password }),
          audio_enabled: form.audio,
        }),
      }),
    );
    if (!stored) return;
    setDraft(null);
    setNotice("Camera saved. Choose it on the Live page to start observing.");
  }
  return (
    <section className="card ip-camera" aria-label="IP camera">
      <div className="card-header">
        <div>
          <h2>
            <Icon name="camera" size={18} /> IP camera (RTSP)
          </h2>
          <p className="muted">
            For a ready-made network camera such as a TP-Link Tapo. FALCON reads
            its stream; picture settings stay in the camera's own app.
          </p>
        </div>
        {saved?.saved && <Pill tone="good">Saved</Pill>}
      </div>
      <form
        className="form-grid"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <div className="form-field">
          <label htmlFor="cam-name">Name</label>
          <input
            id="cam-name"
            value={form.name}
            maxLength={80}
            onChange={(event) =>
              setDraft({ ...form, name: event.target.value })
            }
          />
        </div>
        <div className="form-field wide">
          <label htmlFor="cam-url">Stream address</label>
          <input
            id="cam-url"
            value={form.url}
            spellCheck={false}
            autoComplete="off"
            placeholder="rtsp://camera-address:554/stream1"
            onChange={(event) => setDraft({ ...form, url: event.target.value })}
          />
        </div>
        <div className="form-field">
          <label htmlFor="cam-user">Camera account</label>
          <input
            id="cam-user"
            value={form.username}
            autoComplete="off"
            onChange={(event) =>
              setDraft({ ...form, username: event.target.value })
            }
          />
        </div>
        <div className="form-field">
          <label htmlFor="cam-password">Password</label>
          <input
            id="cam-password"
            type="password"
            value={form.password}
            autoComplete="new-password"
            placeholder={reuse ? "Saved · leave blank to keep" : ""}
            onChange={(event) =>
              setDraft({ ...form, password: event.target.value })
            }
          />
        </div>
        <label className="switch-row wide">
          <input
            type="checkbox"
            role="switch"
            checked={form.audio}
            onChange={(event) =>
              setDraft({ ...form, audio: event.target.checked })
            }
          />
          <span>Identify bird calls in the camera's sound</span>
        </label>
        <div className="form-row wide">
          <button className="primary" type="submit" disabled={!!busy}>
            {busy === "save" ? "Saving…" : "Save camera"}
          </button>
          {saved?.saved && (
            <button
              type="button"
              className="text-button danger-text"
              disabled={!!busy}
              onClick={() => {
                if (window.confirm("Forget the saved camera and its password?"))
                  void run("forget", () =>
                    api<CameraProfile>("/live/profile", { method: "DELETE" }),
                  ).then(() => setDraft(null));
              }}
            >
              Forget camera
            </button>
          )}
          <small className="muted">
            The password is encrypted and stored only on this computer.
          </small>
        </div>
      </form>
      {notice && <p className="banner banner-good">{notice}</p>}
      {error && (
        <p className="banner banner-bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function AutoStartCard({ nodes }: { nodes: SensorNode[] }) {
  const appliance = usePoll(() => api<Appliance>("/appliance"), 15000);
  const { busy, error, run } = useAction(() => appliance.refresh());
  const value = appliance.data;
  if (!value) return null;
  const update = (
    changes: Partial<Pick<Appliance, "auto_observe" | "source">>,
  ) =>
    void run("save", () =>
      api<Appliance>("/appliance", {
        method: "PUT",
        body: JSON.stringify({
          auto_observe: changes.auto_observe ?? value.auto_observe,
          source: changes.source ?? value.source,
        }),
      }),
    );
  return (
    <section className="card autostart" aria-label="Automatic start">
      <div className="card-header">
        <div>
          <h2>
            <Icon name="power" size={18} /> Start automatically
          </h2>
          <p className="muted">
            After a power cut or restart, FALCON reconnects and resumes
            observing without anyone touching it.
          </p>
        </div>
        <Pill tone={value.auto_observe ? "good" : "muted"}>
          {value.auto_observe ? "On" : "Off"}
        </Pill>
      </div>
      <div className="form-grid">
        <label className="switch-row">
          <input
            type="checkbox"
            role="switch"
            checked={value.auto_observe}
            disabled={!!busy}
            onChange={(event) => update({ auto_observe: event.target.checked })}
          />
          <span>Observe automatically when FALCON starts</span>
        </label>
        <div className="form-field">
          <label htmlFor="autostart-source">Source</label>
          <select
            id="autostart-source"
            value={value.source}
            disabled={!!busy}
            onChange={(event) => update({ source: event.target.value })}
          >
            {nodes.map((node) => (
              <option key={node.node_id} value={`node:${node.node_id}`}>
                {node.name} (sensor node)
              </option>
            ))}
            <option value="camera" disabled={!value.camera_saved}>
              Saved IP camera{value.camera_saved ? "" : " (not saved)"}
            </option>
          </select>
        </div>
      </div>
      <p className="muted">{value.message}</p>
      {error && (
        <p className="banner banner-bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default function SensorsPage({
  onNavigate,
}: {
  onNavigate: (page: string) => void;
}) {
  const nodes = usePoll(listNodes, 5000);
  const [pairing, setPairing] = useState(false);
  const list = nodes.data?.nodes ?? [];
  // "#/sensors/<node>/<sensor>" opens that sensor's own settings page.
  const [route, setRoute] = useState(() =>
    typeof window === "undefined" ? null : sensorRoute(window.location.hash),
  );
  useEffect(() => {
    const onHash = () => setRoute(sensorRoute(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const routed = route && list.find((item) => item.node_id === route.nodeId);
  if (route && routed)
    return (
      <div className="page sensors-page">
        <header className="page-header">
          <div>
            <h2 className="page-h1">{routed.name}</h2>
            <p>
              Settings for each sensor on this node. Most changes apply
              immediately; the page says when the stream restarts.
            </p>
          </div>
        </header>
        <SensorSettings
          node={routed}
          section={route.section}
          onChanged={() => nodes.refresh()}
        />
      </div>
    );
  return (
    <div className="page sensors-page">
      <header className="page-header">
        <div>
          <p>
            Sensor nodes and cameras that feed FALCON. A FALCON node can be
            switched and adjusted from here; an IP camera is read as it is.
          </p>
        </div>
        <button className="primary" onClick={() => setPairing(true)}>
          <Icon name="plus" size={16} /> Add sensor node
        </button>
      </header>
      {nodes.error && <p className="banner banner-bad">{nodes.error}</p>}
      {nodes.data && !list.length && (
        <section className="card empty-state">
          <Icon name="node" size={36} />
          <h2>No sensor node paired yet</h2>
          <p>
            A sensor node is a Raspberry Pi with the camera, microphone and
            weather sensors. It can sit next to this computer at a remote site,
            or anywhere on the same network.
          </p>
          <button className="primary" onClick={() => setPairing(true)}>
            <Icon name="plus" size={16} /> Add sensor node
          </button>
        </section>
      )}
      {list.map((node) => (
        <NodePanel
          key={node.node_id}
          node={node}
          onChanged={() => nodes.refresh()}
          onLive={() => onNavigate("live")}
        />
      ))}
      <div className="sensors-lower">
        <IpCameraCard />
        <AutoStartCard nodes={list} />
      </div>
      <SensorHistory />
      {pairing && (
        <PairNodeDialog
          onClose={() => setPairing(false)}
          onPaired={() => {
            setPairing(false);
            nodes.refresh();
          }}
        />
      )}
    </div>
  );
}
