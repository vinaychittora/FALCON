import { describe, expect, it } from "vitest";
import type { Encounter } from "../api/encounters";
import { rings } from "./DetectionBell";

function picture(certainty: string, review = "unreviewed"): Encounter {
  return {
    encounter_id: certainty,
    modality: "visual",
    records: 3,
    review_status: review,
    event: {
      modality: "visual",
      classification: {
        status: certainty === "likely" ? "candidate" : "unknown",
        certainty,
      },
      review: { status: review },
    },
  } as unknown as Encounter;
}

describe("the bell rings for Likely and Confirmed visits only", () => {
  it("never rings for unrecognised pictures shown by Show unresolved", () => {
    expect(rings(picture("unknown"))).toBe(false);
    expect(rings(picture("probable"))).toBe(false);
    expect(rings(picture("likely"))).toBe(true);
    expect(rings(picture("unknown", "correct"))).toBe(true);
  });
});
