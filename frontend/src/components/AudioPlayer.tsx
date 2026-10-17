import { useEffect, useRef, useState } from "react";
import { seekWhenReady } from "../api/media";
import type { Video } from "../types";
import Icon from "./Icon";

export default function AudioPlayer({
  source,
  onTime,
  seek,
}: {
  source: Video;
  onTime: (ms: number) => void;
  seek: { ms: number; nonce: number };
}) {
  const player = useRef<HTMLAudioElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (player.current) return seekWhenReady(player.current, seek.ms);
  }, [seek, source.source_id]);
  return (
    <div className="audio-player">
      <Icon name="sound" size={34} />
      <span>Audio recording</span>
      <audio
        ref={player}
        aria-label={source.filename}
        controls
        preload="metadata"
        src={"/api/videos/" + source.source_id + "/file"}
        onLoadedData={() => setError("")}
        onTimeUpdate={() =>
          onTime(Math.round((player.current?.currentTime ?? 0) * 1000))
        }
        onError={() =>
          setError(
            "The browser cannot play this audio format. The original file is retained for analysis.",
          )
        }
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
