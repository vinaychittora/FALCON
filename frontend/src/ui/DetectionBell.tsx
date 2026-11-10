import { useEffect, useRef, useState } from "react";
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

/** Whether a visit on the Live list may ring: Likely or Confirmed only. */
export function rings(encounter: Encounter): boolean {
  const mark = feedMark(encounter);
  return mark === "likely" || mark === "confirmed";
}

/**
 * "Ring" on the Live bar: a bell (and optionally a desktop notification) once per new
 * animal visit. Volume and notifications sit in its small options menu so the bar
 * stays one row. `resetKey` changes when the list means something else (another
 * session or filter), so switching filters does not ring for old visits.
 */
export default function DetectionBell({
  encounters,
  resetKey,
}: {
  encounters: Encounter[] | null;
  resetKey: string;
}) {
  const [preferences, setPreferences] = useState(readBellPreferences);
  const [armed, setArmed] = useState(bellArmed);
  const [note, setNote] = useState("");
  const bell = useRef(new VisitBell());

  useEffect(() => bell.current.reset(), [resetKey]);

  useEffect(() => {
    if (!encounters) return;
    // Only Likely and Confirmed visits ring; "Show unresolved" adds unrecognised
    // pictures to the list (insects at night), never to the bell.
    const fresh = bell.current.update(encounters.filter(rings));
    if (!fresh.length || !preferences.enabled) return;
    ringBell(preferences.volume);
    if (preferences.notify) notifyVisits(fresh);
  }, [encounters, preferences]);

  // Browsers may suspend sound (sleep, a long idle tab): any later click re-arms it.
  useEffect(() => {
    if (!preferences.enabled) return;
    const rearm = () => {
      void armBell().then(setArmed);
    };
    document.addEventListener("pointerdown", rearm);
    document.addEventListener("keydown", rearm);
    return () => {
      document.removeEventListener("pointerdown", rearm);
      document.removeEventListener("keydown", rearm);
    };
  }, [preferences.enabled]);

  function update(next: BellPreferences) {
    setPreferences(next);
    saveBellPreferences(next);
  }

  async function toggle(enabled: boolean) {
    update({ ...preferences, enabled });
    if (!enabled) return;
    const ready = await armBell();
    setArmed(ready);
    if (ready) ringBell(preferences.volume); // a sample, so the volume can be judged
    setNote(ready ? "" : "Sound is blocked; click anywhere on the page.");
  }

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
    <span className="bar-control">
      <label
        className="switch-row"
        title={
          preferences.enabled && !armed
            ? "Click anywhere on the page to allow sound"
            : "A bell for each new animal visit"
        }
      >
        <input
          type="checkbox"
          role="switch"
          checked={preferences.enabled}
          onChange={(event) => void toggle(event.target.checked)}
        />
        <span>Ring</span>
      </label>
      {preferences.enabled && (
        <details className="bar-options">
          <summary aria-label="Ring options">⋯</summary>
          <div className="bar-popover">
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
              {note ||
                (armed ? "Sound is on." : "Click the page to allow sound.")}
            </small>
          </div>
        </details>
      )}
    </span>
  );
}
