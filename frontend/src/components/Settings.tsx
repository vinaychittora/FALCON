// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useId, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Config } from "../types";
import { classifierLabels } from "../api/models";
import PostingNote from "./PostingNote";

/** Plain-language help for every setting: what it does and what changing it costs.
 *
 * Tuning (species model, detector, picture edges, frames per second, thresholds,
 * clip length, flicker guard, scenery timing, crop quality, BirdNET confidence, sound
 * visits) is fixed at the values that work on this rig and is no longer on this page.
 */
export const SETTING_HELP: Record<string, string> = {
  mask_people:
    "Paint people gray in the live picture, review images and saved clips. On by default. Turn off to see people as filmed, for example while setting up the camera; they are still never recorded as observations. Voices in saved sound clips stay silenced either way.",
  audio_enabled:
    "Listen for bird calls in nine-second windows on the CPU. Each window costs a few seconds of one CPU core. Turn off on a very small computer, or for a camera without a microphone.",
  site: "Lets BirdNET consider only birds expected at this place and time of year, and prefills the export location. Two decimals (about 1 km) are enough; exact coordinates are never needed.",
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
      </button>{" "}
      <a className="text-button" href="#/system?scenery=1">
        Show the saved spots
      </a>
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
  return (
    <section className="settings-grid">
      <div>
        <h3>Camera</h3>
        <p className="muted">
          Species model {classifierLabels[value.classifier_mode] ?? "BioCLIP 2.5"} ·
          detector {value.detector_threshold.toFixed(2)} · picture edges{" "}
          {Math.round(value.roi[0] * 100)} % left and{" "}
          {Math.round((1 - value.roi[2]) * 100)} % right ignored. These are fixed for
          this rig.
        </p>
        <Switch
          name="mask_people"
          label="Mask people in video"
          checked={value.mask_people ?? true}
          onChange={(mask_people) => onChange({ ...value, mask_people })}
        />
        <ForgetScenery />
      </div>
      <div>
        <h3>Sound &amp; site</h3>
        <Switch
          name="audio_enabled"
          label="Analyze audio with BirdNET (CPU)"
          checked={value.audio_enabled}
          onChange={(audio_enabled) => onChange({ ...value, audio_enabled })}
        />
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
        <p className="muted">
          Saving restarts a running observation so the new settings apply now.
        </p>
        <button className="primary" disabled={busy} onClick={onSave}>
          Save configuration
        </button>
        <p className="muted small-note">
          FALCON never learns from your verdicts.
        </p>
      </div>
      <PostingNote />
    </section>
  );
}
