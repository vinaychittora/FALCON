import { useEffect, useId, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Config } from "../types";
import { classifierLabels } from "../api/models";

/** Plain-language help for every setting: what it does and what changing it costs. */
export const SETTING_HELP: Record<string, string> = {
  classifier_mode:
    "Which visual model names the species. BioCLIP 2 is faster and lighter. BioCLIP 2.5 Huge is slower and needs more memory (a GPU is recommended). Cross-check runs both and only names a species when they agree; otherwise the visit stays unknown. The models are reloaded at the next start.",
  sample_fps:
    "How many camera frames are analyzed each second. More frames catch brief visits and keep a moving bird on one track, but use more CPU or GPU. Use 0.5 to 1 on a computer without a GPU, 2 with a GPU.",
  detector_threshold:
    "Minimum detector confidence (0.4 to 0.8) for a box to be looked at. Lower finds more small or dim animals (at night the cat scored 0.60 to 0.88, the 23:42 animal 0.54 to 0.61); higher misses them. Leaves and the bowl are filtered by movement and the species checks, not by this number. Does not change processing time.",
  species_threshold:
    "Minimum similarity before a species name is suggested. Below it a visit stays “Unknown bird” or “Unknown organism” and the alternatives are kept for review. Lower names more visits with more mistakes; higher is stricter. Does not change processing time.",
  group_threshold:
    "A lower bar used only for the group (bird, mammal, reptile…) when the species is uncertain. Keep it below the species threshold. Raise it if unclear visits get the wrong group; lower it to see a group more often.",
  ambiguity_margin:
    "How far ahead the best species must be of the runner-up before it is named. A small margin names species sooner; a larger one marks close calls as unknown and leaves the decision to the reviewer.",
  detector_size:
    "The size the frame is shrunk to before the detector looks at it. 320 is fastest and fine for large animals; 640 is the usual balance; 960 finds small, distant animals but costs about four times the processing of 320.",
  max_proposals:
    "The most boxes classified in one frame. Each box costs one species-model run, so a lower cap keeps busy scenes fast. Rarely needs changing.",
  device:
    "Automatic uses the GPU when one works and the CPU otherwise. CUDA forces the GPU; CPU forces the processor (slower, works everywhere). Takes effect at the next start.",
  fixed_camera:
    "Adds motion-based boxes for small or still animals the detector misses. Only for a camera that never moves: wind-blown foliage makes false boxes. Costs little processing.",
  small_animal_mode:
    "Also scans overlapping sections of each frame to find small, distant animals. Up to five detector passes per frame, so processing time rises sharply. Keep off unless small animals are being missed.",
  min_crop_side:
    "Boxes smaller than this (in camera pixels) are kept as detections but not sent to the species model, because there is too little detail. Lower it to try naming tiny distant animals; expect more unknowns.",
  min_sharpness:
    "Blurred boxes below this sharpness are not sent to the species model. Lower it to name moving animals more often (with more mistakes); raise it if blurred frames keep producing wrong names.",
  crops_per_track:
    "How many good frames of one tracked animal are classified in every five seconds. More frames give a steadier name but cost more model runs. Two or three is usually enough.",
  roi: "Analyze only part of the picture: 0 is the left or top edge, 1 the right or bottom edge. Use it to ignore a road, a feeder stand or the sky. A smaller region is faster and avoids false boxes. A thin margin (about 0.03 on each side) keeps lens-edge artefacts and mounting posts from becoming “animals”. Takes effect when observation next starts.",
  log_non_wildlife:
    "Record people and vehicles as “not wildlife” entries. Off by default: people are ignored and masked out of images, previews and clips. Turn on only for a private test.",
  mask_people:
    "Paint people gray in the live picture, review images and saved clips. On by default. Turn off to see people as filmed, for example while setting up the camera; they are still never recorded as observations. Voices in saved sound clips stay silenced either way.",
  audio_enabled:
    "Listen for bird calls in nine-second windows on the CPU. Each window costs a few seconds of one CPU core. Turn off on a very small computer, or for a camera without a microphone.",
  birdnet_confidence:
    "BirdNET’s own confidence needed to report a call. 0.5 is a sensible start; lower hears more calls and more mistakes, higher keeps only clear calls.",
  still_object_minutes:
    "A box found 6 or more times in the same place and size over this many minutes, without moving, is scenery (the water bowl, a stone, a post): it is counted but no longer recorded. An animal at the bowl has its own smaller box and is recorded; one that moves a body length, comes in over an edge or is clearly recognised for 5 seconds is recorded even on a scenery spot. 3 minutes is recommended.",
  scenery_forget_hours:
    "A scenery spot not seen for this long is forgotten (48 hours is recommended). Spots are remembered across restarts.",
  crop_left_percent:
    "Cut this much off the left of the camera picture, for example a mounting post at the edge of a wide 16:9 mode. Live, detection and saved clips all use the cropped picture. 0 keeps the full width. Takes effect when observation next starts.",
  crop_right_percent:
    "Cut this much off the right of the camera picture. 0 keeps the full width. Takes effect when observation next starts.",
  clip_pre_seconds:
    "How much of each saved clip (video and sound) comes before the first detection or call, so you see and hear the animal arrive. 5 seconds is recommended.",
  clip_post_seconds:
    "How much of each saved clip comes after the first detection or call. An animal that stays gets the next clip straight after. 5 seconds is recommended; at 1280×960 and 2.5 Mbit/s a 10-second video clip is about 4 MB (about 1 TB holds 250,000 clips).",
  flicker_step:
    "At dawn and dusk some cameras flip between a bright and a dark picture while switching between day and night. A brightness change (0–255) bigger than this between two analysed frames counts as a flip. 20 is recommended.",
  flicker_flips_per_minute:
    "This many flips within a minute pause detection, so flickering does not turn into false visits or ring the bell. 6 is recommended; a single day/night switch never pauses anything.",
  flicker_hold_seconds:
    "Detection resumes this long after the last flip. 60 seconds is recommended.",
  sound_bout_gap_seconds:
    "A bird that keeps calling becomes one visit instead of one entry every few seconds. Calls of the same species less than this far apart join the same visit, and the bell rings once for it. 120 seconds is recommended; 0 keeps every call separate. Applies to new detections.",
  sound_bout_max_minutes:
    "After this long, a visit that is still going is closed and the next call starts a new one, so a bird singing all morning is split into readable parts. 15 minutes is recommended.",
  site: "Lets BirdNET consider only birds expected at this place and time of year, and prefills the export location. Two decimals (about 1 km) are enough; exact coordinates are never needed.",
  recording_date:
    "The date used with the location to pick the seasonal bird list for uploaded recordings. Live sessions use today’s date by themselves.",
  week: "Force a specific BirdNET week (1–48, four per month) instead of using the recording date. Leave empty unless testing.",
};

/** A small “i” that explains a setting on hover, focus or tap. */
export function Hint({ name, label }: { name: string; label: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const text = SETTING_HELP[name];
  if (!text) return null;
  return (
    <span className={`hint${open ? " open" : ""}`}>
      <button
        type="button"
        className="hint-button"
        aria-label={`About ${label}`}
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        i
      </button>
      <span role="tooltip" id={id} className="hint-text">
        {text}
      </span>
    </span>
  );
}

function Field({
  name,
  label,
  children,
}: {
  name: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="setting">
      <span className="setting-label">
        {label}
        <Hint name={name} label={label} />
      </span>
      {children}
    </label>
  );
}

function Switch({
  name,
  label,
  checked,
  onChange,
}: {
  name: string;
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="setting setting-switch">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />{" "}
      <span className="setting-label">
        {label}
        <Hint name={name} label={label} />
      </span>
    </label>
  );
}

interface Scenery {
  spots: number;
  stale: number;
}

/** "Forget all scenery (N spots)": learned spots are learned again within minutes. */
export function ForgetScenery() {
  const [scenery, setScenery] = useState<Scenery | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<Scenery>("/live/scenery")
      .then(setScenery)
      .catch(() => setScenery(null));
  }, []);
  if (!scenery) return null;
  async function forget() {
    if (
      !window.confirm(
        "Forget every learned scenery spot? The bowl and other still objects are recorded again (hidden) until they are learned again, about 3 minutes.",
      )
    )
      return;
    setBusy(true);
    try {
      setScenery(
        await api<Scenery>("/live/scenery/forget", { method: "POST" }),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="setting">
      <button
        type="button"
        className="subtle"
        disabled={busy || scenery.spots === 0}
        onClick={() => void forget()}
      >
        Forget all scenery ({scenery.spots} spot{scenery.spots === 1 ? "" : "s"}
        {scenery.stale ? `, ${scenery.stale} stale` : ""})
      </button>
    </div>
  );
}

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
      | "group_threshold"
      | "ambiguity_margin"
      | "birdnet_confidence"
      | "sound_bout_gap_seconds"
      | "sound_bout_max_minutes"
      | "max_proposals"
      | "min_crop_side"
      | "min_sharpness"
      | "crops_per_track"
      | "still_object_minutes"
      | "scenery_forget_hours"
      | "crop_left_percent"
      | "crop_right_percent"
      | "clip_pre_seconds"
      | "clip_post_seconds"
      | "flicker_step"
      | "flicker_flips_per_minute"
      | "flicker_hold_seconds",
    label: string,
    min: number,
    max: number,
    step: number,
  ) => (
    <Field name={key} label={label}>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value[key] ?? ""}
        onChange={(e) => onChange({ ...value, [key]: Number(e.target.value) })}
      />
    </Field>
  );
  return (
    <section className="settings-grid">
      <div>
        <h3>Visual analysis</h3>
        <label className="species-model-setting setting">
          <span className="setting-label">
            Species model
            <Hint name="classifier_mode" label="Species model" />
          </span>
          <select
            value={value.classifier_mode ?? "bioclip_2"}
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
        {number("sample_fps", "Frames analyzed per second", 0.5, 5, 0.5)}
        {number("detector_threshold", "Detector sensitivity", 0.4, 0.8, 0.01)}
        {number(
          "species_threshold",
          "Species similarity threshold",
          -1,
          1,
          0.01,
        )}
        {number("group_threshold", "Group threshold", -1, 1, 0.01)}
        {number("ambiguity_margin", "Top-two margin", 0, 1, 0.005)}
        <Field name="detector_size" label="Detector input">
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
        </Field>
        {number("max_proposals", "Maximum boxes per frame", 1, 50, 1)}
        <Field name="device" label="Inference device">
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
        </Field>
        <Switch
          name="fixed_camera"
          label="Fixed camera mode"
          checked={value.fixed_camera}
          onChange={(fixed_camera) => onChange({ ...value, fixed_camera })}
        />
        <Switch
          name="small_animal_mode"
          label="Small wildlife · slower"
          checked={value.small_animal_mode ?? false}
          onChange={(small_animal_mode) =>
            onChange({ ...value, small_animal_mode })
          }
        />
      </div>
      <div>
        <h3>Detection quality &amp; region</h3>
        {number(
          "min_crop_side",
          "Minimum crop side (camera pixels)",
          8,
          256,
          1,
        )}
        {number("min_sharpness", "Minimum sharpness", 0, 500, 1)}
        {number("crops_per_track", "Classified frames per visit", 1, 8, 1)}
        {number(
          "still_object_minutes",
          "Something that does not move for (minutes) is scenery",
          1,
          10,
          1,
        )}
        {number(
          "scenery_forget_hours",
          "Forget scenery not seen for (hours)",
          1,
          720,
          1,
        )}
        <ForgetScenery />
        {number("crop_left_percent", "Crop left side (% of width)", 0, 30, 1)}
        {number("crop_right_percent", "Crop right side (% of width)", 0, 30, 1)}
        {number(
          "clip_pre_seconds",
          "Clip: seconds before the first detection",
          1,
          12,
          1,
        )}
        {number(
          "clip_post_seconds",
          "Clip: seconds after the first detection",
          2,
          20,
          1,
        )}
        {number(
          "flicker_step",
          "Day/night flicker: brightness jump",
          5,
          128,
          1,
        )}
        {number(
          "flicker_flips_per_minute",
          "Day/night flicker: jumps per minute",
          2,
          120,
          1,
        )}
        {number(
          "flicker_hold_seconds",
          "Day/night flicker: pause after it stops (seconds)",
          10,
          600,
          5,
        )}
        <p className="setting-label roi-label">
          Region of interest · 0 to 1
          <Hint name="roi" label="Region of interest" />
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
        <Switch
          name="log_non_wildlife"
          label="Log person / vehicle proposals"
          checked={value.log_non_wildlife}
          onChange={(log_non_wildlife) =>
            onChange({ ...value, log_non_wildlife })
          }
        />
        <Switch
          name="mask_people"
          label="Mask people in video"
          checked={value.mask_people ?? true}
          onChange={(mask_people) => onChange({ ...value, mask_people })}
        />
        <p className="muted">
          Scores are similarities, not probabilities. Hover or tap an{" "}
          <span className="hint-example">i</span> for what each setting does.
        </p>
      </div>
      <div>
        <h3>Acoustic analysis</h3>
        <Switch
          name="audio_enabled"
          label="Analyze audio with BirdNET (CPU)"
          checked={value.audio_enabled}
          onChange={(audio_enabled) => onChange({ ...value, audio_enabled })}
        />
        {number(
          "birdnet_confidence",
          "Minimum acoustic confidence",
          0.01,
          0.99,
          0.01,
        )}
        {number(
          "sound_bout_gap_seconds",
          "Same visit while calls are less than (seconds) apart",
          0,
          1800,
          10,
        )}
        {number(
          "sound_bout_max_minutes",
          "Longest sound visit (minutes)",
          1,
          120,
          1,
        )}
        {(["site_lat", "site_lon"] as const).map((key, i) => (
          <Field
            key={key}
            name="site"
            label={`Approximate ${i ? "longitude" : "latitude"}`}
          >
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
          </Field>
        ))}
        <Field name="recording_date" label="Recording date">
          <input
            type="date"
            value={value.recording_date ?? ""}
            onChange={(e) =>
              onChange({ ...value, recording_date: e.target.value || null })
            }
          />
        </Field>
        <Field name="week" label="BirdNET week override (1–48)">
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
        </Field>
        <p className="muted">
          Save, then start a new observation to use the new settings.
        </p>
        <button className="primary" disabled={busy} onClick={onSave}>
          Save configuration
        </button>
        <p className="muted small-note">
          FALCON never learns from your verdicts; threshold suggestions are
          printed for you to apply.
        </p>
      </div>
    </section>
  );
}
