import { describe, expect, it } from "vitest";
import { micGainDb, sensorHref, sensorRoute } from "./SensorSettings";

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

  it("shows the microphone gain in decibels like the audio HAT applies it", () => {
    expect(micGainDb(0)).toBe(-4.5);
    expect(micGainDb(67)).toBe(10.5); // the setting chosen for the enclosure
    expect(micGainDb(100)).toBe(18);
  });
});
