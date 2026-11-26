// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { groupName } from "../api/taxa";
import { rankTaxa } from "../api/search";
import Icon from "../components/Icon";
import "../components/review.css";
export interface Taxon {
  taxon_id: number;
  scientific_name: string;
  common_name: string | null;
  group: string;
  observation_count: number;
}
export interface TaxaCache {
  taxa: Taxon[];
  place_name?: string;
  counts: Record<string, number>;
  refreshed_at: string | null;
  refreshing: boolean;
  error: string | null;
  version: string;
  limits: Record<string, number | null>;
  minimum_observations: number;
  coverage?: Record<
    string,
    {
      eligible_species: number;
      selected_species: number;
      omitted_by_limit: number;
      truncated: boolean;
      scan_complete: boolean;
    }
  >;
  warnings?: string[];
  coverage_basis?: string;
}
export default function Taxa() {
  const [data, setData] = useState<TaxaCache | null>(null),
    [search, setSearch] = useState(""),
    [group, setGroup] = useState(""),
    [error, setError] = useState("");
  const load = () =>
    api<TaxaCache>("/taxa")
      .then((value) => {
        setData(value);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, []);
  const refresh = async () => {
    try {
      await api("/taxa/refresh", {
        method: "POST",
        body: JSON.stringify({
          limits: data?.limits,
          minimum_observations: data?.minimum_observations,
        }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const rows = rankTaxa(
    data?.taxa.filter((t) => !group || group === t.group) ?? [],
    search,
  );
  return (
    <section className="panel taxa">
      <div className="panel-heading">
        <div>
          <h3>
            Local taxonomy{" "}
            <span>{data?.taxa.length.toLocaleString() ?? 0}</span>
          </h3>
          <p className="muted">
            Refreshed{" "}
            {data?.refreshed_at
              ? new Date(data.refreshed_at).toLocaleString()
              : "never"}{" "}
            · {data?.place_name ?? "Local"} records from iNaturalist
          </p>
        </div>
        <button disabled={data?.refreshing} onClick={() => void refresh()}>
          <Icon name="refresh" size={15} />
          {data?.refreshing ? "Refreshing…" : "Refresh taxa"}
        </button>
      </div>
      <div
        className="taxa-groups"
        role="group"
        aria-label="Filter by species group"
      >
        <button
          className={!group ? "active" : ""}
          aria-pressed={!group}
          onClick={() => setGroup("")}
        >
          All species <span>{data?.taxa.length ?? 0}</span>
        </button>
        {Object.entries(data?.counts ?? {}).map(([groupKey, n]) => (
          <button
            key={groupKey}
            className={group === groupKey ? "active" : ""}
            aria-pressed={group === groupKey}
            onClick={() => setGroup(groupKey)}
          >
            {groupName(groupKey)} <span>{n}</span>
          </button>
        ))}
      </div>
      {(error || data?.error) && (
        <p className="error">{error || data?.error}</p>
      )}
      <div className="toolbar">
        <input
          aria-label="Search taxa"
          type="search"
          placeholder="Search common or scientific name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="muted">
          {rows.length.toLocaleString()} matches
          {group ? " · " + groupName(group) : ""}
        </span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Common name</th>
              <th>Scientific name</th>
              <th>Group</th>
              <th>iNaturalist records</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.taxon_id}>
                <td>{t.common_name ?? "—"}</td>
                <td>
                  <em>{t.scientific_name}</em>
                </td>
                <td>{groupName(t.group)}</td>
                <td>{t.observation_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && (
        <p className="taxonomy-empty">
          No species match this search and group.
        </p>
      )}
      <details className="taxa-coverage">
        <summary>Taxonomy provenance and coverage</summary>
        <p>
          {data?.coverage_basis ??
            "Local research-grade photo observations; active species only"}
          . This is a candidate list, not a complete biodiversity inventory. A
          species being listed does not mean the models will always detect or
          identify it.
        </p>
        {data?.warnings?.map((warning, index) => (
          <p className="error" key={index}>
            {warning}
          </p>
        ))}
        <div className="coverage-groups">
          {Object.entries(data?.coverage ?? {}).map(([name, coverage]) => (
            <div key={name}>
              <strong>{groupName(name)}</strong>
              <span>
                {coverage.selected_species} included
                {coverage.omitted_by_limit
                  ? ` · ${coverage.omitted_by_limit} omitted by limit`
                  : ""}
                {!coverage.scan_complete || coverage.truncated
                  ? " · partial coverage"
                  : ""}
              </span>
            </div>
          ))}
        </div>
        <p>
          Refreshing changes the names available to future analyses. Analyze a
          recording again to use the updated list.
        </p>
      </details>
    </section>
  );
}
