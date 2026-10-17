import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EnvironmentReading } from "../types";
import Icon from "./Icon";

export default function ClimatePanel() {
  const [reading, setReading] = useState<EnvironmentReading | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const load = () =>
      api<EnvironmentReading>("/sensors/current")
        .then((x) => {
          if (live) {
            setReading(x);
            setError("");
          }
        })
        .catch(() => {
          if (live) setError("Sensor status unavailable");
        });
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  return (
    <section className="climate-panel" aria-label="Climate sensors">
      <div className="climate-heading">
        <div>
          <Icon name="sun" size={18} />
          <h3>Environment</h3>
        </div>
        <p>
          {error ||
            (reading?.status === "not_connected"
              ? "Not connected"
              : (reading?.status ?? "Checking…"))}
        </p>
      </div>
      <dl className="climate-readings">
        <div>
          <Icon name="sun" />
          <dt>Temperature</dt>
          <dd>
            {reading?.temperature_c ?? "—"} <small>°C</small>
          </dd>
        </div>
        <div>
          <Icon name="drop" />
          <dt>Humidity</dt>
          <dd>
            {reading?.humidity_percent ?? "—"} <small>%</small>
          </dd>
        </div>
        <div>
          <Icon name="wind" />
          <dt>Pressure</dt>
          <dd>
            {reading?.pressure_hpa ?? "—"} <small>hPa</small>
          </dd>
        </div>
      </dl>
      <p className="climate-info">No sensor readings are simulated.</p>
    </section>
  );
}
