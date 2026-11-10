from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.schemas import AnalysisSettings, AudioEvent, VisualEvent


class CameraConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Backyard camera", min_length=1, max_length=80)
    url: SecretStr
    username: SecretStr | None = None
    password: SecretStr | None = None

    @model_validator(mode="after")
    def validate_connection(self) -> "CameraConnection":
        raw = self.url.get_secret_value().strip()
        if len(raw) > 2048 or any(ord(char) < 32 for char in raw):
            raise ValueError("Enter a valid RTSP URL")
        try:
            parsed = urlsplit(raw)
            if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname:
                raise ValueError()
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("Use an rtsp:// or rtsps:// camera URL") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "Enter camera credentials in the separate username and password fields"
            )
        if parsed.fragment:
            raise ValueError("Camera URLs cannot contain a fragment")
        if self.password and not self.username:
            raise ValueError("Enter the camera username as well as its password")
        self.url = SecretStr(raw)
        self.name = self.name.strip() or "Backyard camera"
        return self

    def connection_url(self) -> str:
        parsed = urlsplit(self.url.get_secret_value())
        if not self.username:
            return self.url.get_secret_value()
        credentials = quote(self.username.get_secret_value(), safe="")
        if self.password:
            credentials += ":" + quote(self.password.get_secret_value(), safe="")
        return urlunsplit(parsed._replace(netloc=f"{credentials}@{parsed.netloc}"))


class LiveStart(CameraConnection):
    config: AnalysisSettings = Field(default_factory=AnalysisSettings)
    use_saved_credentials: bool = False
    save_profile: bool = True
    # Sound from another stream (with its credentials): an IP camera's picture with a
    # sensor node's microphone. None: sound comes from url like the picture.
    audio_url: SecretStr | None = None


class CameraProfileWrite(CameraConnection):
    audio_enabled: bool = True


class CameraProfile(BaseModel):
    saved: bool = False
    name: str = "Backyard camera"
    url: str = ""
    username: str = ""
    has_password: bool = False
    audio_enabled: bool = True
    updated_at: str | None = None


class LiveState(BaseModel):
    status: Literal[
        "idle", "connecting", "live", "reconnecting", "stopping", "stopped", "failed"
    ] = "idle"
    session_id: str | None = None
    name: str | None = None
    error: str | None = None
    started_at: str | None = None
    session_timestamp_ms: int = 0
    preview_timestamp_ms: int | None = None
    visual: list[VisualEvent] = Field(default_factory=list)
    audio: list[AudioEvent] = Field(default_factory=list)
    metrics: dict[str, str | int | float] = Field(default_factory=dict)
    messages: list[str] = Field(default_factory=list)
    audio_status: str = "idle"
    # Detection paused for camera work since this time (ISO), else None.
    detection_paused_since: str | None = None
