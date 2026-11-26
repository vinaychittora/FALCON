// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SessionRow, Summary } from "../api/summary";
import { hashQuery } from "../api/summary";
import { periodBounds, sessionState, SummaryView } from "./SummaryPage";

const summary: Summary = {
  totals: {
    visits: 12,
    records: 40,
    visual: 10,
    audio: 2,
    identified: 9,
    unresolved: 3,
    reviewed: 5,
    machine: 7,
    not_animal: 0,
  },
  species_count: 2,
  species: [
    {
      scientific_name: "Pavo cristatus",
      common_name: "Indian Peafowl",
      visits: 7,
      reviewed: 4,
      machine: 3,
      visual: 7,
      audio: 0,
      first_seen: "2026-10-18T06:00:10Z",
      last_seen: "2026-10-18T09:00:00Z",
    },
    {
      scientific_name: "Psittacula krameri",
      common_name: null,
      visits: 2,
      reviewed: 1,
      machine: 1,
      visual: 0,
      audio: 2,
      first_seen: null,
      last_seen: null,
    },
  ],
  groups: [
    { group: "Aves", visits: 2 },
    { group: "organism", visits: 1 },
  ],
  note: "A visit is not an animal count.",
};
const session: SessionRow = {
  session_id: "s1",
  source_id: "a".repeat(24),
  name: "Backyard camera",
  started_at: "2026-10-18T06:00:00Z",
  ended_at: "2026-10-18T08:00:00Z",
  status: "stopped",
  duration_ms: 7200000,
  visits: 12,
  records: 40,
  reviewed: 5,
  unresolved: 3,
  species_count: 2,
  species: [
    {
      scientific_name: "Pavo cristatus",
      common_name: "Indian Peafowl",
      visits: 7,
    },
  ],
  clips: 9,
  clock_synchronized: false,
  active: false,
};

describe("summary page", () => {
  it("shows totals, species rows and one row per session with export links", () => {
    const html = renderToStaticMarkup(
      <SummaryView
        summary={summary}
        sessions={[session]}
        onNavigate={() => {}}
      />,
    );
    expect(html).toContain("Animal visits");
    expect(html).toContain("Indian Peafowl");
    expect(html).toContain("Psittacula krameri");
    expect(html).toContain("2 birds · 1 unknown animals");
    expect(html).toContain("Backyard camera");
    expect(html).toContain("2 h 00 min");
    expect(html).toContain("Clock was not synchronized");
    expect(html).toContain(
      `/api/evidence/export?scope=live&amp;source_id=${"a".repeat(24)}`,
    );
    expect(html).toContain("Camtrap DP");
  });

  it("labels sessions and reads the session from the address", () => {
    expect(sessionState(session).label).toBe("Finished");
    expect(sessionState({ ...session, active: true }).label).toBe(
      "Observing now",
    );
    expect(sessionState({ ...session, ended_at: null }).label).toBe(
      "No end recorded",
    );
    expect(hashQuery("#/export?source=abc", "source")).toBe("abc");
    expect(hashQuery("#/export", "source")).toBe("");
    const now = new Date("2026-10-19T00:00:00Z");
    expect(periodBounds("24h", "", "", now).captured_from).toBe(
      "2026-10-18T00:00:00.000Z",
    );
    expect(periodBounds("all", "", "", now)).toEqual({
      captured_from: null,
      captured_to: null,
    });
  });
});
