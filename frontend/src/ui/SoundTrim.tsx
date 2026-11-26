// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import {
  clampTrim,
  SOUND_MAX_S,
  soundUrl,
  spectrogramUrl,
  type VisitSound,
} from "../api/inaturalist";

/** The visit's sound with two trim handles; the chosen part is what gets posted. */
export default function SoundTrim({
  encounterId,
  sound,
  include,
  trim,
  onInclude,
  onTrim,
}: {
  encounterId: string;
  sound: VisitSound;
  include: boolean;
  trim: [number, number];
  onInclude: (value: boolean) => void;
  onTrim: (value: [number, number]) => void;
}) {
  const [w0, w1] = sound.window;
  const span = Math.max(0.01, w1 - w0);
  const pct = (t: number) => `${((t - w0) / span) * 100}%`;
  const set = (value: number, which: "start" | "end") =>
    onTrim(
      clampTrim(which === "start" ? [value, trim[1]] : [trim[0], value], sound.window, which),
    );
  const heardText = sound.heard.length
    ? `BirdNET heard it at ${sound.heard.map((h) => `${(h.start - w0).toFixed(0)} s`).join(", ")}`
    : "BirdNET did not hear this species during the visit";
  return (
    <div className="sound-trim">
      <label className="switch-row">
        <input
          type="checkbox"
          checked={include}
          onChange={(event) => onInclude(event.target.checked)}
        />
        <span>
          Include sound ({sound.kind === "video" ? "from the visit recording" : "sound record"}) ·{" "}
          {heardText}
        </span>
      </label>
      <p className="sound-trim-note">
        The trimmed sound is added to the same observation as the pictures: one post with
        the pictures and this one sound.
      </p>
      <div className={`sound-trim-view${include ? "" : " off"}`}>
        <img src={spectrogramUrl(encounterId)} alt="Spectrogram of the visit's sound" />
        {sound.heard.map((h) => (
          <span
            key={`${h.start}-${h.end}`}
            className="sound-trim-heard"
            style={{ left: pct(h.start), width: `calc(${pct(h.end)} - ${pct(h.start)})` }}
          />
        ))}
        <span
          className="sound-trim-chosen"
          style={{ left: pct(trim[0]), width: `calc(${pct(trim[1])} - ${pct(trim[0])})` }}
        />
        <input
          type="range"
          className="sound-trim-handle"
          aria-label="Start of the sound"
          min={w0}
          max={w1}
          step={0.1}
          value={trim[0]}
          disabled={!include}
          onChange={(event) => set(Number(event.target.value), "start")}
        />
        <input
          type="range"
          className="sound-trim-handle"
          aria-label="End of the sound"
          min={w0}
          max={w1}
          step={0.1}
          value={trim[1]}
          disabled={!include}
          onChange={(event) => set(Number(event.target.value), "end")}
        />
      </div>
      <div className="sound-trim-fields">
        <label>
          From{" "}
          <input
            type="number"
            step={0.1}
            min={0}
            max={span}
            value={(trim[0] - w0).toFixed(1)}
            disabled={!include}
            onChange={(event) => set(w0 + Number(event.target.value), "start")}
          />{" "}
          s
        </label>
        <label>
          to{" "}
          <input
            type="number"
            step={0.1}
            min={0}
            max={span}
            value={(trim[1] - w0).toFixed(1)}
            disabled={!include}
            onChange={(event) => set(w0 + Number(event.target.value), "end")}
          />{" "}
          s
        </label>
        <span className="muted">
          {(trim[1] - trim[0]).toFixed(1)} s of at most {SOUND_MAX_S} s
        </span>
      </div>
      {include && (
        <audio
          key={`${trim[0]}-${trim[1]}`}
          controls
          preload="none"
          src={soundUrl(encounterId, trim[0], trim[1])}
        />
      )}
    </div>
  );
}
