from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

WriteMode = Literal["auto", "emacs", "disk", "read-only"]


class OrgFileConfig(BaseModel):
    id: str
    path: Path
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

