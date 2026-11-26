// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useState } from "react";
import { api } from "../api/client";
import { usePoll } from "../hooks/usePoll";
import type { LiveState } from "../types";

export function setDetectionPaused(paused: boolean) {
  return api<LiveState>("/live/pause", {
    method: "PUT",
    body: JSON.stringify({ paused }),
  });
}

/**
 * "Pause detection (camera work)": while moving the node or refilling the bowl,
 * nothing is detected, recorded or rung; learned scenery is re-learned on resume.
 */
export default function PauseDetection() {
  const live = usePoll(() => api<LiveState>("/live/state"), 5000, "pause");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const since = live.data?.detection_paused_since ?? null;

  async function change(paused: boolean) {
    setPending(true);
    setError("");
    try {
      await setDetectionPaused(paused);
      live.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <label
        className="switch-row"
        title="While you work on the camera or the bowl: no detections, clips or bells. Scenery is re-learned when you switch it off."
      >
        <input
          type="checkbox"
          role="switch"
          checked={since !== null}
          disabled={pending || !live.data}
          onChange={(event) => void change(event.target.checked)}
        />
        <span>
          Pause detection (camera work)
          {since &&
            ` · since ${new Date(since).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}
        </span>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
