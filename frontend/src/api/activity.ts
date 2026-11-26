// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
/**
 * The app's one activity sign (since 25 Nov 2026, so that a lost connection, a slow answer
 * and loading are told apart): every request to FALCON goes through
 * api(), which reports here. The status line under the top bar reads one state from it.
 *
 * Foreground requests are the ones the user started or waits for: a page or list loading for
 * the first time or for changed filters, opening a record, a save, a preview. Background
 * polls (the repeats of usePoll) never show as loading, but every request, background or
 * not, counts as a heartbeat: two network failures in a row mean FALCON cannot be reached.
 */

export const LOADING_AFTER_MS = 250;
export const SLOW_AFTER_MS = 5000;
export const CONFIRM_MS = 3000;

export class NetworkError extends Error {
  constructor() {
    super("Can't reach FALCON. Check the connection and try again.");
    this.name = "NetworkError";
  }
}

type Flight = { started: number; foreground: boolean };

const flights = new Map<number, Flight>();
let nextId = 0;
let failures = 0;
let downSince: number | null = null;
let confirmation: { text: string; until: number } | null = null;
let backgroundDepth = 0;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function subscribeActivity(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Run `start` so that the requests it begins (synchronously) count as background. */
export function inBackground<T>(start: () => T): T {
  backgroundDepth += 1;
  try {
    return start();
  } finally {
    backgroundDepth -= 1;
  }
}

export type Outcome = "ok" | "answered" | "network" | "aborted";

/** api() calls this as a request starts; the returned function ends it. */
export function beginRequest(now = Date.now()): (outcome: Outcome, at?: number) => void {
  const id = nextId++;
  flights.set(id, { started: now, foreground: backgroundDepth === 0 });
  emit();
  return (outcome, at = Date.now()) => {
    flights.delete(id);
    if (outcome === "network") {
      failures += 1;
      if (failures === 1 && downSince === null) downSince = at;
    } else if (outcome !== "aborted") {
      // Any answer from FALCON, even an error page, proves it can be reached.
      if (failures >= 2) confirm("Connected again", at);
      failures = 0;
      downSince = null;
    }
    emit();
  };
}

/** A short confirmation in the status line ("2 reviews saved"). */
export function confirm(text: string, now = Date.now()): void {
  confirmation = { text, until: now + CONFIRM_MS };
  emit();
}

let task: string | null = null;

/** A named action the user started ("Posting…"): the line says it while it runs, also when it
 * takes longer than SLOW_AFTER_MS. The returned function ends it. */
export function startTask(text: string): () => void {
  task = text;
  emit();
  return () => {
    if (task === text) task = null;
    emit();
  };
}

/** The tab came back into view: judge again only after the next heartbeat. */
export function forgetFailures(): void {
  failures = Math.min(failures, 1);
  emit();
}

export type ActivityState =
  | { kind: "offline"; text: string }
  | { kind: "down"; text: string; since: number }
  | { kind: "slow"; text: string }
  | { kind: "loading"; text: string }
  | { kind: "confirm"; text: string }
  | { kind: "sound"; text: string }
  | { kind: "connected"; text: string };

const clock = (time: number) =>
  new Date(time).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** The one state the status line shows: the highest that applies wins. */
export function activityState(
  now = Date.now(),
  online = typeof navigator === "undefined" ? true : navigator.onLine !== false,
  soundBlocked = false,
): ActivityState {
  if (!online) return { kind: "offline", text: "This device has no network." };
  if (failures >= 2 && downSince !== null)
    return { kind: "down", text: `Can't reach FALCON since ${clock(downSince)}. Trying again…`, since: downSince };
  if (task) return { kind: "loading", text: task };
  const waits = [...flights.values()];
  if (waits.some((flight) => now - flight.started > SLOW_AFTER_MS))
    return { kind: "slow", text: "FALCON is slow to answer…" };
  if (waits.some((flight) => flight.foreground && now - flight.started > LOADING_AFTER_MS))
    return { kind: "loading", text: "Loading…" };
  if (confirmation && confirmation.until > now) return { kind: "confirm", text: confirmation.text };
  if (soundBlocked) return { kind: "sound", text: "Tap the page once to allow sound." };
  return { kind: "connected", text: "Connected" };
}

/** A request the user started has waited more than LOADING_AFTER_MS: the moving bar shows. */
export function foregroundBusy(now = Date.now()): boolean {
  return [...flights.values()].some((flight) => flight.foreground && now - flight.started > LOADING_AFTER_MS);
}

/** True while FALCON cannot be reached (the header dot and the status sheet). */
export function falconDown(): boolean {
  return failures >= 2 && downSince !== null;
}

/** Only for tests: start from a clean state. */
export function resetActivity(): void {
  flights.clear();
  failures = 0;
  downSince = null;
  confirmation = null;
  backgroundDepth = 0;
  task = null;
  emit();
}
