import { useEffect, useRef, useState } from "react";
import {
  nodePicture,
  setNodePicture,
  type PictureControl,
  type PictureControls as Controls,
} from "../api/nodes";

/** Plain names and help for the USB webcam controls FALCON shows. */
export const PICTURE_LABELS: Record<string, { label: string; help?: string }> =
  {
    brightness: { label: "Brightness" },
    contrast: { label: "Contrast" },
    saturation: { label: "Colour saturation" },
    hue: { label: "Hue" },
    gamma: {
      label: "Gamma",
      help: "Lifts or darkens the mid-tones; higher shows more in the shade.",
    },
    sharpness: {
      label: "Sharpening",
      help: "Edge sharpening in the camera. It cannot fix focus; too high adds halos.",
    },
    gain: {
      label: "Gain",
      help: "Amplifies a dark picture; adds noise.",
    },
    backlight_compensation: {
      label: "Backlight compensation",
      help: "Brightens subjects in front of a bright sky.",
    },
    white_balance_automatic: { label: "Automatic white balance" },
    white_balance_temperature: {
      label: "White balance (kelvin)",
      help: "Turn off automatic white balance to set this.",
    },
    auto_exposure: { label: "Exposure" },
    exposure_time_absolute: {
      label: "Exposure time",
      help: "Set Exposure to Manual to use this. Units of 0.1 ms; shorter freezes motion.",
    },
    exposure_dynamic_framerate: {
      label: "Slow the frame rate in low light",
      help: "Brighter at dusk, but fewer frames for the detector.",
    },
    power_line_frequency: {
      label: "Mains flicker filter",
      help: "50 Hz in India and Europe; removes banding under electric lights.",
    },
  };

const MENU_LABELS: Record<string, Record<number, string>> = {
  auto_exposure: {
    0: "Automatic",
    1: "Manual",
    2: "Shutter priority",
    3: "Automatic",
  },
};

const DEBOUNCE_MS = 250;

export function controlLabel(control: PictureControl): string {
  return (
    PICTURE_LABELS[control.name]?.label ?? control.name.replaceAll("_", " ")
  );
}

export function menuLabel(
  control: PictureControl,
  value: number,
  text: string,
) {
  return MENU_LABELS[control.name]?.[value] ?? text;
}

export default function PictureControls({ nodeId }: { nodeId: string }) {
  const [data, setData] = useState<Controls | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<Record<string, number>>({});
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let current = true;
    nodePicture(nodeId)
      .then((value) => current && setData(value))
      .catch(
        (reason) =>
          current &&
          setError(reason instanceof Error ? reason.message : String(reason)),
      );
    return () => {
      current = false;
      window.clearTimeout(timer.current);
    };
  }, [nodeId]);

  async function send(
    change: { values: Record<string, number> } | { reset: true },
  ) {
    setBusy(true);
    setError("");
    try {
      const updated = await setNodePicture(nodeId, change);
      setData(updated);
      // Keep any value the user moved while this request was on its way.
      setDraft({ ...pending.current });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setDraft({});
    } finally {
      setBusy(false);
    }
  }

  function change(name: string, value: number) {
    setDraft((previous) => ({ ...previous, [name]: value }));
    pending.current = { ...pending.current, [name]: value };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const values = pending.current;
      pending.current = {};
      void send({ values });
    }, DEBOUNCE_MS);
  }

  if (error && !data) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Reading the camera's controls…</p>;
  if (!data.controls.length)
    return (
      <p className="muted">This camera has no adjustable picture controls.</p>
    );
  const changedFromDefault = data.controls.some(
    (control) => control.value !== control.default,
  );

  return (
    <div className="picture-controls">
      <div className="control-grid">
        {data.controls.map((control) => {
          const id = `${nodeId}-picture-${control.name}`;
          const value = draft[control.name] ?? control.value;
          const help = PICTURE_LABELS[control.name]?.help;
          return (
            <div
              key={control.name}
              className={`control control-${control.type}${control.inactive ? " is-inactive" : ""}`}
            >
              {control.type === "bool" ? (
                <label className="switch-row" htmlFor={id}>
                  <input
                    id={id}
                    type="checkbox"
                    role="switch"
                    checked={Boolean(value)}
                    disabled={control.inactive}
                    onChange={(event) =>
                      change(control.name, event.target.checked ? 1 : 0)
                    }
                  />
                  <span>{controlLabel(control)}</span>
                </label>
              ) : (
                <>
                  <label htmlFor={id}>
                    {controlLabel(control)}
                    {control.type === "int" && (
                      <output htmlFor={id}>{value}</output>
                    )}
                  </label>
                  {control.type === "menu" ? (
                    <select
                      id={id}
                      value={value}
                      disabled={control.inactive}
                      onChange={(event) =>
                        change(control.name, Number(event.target.value))
                      }
                    >
                      {(control.menu ?? []).map(([option, text]) => (
                        <option key={option} value={option}>
                          {menuLabel(control, option, text)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={id}
                      type="range"
                      min={control.min}
                      max={control.max}
                      step={control.step}
                      value={value}
                      disabled={control.inactive}
                      onChange={(event) =>
                        change(control.name, Number(event.target.value))
                      }
                    />
                  )}
                </>
              )}
              {help && (control.inactive || control.type !== "bool") && (
                <small>{help}</small>
              )}
            </div>
          );
        })}
      </div>
      <div className="form-row">
        <button
          type="button"
          className="text-button"
          disabled={busy || !changedFromDefault}
          onClick={() => {
            window.clearTimeout(timer.current);
            pending.current = {};
            void send({ reset: true });
          }}
        >
          Reset to defaults
        </button>
        <span role="status" className="muted">
          {busy ? "Applying…" : "Changes apply immediately and are remembered."}
        </span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
