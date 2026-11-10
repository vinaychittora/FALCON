import { describe, expect, it } from "vitest";
import {
  micGainDb,
  rainDetail,
  sensorHref,
  sensorRoute,
} from "./SensorSettings";

describe("a settings page for each sensor", () => {
  it("routes each sensor of a node to its own page", () => {
    expect(sensorRoute("#/sensors/falcon-node/microphone")).toEqual({
      nodeId: "falcon-node",
      section: "microphone",
    });
    expect(sensorRoute("#/sensors/falcon-node/power")?.section).toBe("power");
    expect(sensorRoute("#/sensors")).toBeNull();
    expect(sensorRoute("#/sensors/falcon-node/unknown")).toBeNull();
    expect(sensorHref("node 1", "rain")).toBe("#/sensors/node%201/rain");
    expect(sensorRoute(sensorHref("node 1", "rain"))?.nodeId).toBe("node 1");
  });

  it("describes recent rain from the node's twice-a-second watch", () => {
    expect(rainDetail({})).toBe("Not wet since the node started");
    const text = rainDetail({
      raining: true,
      last_wet: "2026-11-10T08:15:00Z",
      wet_pulses_last_hour: 3,
    });
    expect(text).toMatch(
      /^Raining · last wet .+ · 3 wet moments in the last hour$/,
    );
  });

  it("shows the microphone gain in decibels like the audio HAT applies it", () => {
    expect(micGainDb(0)).toBe(-4.5);
    expect(micGainDb(67)).toBe(10.5); // the setting chosen for the enclosure
    expect(micGainDb(100)).toBe(18);
  });
});
