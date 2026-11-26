// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { clampCrop, type Crop } from "../api/inaturalist";
import { useBackToClose } from "../hooks/useBackToClose";
import Icon from "../components/Icon";
import "../components/record-view.css";
import "./posting.css";

type Drag = { mode: "move" | "nw" | "ne" | "sw" | "se"; x: number; y: number; start: Crop };

/** Move or resize a crop by a pointer drag of (dx, dy) fractions of the frame. */
export function dragCrop(start: Crop, mode: Drag["mode"], dx: number, dy: number): Crop {
  const [x1, y1, x2, y2] = start;
  if (mode === "move") {
    const w = x2 - x1, h = y2 - y1;
    return clampCrop([x1 + dx, y1 + dy, x1 + dx + w, y1 + dy + h]);
  }
  const left = mode === "nw" || mode === "sw" ? Math.min(x1 + dx, x2 - 0.08) : x1;
  const right = mode === "ne" || mode === "se" ? Math.max(x2 + dx, x1 + 0.08) : x2;
  const top = mode === "nw" || mode === "ne" ? Math.min(y1 + dy, y2 - 0.08) : y1;
  const bottom = mode === "sw" || mode === "se" ? Math.max(y2 + dy, y1 + 0.08) : y2;
  return clampCrop([Math.max(0, left), Math.max(0, top), Math.min(1, right), Math.min(1, bottom)]);
}

/** Arrow keys move the crop; Shift and arrow keys resize it (right and down grow). */
export function keyCrop(crop: Crop, key: string, shift: boolean, step = 0.02): Crop | null {
  const delta: Record<string, [number, number]> = {
    ArrowLeft: [-step, 0],
    ArrowRight: [step, 0],
    ArrowUp: [0, -step],
    ArrowDown: [0, step],
  };
  const move = delta[key];
  if (!move) return null;
  const [x1, y1, x2, y2] = crop;
  return shift
    ? clampCrop([x1, y1, Math.min(1, x2 + move[0]), Math.min(1, y2 + move[1])])
    : clampCrop([x1 + move[0], y1 + move[1], x2 + move[0], y2 + move[1]]);
}

/**
 * The crop tool for one chosen picture: a rectangle moved and resized with the mouse,
 * touch or keyboard, starting at the box around the animal. The stored frame never
 * changes; only the posted copy is cropped.
 */
export default function CropTool({
  src,
  start,
  onUse,
  onWhole,
  onCancel,
}: {
  src: string;
  start: Crop;
  onUse: (crop: Crop) => void;
  onWhole: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLDivElement>(null);
  const [crop, setCrop] = useState<Crop>(start);
  const [aspect, setAspect] = useState(16 / 9);
  const drag = useRef<Drag | null>(null);
  useBackToClose(onCancel);
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    area.current?.focus();
    return () => element.close();
  }, []);

  // Which part is dragged comes from the element's data-mode: the area moves, a corner resizes.
  function down(event: ReactPointerEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    const element = event.currentTarget as HTMLElement;
    element.setPointerCapture(event.pointerId);
    const mode = (element.dataset.mode ?? "move") as Drag["mode"];
    drag.current = { mode, x: event.clientX, y: event.clientY, start: crop };
  }
  function move(event: ReactPointerEvent<HTMLElement>) {
    const current = drag.current;
    const box = frame.current?.getBoundingClientRect();
    if (!current || !box) return;
    setCrop(dragCrop(current.start, current.mode, (event.clientX - current.x) / box.width, (event.clientY - current.y) / box.height));
  }
  const [x1, y1, x2, y2] = crop;
  return (
    <dialog
      ref={dialog}
      className="rv-sheet pp-crop"
      aria-labelledby="pp-crop-title"
      onCancel={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onCancel();
      }}
      onKeyDown={(event) => event.stopPropagation()}
    >
      <div className="rv-sheet-top rv-gut">
        <h2 id="pp-crop-title">Crop the picture</h2>
        <button type="button" className="rv-icon" aria-label="Cancel" onClick={onCancel}>
          <Icon name="close" />
        </button>
      </div>
      <div className="pp-crop-body rv-gut">
        <div className="pp-crop-frame" ref={frame} style={{ aspectRatio: String(aspect) }}>
          <img
            src={src}
            alt="The whole frame"
            draggable={false}
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth && image.naturalHeight) setAspect(image.naturalWidth / image.naturalHeight);
            }}
          />
          <div
            ref={area}
            className="pp-crop-area"
            tabIndex={0}
            role="group"
            aria-label={`Crop area, ${Math.round((x2 - x1) * 100)} by ${Math.round((y2 - y1) * 100)} percent of the frame. Arrow keys move it, Shift and arrow keys resize it.`}
            style={{ left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` }}
            data-mode="move"
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={() => (drag.current = null)}
            onKeyDown={(event) => {
              const next = keyCrop(crop, event.key, event.shiftKey);
              if (next) {
                event.preventDefault();
                setCrop(next);
              } else if (event.key === "Enter") {
                event.preventDefault();
                onUse(crop);
              }
            }}
          >
            {(["nw", "ne", "sw", "se"] as const).map((corner) => (
              <span
                key={corner}
                className={`pp-handle ${corner}`}
                aria-hidden="true"
                data-mode={corner}
                onPointerDown={down}
                onPointerMove={move}
                onPointerUp={() => (drag.current = null)}
              />
            ))}
          </div>
        </div>
        <p className="pp-crop-help">
          Drag the frame to move it and its corners to resize it. With the keyboard:
          arrow keys move it, Shift and arrow keys resize it.
        </p>
        <div className="pp-crop-actions">
          <button type="button" className="rv-next" onClick={() => onUse(crop)}>
            Use this crop
          </button>
          <button type="button" className="pp-btn" onClick={onWhole}>
            Whole frame
          </button>
          <button type="button" className="pp-btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </dialog>
  );
}
