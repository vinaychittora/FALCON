import { useEffect, useState } from "react";
import {
  nodeExtras,
  setNodeExtra,
  slowedByHeat,
  thermalNotice,
  type NodeExtra,
  type NodeExtras,
} from "../api/nodes";

export const NEEDS_UPDATE =
  "Needs the node update: run sudo bash ~/node/install.sh on the node.";

/** One line about the node's heat: protection paused, firmware slowing, or normal. */
export function heatSummary(data: NodeExtras): string {
  const notice = thermalNotice(data.thermal, data.cpu_temperature_c);
  if (notice) return notice;
  const temperature =
    data.cpu_temperature_c != null
      ? `${Math.round(data.cpu_temperature_c)} °C`
      : "temperature unknown";
  if (slowedByHeat(data.power))
    return `${temperature} · slowed by heat (the processor protects itself)`;
  const guard = data.thermal.enabled
    ? `stream pauses at ${data.thermal.stop_c} °C, resumes below ${data.thermal.resume_c} °C`
    : "heat protection is off";
  return `${temperature} · ${guard}`;
}

/** A node from before these switches existed answers "Not found". */
export function needsUpdate(message: string): boolean {
  return /not found/i.test(message);
}

const LABELS = ["Wi-Fi hotspot “falcon”", "Bluetooth"];

/**
 * Hotspot and Bluetooth on the sensor node: off unless needed, because every radio adds
 * heat. "Start at boot" is remembered by the node. Each switch sits next to its label,
 * one feature per block.
 */
export default function NodePower({ nodeId }: { nodeId: string }) {
  const [data, setData] = useState<NodeExtras | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    nodeExtras(nodeId)
      .then((value) => current && setData(value))
      .catch(
        (reason) =>
          current &&
          setError(reason instanceof Error ? reason.message : String(reason)),
      );
    return () => {
      current = false;
    };
  }, [nodeId]);

  async function change(
    extra: NodeExtra,
    update: { on?: boolean; at_boot?: boolean },
  ) {
    setBusy(extra.name);
    setError("");
    try {
      setData(await setNodeExtra(nodeId, { name: extra.name, ...update }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  }

  if (!data && !error) return <p className="muted">Reading the node…</p>;
  // A node without the update cannot report these: say so instead of showing "off".
  const outdated = !data && needsUpdate(error);
  const items: (NodeExtra | null)[] = data ? data.extras : [null, null];

  return (
    <div className="node-power">
      {data && <p className="muted">{heatSummary(data)}</p>}
      {outdated && <p className="muted">{NEEDS_UPDATE}</p>}
      {items.map((extra, index) => {
        const label = extra?.label ?? LABELS[index];
        const disabled = !extra || !extra.available || busy === extra.name;
        return (
          <div className="power-item" key={label}>
            <label className="switch-row">
              <input
                type="checkbox"
                role="switch"
                checked={extra?.on ?? false}
                disabled={disabled}
                onChange={(event) =>
                  extra && void change(extra, { on: event.target.checked })
                }
              />
              <span>
                {label}
                {extra && !extra.available && " (not set up on this node)"}
              </span>
            </label>
            <label className="switch-row power-boot">
              <input
                type="checkbox"
                checked={extra?.at_boot ?? false}
                disabled={disabled}
                onChange={(event) =>
                  extra && void change(extra, { at_boot: event.target.checked })
                }
              />
              <span>Start at boot</span>
            </label>
            {extra?.note && <small className="muted">{extra.note}</small>}
          </div>
        );
      })}
      {error && !outdated && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
