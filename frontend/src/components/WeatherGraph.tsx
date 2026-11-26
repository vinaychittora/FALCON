// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api/client";
import Icon from "./Icon";

export interface SeriesPoint {
  at: string;
  temperature_c: number | null;
  humidity_percent: number | null;
  pressure_hpa: number | null;
  /** Share of readings with a wet rain plate in this step, 0 to 1. */
  wet: number | null;
  readings: number;
}
export interface Series {
  hours: number;
  step_seconds: number;
  start: string;
  end: string;
  points: SeriesPoint[];
  sun: { sunrise: string; sunset: string }[];
}

export const RANGES = [
  { hours: 24, label: "24 h" },
  { hours: 168, label: "7 days" },
  { hours: 720, label: "30 days" },
] as const;

const HEIGHT = 240;
const PAD = { left: 44, right: 44, top: 12, bottom: 40 };
const RAIN_BAND = 14;

/** Nice round bounds for an axis that holds every value, at least `span` wide. */
export function axisBounds(values: number[], span: number): [number, number] {
  if (!values.length) return [0, span];
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (high - low < span) {
    const middle = (high + low) / 2;
    low = middle - span / 2;
    high = middle + span / 2;
  }
  return [Math.floor(low), Math.ceil(high)];
}

/** SVG path for one value; a gap of more than 2.5 steps breaks the line. */
export function linePath(
  points: SeriesPoint[],
  value: (p: SeriesPoint) => number | null,
  x: (p: SeriesPoint) => number,
  y: (v: number) => number,
  stepMs: number,
): string {
  let path = "";
  let previous: number | null = null;
  for (const point of points) {
    const v = value(point);
    const t = Date.parse(point.at);
    if (v === null || !Number.isFinite(v)) {
      previous = null;
      continue;
    }
    const move = previous === null || t - previous > stepMs * 2.5;
    path += `${move ? "M" : "L"}${x(point).toFixed(1)},${y(v).toFixed(1)}`;
    previous = t;
  }
  return path;
}

/** "wet 40 % of the time" or "dry": the rain plate in words. */
export function rainWords(wet: number | null): string {
  if (wet === null) return "no reading";
  return wet > 0 ? `wet ${Math.round(wet * 100)} % of the time` : "dry";
}

const TIP_ROOM = 190; // the tooltip's width plus its gap to the cursor line

/** The tooltip sits right of the cursor line, or left of it where the right has no
 * room; on a very narrow graph it takes the side with more room. */
export function tipSide(x: number, width: number): "right" | "left" {
  if (width - x >= TIP_ROOM) return "right";
  if (x >= TIP_ROOM) return "left";
  return width - x >= x ? "right" : "left";
}

function timeLabel(ms: number, hours: number) {
  const date = new Date(ms);
  return hours <= 24
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function WeatherChart({ series }: { series: Series }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [showPressure, setShowPressure] = useState(false);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const tipId = useId();
  useEffect(() => {
    const element = box.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(280, Math.round(entry.contentRect.width))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const start = Date.parse(series.start);
  const end = Date.parse(series.end);
  const stepMs = series.step_seconds * 1000;
  const plotWidth = width - PAD.left - PAD.right;
  const plotBottom = HEIGHT - PAD.bottom;
  const lineBottom = plotBottom - RAIN_BAND - 4;
  const x = (ms: number) => PAD.left + ((ms - start) / (end - start)) * plotWidth;
  const at = (p: SeriesPoint) => x(Date.parse(p.at));
  const points = series.points;

  const temps = points.flatMap((p) => (p.temperature_c ?? null) !== null ? [p.temperature_c as number] : []);
  const pressures = points.flatMap((p) => (p.pressure_hpa ?? null) !== null ? [p.pressure_hpa as number] : []);
  const [tLow, tHigh] = axisBounds(temps, 4);
  const [pLow, pHigh] = axisBounds(pressures, 4);
  const yT = (v: number) => lineBottom - ((v - tLow) / (tHigh - tLow)) * (lineBottom - PAD.top);
  const yH = (v: number) => lineBottom - (v / 100) * (lineBottom - PAD.top);
  const yP = (v: number) => lineBottom - ((v - pLow) / (pHigh - pLow)) * (lineBottom - PAD.top);

  const ticks = useMemo(() => {
    const count = Math.max(2, Math.min(8, Math.floor(plotWidth / 90)));
    return Array.from({ length: count + 1 }, (_, i) => start + ((end - start) * i) / count);
  }, [start, end, plotWidth]);
  const tTicks = [tLow, (tLow + tHigh) / 2, tHigh];
  const sunMarks = series.sun.flatMap((day) => [
    { ms: Date.parse(day.sunrise), kind: "sunrise" },
    { ms: Date.parse(day.sunset), kind: "sunset" },
  ]).filter((mark) => mark.ms >= start && mark.ms <= end);

  function pick(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ms = start + ((event.clientX - rect.left - PAD.left) / plotWidth) * (end - start);
    let best = -1;
    let distance = Infinity;
    points.forEach((point, index) => {
      const d = Math.abs(Date.parse(point.at) - ms);
      if (d < distance) [best, distance] = [index, d];
    });
    setHoverIndex(best >= 0 && distance <= stepMs * 3 ? best : null);
  }

  // Keyboard: the graph takes focus and the arrow keys move the cursor.
  function step(event: KeyboardEvent<SVGSVGElement>) {
    if (!points.length) return;
    const last = points.length - 1;
    const next =
      event.key === "ArrowRight" ? Math.min(last, (hoverIndex ?? -1) + 1)
      : event.key === "ArrowLeft" ? Math.max(0, (hoverIndex ?? last + 1) - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : event.key === "Escape" ? null
      : undefined;
    if (next === undefined) return;
    event.preventDefault();
    setHoverIndex(next);
  }

  const hover = hoverIndex === null ? null : (points[hoverIndex] ?? null);
  const hoverX = hover ? at(hover) : 0;
  const side = tipSide(hoverX, width);
  const reading = (value: number | null, unit: string) => (value === null ? "—" : `${value} ${unit}`);
  return (
    <div className="weather-chart" ref={box}>
      <div className="weather-legend" aria-label="What the lines show">
        <span className="w-chip" aria-label="Temperature, °C" title="Temperature">
          <i className="w-swatch temperature" aria-hidden="true" />
          <Icon name="thermometer" size={16} />
          <span aria-hidden="true">°C</span>
        </span>
        <span className="w-chip" aria-label="Humidity, %" title="Humidity">
          <i className="w-swatch humidity" aria-hidden="true" />
          <Icon name="drop" size={16} />
          <span aria-hidden="true">%</span>
        </span>
        <span className="w-chip" aria-label="Rain on the plate" title="Rain on the plate">
          <i className="w-swatch rain" aria-hidden="true" />
          <Icon name="rain" size={16} />
          <span aria-hidden="true">Rain</span>
        </span>
        <button
          type="button"
          className="w-chip w-toggle"
          aria-pressed={showPressure}
          aria-label="Pressure, hPa"
          title="Pressure"
          onClick={() => setShowPressure((on) => !on)}
        >
          <i className="w-swatch pressure" aria-hidden="true" />
          <Icon name="gauge" size={16} />
          <span aria-hidden="true">hPa</span>
        </button>
      </div>
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        tabIndex={0}
        aria-label={`Weather over the last ${series.hours} hours: temperature, humidity and rain. Use the left and right arrow keys to read the values at a moment.`}
        aria-describedby={tipId}
        onPointerMove={pick}
        onPointerDown={pick}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") setHoverIndex(null);
        }}
        onKeyDown={step}
        onBlur={() => setHoverIndex(null)}
      >
        {sunMarks.map((mark) => (
          <line
            key={`${mark.kind}-${mark.ms}`}
            className={`sun-mark ${mark.kind}`}
            x1={x(mark.ms)}
            x2={x(mark.ms)}
            y1={PAD.top}
            y2={plotBottom}
          >
            <title>{`${mark.kind === "sunrise" ? "Sunrise" : "Sunset"} ${new Date(mark.ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}</title>
          </line>
        ))}
        {tTicks.map((v) => (
          <g key={v}>
            <line className="grid" x1={PAD.left} x2={width - PAD.right} y1={yT(v)} y2={yT(v)} />
            <text className="axis axis-temperature" x={PAD.left - 6} y={yT(v) + 4} textAnchor="end">
              {Math.round(v * 10) / 10}°
            </text>
          </g>
        ))}
        {[0, 50, 100].map((v) => (
          <text key={v} className="axis axis-humidity" x={width - PAD.right + 6} y={yH(v) + 4}>
            {v}%
          </text>
        ))}
        {points.map((p) =>
          p.wet ? (
            <rect
              key={`rain-${p.at}`}
              className="rain"
              x={at(p) - Math.max(1, (stepMs / (end - start)) * plotWidth) / 2}
              width={Math.max(1, (stepMs / (end - start)) * plotWidth)}
              y={plotBottom - RAIN_BAND * Math.max(0.3, p.wet)}
              height={RAIN_BAND * Math.max(0.3, p.wet)}
            />
          ) : null,
        )}
        <line className="baseline" x1={PAD.left} x2={width - PAD.right} y1={plotBottom} y2={plotBottom} />
        {showPressure && (
          <path className="line pressure" d={linePath(points, (p) => p.pressure_hpa, at, yP, stepMs)} />
        )}
        <path className="line humidity" d={linePath(points, (p) => p.humidity_percent, at, yH, stepMs)} />
        <path className="line temperature" d={linePath(points, (p) => p.temperature_c, at, yT, stepMs)} />
        {ticks.map((ms) => (
          <text key={ms} className="axis" x={x(ms)} y={plotBottom + 16} textAnchor="middle">
            {timeLabel(ms, series.hours)}
          </text>
        ))}
        {hover && <line className="hover" x1={hoverX} x2={hoverX} y1={PAD.top} y2={plotBottom} />}
      </svg>
      {/* Mounted all the time; only its text and position change, so it never flickers. */}
      <div
        id={tipId}
        className={`weather-tip side-${side}`}
        style={{ left: `${hoverX}px`, visibility: hover ? "visible" : "hidden" }}
        role="status"
        aria-live="polite"
      >
        {hover && (
          <>
            <strong>
              {new Date(hover.at).toLocaleString([], {
                dateStyle: series.hours > 24 ? "medium" : undefined,
                timeStyle: "short",
              })}
            </strong>
            <span className="w-row">
              <i className="w-swatch temperature" aria-hidden="true" />
              <Icon name="thermometer" size={14} />
              <span className="rv-sr">Temperature </span>
              {reading(hover.temperature_c, "°C")}
            </span>
            <span className="w-row">
              <i className="w-swatch humidity" aria-hidden="true" />
              <Icon name="drop" size={14} />
              <span className="rv-sr">Humidity </span>
              {reading(hover.humidity_percent, "%")}
            </span>
            {showPressure && (
              <span className="w-row">
                <i className="w-swatch pressure" aria-hidden="true" />
                <Icon name="gauge" size={14} />
                <span className="rv-sr">Pressure </span>
                {reading(hover.pressure_hpa, "hPa")}
              </span>
            )}
            <span className="w-row">
              <i className="w-swatch rain" aria-hidden="true" />
              <Icon name="rain" size={14} />
              <span className="rv-sr">Rain plate </span>
              {rainWords(hover.wet)}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/** Environment history as a graph: 24 h, 7 days or 30 days. */
export default function WeatherGraph() {
  const [hours, setHours] = useState<number>(24);
  const [series, setSeries] = useState<Series | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = () =>
      api<Series>(`/sensors/series?hours=${hours}`)
        .then((value) => {
          if (active) {
            setSeries(value);
            setError("");
          }
        })
        .catch((reason) => active && setError(reason instanceof Error ? reason.message : String(reason)));
    void load();
    const timer = window.setInterval(load, 60000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [hours]);
  return (
    <div className="weather-graph">
      <div className="segmented" role="group" aria-label="Time range">
        {RANGES.map((range) => (
          <button
            key={range.hours}
            type="button"
            aria-pressed={hours === range.hours}
            className={hours === range.hours ? "active" : ""}
            onClick={() => setHours(range.hours)}
          >
            {range.label}
          </button>
        ))}
      </div>
      {error && <p role="alert">{error}</p>}
      {!series ? (
        <p className="sensor-history-empty" role="status">Loading the weather…</p>
      ) : series.points.length ? (
        <WeatherChart series={series} />
      ) : (
        <p className="sensor-history-empty" role="status">
          No weather readings in this period.
        </p>
      )}
    </div>
  );
}
