from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from stempelwerk.config import WriteMode


class Heading(BaseModel):
    id: str
    file_id: str
    title: str
    outline: list[str]
    tags: list[str] = Field(default_factory=list)
    todo: str | None = None
    stable: bool


class ClockEntry(BaseModel):
    id: str
    file_id: str
    heading_id: str
    heading_title: str
    outline: list[str]
    start: datetime
    end: datetime
    duration_minutes: int
    revision: str
    editable: bool = True


class ClockEntriesResponse(BaseModel):
    clocks: list[ClockEntry]
    revisions: dict[str, str]


class ClockUpdateRequest(BaseModel):
    start: datetime
    end: datetime
    expected_revision: str


class HeadingRenameRequest(BaseModel):
    title: str
    expected_revision: str


class StatusResponse(BaseModel):
    status: Literal["ok"]
    emacs_available: bool
    write_mode: WriteMode
    timezone: str
    files: list[str]
    file_colors: dict[str, str] = Field(default_factory=dict)


class BackupInfo(BaseModel):
    file_id: str
    filename: str
    created_at: datetime


class BackupsListResponse(BaseModel):
    backups: list[BackupInfo]


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody
