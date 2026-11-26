# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    model_dir: Path = ROOT / "models"
    frontend_dir: Path = ROOT / "frontend" / "dist"
    docs_dir: Path = ROOT / "docs"
    site_lat: float | None = None
    site_lon: float | None = None
    debug_audio: bool = False
    sensor_ingest_token: SecretStr | None = None
    sensor_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
    sensor_stale_after_seconds: float = Field(default=120, gt=0, le=86400)
    upload_limit_bytes: int | None = Field(default=None, gt=0)
    device: Literal["auto", "cuda", "cpu"] = "auto"
    # Names the home DNS (Pi-hole) points at this computer; phones may use them for
    # FALCON. Change in .env as LAN_NAMES='["falcon.lan"]'.
    lan_names: list[str] = ["falcon.lan", "falcon.home.arpa"]

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        for name in ("samples", "logs", "cache", "taxa", "temp", "jobs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(self.model_dir / "huggingface"))
        os.environ.setdefault("TORCH_HOME", str(self.model_dir / "torch"))
        os.environ.setdefault("YOLO_CONFIG_DIR", str(self.data_dir / "cache" / "yolo"))


settings = Settings()


def media_binary(name: str) -> str:
    local = ROOT / ".tools" / "ffmpeg" / "bin" / name
    return str(local) if local.exists() else name
