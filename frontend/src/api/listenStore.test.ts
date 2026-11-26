// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readPersistent, writePersistent } from "../hooks/usePersistentState";

function memoryStorage() {
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
  return storage;
}

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllGlobals());

describe("Live switches are remembered", () => {
  it("keeps each switch across pages, reloads and restarts", () => {
    memoryStorage();
    expect(readPersistent("live.unresolved", false)).toBe(false);
    writePersistent("live.unresolved", true);
    writePersistent("live.boxes", false);
    writePersistent("live.feed", "unreviewed");
    // A new page or a reload reads the same values back.
    expect(readPersistent("live.unresolved", false)).toBe(true);
    expect(readPersistent("live.boxes", true)).toBe(false);
    expect(readPersistent("live.feed", "all")).toBe("unreviewed");
  });

  it("ignores damaged or mistyped values and blocked storage", () => {
    const storage = memoryStorage();
    storage.set("falcon.ui.live.boxes", "not json");
    storage.set("falcon.ui.live.unresolved", '"yes"');
    expect(readPersistent("live.boxes", true)).toBe(true);
    expect(readPersistent("live.unresolved", false)).toBe(false);
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(readPersistent("live.boxes", true)).toBe(true);
    expect(() => writePersistent("live.boxes", false)).not.toThrow();
  });
});

describe("one listening player for the whole app", () => {
  it("shares state between every Listen control and survives re-subscribing", async () => {
    memoryStorage();
    const store = await import("./listenStore");
    store.resetListenForTests();
    const seen: boolean[] = [];
    const unsubscribe = store.subscribeListen(() =>
      seen.push(store.getListenState().on),
    );
    store.setListenVolume(0.4);
    unsubscribe(); // a page unmounts: the player and its settings stay
    expect(store.getListenState().volume).toBe(0.4);
    expect(seen.length).toBeGreaterThan(0);
    store.setListenDenoise(false);
    const reloaded = (await import("./listenStore")).getListenState();
    expect(reloaded.denoise).toBe(false);
    expect(localStorage.getItem("falcon.listen-denoise.v1")).toBe("off");
  });
});
