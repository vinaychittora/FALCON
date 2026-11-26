// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import {
  camtrapDownloadUrl,
  fetchExportPreview,
  LICENSES,
  missingForCamtrap,
  presetWindow,
  REVIEW_SCOPES,
  type ExportForm,
} from "../api/exports";
import {
  formatBytes,
  formatDateTime,
  fromLocalInput,
  toLocalInput,
} from "../api/format";
import Icon from "../components/Icon";
import { hashQuery } from "../api/summary";
import { usePoll } from "../hooks/usePoll";
import type { Config } from "../types";
import Pill from "../ui/Pill";

const STORAGE_KEY = "falcon.export-details.v1";
type Preset = "24h" | "7d" | "30d" | "all" | "custom";

function savedDetails(): Partial<ExportForm> {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

const INITIAL: ExportForm = {
  captured_from: null,
  captured_to: null,
  source_id: "",
  visual: true,
  audio: true,
  review: "verified",
  min_score: "",
  include_media: true,
  include_environment: true,
  title: "FALCON wildlife observations",
  project_title: "FALCON field monitoring",
  contact_name: "",
  contact_email: "",
  license: "",
  latitude: "",
  longitude: "",
  coordinate_uncertainty_m: "",
  location_name: "",
};

export default function ExportPage() {
  // "#/export?source=…" preselects one session (from the Summary page) over all time.
  const requested =
    typeof window === "undefined"
      ? ""
      : hashQuery(window.location.hash, "source");
  const [form, setForm] = useState<ExportForm>(() => ({
    ...INITIAL,
    ...savedDetails(),
    ...presetWindow(requested ? "all" : "7d"),
    ...(requested ? { source_id: requested } : {}),
  }));
  const [preset, setPreset] = useState<Preset>(requested ? "all" : "7d");
  const [from, setFrom] = useState(() =>
    toLocalInput(new Date(Date.now() - 7 * 86400_000)),
  );
  const [to, setTo] = useState(() => toLocalInput(new Date()));
  const [started, setStarted] = useState(false);
  const sources = usePoll(
    () =>
      api<{
        sources: {
          source_id: string;
          source_filename: string;
          count: number;
          started_at: string | null;
          latest_at: string | null;
        }[];
      }>("/detections/sources?scope=live"),
    0,
  );
  useEffect(() => {
    // Prefill the site location from the analysis settings once.
    let alive = true;
    api<Config>("/config")
      .then((config) => {
        if (!alive || config.site_lat === null || config.site_lon === null)
          return;
        setForm((current) =>
          current.latitude || current.longitude
            ? current
            : {
                ...current,
                latitude: String(config.site_lat),
                longitude: String(config.site_lon),
              },
        );
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    const details = {
      title: form.title,
      project_title: form.project_title,
      contact_name: form.contact_name,
      contact_email: form.contact_email,
      license: form.license,
      latitude: form.latitude,
      longitude: form.longitude,
      coordinate_uncertainty_m: form.coordinate_uncertainty_m,
      location_name: form.location_name,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(details));
    } catch {
      // Private windows may refuse storage; the form still works.
    }
  }, [
    form.title,
    form.project_title,
    form.contact_name,
    form.contact_email,
    form.license,
    form.latitude,
    form.longitude,
    form.coordinate_uncertainty_m,
    form.location_name,
  ]);
  const previewKey = JSON.stringify([
    form.captured_from,
    form.captured_to,
    form.source_id,
    form.visual,
    form.audio,
    form.review,
    form.min_score,
    form.include_media,
    form.include_environment,
    form.latitude,
    form.longitude,
  ]);
  const preview = usePoll(() => fetchExportPreview(form), 0, previewKey);
  const missing = missingForCamtrap(form);
  const set = <K extends keyof ExportForm>(key: K, value: ExportForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  function choosePreset(next: Preset) {
    setPreset(next);
    if (next === "custom")
      setForm((current) => ({
        ...current,
        captured_from: fromLocalInput(from),
        captured_to: fromLocalInput(to),
      }));
    else setForm((current) => ({ ...current, ...presetWindow(next) }));
  }

  const data = preview.data;
  return (
    <div className="page export-page">
      <header className="page-header">
        <div>
          <p>
            A clean dataset for researchers: choose a time window and which
            identifications to include. The download is a Camera Trap Data
            Package (Camtrap DP 1.0), the TDWG standard read by GBIF, Agouti,
            Wildlife Insights and R (camtrapdp).
          </p>
        </div>
      </header>
      <div className="export-grid">
        <form
          className="card export-form"
          onSubmit={(event) => {
            event.preventDefault();
          }}
        >
          <fieldset>
            <legend>1 · Time window</legend>
            <div
              className="segmented wrap"
              role="group"
              aria-label="Time window"
            >
              {(["24h", "7d", "30d", "all", "custom"] as Preset[]).map(
                (value) => (
                  <button
                    type="button"
                    key={value}
                    aria-pressed={preset === value}
                    onClick={() => choosePreset(value)}
                  >
                    {
                      {
                        "24h": "Last 24 h",
                        "7d": "Last 7 days",
                        "30d": "Last 30 days",
                        all: "Everything",
                        custom: "Custom",
                      }[value]
                    }
                  </button>
                ),
              )}
            </div>
            {preset === "custom" && (
              <div className="form-grid">
                <div className="form-field">
                  <label htmlFor="export-from">From</label>
                  <input
                    id="export-from"
                    type="datetime-local"
                    value={from}
                    onChange={(event) => {
                      setFrom(event.target.value);
                      set("captured_from", fromLocalInput(event.target.value));
                    }}
                  />
                </div>
                <div className="form-field">
                  <label htmlFor="export-to">To</label>
                  <input
                    id="export-to"
                    type="datetime-local"
                    value={to}
                    onChange={(event) => {
                      setTo(event.target.value);
                      set("captured_to", fromLocalInput(event.target.value));
                    }}
                  />
                </div>
              </div>
            )}
            <div className="form-field">
              <label htmlFor="export-source">Sessions</label>
              <select
                id="export-source"
                value={form.source_id}
                onChange={(event) => set("source_id", event.target.value)}
              >
                <option value="">All field sessions</option>
                {(sources.data?.sources ?? []).map((row) => (
                  <option key={row.source_id} value={row.source_id}>
                    {row.source_filename} ·{" "}
                    {formatDateTime(row.started_at ?? row.latest_at, false)} ·{" "}
                    {row.count} records
                  </option>
                ))}
              </select>
            </div>
          </fieldset>
          <fieldset>
            <legend>2 · What to include</legend>
            <div className="choice-list">
              {REVIEW_SCOPES.map((scope) => (
                <label
                  key={scope.value}
                  className={`choice${form.review === scope.value ? " selected" : ""}`}
                >
                  <input
                    type="radio"
                    name="review-scope"
                    checked={form.review === scope.value}
                    onChange={() => set("review", scope.value)}
                  />
                  <span>
                    <strong>{scope.label}</strong>
                    <small>{scope.detail}</small>
                  </span>
                </label>
              ))}
            </div>
            <div className="toggle-row">
              <label className="switch-row">
                <input
                  type="checkbox"
                  role="switch"
                  checked={form.visual}
                  onChange={(event) => set("visual", event.target.checked)}
                />
                <span>Video detections</span>
              </label>
              <label className="switch-row">
                <input
                  type="checkbox"
                  role="switch"
                  checked={form.audio}
                  onChange={(event) => set("audio", event.target.checked)}
                />
                <span>Sound detections</span>
              </label>
              <label className="switch-row">
                <input
                  type="checkbox"
                  role="switch"
                  checked={form.include_media}
                  onChange={(event) =>
                    set("include_media", event.target.checked)
                  }
                />
                <span>Include clip files</span>
              </label>
              <label className="switch-row">
                <input
                  type="checkbox"
                  role="switch"
                  checked={form.include_environment}
                  onChange={(event) =>
                    set("include_environment", event.target.checked)
                  }
                />
                <span>Include weather readings</span>
              </label>
            </div>
            <div className="form-field narrow">
              <label htmlFor="export-score">
                Minimum model score for unreviewed records
              </label>
              <input
                id="export-score"
                type="number"
                min={0}
                max={1}
                step={0.05}
                placeholder="any"
                value={form.min_score}
                onChange={(event) => set("min_score", event.target.value)}
              />
              <small>Reviewed records are always kept.</small>
            </div>
          </fieldset>
          <fieldset>
            <legend>3 · Dataset details</legend>
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="export-lat">Site latitude</label>
                <input
                  id="export-lat"
                  inputMode="decimal"
                  value={form.latitude}
                  placeholder="decimal degrees, e.g. 26.91"
                  onChange={(event) => set("latitude", event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-lon">Site longitude</label>
                <input
                  id="export-lon"
                  inputMode="decimal"
                  value={form.longitude}
                  placeholder="decimal degrees, e.g. 75.79"
                  onChange={(event) => set("longitude", event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-uncertainty">
                  Location uncertainty (m)
                </label>
                <input
                  id="export-uncertainty"
                  inputMode="numeric"
                  value={form.coordinate_uncertainty_m}
                  placeholder="optional"
                  onChange={(event) =>
                    set("coordinate_uncertainty_m", event.target.value)
                  }
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-location">Location name</label>
                <input
                  id="export-location"
                  value={form.location_name}
                  placeholder="optional, e.g. Backyard pond"
                  onChange={(event) => set("location_name", event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-contact">Contact name</label>
                <input
                  id="export-contact"
                  value={form.contact_name}
                  placeholder="Person responsible for the data"
                  onChange={(event) => set("contact_name", event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-email">Contact email</label>
                <input
                  id="export-email"
                  type="email"
                  value={form.contact_email}
                  placeholder="optional"
                  onChange={(event) => set("contact_email", event.target.value)}
                />
              </div>
              <div className="form-field wide">
                <label htmlFor="export-title">Dataset title</label>
                <input
                  id="export-title"
                  value={form.title}
                  onChange={(event) => set("title", event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-project">Project</label>
                <input
                  id="export-project"
                  value={form.project_title}
                  onChange={(event) => set("project_title", event.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="export-license">License</label>
                <select
                  id="export-license"
                  value={form.license}
                  onChange={(event) =>
                    set("license", event.target.value as ExportForm["license"])
                  }
                >
                  {LICENSES.map((license) => (
                    <option key={license.value} value={license.value}>
                      {license.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </fieldset>
        </form>
        <aside className="card export-summary" aria-live="polite">
          <h2>This export</h2>
          {data ? (
            <>
              <dl className="summary-numbers">
                <div>
                  <dt>Animal visits</dt>
                  <dd>
                    {data.observations.toLocaleString()}
                    <small>
                      {data.records.toLocaleString()} analyzed frames and sound
                      windows
                    </small>
                  </dd>
                </div>
                <div>
                  <dt>Species</dt>
                  <dd>{data.species.length}</dd>
                </div>
                <div>
                  <dt>Sessions</dt>
                  <dd>{data.deployments}</dd>
                </div>
                <div>
                  <dt>Clips</dt>
                  <dd>
                    {data.media}
                    <small>
                      {form.include_media
                        ? formatBytes(data.media_bytes)
                        : "not included"}
                    </small>
                  </dd>
                </div>
                <div>
                  <dt>Weather readings</dt>
                  <dd>
                    {form.include_environment
                      ? data.environment_readings.toLocaleString()
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Identified by</dt>
                  <dd className="small">
                    {data.classification.human ?? 0} reviewer ·{" "}
                    {data.classification.machine ?? 0} model
                  </dd>
                </div>
              </dl>
              {!!data.species.length && (
                <div className="species-table">
                  <h3>Species</h3>
                  <ul>
                    {data.species.slice(0, 12).map((item) => (
                      <li key={item.scientific_name}>
                        <span>
                          {item.common_name ?? item.scientific_name}
                          {item.common_name && <em>{item.scientific_name}</em>}
                        </span>
                        <strong>{item.count}</strong>
                      </li>
                    ))}
                  </ul>
                  {data.species.length > 12 && (
                    <small className="muted">
                      and {data.species.length - 12} more
                    </small>
                  )}
                </div>
              )}
              {data.warnings
                .filter((warning) => !warning.startsWith("Site latitude"))
                .map((warning) => (
                  <p className="banner banner-warn" key={warning}>
                    {warning}
                  </p>
                ))}
            </>
          ) : (
            <p className="muted">{preview.error || "Counting…"}</p>
          )}
          {missing.length ? (
            <p className="banner banner-warn">
              Still needed: {missing.join(", ")}.
            </p>
          ) : (
            <Pill tone="good">Ready to export</Pill>
          )}
          <a
            className={`button primary large${missing.length || !data?.observations ? " disabled" : ""}`}
            href={
              missing.length || !data?.observations
                ? undefined
                : camtrapDownloadUrl(form)
            }
            aria-disabled={!!missing.length || !data?.observations}
            onClick={() => setStarted(true)}
            download
          >
            <Icon name="download" size={17} /> Download Camtrap DP (.zip)
          </a>
          {started && (
            <p className="muted">
              The download starts when the package is ready; large clip sets
              take a moment.
            </p>
          )}
          <details className="export-explain">
            <summary>What is inside</summary>
            <ul>
              <li>
                <code>datapackage.json</code>: project, contact, location,
                dates, species list
              </li>
              <li>
                <code>deployments.csv</code>: each live session (camera or
                node), start and end
              </li>
              <li>
                <code>media.csv</code> + <code>media/</code>: 5-second video and
                sound clips
              </li>
              <li>
                <code>observations.csv</code>: one row per animal visit, with
                who identified it
              </li>
              <li>
                <code>falcon_observations.csv</code>: boxes, model scores,
                review and weather at detection
              </li>
              <li>
                <code>environment.csv</code>: temperature, humidity, pressure
                and rain-plate readings
              </li>
            </ul>
          </details>
          <a
            className="text-button"
            href="/api/evidence/export?scope=live"
            download
          >
            Complete FALCON archive (all records and review history, for backup)
          </a>
        </aside>
      </div>
    </div>
  );
}
