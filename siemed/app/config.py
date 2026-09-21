from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


def _default_data() -> Path:
    env = os.environ.get("SIEMED_DATA_DIR") or os.environ.get("SIEMED_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        return ROOT / "var"
    return Path("/var/lib/siemed")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIEMED_",
        env_file=str(ROOT / ".env"),
        extra="ignore",
    )

    station_name: str = "Кабинет сестринского дела"
    timezone: str = "Asia/Yekaterinburg"
    secret: str = Field(default_factory=lambda: secrets.token_hex(24))

    lan_host: str = "0.0.0.0"
    lan_port: int = 8080
    tablet_host: str = "0.0.0.0"
    tablet_port: int = 8070
    public_host: str = "0.0.0.0"
    public_port: int = 9080
    public_url: str = "http://127.0.0.1:9080"

    data_dir: Path = Field(default_factory=_default_data)
    player_enabled: bool = True
    mpv_ipc: str = "/run/siemed/mpv.sock"
    mpv_screen: int = 1
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    mpv_bin: str = "mpv"

    nvr_host: str = "192.168.0.99"
    nvr_user: str = "admin"
    nvr_password: str = "12345"
    nvr_rtsp_template: str = (
        "rtsp://{user}:{password}@{host}:554/cam/realmonitor?channel={ch}&subtype=0"
    )

    cancel_lead_hours: int = 24
    slot_grace_minutes: int = 5
    disk_min_free_gb: int = 20

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def lessons_dir(self) -> Path:
        return self.data_dir / "lessons"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "station.db"

    @property
    def splash_path(self) -> Path:
        return self.data_dir / "splash.jpg"


settings = Settings()
