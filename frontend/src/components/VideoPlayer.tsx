import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { drawObservationOverlays } from "../api/overlays";
import { seekWhenReady } from "../api/media";
import type { Box, Video } from "../types";

export function contentRect(
  width: number,
  height: number,
  videoWidth: number,
  videoHeight: number,
) {
  const scale = Math.min(width / videoWidth, height / videoHeight);
  const w = videoWidth * scale,
    h = videoHeight * scale;
  return { x: (width - w) / 2, y: (height - h) / 2, width: w, height: h };
}

export default function VideoPlayer({
  video,
  boxesAt,
  show,
  onTime,
  seek,
}: {
  video: Video;
  boxesAt: (ms: number) => Box[];
  show: boolean;
  onTime: (ms: number) => void;
  seek?: { ms: number; nonce: number };
}) {
  const ref = useRef<HTMLVideoElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const [playbackError, setPlaybackError] = useState("");
  const latest = useRef({ boxesAt, show, onTime });
  const repaint = useRef<() => void>(() => {});
  useLayoutEffect(() => {
    latest.current = { boxesAt, show, onTime };
  }, [boxesAt, show, onTime]);
  useEffect(() => {
    const v = ref.current!,
      c = canvas.current!;
    let callback = 0,
      animation = 0;
    const draw = (seconds = v.currentTime) => {
      latest.current.onTime(Math.round(seconds * 1000));
      const width = v.clientWidth,
        height = v.clientHeight,
        dpr = window.devicePixelRatio || 1;
      c.width = width * dpr;
      c.height = height * dpr;
      const ctx = c.getContext("2d")!;
      ctx.scale(dpr, dpr);
      if (!latest.current.show || !v.videoWidth) return;
      const r = contentRect(width, height, v.videoWidth, v.videoHeight);
      drawObservationOverlays(
        ctx,
        latest.current.boxesAt(Math.round(seconds * 1000)),
        r,
        width,
      );
    };
    const frame = (_now: number, meta: VideoFrameCallbackMetadata) => {
      draw(meta.mediaTime);
      callback = v.requestVideoFrameCallback(frame);
    };
    const fallback = () => {
      draw();
      animation = requestAnimationFrame(fallback);
    };
    if ("requestVideoFrameCallback" in HTMLVideoElement.prototype)
      callback = v.requestVideoFrameCallback(frame);
    else animation = requestAnimationFrame(fallback);
    const update = () => draw();
    repaint.current = update;
    v.addEventListener("seeked", update);
    v.addEventListener("timeupdate", update);
    v.addEventListener("loadedmetadata", update);
    const resize = new ResizeObserver(update);
    resize.observe(v);
    return () => {
      if (callback) v.cancelVideoFrameCallback(callback);
      cancelAnimationFrame(animation);
      resize.disconnect();
      v.removeEventListener("seeked", update);
      v.removeEventListener("timeupdate", update);
      v.removeEventListener("loadedmetadata", update);
    };
  }, [video.source_id]);
  useEffect(() => {
    repaint.current();
  }, [boxesAt, show]);
  useEffect(() => {
    if (seek && ref.current) return seekWhenReady(ref.current, seek.ms);
  }, [seek, video.source_id]);
  return (
    <>
      <div className="player">
        <video
          ref={ref}
          controls
          preload="metadata"
          src={`/api/videos/${video.source_id}/file`}
          onLoadedData={() => setPlaybackError("")}
          onError={() =>
            setPlaybackError(
              "This browser could not play the original media. Try a browser with this codec, or choose an H.264 sample. No transcoding was performed.",
            )
          }
        />
        <canvas ref={canvas} aria-hidden="true" />
      </div>
      {playbackError && (
        <p role="alert" className="error">
          {playbackError}
        </p>
      )}
    </>
  );
}
