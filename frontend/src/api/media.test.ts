import { describe, expect, it } from "vitest";
import { seekWhenReady } from "./media";

function media(readyState = 0, duration = NaN) {
  return Object.assign(new EventTarget(), {
    readyState,
    duration,
    currentTime: 0,
  });
}

describe("opening media at an observation", () => {
  it("waits for video metadata before seeking to the requested observation", () => {
    const player = media();
    seekWhenReady(player, 73507);
    expect(player.currentTime).toBe(0);
    player.readyState = 1;
    player.duration = 120;
    player.dispatchEvent(new Event("loadedmetadata"));
    expect(player.currentTime).toBe(73.507);
  });

  it("cancels an older pending observation when another is selected", () => {
    const player = media();
    const cancel = seekWhenReady(player, 73507);
    cancel();
    seekWhenReady(player, 4000);
    player.readyState = 1;
    player.duration = 120;
    player.dispatchEvent(new Event("loadedmetadata"));
    expect(player.currentTime).toBe(4);
  });

  it("seeks an already loaded source immediately and respects its duration", () => {
    const player = media(1, 10);
    seekWhenReady(player, 4200);
    expect(player.currentTime).toBe(4.2);
    seekWhenReady(player, 11000);
    expect(player.currentTime).toBe(10);
    seekWhenReady(player, -1000);
    expect(player.currentTime).toBe(0);
  });

  it("does not seek after a preview is closed while loading", () => {
    const player = media();
    seekWhenReady(player, 73507)();
    player.dispatchEvent(new Event("loadedmetadata"));
    expect(player.currentTime).toBe(0);
  });
});
