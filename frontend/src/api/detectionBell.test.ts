import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BELL_STORAGE_KEY,
  DEFAULT_BELL,
  parseBellPreferences,
  readBellPreferences,
  RING_INTERVAL_MS,
  saveBellPreferences,
  visitName,
  VisitBell,
} from "./detectionBell";
import type { Encounter } from "./encounters";

afterEach(() => vi.unstubAllGlobals());

function visit(id: string, name = "Indian Robin"): Encounter {
  return {
    encounter_id: id,
    modality: "visual",
    thumbnail_event_id: `e-${id}`,
    event: {
      modality: "visual",
      classification: {
        common_name: name,
        scientific_name: "Copsychus fulicatus",
        display_label: name,
      },
    },
  } as unknown as Encounter;
}

describe("ring on detection", () => {
  it("does not ring for visits already on screen when the page opens", () => {
    const bell = new VisitBell(() => 0);
    expect(bell.update([visit("a"), visit("b")])).toEqual([]);
  });

  it("rings once per new visit, not for every update of the same visit", () => {
    let now = 0;
    const bell = new VisitBell(() => now);
    bell.update([visit("a")]);
    now = 10_000;
    expect(
      bell.update([visit("b"), visit("a")]).map((v) => v.encounter_id),
    ).toEqual(["b"]);
    now = 20_000;
    expect(bell.update([visit("b"), visit("a")])).toEqual([]); // same visits, new frames
  });

  it("rings once when a visit becomes Likely, never again for the same visit", () => {
    let now = 0;
    const bell = new VisitBell(() => now);
    bell.update([]); // the cat is still Probable: not on the Live list
    now += RING_INTERVAL_MS;
    expect(bell.update([visit("cat")])).toHaveLength(1); // third good frame: Likely
    now += RING_INTERVAL_MS;
    expect(bell.update([])).toEqual([]); // briefly off the list
    now += RING_INTERVAL_MS;
    expect(bell.update([visit("cat")])).toEqual([]); // back: no second ring
  });

  it("rings at most once every 3 seconds", () => {
    let now = 0;
    const bell = new VisitBell(() => now);
    bell.update([]);
    now = 1000;
    expect(bell.update([visit("a")])).toHaveLength(1);
    now = 1000 + RING_INTERVAL_MS - 1;
    expect(bell.update([visit("b"), visit("a")])).toEqual([]);
    now = 1000 + RING_INTERVAL_MS + 10;
    expect(bell.update([visit("c"), visit("b"), visit("a")])).toHaveLength(1);
  });

  it("starts fresh for a new session or filter", () => {
    const bell = new VisitBell(() => 0);
    bell.update([visit("a")]);
    bell.reset();
    expect(bell.update([visit("a"), visit("b")])).toEqual([]);
  });

  it("names the visit the way people know it", () => {
    expect(visitName(visit("a", "Red-vented Bulbul"))).toBe(
      "Red-vented Bulbul",
    );
    const heard = {
      encounter_id: "s",
      event: {
        modality: "audio",
        common_name: "Asian Koel",
        scientific_name: "Eudynamys scolopaceus",
      },
    } as unknown as Encounter;
    expect(visitName(heard)).toBe("Asian Koel");
  });

  it("keeps the bell setting in this browser and validates it", () => {
    expect(parseBellPreferences(null)).toEqual(DEFAULT_BELL);
    expect(DEFAULT_BELL.enabled).toBe(false);
    expect(
      parseBellPreferences('{"enabled":true,"volume":7,"notify":"yes"}'),
    ).toEqual({
      enabled: true,
      volume: 1,
      notify: false,
    });
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    });
    const choice = { enabled: true, volume: 0.3, notify: true };
    expect(saveBellPreferences(choice)).toBe(true);
    expect(readBellPreferences()).toEqual(choice);
    expect([...storage.keys()]).toEqual([BELL_STORAGE_KEY]);
  });
});
