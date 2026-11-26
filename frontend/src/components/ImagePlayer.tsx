// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useEffect, useRef, useState } from "react";
import { drawObservationOverlays } from "../api/overlays";
import type { Box, Video } from "../types";
import { contentRect } from "./VideoPlayer";

export default function ImagePlayer({
  video,
  boxesAt,
  show,
}: {
  video: Video;
  boxesAt: (ms: number) => Box[];
  show: boolean;
}) {
  const picture = useRef<HTMLImageElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const [loaded, setLoaded] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    const img = picture.current!,
      c = canvas.current!;
    function draw() {
      const width = img.clientWidth,
        height = img.clientHeight,
        dpr = window.devicePixelRatio || 1;
      c.width = width * dpr;
      c.height = height * dpr;
      const ctx = c.getContext("2d")!;
      ctx.scale(dpr, dpr);
      if (!show || !loaded) return;
      const r = contentRect(width, height, video.width, video.height);
      drawObservationOverlays(ctx, boxesAt(0), r, width);
    }
    draw();
    const resize = new ResizeObserver(draw);
    resize.observe(img);
    return () => resize.disconnect();
  }, [loaded, video, boxesAt, show]);
  return (
    <>
      <div className="player">
        <img
          ref={picture}
          src={"/api/videos/" + video.source_id + "/file"}
          alt={video.filename}
          onLoad={() => {
            setLoaded(true);
            setError("");
          }}
          onError={() => setError("This image could not be displayed.")}
        />
        <canvas ref={canvas} aria-hidden="true" />
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
