import { useEffect, useState } from "react";
import { api } from "../api/client";
import { wetness } from "../api/environment";
import { captureTime } from "../api/observations";
import Icon from "./Icon";
import "./sensor-history.css";

export interface Reading {
  reading_id: string;
  sensor_id: string;
  observed_at: string;
  received_at: string;
  temperature_c: number | null;
  humidity_percent: number | null;
  pressure_hpa: number | null;
  surface_wet?: boolean | null;
  quality: "valid" | "suspect" | "invalid";
  quality_note: string | null;
}
interface History {
  readings: Reading[];
  total: number;
}
const LIMIT = 25;
const measurement = (value: number | null) =>
  value === null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function SensorHistory() {
  const [snapshot, setSnapshot] = useState<{
    offset: number | null;
    history: History;
    error: string;
  }>({ offset: null, history: { readings: [], total: 0 }, error: "" });
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const abort = new AbortController();
    const load = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await api<History>(
          `/sensors/history?limit=${LIMIT}&offset=${offset}`,
          { signal: abort.signal },
        );
        if (active) setSnapshot({ offset, history: result, error: "" });
      } catch (err) {
        if (active)
          setSnapshot((previous) => ({
            offset,
            history:
              previous.offset === offset
                ? previous.history
                : { readings: [], total: 0 },
            error:
              err instanceof Error ? err.message : "Sensor history unavailable",
          }));
      } finally {
        inFlight = false;
      }
    };
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 15000);
    return () => {
      active = false;
      abort.abort();
      window.clearInterval(timer);
    };
  }, [offset, refresh]);
  const loading = snapshot.offset !== offset;
  return (
    <SensorHistoryView
      history={
        loading
          ? { readings: [], total: snapshot.history.total }
          : snapshot.history
      }
      offset={offset}
      loading={loading}
      error={loading ? "" : snapshot.error}
      onRefresh={() => setRefresh((value) => value + 1)}
      onPage={setOffset}
    />
  );
}

export function SensorHistoryView({
  history,
  offset,
  loading,
  error,
  onRefresh,
  onPage,
}: {
  history: History;
  offset: number;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onPage: (offset: number) => void;
}) {
  return (
    <section
      className="sensor-history"
      aria-labelledby="sensor-history-heading"
    >
      <header>
        <div>
          <h2 id="sensor-history-heading">
            <Icon name="activity" /> Environmental history
          </h2>
          <p>
            Periodic measurements, including intervals without wildlife
            detections.
          </p>
        </div>
        <button
          className="quiet"
          aria-label="Refresh environmental history"
          disabled={loading}
          onClick={onRefresh}
        >
          <Icon name="refresh" />
        </button>
      </header>
      {error && <p role="alert">{error}</p>}
      {loading || !history.readings.length ? (
        <p className="sensor-history-empty" role="status">
          {loading
            ? "Loading sensor history…"
            : error
              ? "Sensor readings could not be loaded. Use Refresh to retry."
              : history.total
                ? "No readings on this page. Return to the previous page."
                : "No sensor readings recorded. Measurements will appear when a sensor node is connected."}
        </p>
      ) : (
        <>
          <div className="sensor-history-scroll">
            <table>
              <thead>
                <tr>
                  <th>Measured at</th>
                  <th>Sensor</th>
                  <th>
                    <Icon name="sun" size={15} /> Temperature · °C
                  </th>
                  <th>
                    <Icon name="drop" size={15} /> Humidity · %
                  </th>
                  <th>
                    <Icon name="wind" size={15} /> Pressure · hPa
                  </th>
                  <th title="Rain or dew on the plate; not a rainfall amount">
                    <Icon name="rain" size={15} /> Rain plate
                  </th>
                  <th>Quality</th>
                </tr>
              </thead>
              <tbody>
                {history.readings.map((reading) => {
                  const time = captureTime(reading.observed_at);
                  return (
                    <tr key={`${reading.sensor_id}:${reading.reading_id}`}>
                      <td title={time?.utc}>
                        {time ? (
                          <time dateTime={time.utc}>
                            {time.date}
                            <small>{time.time}</small>
                          </time>
                        ) : (
                          "Measurement time unavailable"
                        )}
                      </td>
                      <td>{reading.sensor_id}</td>
                      <td>{measurement(reading.temperature_c)}</td>
                      <td>{measurement(reading.humidity_percent)}</td>
                      <td>{measurement(reading.pressure_hpa)}</td>
                      <td>{wetness(reading.surface_wet)}</td>
                      <td title={reading.quality_note ?? undefined}>
                        {reading.quality}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {(history.total > 0 || offset > 0) && (
        <footer>
          <span>
            {loading
              ? "Loading page…"
              : history.readings.length
                ? `${offset + 1}–${Math.min(offset + history.readings.length, history.total)} of ${history.total.toLocaleString()} readings`
                : "No readings shown"}
          </span>
          <div>
            <button
              className="quiet"
              disabled={loading || !offset}
              onClick={() => onPage(Math.max(0, offset - LIMIT))}
            >
              Previous
            </button>
            <button
              className="quiet"
              disabled={loading || offset + LIMIT >= history.total}
              onClick={() => onPage(offset + LIMIT)}
            >
              Next
            </button>
          </div>
        </footer>
      )}
    </section>
  );
}
