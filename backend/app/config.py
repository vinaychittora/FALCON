import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    model_dir: Path = ROOT / "models"
    frontend_dir: Path = ROOT / "frontend" / "dist"
    site_lat: float | None = None
    site_lon: float | None = None
    save_reviewed_crops: bool = False
    debug_audio: bool = False
    upload_limit_bytes: int | None = Field(default=None, gt=0)
    device: Literal["auto", "cuda", "cpu"] = "auto"

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
