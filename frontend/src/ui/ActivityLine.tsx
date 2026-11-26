// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Activity } from "../hooks/useActivity";

const MARK: Record<Activity["state"]["kind"], string> = {
  offline: "×",
  down: "!",
  slow: "…",
  loading: "↻",
  confirm: "✓",
  sound: "♪",
  connected: "●",
};

/**
 * The status line of the top bar (25 Nov): working, loading or cannot reach FALCON, in one
 * place on every page. Text plus a mark, never colour alone; its room is always kept, so
 * it never covers anything or moves the page.
 */
export default function ActivityLine({ activity }: { activity: Activity }) {
  const { state, busy } = activity;
  return (
    <>
      <p className={`fs-activity is-${state.kind}`} role="status" aria-live="polite">
        <span className="fs-activity-mark" aria-hidden="true">
          {MARK[state.kind]}
        </span>
        <span className="fs-activity-text">{state.text}</span>
      </p>
      <span className={`fs-progress${busy ? " on" : ""}`} aria-hidden="true" />
    </>
  );
}
