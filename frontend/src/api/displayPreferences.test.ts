import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyDisplayPreferences,
  DEFAULT_DISPLAY,
  DISPLAY_STORAGE_KEY,
  parseDisplayPreferences,
  readDisplayPreferences,
  resolvedTheme,
  saveDisplayPreferences,
} from "./displayPreferences";

afterEach(() => vi.unstubAllGlobals());

describe("browser display preferences", () => {
  it("starts in dark mode and tolerates missing or damaged settings", () => {
    for (const value of [null, "broken", "null", "4", "[]"]) {
      expect(parseDisplayPreferences(value)).toEqual(DEFAULT_DISPLAY);
    }
  });

  it("validates each setting rather than trusting browser storage", () => {
    expect(
      parseDisplayPreferences(
        JSON.stringify({
          theme: "light",
          textSize: "enormous",
          contrast: "high",
          secret: "discard",
        }),
      ),
    ).toEqual({
      theme: "light",
      textSize: "standard",
      contrast: "high",
      navigation: "side",
    });
    expect(
      parseDisplayPreferences('{"theme":"system","textSize":"extra-large"}'),
    ).toEqual({
      theme: "system",
      textSize: "extra-large",
      contrast: "standard",
      navigation: "side",
    });
  });

  it("keeps the side navigation unless the top bar was chosen", () => {
    expect(DEFAULT_DISPLAY.navigation).toBe("side");
    expect(parseDisplayPreferences('{"navigation":"top"}').navigation).toBe(
      "top",
    );
    expect(parseDisplayPreferences('{"navigation":"left"}').navigation).toBe(
      "side",
    );
  });

  it("keeps the interface usable when browser storage is blocked", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(readDisplayPreferences()).toEqual(DEFAULT_DISPLAY);
    expect(saveDisplayPreferences(DEFAULT_DISPLAY)).toBe(false);
  });

  it("restores exactly the selected browser preferences", () => {
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    });
    const preferences = {
      theme: "light",
      textSize: "large",
      contrast: "high",
      navigation: "top",
    } as const;
    expect(saveDisplayPreferences(preferences)).toBe(true);
    expect(readDisplayPreferences()).toEqual(preferences);
    expect([...storage.keys()]).toEqual([DISPLAY_STORAGE_KEY]);
  });

  it("only follows OS changes when requested", () => {
    expect(resolvedTheme(DEFAULT_DISPLAY, false)).toBe("dark");
    expect(resolvedTheme({ ...DEFAULT_DISPLAY, theme: "light" }, true)).toBe(
      "light",
    );
    expect(resolvedTheme({ ...DEFAULT_DISPLAY, theme: "system" }, true)).toBe(
      "dark",
    );
    expect(resolvedTheme({ ...DEFAULT_DISPLAY, theme: "system" }, false)).toBe(
      "light",
    );
  });

  it("applies theme, size, contrast and browser chrome together", () => {
    const dataset: Record<string, string> = {};
    const setAttribute = vi.fn();
    vi.stubGlobal("document", {
      documentElement: { dataset },
      querySelector: () => ({ setAttribute }),
    });
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    applyDisplayPreferences({
      theme: "system",
      textSize: "extra-large",
      contrast: "high",
      navigation: "top",
    });
    expect(dataset).toEqual({
      theme: "dark",
      textSize: "extra-large",
      contrast: "high",
      nav: "top",
    });
    expect(setAttribute).toHaveBeenCalledWith("content", "#14191e");
  });
});
