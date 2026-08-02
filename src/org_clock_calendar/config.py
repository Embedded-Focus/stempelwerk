import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

WriteMode = Literal["auto", "emacs", "disk", "read-only"]


class OrgFileConfig(BaseModel):
    id: str
    path: Path
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    timezone: str = "Europe/Vienna"
    write_mode: WriteMode = "auto"
    clock_in_logbook: bool = True
    backup: bool = True
    backup_retention: int = 20
    first_day: int = 1
    snap_minutes: int = 5
    working_hours_start: str = "07:00"
    working_hours_end: str = "20:00"
    files: list[OrgFileConfig] = Field(default_factory=list)


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or configured_config_path()
    if config_path is None:
        return AppConfig()

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)


def configured_config_path() -> Path | None:
    raw_path = os.environ.get("ORG_CLOCK_CALENDAR_CONFIG")
    if raw_path:
        return Path(raw_path).expanduser()

    default_path = Path("config.toml")
    if default_path.exists():
        return default_path

    return None
