// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { wetness } from "./environment";

describe("rain plate display", () => {
  it("shows a wetness state, and a dash when no plate reading exists", () => {
    expect(wetness(true)).toBe("Wet");
    expect(wetness(false)).toBe("Dry");
    expect(wetness(null)).toBe("—");
    expect(wetness(undefined)).toBe("—");
  });
});
