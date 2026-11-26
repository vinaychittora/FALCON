// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { rodentNights } from "./rodentNights";

describe("rats and mice at night on System", () => {
  it("names the two most recent nights by their evening", () => {
    expect(rodentNights("2026-11-22:220,2026-11-21:124")).toBe(
      "Not kept · 220 on the night of 22 Nov, 124 on 21 Nov",
    );
  });
  it("one night, and none", () => {
    expect(rodentNights("2026-11-23:12")).toBe("Not kept · 12 on the night of 23 Nov");
    expect(rodentNights("")).toBe("Not kept · none so far");
    expect(rodentNights(undefined)).toBe("Not kept · none so far");
  });
});
