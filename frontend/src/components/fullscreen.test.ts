// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it, vi } from "vitest";
import { toggleFullscreen, typingTarget } from "./fullscreen";

describe("live view full screen", () => {
  it("enters full screen on the live view, and leaves it when it is on", async () => {
    const element = { requestFullscreen: vi.fn().mockResolvedValue(undefined) };
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    await toggleFullscreen(element as unknown as HTMLElement, {
      fullscreenElement: null,
      exitFullscreen,
    });
    expect(element.requestFullscreen).toHaveBeenCalledOnce();
    expect(exitFullscreen).not.toHaveBeenCalled();
    await toggleFullscreen(element as unknown as HTMLElement, {
      fullscreenElement: element as unknown as Element,
      exitFullscreen,
    });
    expect(exitFullscreen).toHaveBeenCalledOnce();
    expect(element.requestFullscreen).toHaveBeenCalledOnce();
  });

  it("does nothing without an element or browser support", async () => {
    await expect(
      toggleFullscreen(null, {
        fullscreenElement: null,
        exitFullscreen: vi.fn(),
      }),
    ).resolves.toBeUndefined();
    await expect(
      toggleFullscreen({} as HTMLElement, {
        fullscreenElement: null,
        exitFullscreen: vi.fn(),
      }),
    ).resolves.toBeUndefined();
  });

  it("ignores the F key while typing", () => {
    expect(typingTarget(null)).toBe(false);
    expect(typingTarget({} as EventTarget)).toBe(false);
    expect(typingTarget({ tagName: "INPUT" } as unknown as EventTarget)).toBe(
      true,
    );
    expect(typingTarget({ tagName: "SELECT" } as unknown as EventTarget)).toBe(
      true,
    );
    expect(
      typingTarget({
        tagName: "DIV",
        isContentEditable: true,
      } as unknown as EventTarget),
    ).toBe(true);
    expect(typingTarget({ tagName: "BUTTON" } as unknown as EventTarget)).toBe(
      false,
    );
  });
});
