// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { clockAt } from "./FramePicker";

describe("frame picker", () => {
  it("names moments of the recording as minutes and seconds", () => {
    expect(clockAt(90.17)).toBe("1:30");
    expect(clockAt(106.6)).toBe("1:46");
    expect(clockAt(5)).toBe("0:05");
  });
});
