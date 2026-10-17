import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SensorHistoryView, type Reading } from "./SensorHistory";

const reading: Reading = {
  reading_id: "one",
  sensor_id: "field-node",
  observed_at: "2026-10-17T08:30:13Z",
  received_at: "2026-10-17T08:30:14Z",
  temperature_c: 31.123456,
  humidity_percent: 0,
  pressure_hpa: null,
  quality: "suspect",
  quality_note: "Sensor clock differs from server",
};
function render({
  loading = false,
  error = "",
  rows = [] as Reading[],
  offset = 0,
  total = rows.length,
}: {
  loading?: boolean;
  error?: string;
  rows?: Reading[];
  offset?: number;
  total?: number;
} = {}) {
  return renderToStaticMarkup(
    <SensorHistoryView
      history={{ readings: rows, total }}
      offset={offset}
      loading={loading}
      error={error}
      onRefresh={() => {}}
      onPage={() => {}}
    />,
  );
}
describe("environmental history", () => {
  it("shows measured time, zero readings, missing values and precision capped at two decimals", () => {
    const html = render({ rows: [reading] });
    expect(html).toContain('dateTime="2026-10-17T08:30:13.000Z"');
    expect(html).toContain("31.12");
    expect(html).not.toContain("31.123456");
    expect(html).toContain("<td>0</td>");
    expect(html).toContain("<td>—</td>");
    expect(html).toContain('title="Sensor clock differs from server">suspect');
  });
  it("does not describe a failed request as an empty sensor database", () => {
    const html = render({ error: "Connection unavailable" });
    expect(html).toContain('role="alert">Connection unavailable');
    expect(html).toContain("Use Refresh to retry");
    expect(html).not.toContain("No sensor readings recorded");
  });
  it("hides the prior page while loading and disables further paging", () => {
    const html = render({
      loading: true,
      rows: [reading],
      offset: 25,
      total: 100,
    });
    expect(html).toContain("Loading sensor history");
    expect(html).toContain("Loading page");
    expect(html).not.toContain("field-node");
    expect(html).not.toContain("26–");
    expect(html).toContain('disabled="">Next');
  });
  it("retains the current page on a refresh error and never invents unknown measurement times", () => {
    const html = render({
      rows: [{ ...reading, observed_at: "2026-10-17T08:30:13" }],
      error: "Refresh unavailable",
    });
    expect(html).toContain("field-node");
    expect(html).toContain("Measurement time unavailable");
    expect(html).not.toContain("<time");
  });
});
