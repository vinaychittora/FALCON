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
