// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { ActivityState } from "../api/activity";
import { useActivity } from "../hooks/useActivity";

/** The connection states a full-screen layer shows in its own top bar (25 Nov, build 2b):
 * the layer covers the app bar and its status line. Save confirmations and the sound hint
 * stay out (the layer says itself what was decided); `extra` lets a layer add its own
 * confirmations ("Posted to iNaturalist" in the posting panel). Connected shows nothing. */
export function layerState(state: ActivityState, extra: readonly string[] = []): ActivityState | null {
  switch (state.kind) {
    case "down":
      // The short form inside a layer, so it is not cut on a phone; the app bar keeps
      // "… Trying again…".
      return { ...state, text: state.text.replace(/\s*Trying again…$/, "") };
    case "offline":
    case "slow":
    case "loading":
      return state;
    case "confirm":
      return state.text === "Connected again" || extra.includes(state.text) ? state : null;
    default:
      return null;
  }
}

const MARK: Record<ActivityState["kind"], string> = {
  offline: "×",
  down: "!",
  slow: "…",
  loading: "↻",
  confirm: "✓",
  sound: "♪",
  connected: "●",
};

/** What a layer's top bar needs: the state to show (null: show its own line), the state
 * for an always-shown place (Connected when nothing else), and the moving bar. */
export function useLayerStatus(extra: readonly string[] = []): {
  shown: ActivityState | null;
  always: ActivityState;
  busy: boolean;
} {
  const activity = useActivity();
  const shown = layerState(activity.state, extra);
  return {
    shown,
    always: shown ?? { kind: "connected", text: "Connected" },
    busy: activity.busy,
  };
}

/** One status, as text with its mark (never colour alone). */
export function StatusText({ state, live = true }: { state: ActivityState; live?: boolean }) {
  return (
    <span
      className={`ly-status is-${state.kind}`}
      role={live ? "status" : undefined}
      aria-live={live ? "polite" : undefined}
    >
      <span className="ly-status-mark" aria-hidden="true">
        {MARK[state.kind]}
      </span>
      <span className="ly-status-text">{state.text}</span>
    </span>
  );
}
