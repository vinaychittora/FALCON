// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { showRecordsLabel, waitingLine } from "./reviewList";

describe("Review footer on the phone (25 Nov)", () => {
  it("says how many records the filters found", () => {
    expect(showRecordsLabel(1)).toBe("Show 1 record");
    expect(showRecordsLabel(2)).toBe("Show 2 records");
    expect(showRecordsLabel(1234)).toBe(`Show ${(1234).toLocaleString()} records`);
  });

  it("puts the count first when nothing waits, so it never reads as an empty result", () => {
    expect(waitingLine(2)).toBe("2 records in this list, none waiting for a review.");
    expect(waitingLine(1)).toBe("1 record in this list, not waiting for a review.");
    expect(waitingLine(0)).toBe("No encounters match.");
  });
});
