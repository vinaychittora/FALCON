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
