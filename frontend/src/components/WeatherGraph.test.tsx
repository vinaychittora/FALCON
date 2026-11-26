// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { axisBounds, linePath, rainWords, tipSide, WeatherChart, type Series, type SeriesPoint } from "./WeatherGraph";

const point = (at: string, t: number | null, wet = 0): SeriesPoint => ({
  at,
  temperature_c: t,
  humidity_percent: 60,
  pressure_hpa: 980,
  wet,
  readings: 10,
});

describe("weather graph", () => {
  it("keeps a flat temperature readable with at least a few degrees of axis", () => {
    expect(axisBounds([24.8, 25.1], 4)).toEqual([22, 27]);
    expect(axisBounds([18, 31.2], 4)).toEqual([18, 32]);
  });

  it("breaks the line where readings are missing", () => {
    const points = [
      point("2026-11-10T00:02:30Z", 20),
      point("2026-11-10T00:07:30Z", 21),
      point("2026-11-10T01:02:30Z", 22), // an hour later: a gap
    ];
    const path = linePath(points, (p) => p.temperature_c, () => 0, (v) => v, 300_000);
    expect(path.match(/M/g)?.length).toBe(2);
    expect(path.match(/L/g)?.length).toBe(1);
  });

  it("draws temperature, humidity, rain and sunrise with axis units", () => {
    const series: Series = {
      hours: 24,
      step_seconds: 300,
      start: "2026-11-10T00:00:00Z",
      end: "2026-11-11T00:00:00Z",
      points: [point("2026-11-10T06:02:30Z", 19, 0.5), point("2026-11-10T06:07:30Z", 19.4)],
      sun: [{ sunrise: "2026-11-10T01:15+00:00", sunset: "2026-11-10T12:10+00:00" }],
    };
    const html = renderToStaticMarkup(<WeatherChart series={series} />);
    expect(html).toContain("line temperature");
    expect(html).toContain("line humidity");
    expect(html).toContain('class="rain"');
    expect(html).toContain("sun-mark sunrise");
    // Legend chips: colour key, icon and unit; the full name is the accessible name.
    expect(html).toContain('aria-label="Temperature, °C"');
    expect(html).toContain('aria-label="Humidity, %"');
    expect(html).toContain('aria-label="Rain on the plate"');
    expect(html).toMatch(/aria-pressed="false"[^>]*aria-label="Pressure, hPa"/);
    // The graph is focusable and the tooltip stays mounted; no readout line.
    expect(html).toMatch(/<svg[^>]*tabindex="0"/);
    expect(html).toMatch(/class="weather-tip side-right"[^>]*visibility:hidden/);
    expect(html).not.toContain("weather-readout");
    expect(html).toContain("100%");
    expect(html).not.toContain("line pressure"); // behind the legend toggle
  });

  it("writes the rain plate in words and flips the tooltip near the right edge", () => {
    expect(rainWords(0)).toBe("dry");
    expect(rainWords(0.4)).toBe("wet 40 % of the time");
    expect(rainWords(null)).toBe("no reading");
    expect(tipSide(100, 800)).toBe("right");
    expect(tipSide(700, 800)).toBe("left");
  });
});
