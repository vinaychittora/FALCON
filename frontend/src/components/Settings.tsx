import type { Config } from "../types";
import { classifierLabels } from "../api/models";

export default function Settings({
  value,
  onChange,
  onSave,
  busy,
}: {
  value: Config;
  onChange: (c: Config) => void;
  onSave: () => void;
  busy: boolean;
}) {
  const number = (
    key:
      | "sample_fps"
      | "detector_threshold"
      | "species_threshold"
      | "ambiguity_margin"
      | "birdnet_confidence"
      | "max_proposals"
      | "min_crop_side"
      | "min_sharpness"
      | "crops_per_track",
    label: string,
    min: number,
    max: number,
    step: number,
  ) => (
    <label>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value[key]}
        onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })}
      />
    </label>
  );
  return (
    <section className="settings-grid">
      <div>
        <h3>Visual analysis</h3>
        <label className="species-model-setting">
          Species model
          <select
            value={value.classifier_mode ?? "bioclip_2"}
            aria-describedby="species-model-help"
            disabled={busy}
            onChange={(e) =>
              onChange({
                ...value,
                classifier_mode: e.target.value as Config["classifier_mode"],
              })
            }
          >
            {Object.entries(classifierLabels).map(([mode, label]) => (
              <option key={mode} value={mode}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <p id="species-model-help" className="muted">
          Huge and cross-check use more memory and time; a GPU is recommended.
          Cross-check keeps both suggestions and marks disagreements uncertain.
          A larger model does not guarantee a correct identification.
        </p>
        {number("sample_fps", "Sample frames per second", 0.5, 5, 0.5)}
        {number("detector_threshold", "Detector threshold", 0.01, 0.99, 0.01)}
        {number(
          "species_threshold",
          "Species similarity threshold",
          -1,
          1,
          0.01,
        )}
        {number("ambiguity_margin", "Top-two margin", 0, 1, 0.005)}
        <label>
          Detector input
          <select
            value={value.detector_size}
            onChange={(e) =>
              onChange({
                ...value,
                detector_size: Number(
                  e.target.value,
                ) as Config["detector_size"],
              })
            }
          >
            {[320, 640, 960].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        {number("max_proposals", "Maximum proposals per frame", 1, 50, 1)}
        <label>
          Inference device
          <select
            value={value.device}
            onChange={(e) =>
              onChange({ ...value, device: e.target.value as Config["device"] })
            }
          >
            <option value="auto">Automatic</option>
            <option value="cuda">CUDA</option>
            <option value="cpu">CPU</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={value.fixed_camera}
            onChange={(e) =>
              onChange({ ...value, fixed_camera: e.target.checked })
            }
          />{" "}
          Fixed camera mode
        </label>
        <p className="muted">
          Adds motion proposals for small organisms. Use only with a stationary
          camera; moving foliage can trigger false proposals.
        </p>
        <label>
          <input
            type="checkbox"
            checked={value.small_animal_mode ?? false}
            onChange={(e) =>
              onChange({ ...value, small_animal_mode: e.target.checked })
            }
          />
          Small wildlife · slower
        </label>
        <p className="muted">
          Examines overlapping sections of each frame for smaller animals. Uses
          more processing time.
        </p>
      </div>
      <div>
        <h3>Detection quality & region</h3>
        {number(
          "min_crop_side",
          "Minimum crop side (source pixels)",
          8,
          256,
          1,
        )}
        {number("min_sharpness", "Minimum sharpness", 0, 500, 1)}
        {number("crops_per_track", "Classification crops per track", 1, 8, 1)}
        <p className="muted">
          Region of interest · normalized coordinates from 0 to 1
        </p>
        <div className="roi-grid">
          {["Left", "Top", "Right", "Bottom"].map((label, i) => (
            <label key={label}>
              {label}
              <input
                type="number"
                step=".05"
                min="0"
                max="1"
                value={value.roi[i]}
                onChange={(e) => {
                  const roi = [...value.roi] as Config["roi"];
                  roi[i] = Number(e.target.value);
                  onChange({ ...value, roi });
                }}
              />
            </label>
          ))}
        </div>
        <label>
          <input
            type="checkbox"
            checked={value.log_non_wildlife}
            onChange={(e) =>
              onChange({ ...value, log_non_wildlife: e.target.checked })
            }
          />{" "}
          Log person / vehicle proposals
        </label>
        <p className="muted">
          Scores are cosine similarities, not calibrated probabilities. The
          thresholds are experimental.
        </p>
      </div>
      <div>
        <h3>Acoustic analysis</h3>
        <label>
          <input
            type="checkbox"
            checked={value.audio_enabled}
            onChange={(e) =>
              onChange({ ...value, audio_enabled: e.target.checked })
            }
          />{" "}
          Analyze audio with BirdNET (CPU)
        </label>
        {number(
          "birdnet_confidence",
          "Minimum acoustic confidence",
          0.01,
          0.99,
          0.01,
        )}
        {(["site_lat", "site_lon"] as const).map((key, i) => (
          <label key={key}>
            Approximate {i ? "longitude" : "latitude"}
            <input
              type="number"
              step=".01"
              min={i ? -180 : -90}
              max={i ? 180 : 90}
              placeholder="Not configured"
              value={value[key] ?? ""}
              onChange={(e) =>
                onChange({
                  ...value,
                  [key]: e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          </label>
        ))}
        <label>
          Recording date
          <input
            type="date"
            value={value.recording_date ?? ""}
            onChange={(e) =>
              onChange({ ...value, recording_date: e.target.value || null })
            }
          />
        </label>
        <label>
          BirdNET week override (1–48)
          <input
            type="number"
            min="1"
            max="48"
            value={value.week ?? ""}
            onChange={(e) =>
              onChange({
                ...value,
                week: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
        <p className="muted">
          Without coordinates, BirdNET uses the configured Rajasthan bird list.
          Week values use four BirdNET weeks per month.
        </p>
        <button className="primary" disabled={busy} onClick={onSave}>
          Save configuration
        </button>
      </div>
    </section>
  );
}
