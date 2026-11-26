// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useState } from "react";
import { nodeCamera, type CameraSettings, type SensorNode } from "../api/nodes";

type Field = {
  key: keyof CameraSettings;
  label: string;
  help?: string;
  quick?: boolean;
} & (
  | { type: "select"; options: [string, string][] }
  | {
      type: "range";
      min: number;
      max: number;
      step: number;
      format?: (value: number) => string;
    }
  | { type: "toggle" }
);

export function focusDistance(dioptres: number): string {
  if (dioptres <= 0.05) return "infinity";
  const metres = 1 / dioptres;
  return metres >= 10 ? `${metres.toFixed(0)} m` : `${metres.toFixed(1)} m`;
}

const FIELDS: Field[] = [
  {
    key: "night_mode",
    label: "Night picture",
    type: "select",
    quick: true,
    options: [
      ["auto", "Automatic: greyscale under IR light"],
      ["colour", "Always colour"],
      ["mono", "Always greyscale"],
    ],
    help: "This webcam has no IR-cut filter, so its colours are only right by day. At night its IR lights turn the picture magenta; Automatic switches to greyscale then, and back at dawn. Detection, clips and Live all get the same picture.",
  },
  {
    key: "focus_mode",
    label: "Focus",
    type: "select",
    quick: true,
    options: [
      ["continuous", "Automatic (continuous)"],
      ["manual", "Fixed distance"],
      ["auto", "Focus once at start"],
    ],
    help: "A fixed scene usually works best with a fixed focus distance, so leaves do not make it hunt.",
  },
  {
    key: "lens_position",
    label: "Focus distance",
    type: "range",
    min: 0,
    max: 10,
    step: 0.1,
    quick: true,
    format: focusDistance,
    help: "Used when focus is fixed. 0 = infinity, 0.5 ≈ 2 m, 2 ≈ 50 cm.",
  },
  {
    key: "ev",
    label: "Brightness compensation (EV)",
    type: "range",
    min: -4,
    max: 4,
    step: 0.5,
    quick: true,
    format: (v) => (v > 0 ? `+${v}` : `${v}`),
  },
  {
    key: "awb",
    label: "White balance",
    type: "select",
    quick: true,
    options: [
      ["auto", "Automatic"],
      ["daylight", "Daylight"],
      ["cloudy", "Cloudy"],
      ["tungsten", "Tungsten"],
      ["fluorescent", "Fluorescent"],
      ["indoor", "Indoor"],
      ["incandescent", "Incandescent"],
    ],
  },
  {
    key: "hdr",
    label: "HDR (bright sky and deep shade)",
    type: "toggle",
    quick: true,
  },
  {
    key: "vflip",
    label: "Flip vertically (camera upside down)",
    type: "toggle",
    quick: true,
  },
  { key: "hflip", label: "Mirror horizontally", type: "toggle" },
  {
    key: "video_codec",
    label: "Video encoding",
    type: "select",
    options: [
      ["mjpeg", "On this PC (camera frames passed through)"],
      ["h264", "On the sensor node (H.264)"],
    ],
    help: "On this PC: the node sends the webcam's own frames without re-encoding, so it runs much cooler (about 66 °C instead of 76 °C here) and FALCON decodes them on the PC. Needs about 10 Mbit/s at 1280×960 and 10 fps, so a wired network is best. On the sensor node: the node encodes H.264 (about 2.5 Mbit/s) using about 1.5 CPU cores. Changing it restarts the stream for a few seconds.",
  },
  { key: "resolution", label: "Resolution", type: "select", options: [] },
  {
    key: "framerate",
    label: "Frame rate",
    type: "range",
    min: 2,
    max: 30,
    step: 1,
    format: (v) => `${v} fps`,
    help: "FALCON analyzes about 2 frames per second; 10–15 fps keeps clips smooth and saves bandwidth.",
  },
  {
    key: "bitrate_kbps",
    label: "Video bitrate",
    type: "range",
    min: 500,
    max: 10000,
    step: 250,
    format: (v) => `${(v / 1000).toFixed(2)} Mb/s`,
  },
  {
    key: "exposure",
    label: "Exposure mode",
    type: "select",
    options: [
      ["normal", "Normal"],
      ["sport", "Sport (short exposures, less blur)"],
      ["long", "Long (low light)"],
    ],
  },
  {
    key: "shutter_us",
    label: "Shutter time",
    type: "range",
    min: 0,
    max: 100000,
    step: 500,
    format: (v) => (v ? `${(v / 1000).toFixed(1)} ms` : "automatic"),
  },
  {
    key: "gain",
    label: "Analogue gain",
    type: "range",
    min: 0,
    max: 16,
    step: 0.5,
    format: (v) => (v ? `${v}×` : "automatic"),
  },
  {
    key: "metering",
    label: "Metering",
    type: "select",
    options: [
      ["centre", "Centre-weighted"],
      ["spot", "Spot"],
      ["average", "Average"],
    ],
  },
  {
    key: "brightness",
    label: "Brightness",
    type: "range",
    min: -1,
    max: 1,
    step: 0.05,
  },
  {
    key: "contrast",
    label: "Contrast",
    type: "range",
    min: 0,
    max: 2,
    step: 0.05,
  },
  {
    key: "saturation",
    label: "Saturation",
    type: "range",
    min: 0,
    max: 2,
    step: 0.05,
  },
  {
    key: "sharpness",
    label: "Sharpness",
    type: "range",
    min: 0,
    max: 4,
    step: 0.1,
  },
  {
    key: "denoise",
    label: "Noise reduction",
    type: "select",
    options: [
      ["auto", "Automatic"],
      ["off", "Off"],
      ["cdn_off", "Spatial only"],
      ["cdn_fast", "Fast"],
      ["cdn_hq", "High quality"],
    ],
  },
];

export default function CameraControls({
  node,
  quick = false,
  onChanged,
}: {
  node: SensorNode;
  quick?: boolean;
  onChanged: (node: SensorNode) => void;
}) {
  const status = node.status;
  const camera = status?.components.camera;
  const saved = status?.camera_settings;
  const [draft, setDraft] = useState<Partial<CameraSettings>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  if (!status || !camera?.present || !saved)
    return <p className="muted">This node has no camera connected.</p>;
  const controls = new Set(camera.controls ?? []);
  if (!controls.size)
    return (
      <p className="muted">
        This camera is relayed as-is; its picture settings are changed on the
        camera itself.
      </p>
    );
  const values = { ...saved, ...draft };
  const changed = Object.keys(draft).filter(
    (key) =>
      draft[key as keyof CameraSettings] !== saved[key as keyof CameraSettings],
  );
  const fields = FIELDS.filter(
    (field) => controls.has(field.key) && (!quick || field.quick),
  )
    .filter(
      (field) =>
        field.key !== "lens_position" || values.focus_mode === "manual",
    )
    // Pass-through sends the camera's frames as they are: no bitrate to choose.
    .filter(
      (field) => field.key !== "bitrate_kbps" || values.video_codec !== "mjpeg",
    );

  async function apply() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const changes = Object.fromEntries(
        changed.map((key) => [key, draft[key as keyof CameraSettings]]),
      );
      const updated = await nodeCamera(node.node_id, changes);
      setDraft({});
      setMessage("Applied. The stream restarts for a few seconds.");
      onChanged(updated);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className={`camera-controls${quick ? " quick" : ""}`}
      onSubmit={(submit) => {
        submit.preventDefault();
        void apply();
      }}
    >
      <div className="control-grid">
        {fields.map((field) => {
          const value = values[field.key];
          const id = `${node.node_id}-${field.key}`;
          return (
            <div className={`control control-${field.type}`} key={field.key}>
              {field.type === "toggle" ? (
                <label className="switch-row" htmlFor={id}>
                  <input
                    id={id}
                    type="checkbox"
                    role="switch"
                    checked={Boolean(value)}
                    onChange={(change) =>
                      setDraft({ ...draft, [field.key]: change.target.checked })
                    }
                  />
                  <span>{field.label}</span>
                </label>
              ) : (
                <>
                  <label htmlFor={id}>
                    {field.label}
                    {field.type === "range" && (
                      <output htmlFor={id}>
                        {field.format
                          ? field.format(Number(value))
                          : Number(value).toFixed(2)}
                      </output>
                    )}
                  </label>
                  {field.type === "select" ? (
                    <select
                      id={id}
                      value={String(value)}
                      onChange={(change) =>
                        setDraft({ ...draft, [field.key]: change.target.value })
                      }
                    >
                      {(field.key === "resolution"
                        ? (camera.resolutions ?? []).map(
                            (size) =>
                              [size, size.replace("x", " × ")] as [
                                string,
                                string,
                              ],
                          )
                        : field.options
                      ).map(([option, label]) => (
                        <option key={option} value={option}>
                          {label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={id}
                      type="range"
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      value={Number(value)}
                      onChange={(change) =>
                        setDraft({
                          ...draft,
                          [field.key]: Number(change.target.value),
                        })
                      }
                    />
                  )}
                </>
              )}
              {field.help && !quick && <small>{field.help}</small>}
            </div>
          );
        })}
      </div>
      <div className="form-row">
        <button
          className="primary"
          type="submit"
          disabled={busy || !changed.length}
        >
          {busy
            ? "Applying…"
            : changed.length
              ? `Apply ${changed.length} change${changed.length > 1 ? "s" : ""}`
              : "No changes"}
        </button>
        {!!changed.length && (
          <button
            type="button"
            className="text-button"
            onClick={() => setDraft({})}
            disabled={busy}
          >
            Undo
          </button>
        )}
        <span role="status" className="muted">
          {message}
        </span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
