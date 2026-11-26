// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import {
  setListenDenoise,
  setListenVolume,
  startListening,
  stopListening,
  useListen,
} from "../api/listenStore";
import { meterFraction } from "../api/liveListen";
import { BarOptions } from "./Floating";

/** A small level bar (−60 to 0 dBFS) with the RMS level and a peak tick. */
export function LevelMeter({ rms, peak }: { rms: number; peak: number }) {
  return (
    <span
      className="level-meter"
      role="meter"
      aria-label="Sound level"
      aria-valuemin={-60}
      aria-valuemax={0}
      aria-valuenow={Number.isFinite(rms) ? Math.round(rms) : -60}
    >
      <i style={{ width: `${meterFraction(rms) * 100}%` }} />
      <b style={{ left: `${meterFraction(peak) * 100}%` }} />
    </span>
  );
}

/** Volume and noise reduction, shared by every Listen control. */
export function ListenOptions() {
  const listen = useListen();
  return (
    <>
      <label>
        Volume
        <input
          type="range"
          min={0.05}
          max={1}
          step={0.05}
          value={listen.volume}
          onChange={(event) => setListenVolume(Number(event.target.value))}
        />
      </label>
      <label className="switch-row">
        <input
          type="checkbox"
          checked={listen.denoise}
          onChange={(event) => setListenDenoise(event.target.checked)}
        />
        <span>Noise reduction</span>
      </label>
      <small className="muted">
        Noise reduction only changes what you hear; bird-call detection and
        saved clips keep the original sound. Live only, nothing is recorded.
      </small>
    </>
  );
}

/**
 * "Listen": hear the sensor's microphone on this computer. The player is shared by the
 * whole app, so it keeps playing on other pages until it is switched off.
 * `compact` is the small version for the top bar.
 */
export default function LiveListen({
  available = true,
  compact = false,
}: {
  available?: boolean;
  compact?: boolean;
}) {
  const listen = useListen();
  if (compact && !listen.on) return null;
  return (
    <span className={`bar-control${compact ? " listen-compact" : ""}`}>
      <label
        className="switch-row"
        title={listen.error || "Hear the sensor's microphone on this computer"}
      >
        <input
          type="checkbox"
          role="switch"
          checked={listen.on}
          disabled={!available && !listen.on}
          onChange={(event) =>
            event.target.checked ? void startListening() : stopListening()
          }
        />
        <span>Listen</span>
      </label>
      {listen.on && <LevelMeter rms={listen.rms} peak={listen.peak} />}
      {listen.on && !compact && (
        <BarOptions label="Listen options">
          <ListenOptions />
        </BarOptions>
      )}
    </span>
  );
}
