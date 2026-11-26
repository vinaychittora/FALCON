// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState } from "react";
import {
  activityState,
  falconDown,
  forgetFailures,
  foregroundBusy,
  subscribeActivity,
  type ActivityState,
} from "../api/activity";
import { bellArmed } from "../api/detectionBell";
import { useBellPreferences } from "../ui/DetectionBell";

export interface Activity {
  state: ActivityState;
  /** FALCON cannot be reached (two heartbeats failed in a row). */
  down: boolean;
  /** A request the user started is on its way: the thin moving bar. */
  busy: boolean;
}

function read(soundBlocked: boolean): Activity {
  return { state: activityState(Date.now(), undefined, soundBlocked), down: falconDown(), busy: foregroundBusy() };
}

const same = (a: Activity, b: Activity) =>
  a.state.kind === b.state.kind && a.state.text === b.state.text && a.down === b.down && a.busy === b.busy;

/**
 * The one activity sign, read by the status line, the header dot and the status sheet.
 * Thresholds (250 ms, 5 s, 3 s confirmations) pass without a request ending, so it also
 * looks again every 250 ms; it only re-renders when what it shows changes.
 * `onVisible` runs when the tab comes back into view (the heartbeat polls at once).
 */
export function useActivity(onVisible?: () => void): Activity {
  const [preferences] = useBellPreferences();
  const [activity, setActivity] = useState<Activity>(() => read(false));
  useEffect(() => {
    // Ring is on but the browser still blocks sound until the page is tapped once.
    const look = () => {
      const next = read(preferences.enabled && !bellArmed());
      setActivity((previous) => (same(previous, next) ? previous : next));
    };
    const unsubscribe = subscribeActivity(look);
    const timer = window.setInterval(look, 250);
    window.addEventListener("online", look);
    window.addEventListener("offline", look);
    look();
    return () => {
      unsubscribe();
      window.clearInterval(timer);
      window.removeEventListener("online", look);
      window.removeEventListener("offline", look);
    };
  }, [preferences.enabled]);
  useEffect(() => {
    const visible = () => {
      if (document.visibilityState !== "visible") return;
      forgetFailures();
      onVisible?.();
    };
    document.addEventListener("visibilitychange", visible);
    return () => document.removeEventListener("visibilitychange", visible);
  }, [onVisible]);
  return activity;
}
