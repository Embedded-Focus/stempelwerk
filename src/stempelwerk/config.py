import os
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt, field_validator

WriteMode = Literal["auto", "emacs", "disk", "read-only"]


class OrgFileConfig(BaseModel):
    id: str
    path: Path
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)


class CalDAVCalendarConfig(BaseModel):
    id: str
    name: str
    url: str
    username_env: str
    password_env: str
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("url")
    @classmethod
    def _validated_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("CalDAV calendar URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("CalDAV credentials must use environment variables")
        return value


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
    caldav_timeout_seconds: PositiveInt = 10
    caldav_cache_seconds: NonNegativeInt = 60
    caldav_calendars: list[CalDAVCalendarConfig] = Field(default_factory=list)

    @field_validator("caldav_calendars")
    @classmethod
    def _unique_caldav_calendar_ids(
        cls, value: list[CalDAVCalendarConfig]
    ) -> list[CalDAVCalendarConfig]:
        ids = [calendar.id for calendar in value]
        duplicates = sorted({calendar_id for calendar_id in ids if ids.count(calendar_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate CalDAV calendar id(s): {', '.join(duplicates)}")
        return value


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or configured_config_path()
    if config_path is None:
        return AppConfig()

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)


def configured_config_path() -> Path | None:
    raw_path = os.environ.get("STEMPELWERK_CONFIG")
    if raw_path:
        return Path(raw_path).expanduser()

    default_path = Path("config.toml")
    if default_path.exists():
        return default_path

    return None
