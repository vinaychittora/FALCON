# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, media_binary
from app.main import create_app


def test_video_probe_range_and_missing(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    video = samples / "fixture.mp4"
    subprocess.run(
        [
            media_binary("ffmpeg"),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=10",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        record = client.get("/api/videos").json()["videos"][0]
        assert record["width"] == 320 and record["duration_ms"] == 1000
        assert record["audio"] is False
        url = f"/api/videos/{record['source_id']}/file"
        partial = client.get(url, headers={"Range": "bytes=0-31"})
        assert partial.status_code == 206
        assert partial.content == video.read_bytes()[:32]
        assert client.get(url, headers={"Range": "bytes=9999999-"}).status_code == 416
        assert client.get("/api/videos/missing/file").status_code == 404


def test_invalid_and_external_media(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "bad.mp4").write_bytes(b"not media")
    private = tmp_path / "outside.mp4"
    private.write_bytes(b"private")
    (samples / "link.mp4").symlink_to(private)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        data = client.get("/api/videos").json()
        assert not data["videos"] and len(data["errors"]) == 2


def test_pts_sampling_preserves_nonuniform_presentation_times(tmp_path: Path) -> None:
    from fractions import Fraction

    import av
    import numpy as np

    from app.media.file_source import FileSource

    path = tmp_path / "variable.mkv"
    expected = [0, 100, 700, 1700, 2000]
    with av.open(str(path), "w") as output:
        stream = output.add_stream("ffv1", rate=10)
        stream.width, stream.height = 32, 24
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 1000)
        for ms in expected:
            frame = av.VideoFrame.from_ndarray(
                np.full((24, 32, 3), 100, dtype=np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = ms, Fraction(1, 1000)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    assert [frame.timestamp_ms for frame in FileSource(path).frames(2)] == [0, 700, 1700, 2000]
    assert [frame.timestamp_ms for frame in FileSource(path).frames(2, 1)] == [0, 700]


def test_disguised_playlist_is_rejected_without_following_references(tmp_path: Path) -> None:
    import wave

    import pytest

    from app.media.file_source import FileSource
    from app.media.probe import probe

    # FFmpeg auto-detects this as a concat manifest despite its .mp4 suffix.
    # The referenced WAV is valid, so only the policy should reject it.
    with wave.open(str(tmp_path / "linked.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)
    manifest = tmp_path / "disguised.mp4"
    manifest.write_text("ffconcat version 1.0\nfile 'linked.wav'\n")
    with pytest.raises(subprocess.CalledProcessError):
        probe(manifest)
    with pytest.raises(Exception, match="Invalid argument"):
        list(FileSource(manifest).frames(2))
