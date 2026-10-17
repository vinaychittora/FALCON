import { describe, expect, it, vi } from "vitest";
import { initialResourceLoader } from "./initialLoad";

describe("initial backend recovery", () => {
  it("retries a failed library read without replacing successfully loaded settings", async () => {
    const config = vi.fn().mockResolvedValue(true);
    const library = vi
      .fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValue(true);
    const retry = initialResourceLoader([config, library]);
    await retry();
    await retry();
    await retry();
    expect(config).toHaveBeenCalledTimes(1);
    expect(library).toHaveBeenCalledTimes(2);
  });

  it("recovers rejected reads while preserving independent successful responses", async () => {
    const config = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(true);
    const library = vi.fn().mockResolvedValue(true);
    const retry = initialResourceLoader([config, library]);
    await retry();
    await retry();
    expect(config).toHaveBeenCalledTimes(2);
    expect(library).toHaveBeenCalledTimes(1);
  });

  it("does not duplicate in-flight requests when focus and retry timers coincide", async () => {
    let finish: (success: boolean) => void = () => {};
    const request = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          finish = resolve;
        }),
    );
    const retry = initialResourceLoader([request]);
    const first = retry();
    await retry();
    expect(request).toHaveBeenCalledTimes(1);
    finish(true);
    await first;
    await retry();
    expect(request).toHaveBeenCalledTimes(1);
  });
});
