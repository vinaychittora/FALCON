// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

const GAP = 8;
const EDGE = 12;

type Rect = { left: number; top: number; right: number; bottom: number };
type Size = { width: number; height: number };

/**
 * Where a floating panel goes: above its anchor (below when there is no room), right
 * edges lined up, and always entirely on screen. The panels are drawn on top of the
 * whole page, so nothing they sit in can cut them off (14 Nov: the Ring and Listen
 * menus were clipped by the Live picture's frame).
 */
export function placePanel(anchor: Rect, panel: Size, view: Size): { left: number; top: number } {
  const left = Math.max(EDGE, Math.min(anchor.right - panel.width, view.width - EDGE - panel.width));
  let top = anchor.top - GAP - panel.height;
  if (top < EDGE) top = Math.min(anchor.bottom + GAP, view.height - EDGE - panel.height);
  return { left, top: Math.max(EDGE, top) };
}

/** Full screen shows only the full-screen element, so panels go inside it then. */
function portalRoot(): Element {
  return document.fullscreenElement ?? document.body;
}

function useFloating(
  open: boolean,
  anchor: RefObject<HTMLElement | null>,
  panel: RefObject<HTMLElement | null>,
) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      if (!anchor.current || !panel.current) return;
      const next = placePanel(
        anchor.current.getBoundingClientRect(),
        { width: panel.current.offsetWidth, height: panel.current.offsetHeight },
        { width: document.documentElement.clientWidth, height: window.innerHeight },
      );
      setPosition((now) =>
        now && now.left === next.left && now.top === next.top ? now : next,
      );
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    if (panel.current) observer?.observe(panel.current);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      observer?.disconnect();
    };
  }, [open, anchor, panel]);
  // Placed again (before paint) each time it opens; nothing is shown while closed.
  return open ? position : null;
}

function placedStyle(position: { left: number; top: number } | null) {
  // Measured hidden first, then shown in place: never a frame in the wrong spot.
  return position
    ? { left: position.left, top: position.top }
    : { left: 0, top: 0, visibility: "hidden" as const };
}

/** The "⋯" options menu on the Live bar (Listen, Ring). */
export function BarOptions({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const position = useFloating(open, anchor, panel);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !anchor.current?.contains(target)) {
        setOpen(false);
      }
    };
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      anchor.current?.focus();
    };
    const close = () => setOpen(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    document.addEventListener("fullscreenchange", close);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      document.removeEventListener("fullscreenchange", close);
    };
  }, [open]);

  return (
    <span className="bar-options">
      <button
        ref={anchor}
        type="button"
        className="bar-options-button"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((now) => !now)}
      >
        ⋯
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            role="dialog"
            aria-label={label}
            className="bar-popover"
            style={placedStyle(position)}
          >
            {children}
          </div>,
          portalRoot(),
        )}
    </span>
  );
}

/**
 * A hover/focus tooltip whose text can change while it is showing. The browser's own
 * tooltip (the title attribute) disappears every time its text changes, so a live
 * status in it blinked on every update (14 Nov).
 */
export function HoverTip({
  tip,
  className,
  children,
}: {
  tip: string;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const position = useFloating(open, anchor, panel);
  const id = useId();
  return (
    <span
      ref={anchor}
      className={className}
      tabIndex={0}
      aria-describedby={open ? id : undefined}
      aria-label={tip}
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            role="tooltip"
            className="hover-tip"
            style={placedStyle(position)}
          >
            {tip}
          </div>,
          portalRoot(),
        )}
    </span>
  );
}
