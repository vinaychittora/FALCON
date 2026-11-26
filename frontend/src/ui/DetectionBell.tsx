// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  allowNotifications,
  armBell,
  bellArmed,
  notifyVisits,
  readBellPreferences,
  ringBell,
  saveBellPreferences,
  VisitBell,
  type BellPreferences,
} from "../api/detectionBell";
import type { Encounter } from "../api/encounters";
import { feedMark } from "../api/liveFeed";
import { BarOptions } from "./Floating";

/** Whether a visit on the Live list may ring: Likely or Confirmed only. */
export function rings(encounter: Encounter): boolean {
  const mark = feedMark(encounter);
  return mark === "likely" || mark === "confirmed";
}

// One set of Ring preferences for every Ring control on screen (top bar, station
// status layer, full-screen Live), so they never disagree.
let shared: BellPreferences | null = null;
const listeners = new Set<() => void>();
function current(): BellPreferences {
  if (!shared) shared = readBellPreferences();
  return shared;
}
function setShared(next: BellPreferences) {
  shared = next;
  saveBellPreferences(next);
  listeners.forEach((listener) => listener());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function useBellPreferences(): [BellPreferences, (next: BellPreferences) => void] {
  return [useSyncExternalStore(subscribe, current, current), setShared];
}

/** Volume and desktop notification, shared by every Ring control. */
export function RingOptions() {
  const [preferences, update] = useBellPreferences();
  const [note, setNote] = useState("");
  const [armed] = useState(bellArmed);
  async function toggleNotify(notify: boolean) {
    if (notify && !(await allowNotifications())) {
      setNote("Desktop notifications are blocked for this site.");
      update({ ...preferences, notify: false });
      return;
    }
    setNote("");
    update({ ...preferences, notify });
  }
  return (
    <>
      <label>
        Volume
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={preferences.volume}
          onChange={(event) =>
            update({ ...preferences, volume: Number(event.target.value) })
          }
          onPointerUp={() => ringBell(preferences.volume)}
        />
      </label>
      <label className="switch-row">
        <input
          type="checkbox"
          checked={preferences.notify}
          onChange={(event) => void toggleNotify(event.target.checked)}
        />
        <span>Desktop notification</span>
      </label>
      <small className="muted">
        {note || (armed ? "Sound is on." : "Click the page to allow sound.")}
      </small>
    </>
  );
}

/**
 * "Ring": a bell (and optionally a desktop notification) once per new animal visit.
 * `resetKey` changes when the list means something else (another session or filter),
 * so switching does not ring for old visits. `quiet` makes a control only (the one
 * in the top bar does the ringing); `options` shows the small options menu.
 */
export default function DetectionBell({
  encounters,
  resetKey,
  quiet = false,
  options = true,
  bar = false,
}: {
  encounters: Encounter[] | null;
  resetKey: string;
  quiet?: boolean;
  options?: boolean;
  bar?: boolean;
}) {
  const [preferences, update] = useBellPreferences();
  const [armed, setArmed] = useState(bellArmed);
  const bell = useRef(new VisitBell());

  useEffect(() => bell.current.reset(), [resetKey]);

  useEffect(() => {
    if (quiet || !encounters) return;
    // Only Likely and Confirmed visits ring; "Show unresolved" adds unrecognised
    // pictures to the list (insects at night), never to the bell.
    const fresh = bell.current.update(encounters.filter(rings));
    if (!fresh.length || !preferences.enabled) return;
    ringBell(preferences.volume);
    if (preferences.notify) notifyVisits(fresh);
  }, [encounters, preferences, quiet]);

  // Browsers may suspend sound (sleep, a long idle tab): any later click re-arms it.
  useEffect(() => {
    if (quiet || !preferences.enabled) return;
    const rearm = () => {
      void armBell().then(setArmed);
    };
    document.addEventListener("pointerdown", rearm);
    document.addEventListener("keydown", rearm);
    return () => {
      document.removeEventListener("pointerdown", rearm);
      document.removeEventListener("keydown", rearm);
    };
  }, [preferences.enabled, quiet]);

  async function toggle(enabled: boolean) {
    update({ ...preferences, enabled });
    if (!enabled) return;
    const ready = await armBell();
    setArmed(ready);
    if (ready) ringBell(preferences.volume); // a sample, so the volume can be judged
  }

  const title =
    preferences.enabled && !armed
      ? "Click anywhere on the page to allow sound"
      : "A bell for each new animal visit";
  if (bar)
    return (
      <button
        type="button"
        role="switch"
        aria-checked={preferences.enabled}
        className="fs-switch"
        title={title}
        onClick={() => void toggle(!preferences.enabled)}
      >
        <span className="rv-switch-track" aria-hidden="true" />
        Ring
      </button>
    );
  return (
    <span className="bar-control">
      <label className="switch-row" title={title}>
        <input
          type="checkbox"
          role="switch"
          checked={preferences.enabled}
          onChange={(event) => void toggle(event.target.checked)}
        />
        <span>Ring</span>
      </label>
      {options && preferences.enabled && (
        <BarOptions label="Ring options">
          <RingOptions />
        </BarOptions>
      )}
    </span>
  );
}
