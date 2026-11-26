// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
/**
 * One live-listening player for the whole app. It lives outside React, so changing
 * page (Live → Sensors → Microphone settings → System) or re-rendering never stops
 * it; only switching it off, the live session ending or closing the tab does.
 */
import { useSyncExternalStore } from "react";
import { LiveListener, readListenVolume, saveListenVolume } from "./liveListen";

export type ListenState = {
  on: boolean;
  volume: number;
  /** Lower the microphone's steady hiss in what you hear (not in BirdNET or clips). */
  denoise: boolean;
  rms: number;
  peak: number;
  error: string;
};

const DENOISE_KEY = "falcon.listen-denoise.v1";

function readDenoise(): boolean {
  try {
    return localStorage.getItem(DENOISE_KEY) !== "off";
  } catch {
    return true;
  }
}

let state: ListenState = {
  on: false,
  volume: readListenVolume(),
  denoise: readDenoise(),
  rms: -Infinity,
  peak: -Infinity,
  error: "",
};
const subscribers = new Set<() => void>();
let player: LiveListener | null = null;

function set(next: Partial<ListenState>): void {
  state = { ...state, ...next };
  subscribers.forEach((notify) => notify());
}

export function getListenState(): ListenState {
  return state;
}

export function subscribeListen(notify: () => void): () => void {
  subscribers.add(notify);
  return () => subscribers.delete(notify);
}

/** Start listening (call from a click: browsers allow sound only after one). */
export async function startListening(): Promise<void> {
  if (state.on) return;
  player ??= new LiveListener(({ rms, peak }) => set({ rms, peak }));
  set({ on: true, error: "" });
  try {
    await player.start(state.volume, state.denoise);
  } catch (reason) {
    set({ error: reason instanceof Error ? reason.message : String(reason) });
  } finally {
    // The stream ended: switched off, the live session stopped, or the network dropped.
    set({ on: false, rms: -Infinity, peak: -Infinity });
  }
}

export function stopListening(): void {
  player?.stop();
  set({ on: false });
}

export function setListenVolume(volume: number): void {
  saveListenVolume(volume);
  player?.setVolume(volume);
  set({ volume });
}

/** Changing noise reduction while listening restarts the sound with the new choice. */
export function setListenDenoise(denoise: boolean): void {
  try {
    localStorage.setItem(DENOISE_KEY, denoise ? "on" : "off");
  } catch {
    /* per-browser convenience only */
  }
  const wasOn = state.on;
  set({ denoise });
  if (wasOn) {
    player?.stop();
    window.setTimeout(() => void startListening(), 50);
  }
}

export function useListen(): ListenState {
  return useSyncExternalStore(subscribeListen, getListenState, getListenState);
}

/** For tests: forget the player and state. */
export function resetListenForTests(next?: Partial<ListenState>): void {
  player = null;
  state = {
    ...state,
    on: false,
    rms: -Infinity,
    peak: -Infinity,
    error: "",
    ...next,
  };
}
