// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { slowedByHeat, thermalNotice, type ThermalState } from "./nodes";
import { heatSummary } from "../ui/NodePower";

const normal: ThermalState = {
  enabled: true,
  state: "normal",
  temperature_c: 71,
  pause_c: 84,
  stop_c: 84,
  resume_c: 75,
  since: null,
  events: 0,
};

describe("node heat in FALCON", () => {
  it("says plainly when the node paused itself and when it resumes", () => {
    expect(thermalNotice(normal)).toBeNull();
    expect(
      thermalNotice({
        ...normal,
        state: "stream stopped",
        temperature_c: 84.6,
      }),
    ).toBe("Paused: node too hot (85 °C), resumes below 75 °C");
    expect(
      thermalNotice(
        { ...normal, state: "camera paused", temperature_c: null },
        83,
      ),
    ).toBe("Camera paused: node too hot (83 °C), resumes below 75 °C");
    expect(thermalNotice(undefined)).toBeNull(); // nodes installed before heat protection
  });

  it("shows the firmware slowing down as information, not a pause", () => {
    expect(slowedByHeat({ soft_temp_limit_now: true } as never)).toBe(true);
    expect(slowedByHeat({ throttled_now: true } as never)).toBe(true);
    expect(slowedByHeat(null)).toBe(false);
    const data = {
      extras: [],
      thermal: normal,
      cpu_temperature_c: 81.2,
      power: { soft_temp_limit_now: true },
    };
    expect(heatSummary(data as never)).toBe(
      "81 °C · slowed by heat (the processor protects itself)",
    );
    expect(heatSummary({ ...data, power: null } as never)).toBe(
      "81 °C · stream pauses at 84 °C, resumes below 75 °C",
    );
  });
});
