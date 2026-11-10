import pytest

from falcon_node import media

WEBCAM = media.Camera("v4l2", "/dev/video0", "USB Camera", "mjpeg", ("1280x960",))
YUYV_ONLY = media.Camera("v4l2", "/dev/video1", "Old webcam", "", ("640x480",))
PUBLISH = "rtsp://127.0.0.1:8554/falcon"


def test_mjpeg_passthrough_copies_frames_and_drops_to_the_asked_rate() -> None:
    settings = media.CameraSettings(resolution="1280x960", framerate=10, video_codec="mjpeg")
    (command,) = media.build_pipeline(WEBCAM, settings, None, media.MicrophoneSettings(), PUBLISH)
    assert command[command.index("-input_format") + 1] == "mjpeg"
    assert command[command.index("-framerate") + 1] == "30"  # what the webcam delivers
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-bsf:v") + 1] == "noise=drop=mod(n\\,3)"  # keep every 3rd: 10 fps
    assert "libx264" not in command and "-filter_complex" not in command


def test_passthrough_at_full_rate_drops_nothing_and_ignores_night_filters() -> None:
    settings = media.CameraSettings(resolution="1280x960", framerate=30, video_codec="mjpeg")
    (command,) = media.build_pipeline(
        WEBCAM, settings, None, media.MicrophoneSettings(), PUBLISH, mono=True, probe_path="/tmp/p.ppm",
    )
    assert "-bsf:v" not in command and "hue=s=0" not in " ".join(command)


def test_h264_mode_and_cameras_without_mjpeg_still_encode() -> None:
    h264 = media.CameraSettings(resolution="1280x960", framerate=10, video_codec="h264")
    (command,) = media.build_pipeline(WEBCAM, h264, None, media.MicrophoneSettings(), PUBLISH)
    assert "libx264" in command
    mjpeg = media.CameraSettings(resolution="640x480", framerate=10, video_codec="mjpeg")
    (command,) = media.build_pipeline(YUYV_ONLY, mjpeg, None, media.MicrophoneSettings(), PUBLISH)
    assert "libx264" in command  # no MJPEG to pass through: encode as before


def test_video_codec_is_a_validated_setting() -> None:
    assert media.CameraSettings().updated({"video_codec": "mjpeg"}, "v4l2").video_codec == "mjpeg"
    with pytest.raises(ValueError):
        media.CameraSettings().updated({"video_codec": "vp9"}, "v4l2")
    assert "video_codec" in media.CONTROLS["v4l2"]
