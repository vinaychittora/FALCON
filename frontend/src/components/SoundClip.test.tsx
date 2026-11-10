import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { cleanSoundUrl, SoundClip } from "./EvidencePlayer";

describe("sound clip with Clean and a spectrogram", () => {
  it("plays the saved clip by default and offers the cleaned copy", () => {
    const html = renderToStaticMarkup(
      <SoundClip
        evidenceId="abc-1"
        url="/api/evidence/abc-1/media"
        onError={() => {}}
      />,
    );
    expect(html).toContain('src="/api/evidence/abc-1/media"');
    expect(html).toContain(">Clean<");
    expect(html).toContain("/api/evidence/abc-1/spectrogram.png");
    expect(cleanSoundUrl("abc-1")).toBe("/api/evidence/abc-1/clean.wav");
  });
});
