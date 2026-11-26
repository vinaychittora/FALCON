// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { formatAgo } from "../api/format";
import { hashQuery } from "../api/summary";
import "./scenery.css";

export type ScenerySpot = {
  id: number;
  box: [number, number, number, number];
  kind: string;
  first_seen: string;
  last_hit: string;
  hits: number;
  stale: boolean;
  drops_at: string;
};
export type SceneryData = {
  spots: number;
  stale: number;
  items?: ScenerySpot[];
  scenery_hours?: number;
};

export const SCENERY_RULE =
  "A spot is saved when FALCON boxes the same thing at the same place and size without movement for 3 minutes. Boxes that match it are held back. An animal is still recorded when it moves by its own length, comes in over an edge, or is recognised as one species for 5 seconds.";

/** "Saved 19 Nov, 11:44" */
export function savedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Saved —";
  const day = date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const time = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `Saved ${day}, ${time}`;
}

/** The facts of one spot, in the words of the view. */
export function spotFacts(spot: ScenerySpot, sceneryHours = 48, now = Date.now()): string[] {
  const maybe = spot.kind === "maybe animal";
  return [
    maybe ? "Maybe an animal" : "Scenery",
    savedAt(spot.first_seen),
    `Last matched ${formatAgo(spot.last_hit, now)}`,
    `Matched ${spot.hits.toLocaleString()} time${spot.hits === 1 ? "" : "s"}`,
    `Dropped by itself ${maybe ? 6 : Math.round(sceneryHours)} hours after its last match`,
    ...(spot.stale ? ["Stale"] : []),
  ];
}

/** Background position and size that show one box of the still in a thumbnail. */
export function cropStyle(box: ScenerySpot["box"]): { size: string; position: string } {
  const [x1, y1, x2, y2] = box;
  const w = Math.max(0.001, x2 - x1);
  const h = Math.max(0.001, y2 - y1);
  const px = w >= 1 ? 0 : (x1 / (1 - w)) * 100;
  const py = h >= 1 ? 0 : (y1 / (1 - h)) * 100;
  return { size: `${(100 / w).toFixed(2)}% ${(100 / h).toFixed(2)}%`, position: `${px.toFixed(2)}% ${py.toFixed(2)}%` };
}

/**
 * System → Live status: "Scenery ignored" as an expand. Inside, the current camera
 * picture (taken when it opens, blurred for people like the live picture) with every
 * saved spot drawn on it, and one row per spot with a small crop of what is there.
 * The still and the crops are never stored.
 */
export default function SceneryView({ boxes, heldBack }: { boxes: number; heldBack: number }) {
  const [open, setOpen] = useState(
    () => typeof window !== "undefined" && hashQuery(window.location.hash, "scenery") === "1",
  );
  const [data, setData] = useState<SceneryData | null>(null);
  const [stamp, setStamp] = useState(() => (open ? Date.now() : 0));
  const [pictureFailed, setPictureFailed] = useState(false);
  const [aspect, setAspect] = useState(16 / 9);
  const [active, setActive] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const details = useRef<HTMLDetailsElement>(null);
  const rows = useRef(new Map<number, HTMLLIElement>());

  const load = useCallback(() => {
    api<SceneryData>("/live/scenery")
      .then(setData)
      .catch(() => setData(null));
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (open && hashQuery(window.location.hash, "scenery") === "1")
      details.current?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function forget(spot: ScenerySpot) {
    if (
      !window.confirm(
        `Forget spot ${spot.id}? Boxes at that place are recorded again (hidden) until it is learned again, about 3 minutes, if it is still there.`,
      )
    )
      return;
    setBusy(spot.id);
    setError("");
    try {
      setData(await api<SceneryData>(`/live/scenery/${spot.id}/forget`, { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  const spots = data?.items ?? [];
  const count = data?.spots ?? 0;
  const still = stamp ? `/api/live/preview.jpg?still=${stamp}` : "";
  const summary = `${boxes} boxes${heldBack ? ` · ${heldBack} detections held back this session` : ""} · ${count} spot${count === 1 ? "" : "s"} saved`;
  return (
    <details
      ref={details}
      className="sc-xp"
      id="scenery-ignored"
      open={open}
      onToggle={(event) => {
        const opened = event.currentTarget.open;
        setOpen(opened);
        if (opened) {
          // A fresh still each time the view opens; never stored.
          setStamp(Date.now());
          setPictureFailed(false);
          load();
        }
      }}
    >
      <summary>
        <span className="sc-xp-t">Scenery ignored</span>
        <span className="sc-xp-s">{summary}</span>
      </summary>
      {open && (
        <div className="sc-body">
          <div className="sc-picture">
            <div className="sc-frame" style={{ aspectRatio: String(aspect) }}>
              {still && !pictureFailed ? (
                <img
                  src={still}
                  alt="Current camera picture with the saved spots"
                  onLoad={(event) => {
                    const image = event.currentTarget;
                    if (image.naturalWidth && image.naturalHeight)
                      setAspect(image.naturalWidth / image.naturalHeight);
                  }}
                  onError={() => setPictureFailed(true)}
                />
              ) : (
                <p className="sc-nopic">No live picture right now. Start observing on Live to see the spots on the picture.</p>
              )}
              {spots.map((spot) => {
                const [x1, y1, x2, y2] = spot.box;
                return (
                  <button
                    key={spot.id}
                    type="button"
                    className={`sc-spot kind-${spot.kind === "maybe animal" ? "maybe" : "scenery"}${spot.stale ? " stale" : ""}${active === spot.id ? " active" : ""}`}
                    style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}
                    aria-label={`Spot ${spot.id}: ${spotFacts(spot, data?.scenery_hours)[0]}${spot.stale ? ", stale" : ""}. Go to its row.`}
                    onClick={() => rows.current.get(spot.id)?.focus()}
                    onMouseEnter={() => setActive(spot.id)}
                    onMouseLeave={() => setActive(null)}
                  >
                    <span className="sc-num">{spot.id}</span>
                  </button>
                );
              })}
            </div>
            <div className="sc-picture-bar">
              <span>
                {still && !pictureFailed
                  ? `Picture taken ${new Date(stamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
                  : ""}
              </span>
              <button
                type="button"
                className="tlink"
                onClick={() => {
                  setPictureFailed(false);
                  setStamp(Date.now());
                  load();
                }}
              >
                Refresh
              </button>
            </div>
            <p className="sc-key">
              <span className="sc-key-item"><i className="sc-key-box kind-scenery" aria-hidden="true" /> Scenery (dashed, grey)</span>
              <span className="sc-key-item"><i className="sc-key-box kind-maybe" aria-hidden="true" /> Maybe an animal (dashed, orange)</span>
              <span className="sc-key-item"><i className="sc-key-box stale" aria-hidden="true" /> Stale (dotted, dim)</span>
            </p>
          </div>
          <div className="sc-list-col">
            {data && !data.items && count > 0 ? (
              <p className="sc-note">
                {count} spot{count === 1 ? "" : "s"} saved. The list and the picture with the spots appear after FALCON's next restart.
              </p>
            ) : !spots.length ? (
              <p className="sc-note">No spots saved.</p>
            ) : (
              <ol className="sc-list">
                {spots.map((spot) => {
                  const crop = cropStyle(spot.box);
                  const [x1, y1, x2, y2] = spot.box;
                  const ratio = ((x2 - x1) * aspect) / Math.max(0.001, y2 - y1);
                  return (
                    <li
                      key={spot.id}
                      ref={(element) => {
                        if (element) rows.current.set(spot.id, element);
                        else rows.current.delete(spot.id);
                      }}
                      tabIndex={-1}
                      className={`sc-row${active === spot.id ? " active" : ""}`}
                      onMouseEnter={() => setActive(spot.id)}
                      onMouseLeave={() => setActive(null)}
                      onFocus={() => setActive(spot.id)}
                      onBlur={() => setActive(null)}
                    >
                      <span className="sc-row-num" aria-hidden="true">{spot.id}</span>
                      <span
                        className="sc-crop"
                        role="img"
                        aria-label={`What is at spot ${spot.id}`}
                        style={
                          still && !pictureFailed
                            ? {
                                backgroundImage: `url(${still})`,
                                backgroundSize: crop.size,
                                backgroundPosition: crop.position,
                                aspectRatio: String(Math.min(3, Math.max(0.5, ratio))),
                              }
                            : undefined
                        }
                      />
                      <span className="sc-facts">
                        <span className="rv-sr">Spot {spot.id}. </span>
                        {spotFacts(spot, data?.scenery_hours).map((fact, index) => (
                          <span key={fact} className={index === 0 ? "sc-kind" : fact === "Stale" ? "sc-stale" : undefined}>
                            {fact}
                          </span>
                        ))}
                      </span>
                      <button
                        type="button"
                        className="sc-forget"
                        disabled={busy !== null}
                        onClick={() => void forget(spot)}
                      >
                        Forget this spot
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
            {error && <p className="sc-error" role="alert">{error}</p>}
            <p className="sc-rule">{SCENERY_RULE}</p>
          </div>
        </div>
      )}
    </details>
  );
}
