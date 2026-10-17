from collections.abc import Iterator
from pathlib import Path

import av
import numpy as np

from app.media.base import Frame
from app.media.local_policy import local_media_options

# FFmpeg worker threads must not call Python logging while codec teardown holds
# the GIL. Native stderr keeps decode errors visible without that callback cycle.
# Reproduced on the 60-second threaded H.264 benchmark with PyAV 18.0.0.


class FileSource:
    def __init__(
        self,
        path: Path,
        start_time_s: float = 0,
        *,
        resume_after_ms: int = -1,
        next_sample_s: float = 0,
    ):
        self.path = path
        self.start_time_s = start_time_s
        self.resume_after_ms = resume_after_ms
        self.next_sample_s = next_sample_s

    def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
        # torchvision imports re-enable Python logging during model loading, so
        # restore this immediately before decoding, not just at module import.
        av.logging.restore_default_callback()
        with av.open(str(self.path), options=local_media_options()) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            stream.codec_context.thread_count = 4
            next_sample = self.next_sample_s
            if next_sample > 0:
                if stream.time_base is None:
                    raise ValueError("Video stream has no time base for resuming")
                # Seek to a preceding keyframe, then decode up to the original
                # absolute sampling grid. Coverage is not a sampling timestamp.
                seek_seconds = min(next_sample, max(0, self.resume_after_ms / 1000 - 0.001))
                container.seek(
                    int((self.start_time_s + seek_seconds) / float(stream.time_base)),
                    stream=stream,
                    backward=True,
                    any_frame=False,
                )
            for frame in container.decode(stream):
                if frame.pts is None or frame.time_base is None:
                    raise ValueError("Video frame has no presentation timestamp")
                seconds = float(frame.pts * frame.time_base) - self.start_time_s
                if max_seconds is not None and seconds >= max_seconds:
                    break
                timestamp_ms = round(max(0, seconds) * 1000)
                if timestamp_ms <= self.resume_after_ms:
                    if timestamp_ms == self.resume_after_ms and seconds >= 0:
                        # Recover the exact grid phase from the previous PTS;
                        # older checkpoints rounded it to milliseconds.
                        next_sample = max(next_sample, (int(seconds * fps + 0.000001) + 1) / fps)
                    continue
                if seconds < -0.001 or seconds + 0.000001 < next_sample:
                    continue
                following_sample = (int(seconds * fps + 0.000001) + 1) / fps
                yield Frame(
                    timestamp_ms,
                    frame.to_ndarray(format="rgb24").astype(np.uint8, copy=False),
                    next_sample_s=following_sample,
                )
                # Do not invent duplicate frames when presentation timestamps have gaps.
                next_sample = following_sample
