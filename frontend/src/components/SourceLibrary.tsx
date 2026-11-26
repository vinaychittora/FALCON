// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useMemo, useState } from "react";
import { rankSearch } from "../api/search";
import { formatTime } from "../api/timeline";
import type { Video } from "../types";
import Icon from "./Icon";

export default function SourceLibrary({
  videos,
  selected,
  onSelect,
  onRefresh,
}: {
  videos: Video[];
  selected: string;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const matches = useMemo(
    () => rankSearch(videos, query, (item) => [item.filename]),
    [videos, query],
  );
  return (
    <section className="source-library" aria-label="Local media library">
      <div className="library-selector">
        <label htmlFor="media-source">Media source</label>
        <select
          id="media-source"
          aria-label="Media source"
          value={selected}
          onChange={(event) => onSelect(event.target.value)}
        >
          {videos.map((item) => (
            <option key={item.source_id} value={item.source_id}>
              {item.filename}
            </option>
          ))}
        </select>
        <button
          className="text-button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-controls="library-browser"
        >
          {expanded ? "Close library" : "Browse library"}
        </button>
        <button
          className="icon-button"
          onClick={onRefresh}
          aria-label="Rescan local library"
          title="Rescan local library"
        >
          <Icon name="refresh" size={17} />
        </button>
      </div>
      {expanded && (
        <div id="library-browser" className="library-browser">
          <div className="library-search">
            <input
              aria-label="Search media sources"
              type="search"
              placeholder="Search filenames…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <span>
              {matches.length} {matches.length === 1 ? "source" : "sources"}
            </span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Type</th>
                  <th>Duration</th>
                  <th>Size</th>
                  <th aria-label="Source action" />
                </tr>
              </thead>
              <tbody>
                {matches.map((item) => (
                  <tr
                    key={item.source_id}
                    className={
                      item.source_id === selected ? "selected-source" : ""
                    }
                  >
                    <td>
                      <button
                        className="source-name-button"
                        onClick={() => {
                          onSelect(item.source_id);
                          setExpanded(false);
                        }}
                      >
                        {item.filename}
                      </button>
                    </td>
                    <td>{item.media_kind}</td>
                    <td>
                      {item.duration_ms ? formatTime(item.duration_ms) : "—"}
                    </td>
                    <td>{(item.size_bytes / 1024 / 1024).toFixed(1)} MB</td>
                    <td>
                      {item.source_id === selected ? (
                        <span className="tag">Selected</span>
                      ) : (
                        <button
                          className="text-button"
                          onClick={() => {
                            onSelect(item.source_id);
                            setExpanded(false);
                          }}
                        >
                          Open <Icon name="arrow" size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!matches.length && (
              <p className="empty-text">No matching media sources.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
