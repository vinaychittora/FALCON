// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState } from "react";
import { getSpot, parseSpot, saveSpot, type Spot } from "../api/inaturalist";

/**
 * Where this node's camera stands, for iNaturalist posts. Kept on this computer only
 * and shown publicly only as an obscured area. Set again if the node is moved.
 */
export default function CameraSpot({ nodeId }: { nodeId: string }) {
  const [spot, setSpot] = useState<Spot | null>(null);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getSpot(nodeId)
      .then(setSpot)
      .catch(() => setSpot(null));
  }, [nodeId]);
  const set = spot?.latitude != null && spot?.longitude != null;
  async function save(value: string) {
    setBusy(true);
    setError("");
    try {
      setSpot(await saveSpot(nodeId, value));
      setEditing(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="camera-spot">
      <h3 className="section-title">Camera spot (for iNaturalist posts)</h3>
      {editing ? (
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save(text);
          }}
        >
          <input
            value={text}
            placeholder="latitude, longitude (paste from a map)"
            aria-label="Camera spot as latitude, longitude"
            onChange={(event) => setText(event.target.value)}
            autoFocus
          />
          <button
            className="primary"
            type="submit"
            disabled={busy || !parseSpot(text)}
          >
            Save
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
        </form>
      ) : (
        <p className="muted">
          {set
            ? `Set: ${spot.latitude!.toFixed(5)}, ${spot.longitude!.toFixed(5)}. `
            : "Not set yet: posts from this node are blocked until it is. "}
          Kept on this computer only; iNaturalist shows it publicly only as an
          obscured area.{" "}
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setText(set ? `${spot.latitude}, ${spot.longitude}` : "");
              setEditing(true);
            }}
          >
            {set ? "Change" : "Set the camera spot"}
          </button>
          {set && (
            <>
              {" "}
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  if (window.confirm("Clear this node's camera spot?"))
                    void save("");
                }}
              >
                Clear
              </button>
            </>
          )}
        </p>
      )}
      {error && (
        <p className="banner banner-bad" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
