import { describe, expect, it } from "vitest";
import { requestAppInstall } from "./install";

describe("browser app installation", () => {
  it.each(["accepted", "dismissed"] as const)(
    "handles %s without an error",
    async (outcome) => {
      expect(
        await requestAppInstall({
          prompt: async () => {},
          userChoice: Promise.resolve({ outcome }),
        }),
      ).toBe(outcome);
    },
  );

  it("handles a rejected or expired browser prompt", async () => {
    expect(
      await requestAppInstall({
        prompt: async () => {
          throw new Error("expired");
        },
        userChoice: Promise.resolve({ outcome: "dismissed" }),
      }),
    ).toBe("failed");
  });

  it("handles a rejected installation-choice promise", async () => {
    expect(
      await requestAppInstall({
        prompt: async () => {},
        userChoice: Promise.reject(new Error("blocked")),
      }),
    ).toBe("failed");
  });
});
