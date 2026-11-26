// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Encounter } from "./encounters";
import { thumbnailUrl } from "./encounters";
import { UNIDENTIFIED_SOUND, unidentifiedSound } from "./certainty";

/** "Ring on detection": a short bell and, optionally, a desktop notification. */
export type BellPreferences = {
  enabled: boolean;
  /** 0 to 1. */
  volume: number;
  /** Also show a desktop notification (asks the browser for permission). */
  notify: boolean;
};

export const BELL_STORAGE_KEY = "falcon.detection-bell.v1";
export const DEFAULT_BELL: BellPreferences = {
  enabled: false,
  volume: 0.6,
  notify: false,
};
/** At most one ring this often, however many visits arrive together. */
export const RING_INTERVAL_MS = 3000;

export function parseBellPreferences(raw: string | null): BellPreferences {
  try {
    const value: unknown = JSON.parse(raw ?? "null");
    if (!value || typeof value !== "object") return { ...DEFAULT_BELL };
    const candidate = value as Record<string, unknown>;
    const volume = Number(candidate.volume);
    return {
      enabled: candidate.enabled === true,
      volume: Number.isFinite(volume)
        ? Math.min(1, Math.max(0, volume))
        : DEFAULT_BELL.volume,
      notify: candidate.notify === true,
    };
  } catch {
    return { ...DEFAULT_BELL };
  }
}

export function readBellPreferences(): BellPreferences {
  try {
    return parseBellPreferences(localStorage.getItem(BELL_STORAGE_KEY));
  } catch {
    return { ...DEFAULT_BELL };
  }
}

export function saveBellPreferences(value: BellPreferences): boolean {
  try {
    localStorage.setItem(BELL_STORAGE_KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** The name people know for what a visit is: species, else its group label. */
export function visitName(encounter: Encounter): string {
  const event = encounter.event;
  if (event.modality === "audio")
    return unidentifiedSound(event)
      ? UNIDENTIFIED_SOUND
      : event.common_name || event.scientific_name;
  return (
    event.classification.common_name ||
    event.classification.scientific_name ||
    event.classification.display_label ||
    "An animal"
  );
}

/**
 * Decides when to ring: once per new animal visit (not per frame or per update of a
 * visit already seen), at most once every RING_INTERVAL_MS. The first list it sees
 * only marks what is already there, so opening the page does not ring for old visits.
 */
export class VisitBell {
  private seen = new Set<string>();
  private primed = false;
  private lastRing = -Infinity;

  constructor(private readonly now: () => number = () => Date.now()) {}

  /** New visits that should ring now (empty when nothing should ring). */
  update(encounters: Encounter[]): Encounter[] {
    const fresh = encounters.filter(
      (item) => !this.seen.has(item.encounter_id),
    );
    for (const item of encounters) this.seen.add(item.encounter_id);
    if (!this.primed) {
      this.primed = true;
      return [];
    }
    if (!fresh.length) return [];
    const time = this.now();
    if (time - this.lastRing < RING_INTERVAL_MS) return [];
    this.lastRing = time;
    return fresh;
  }

  /** Forget what was seen (a new observing session). */
  reset(): void {
    this.seen.clear();
    this.primed = false;
  }
}

type AudioContextClass = typeof AudioContext;

let context: AudioContext | null = null;

/**
 * Browsers only allow sound after a click or key press. Call this from the click that
 * switches the bell on (and again on later clicks) so the bell can ring by itself.
 */
export async function armBell(): Promise<boolean> {
  const Context: AudioContextClass | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: AudioContextClass })
      .webkitAudioContext;
  if (!Context) return false;
  context ??= new Context();
  if (context.state === "suspended") {
    try {
      await context.resume();
    } catch {
      return false;
    }
  }
  return context.state === "running";
}

export function bellArmed(): boolean {
  return context?.state === "running";
}

/** A soft two-tone bell made in the browser: two short sine tones that fade out. */
export function ringBell(volume: number): void {
  if (!context || context.state !== "running" || volume <= 0) return;
  const start = context.currentTime + 0.01;
  for (const [frequency, delay] of [
    [880, 0],
    [1320, 0.18],
  ] as const) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, start + delay);
    gain.gain.exponentialRampToValueAtTime(0.4 * volume, start + delay + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + delay + 0.9);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start + delay);
    oscillator.stop(start + delay + 1);
  }
}

/** Ask for desktop notifications; true when they are allowed. */
export async function allowNotifications(): Promise<boolean> {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  return (await Notification.requestPermission()) === "granted";
}

/** A desktop notification for the newest visit, with its thumbnail. */
export function notifyVisits(visits: Encounter[]): void {
  if (
    !visits.length ||
    typeof Notification === "undefined" ||
    Notification.permission !== "granted"
  )
    return;
  const first = visits[0];
  const more = visits.length > 1 ? ` and ${visits.length - 1} more` : "";
  const notification = new Notification(`FALCON: ${visitName(first)}${more}`, {
    body:
      first.modality === "audio"
        ? "Heard on the sensor node"
        : "Seen on the sensor node",
    icon: thumbnailUrl(first.thumbnail_event_id),
    tag: "falcon-detection",
  });
  notification.onclick = () => {
    window.focus();
    notification.close();
  };
}
