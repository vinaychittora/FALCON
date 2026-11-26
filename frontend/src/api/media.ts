// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
interface SeekableMedia {
  readyState: number;
  duration: number;
  currentTime: number;
  addEventListener(type: "loadedmetadata", listener: () => void): void;
  removeEventListener(type: "loadedmetadata", listener: () => void): void;
}

/** Keep an observation seek pending until a newly opened source can accept it. */
export function seekWhenReady(media: SeekableMedia, milliseconds: number) {
  const apply = () => {
    const seconds = Number.isFinite(milliseconds)
      ? Math.max(0, milliseconds / 1000)
      : 0;
    media.currentTime = Number.isFinite(media.duration)
      ? Math.min(seconds, Math.max(0, media.duration))
      : seconds;
  };
  if (media.readyState >= 1) apply();
  else media.addEventListener("loadedmetadata", apply);
  // A newer selection must cancel an earlier pending observation seek.
  return () => media.removeEventListener("loadedmetadata", apply);
}
